"""The team web app: the workflow, the work board, Cases, Batches, and data sources (caption-plan.md §4).

A FastAPI JSON API over the store, plus a no-build front end in ui/static/. It reads whatever
store the settings point at (local folders or the account's S3 bucket). It's read-only unless
started with --allow-launch, which lets the browser start Batches; it listens on localhost.
"""

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
from clayzer.cases import cases_key, load_cases
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

    def summary_row(batch_id: str) -> dict:
        cfg, s = batches.load_summary(store, batch_id)
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

    @app.get("/api/overview")
    def overview():
        ids = batches.list_batches(store)
        latest = summary_row(ids[-1]) if ids else None
        base = baseline_or_none()
        cases = load_cases(store, cases_key(region))
        return {
            "latest": latest,
            "baseline": {
                "batch_id": base["config"].batch_id,
                "correctness": base["summary"]["batch"].get("correctness"),
                "coverage": base["summary"]["batch"].get("coverage"),
                "fidelity": base["summary"]["batch"]["fidelity"],
                "retrieval": base["summary"]["batch"]["retrieval_mrr"],
                "cases": len(base["config"].case_ids),
                "repeats": base["config"].repeats,
            }
            if base
            else None,
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
        return [summary_row(b) for b in reversed(batches.list_batches(store))]

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

    @app.get("/api/batches/{batch_id}/report.html", response_class=HTMLResponse)
    def report(batch_id: str):
        key = f"batches/{_safe(batch_id)}/report.html"
        if not store.exists(key):
            raise HTTPException(404, "no report yet")
        return HTMLResponse(store.get(key).decode())

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

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    @app.get("/deck")
    def deck():
        return FileResponse(STATIC / "deck" / "index.html")

    return app


def serve(settings: Settings, region: str, allow_launch: bool, host: str, port: int) -> None:
    import uvicorn

    uvicorn.run(
        create_app(settings, region, allow_launch), host=host, port=port, log_level="warning"
    )
