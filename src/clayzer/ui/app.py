"""The team web app: the workflow, the work board, Cases, Batches, and data sources (caption-plan.md §4).

A FastAPI JSON API over the store, plus a no-build front end in ui/static/. It reads whatever
store the settings point at (local folders or the account's S3 bucket). It's read-only unless
started with --allow-launch, which lets the browser start Batches; it listens on localhost.
"""

import json
import re
import threading
import tomllib
import traceback
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from clayzer import batch as batches
from clayzer import provenance
from clayzer.cases import cases_key, load_cases, parse_jsonl
from clayzer.config import REPO, Settings
from clayzer.gate import DEFAULT_TOLERANCE, compare, gate, load_baseline

STATIC = Path(__file__).parent / "static"
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,120}$")


def _safe(value: str) -> str:
    """Ids end up in store keys: refuse anything that could leave its folder."""
    if not SAFE_ID.match(value) or ".." in value:
        raise HTTPException(400, f"invalid id: {value!r}")
    return value


def load_tasks(path: Path = REPO / "docs" / "tasks.toml") -> list[dict]:
    if not path.exists():
        return []
    return tomllib.loads(path.read_text())["task"]


def load_sources(path: Path = REPO / "docs" / "sources.toml") -> list[dict]:
    if not path.exists():
        return []
    return tomllib.loads(path.read_text())["source"]


def load_requirements(path: Path = REPO / "docs" / "caption-design.md") -> dict[str, str]:
    """Requirement id -> its text, from the CAP, REQ, and AWS tables in caption-design.md §2."""
    if not path.exists():
        return {}
    reqs = {}
    for line in path.read_text().splitlines():
        m = re.match(r"^\|\s*((?:CAP|REQ|AWS)-\d+)\s*\|\s*(.+?)\s*\|", line)
        if m:
            reqs.setdefault(m.group(1), m.group(2))
    return reqs


def load_glossary(path: Path = REPO / "GLOSSARY.md") -> list[dict]:
    """Terms from GLOSSARY.md: '**Term**:' then a definition, then an optional '_Avoid_:'."""
    if not path.exists():
        return []
    terms, section = [], ""
    lines = path.read_text().splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith(("## ", "### ")):
            section = line.lstrip("#").strip()
        m = re.match(r"^\*\*(.+?)\*\*:\s*$", line)
        if m:
            body, avoid = [], ""
            i += 1
            while i < len(lines) and lines[i].strip() and not lines[i].startswith("**"):
                if lines[i].startswith("_Avoid_:"):
                    avoid = lines[i].removeprefix("_Avoid_:").strip()
                else:
                    body.append(lines[i].strip())
                i += 1
            terms.append({"term": m.group(1), "section": section,
                          "definition": " ".join(body), "avoid": avoid})  # fmt: skip
            continue
        i += 1
    return terms


class Launch(BaseModel):
    repeats: int = Field(3, ge=1, le=10)
    label: str = Field("", max_length=40)
    judge: bool = True
    only: list[str] | None = None


def create_app(settings: Settings, region: str = "dev", allow_launch: bool = False) -> FastAPI:
    store = settings.store()
    app = FastAPI(title="Clayzer", docs_url=None, redoc_url=None)
    jobs: dict[str, dict] = {}
    lock = threading.Lock()
    # A finished Batch never changes, so its summary and showcase are read from the store once.
    finished: dict[str, tuple] = {}
    showcases: dict[str, list] = {}

    def summary_of(batch_id: str):
        if batch_id in finished:
            return finished[batch_id]
        cfg, summ = batches.load_summary(store, batch_id)
        if summ and not summ.get("stopped") and not summ["batch"]["runs"]["sandbox_failures"]:
            finished[batch_id] = (cfg, summ)
        return cfg, summ

    def summaries(ids: list[str]) -> dict[str, tuple]:
        """Summaries for many Batches, reading the uncached ones from the store in parallel."""
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=8) as pool:
            return dict(zip(ids, pool.map(summary_of, ids), strict=True))

    def summary_row(batch_id: str, loaded: tuple | None = None) -> dict:
        cfg, s = loaded or summary_of(batch_id)
        row = {
            "batch_id": batch_id, "label": cfg.label, "created": cfg.created,
            "cases": len(cfg.case_ids), "repeats": cfg.repeats,
            "caption_model": cfg.caption_model, "judge_model": cfg.judge_model,
            "prompt_sha": cfg.prompt_sha, "prompt_source": cfg.prompt_source,
            "complete": bool(s) and not s.get("stopped")
            and not s["batch"]["runs"]["sandbox_failures"],
        }  # fmt: skip
        if s:
            row.update(
                correctness=s["batch"].get("correctness"),
                coverage=s["batch"].get("coverage"),
                fidelity=s["batch"]["fidelity"],
                retrieval=s["batch"]["retrieval_mrr"],
                unscored_share=s["batch"]["unscored_share"],
                runs=s["batch"]["runs"],
                stopped=s.get("stopped"),
            )
        return row

    def baseline_or_none(name: str = "default"):
        try:
            return load_baseline(settings.baselines_dir, name)
        except FileNotFoundError:
            return None

    @app.get("/api/config")
    def config():
        return {
            "store": store.url("").rstrip("/"),
            "region": region,
            "allow_launch": allow_launch,
            "caption_model": settings.caption_model,
            "judge_model": settings.judge_model,
            "embed_model": settings.embed_model,
        }

    def showcase(batch_id: str, limit: int = 8) -> list[dict]:
        """The best Run of each Case in a Batch, with what's needed to draw it: the Chip, the
        Caption, each Claim's verdict and cell, and the Reference Labels' cells."""
        if batch_id in showcases:
            return showcases[batch_id]
        try:
            b = batches.load(store, batch_id)
        except Exception:  # noqa: BLE001 -- the Baseline may live in another teammate's store
            return []
        caps = {(c["case_id"], c["repeat"]): c for c in b["captions"]}
        cases = {c["id"]: c for c in b["cases"]}
        best: dict[str, dict] = {}
        for r in b["results"]:
            g = r.get("grounding")
            if r["status"] != "ok" or not g or (r["case_id"], r["repeat"]) not in caps:
                continue
            score = (g.get("correctness") or 0) + (g.get("coverage") or 0)
            if r["case_id"] not in best or score > best[r["case_id"]]["_score"]:
                best[r["case_id"]] = {**r, "_score": score}
        out = []
        for case_id, r in sorted(best.items(), key=lambda kv: -kv[1]["_score"])[:limit]:
            case, cap, g = cases[case_id], caps[(case_id, r["repeat"])], r["grounding"]
            claims = [
                {"object": row["claim"]["object"], "count": row["claim"]["count"],
                 "position": row["claim"]["position"], "verdict": row["verdict"],
                 "position_score": row.get("position")}
                for row in g.get("rows", [])
            ]  # fmt: skip
            right = sum(c["verdict"] == "matched" and c["position_score"] == 1.0 for c in claims)
            out.append({
                "case_id": case_id, "run_id": r["run_id"], "chip": case["chips"][0],
                "text": cap["text"], "claims": claims,
                "labels": [{"object": lb["object"], "cells": lb["cells"]} for lb in case["reference_labels"]],
                "missed": g.get("missed", []), "unscored": g.get("unscored", []),
                "right": right, "gradable": len(claims),
                "correctness": g.get("correctness"), "coverage": g.get("coverage"),
                "fidelity": (r.get("fidelity") or {}).get("score"),
            })  # fmt: skip
        showcases[batch_id] = out
        return out

    def experiments(base, limit: int = 6) -> list[dict]:
        """Recent Batches, each judged against the Baseline."""
        rows = []
        ids = list(reversed(batches.list_batches(store)))[: limit + 4]
        loaded = summaries(ids)
        for batch_id in ids:
            if len(rows) >= limit:
                break
            cfg, summ = loaded[batch_id]
            if not summ:
                continue
            b = summ["batch"]
            row = {"batch_id": batch_id, "label": cfg.label or "unlabelled", "created": cfg.created,
                   "cases": len(cfg.case_ids), "repeats": cfg.repeats, "moves": []}  # fmt: skip
            if base is None:
                row["verdict"] = "no Baseline"
            elif batch_id == base["config"].batch_id:
                row["verdict"] = "baseline"
            elif cfg.cases_sha != base["config"].cases_sha:
                same_ids = set(cfg.case_ids) == set(base["config"].case_ids)
                row["verdict"] = (
                    "different Cases"
                    if same_ids or len(cfg.case_ids) >= len(base["config"].case_ids)
                    else "partial"
                )
            else:
                row["verdict"] = gate(base, {"config": cfg, "summary": summ}).verdict
            # Moves only mean something when the two Batches scored the same Cases.
            if base is not None and row["verdict"] in ("pass", "fail", "inconclusive"):
                bb = base["summary"]["batch"]
                pairs = [("right", "correctness"), ("say enough", "coverage"),
                         ("Judge", "fidelity")]  # fmt: skip
                for name, key in pairs:
                    if b.get(key) is not None and bb.get(key) is not None:
                        row["moves"].append(
                            {"name": name, "points": round(100 * (b[key] - bb[key]))}
                        )
                rb, rc = bb["retrieval_mrr"]["mean"], b["retrieval_mrr"]["mean"]
                if rb is not None and rc is not None:
                    row["moves"].append({"name": "search", "points": round(100 * (rc - rb))})
                row["moves"].sort(key=lambda m: -abs(m["points"]))
            rows.append(row)
        return rows

    @app.get("/api/overview")
    def overview():
        ids = batches.list_batches(store)
        latest = summary_row(ids[-1]) if ids else None
        base = baseline_or_none()
        cases = load_cases(store, cases_key(region))
        baseline = None
        if base:
            bb = base["summary"]["batch"]
            baseline = {
                "batch_id": base["config"].batch_id,
                "correctness": bb.get("correctness"),
                "coverage": bb.get("coverage"),
                "fidelity": bb["fidelity"],
                "retrieval": bb["retrieval_mrr"],
                "retrieval_top1": (bb.get("retrieval_recall_at_1") or {}).get("mean"),
                "label_prep_seconds": bb.get("label_prep_seconds"),
                "workflow": bb.get("workflow"),
                "tools": base["config"].tools if hasattr(base["config"], "tools") else [],
                "label_prep_seconds_per_case": bb.get("label_prep_seconds_per_case"),
                "seconds_per_caption": bb.get("seconds_per_caption"),
                "tokens_per_caption": bb.get("tokens_per_caption"),
                "unscored_share": bb.get("unscored_share"),
                "cases": len(base["config"].case_ids),
                "repeats": base["config"].repeats,
                "caption_model": base["config"].caption_model,
            }
        return {
            "latest": latest,
            "baseline": baseline,
            "showcase": showcase(base["config"].batch_id) if base else [],
            "experiments": experiments(base),
            "batches": len(ids),
            "cases": len(cases),
            "tasks": load_tasks(),
        }

    @app.get("/api/tasks")
    def tasks():
        return load_tasks()

    @app.get("/api/sources")
    def sources():
        return load_sources()

    @app.get("/api/requirements")
    def requirements():
        return load_requirements()

    @app.get("/api/glossary")
    def glossary():
        return load_glossary()

    @app.get("/api/cases")
    def cases():
        return [
            {
                "id": c["id"],
                "kind": c.get("kind", "fixed"),
                "chip": c["chips"][0],
                "labels": c["reference_labels"],
                "prep_seconds": c.get("prep_seconds"),
            }
            for c in load_cases(store, cases_key(region))
        ]

    @app.get("/api/chips/{chip_id}.png")
    def chip(chip_id: str):
        key = f"chips/{_safe(chip_id)}.png"
        if not store.exists(key):
            raise HTTPException(404, "no such Chip")
        return Response(store.get(key), media_type="image/png")

    @app.get("/api/batches")
    def list_all():
        ids = list(reversed(batches.list_batches(store)))
        loaded = summaries(ids)
        return [summary_row(b, loaded[b]) for b in ids]

    def light(batch_id: str) -> dict:
        """Configuration and summary only: all that compare and the regression gate read."""
        cfg, summary = batches.load_summary(store, _safe(batch_id))
        if summary is None:
            raise HTTPException(409, f"{batch_id} has no summary yet")
        return {"config": cfg, "summary": summary}

    @app.get("/api/batches/{batch_id}")
    def one(batch_id: str):
        cfg, summary = batches.load_summary(store, _safe(batch_id))
        return {"config": asdict(cfg), "summary": summary}

    @app.get("/api/batches/{batch_id}/provenance")
    def batch_provenance(batch_id: str):
        """Every setting the Batch ran and was judged with, beside the Baseline's, and where
        each of its stored files is."""
        bid = _safe(batch_id)
        cfg = asdict(batches.load_config(store, bid))
        base = baseline_or_none()
        bcfg = asdict(base["config"]) if base else None
        rows = []
        for key, label, group in provenance.SETTINGS:
            value = cfg.get(key)
            row = {"key": key, "label": label, "group": group, "value": value,
                   "recorded": not (key in provenance.RECORDED_SINCE and value is None)}  # fmt: skip
            if bcfg is not None and key not in ("created", "region"):
                old = bcfg.get(key)
                row["baseline"] = old
                row["baseline_recorded"] = not (key in provenance.RECORDED_SINCE and old is None)
                row["differs"] = row["recorded"] and row["baseline_recorded"] and old != value
            rows.append(row)
        for key, value in cfg["extra"].items():
            rows.append({"key": key, "label": key, "group": "Recorded by another branch's code",
                         "value": value, "recorded": True})  # fmt: skip
        return {
            "batch_id": bid,
            "baseline_id": bcfg["batch_id"] if bcfg else None,
            "settings": rows,
            "files": provenance.files(store, bid, provenance.BATCH_FILES),
        }

    @app.get("/api/batches/{batch_id}/runs/{name}/provenance")
    def run_provenance(batch_id: str, name: str):
        """A Run's stored files, and exactly which Case and Chip it was scored on."""
        bid = _safe(batch_id)
        m = re.match(r"^(.+)--r(\d+)$", _safe(name))
        if not m:
            raise HTTPException(404, "not a Run")
        case_id, repeat = m.group(1), int(m.group(2))
        cases = {c["id"]: c for c in parse_jsonl(store.get(f"batches/{bid}/cases.jsonl"))}
        if case_id not in cases:
            raise HTTPException(404, f"{case_id} isn't in {bid}")
        case = cases[case_id]
        chip = case["chips"][0]
        chips_key = f"batches/{bid}/chips.json"
        chip_shas = json.loads(store.get(chips_key)) if store.exists(chips_key) else {}
        return {
            "batch_id": bid,
            "case": {
                "id": case_id,
                "sha": provenance.sha(json.dumps(case, sort_keys=True).encode()),
                "reference_labels": len(case.get("reference_labels", [])),
                "chip_uri": chip["uri"],
                "chip_store_url": store.url(chip["uri"]),
                "chip_sha256": chip_shas.get(chip["uri"]),
            },
            "files": provenance.run_files(store, bid, case_id, repeat),
        }

    @app.get("/api/batches/{batch_id}/files/{name:path}")
    def batch_file(batch_id: str, name: str):
        """One of a Batch's stored files, as stored. Only the files provenance.py lists."""
        if not provenance.allowed_file(name):
            raise HTTPException(404, "not a Batch file")
        key = f"batches/{_safe(batch_id)}/{name}"
        if not store.exists(key):
            raise HTTPException(404, "not stored for this Batch")
        kind = ("application/json" if name.endswith(".json")
                else "text/html; charset=utf-8" if name.endswith(".html")
                else "text/plain; charset=utf-8")  # fmt: skip
        return Response(store.get(key), media_type=kind)

    @app.get("/api/batches/{batch_id}/report.html", response_class=HTMLResponse)
    def report(batch_id: str):
        key = f"batches/{_safe(batch_id)}/report.html"
        if not store.exists(key):
            raise HTTPException(404, "no report yet")
        return HTMLResponse(store.get(key).decode())

    @app.get("/api/batches/{batch_id}/runs/{name}.html", response_class=HTMLResponse)
    def run_html(batch_id: str, name: str):
        key = f"batches/{_safe(batch_id)}/runs/{_safe(name)}.html"
        if not store.exists(key):
            raise HTTPException(404, "no report for this Run yet")
        return HTMLResponse(store.get(key).decode())

    @app.get("/api/batches/{batch_id}/runs/{name}.json")
    def run_json(batch_id: str, name: str):
        key = f"batches/{_safe(batch_id)}/runs/{_safe(name)}.json"
        if not store.exists(key):
            raise HTTPException(404, "no report for this Run yet")
        return json.loads(store.get(key))

    @app.get("/api/compare")
    def compare_two(a: str, b: str):
        return compare(light(a), light(b))

    @app.get("/api/gate/{batch_id}")
    def gate_one(batch_id: str, baseline: str = "default", tolerance: float = DEFAULT_TOLERANCE):
        base = baseline_or_none(_safe(baseline))
        if base is None:
            raise HTTPException(404, f"no Baseline named {baseline!r}; accept one first")
        result = gate(base, light(batch_id), tolerance)
        return {**asdict(result), "exit_code": result.exit_code}

    @app.post("/api/batches")
    def launch(req: Launch):
        if not allow_launch:
            raise HTTPException(403, "start the app with --allow-launch to run Batches")
        with lock:
            if any(j["state"] == "running" for j in jobs.values()):
                raise HTTPException(409, "a Batch is already running")
        cases = load_cases(store, cases_key(region))
        if req.only:
            cases = [c for c in cases if c["id"] in req.only]
        if not cases:
            raise HTTPException(400, "no Cases to run")
        batch_id = batches.create(
            cases, settings, store, req.repeats, req.label, region, judge=req.judge
        )
        job = {"batch_id": batch_id, "state": "running", "lines": [],
               "started": datetime.now(UTC).isoformat(timespec="seconds")}  # fmt: skip
        jobs[batch_id] = job

        def work():
            try:
                s = batches.resume(batch_id, settings, store, progress=job["lines"].append)
                job["state"] = "stopped" if s.get("stopped") else "done"
                if s.get("stopped"):
                    job["lines"].append(s["stopped"])
            except Exception as e:  # noqa: BLE001 -- shown in the browser; the Batch can be resumed
                job["state"] = "failed"
                job["lines"].append(f"failed: {e}")
                job["lines"].append(traceback.format_exc(limit=3))

        threading.Thread(target=work, daemon=True).start()
        return job

    @app.get("/api/jobs")
    def list_jobs():
        return list(jobs.values())

    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    # Every page links to the app's other URLs relatively, against a <base> that points back at the
    # app's root. That way the app works behind a path-prefixing proxy (/proxy/8770/) as well as
    # at the root, with no prefix to configure.
    def page(name: str, base: str = "./") -> HTMLResponse:
        html = (STATIC / name).read_text()
        return HTMLResponse(html.replace("<head>", f'<head>\n  <base href="{base}">', 1))

    @app.get("/")
    def index():
        return page("index.html")

    @app.get("/docs", include_in_schema=False)
    def docs_index():
        from fastapi.responses import RedirectResponse

        return RedirectResponse("docs/docs/caption-plan.md")

    @app.get("/docs/{path:path}", response_class=HTMLResponse, include_in_schema=False)
    def doc(path: str):
        from clayzer.ui.docs import render

        # /docs/<path> sits as many directories below the root as <path> has slashes, plus one.
        up = "../" * (path.count("/") + 1)
        html = render(path, base=up)
        if html is None:
            raise HTTPException(404, "not one of the project's docs")
        return HTMLResponse(html)

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon():
        # Browsers ask the root for it on pages without a <link rel="icon">, like reports.
        return FileResponse(STATIC / "favicon.ico")

    @app.get("/deck")
    def deck():
        html = (STATIC / "deck" / "index.html").read_text()
        return HTMLResponse(html.replace("<head>", '<head>\n  <base href="./">', 1))

    return app


def serve(settings: Settings, region: str, allow_launch: bool, host: str, port: int) -> None:
    import uvicorn

    uvicorn.run(
        create_app(settings, region, allow_launch), host=host, port=port, log_level="warning"
    )
