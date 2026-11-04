"""Hand-made labels in the web app: the /label page and its API (`clayzer ui --calibrate`).

People label a sample blind, and the evaluation's models are calibrated against them. The first
set is Claims from free text (labels/extraction/sample.jsonl; extract.py). Labels live in the
repo, one JSON object per line, so they're reviewed and committed like any other file. Saving is
off unless the app is started with --calibrate, so a hosted copy can show a set but never change
it.

An item may carry a `proposed` label from a model, to check and fix rather than write from
scratch, or be `blind`, labelled from scratch with no proposal shown. Each saved label records
its `source`, worked out here rather than trusted from the page: "proposal accepted", "proposal
edited", "blind", or "by hand". Changing a saved blind label afterwards (once a person may have
seen a model's answer) makes it "blind, adjudicated", reported apart from the untouched ones. Calibration reports the groups separately, because a checked
proposal pulls a person toward the model's answer and only blind labels are free of that.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from clayzer.config import REPO

SETS = {"extraction": REPO / "labels" / "extraction" / "sample.jsonl"}


class Label(BaseModel):
    claims: dict | None  # None clears the label


def _read(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _write(path: Path, rows: list[dict]) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    tmp.replace(path)


def _same(a: dict, b: dict) -> bool:
    """Two labels say the same: objects compared without their ids, relations by the objects
    they join, uncertain phrases ignoring case and spacing."""

    def norm(c):
        names = {o["id"]: (o["object"], o.get("count"), o.get("position")) for o in c["objects"]}
        return (
            sorted(names.values(), key=repr),
            # repr, not the tuples: a count or position may be None beside a value.
            sorted(
                (
                    repr((names.get(r["subject"]), r["relation"], names.get(r["object"])))
                    for r in c.get("relations", [])
                ),
            ),
            sorted(" ".join(u.lower().split()) for u in c.get("uncertain", [])),
        )

    return norm(a) == norm(b)


def _source(row: dict, claims: dict | None, before: dict | None = None) -> str | None:
    if claims is None:
        return None
    if row.get("blind"):
        prior = row.get("source") or ""
        if prior.startswith("blind") or row.get("labelled_before"):
            unchanged = prior == "blind" and before is not None and _same(claims, before)
            return "blind" if unchanged else "blind, adjudicated"
        return "blind"
    if row.get("proposed") is not None:
        return "proposal accepted" if _same(claims, row["proposed"]) else "proposal edited"
    return "by hand"


def router(calibrate: bool, static: Path, sets: dict[str, Path] | None = None) -> APIRouter:
    from clayzer.extract import check_claims, vocabulary

    sets = SETS if sets is None else sets
    lock = threading.Lock()
    r = APIRouter()

    def path_for(name: str) -> Path:
        if name not in sets:
            raise HTTPException(404, f"no label set {name!r}")
        return sets[name]

    @r.get("/api/labels")
    def label_sets():
        out = []
        for name, path in sets.items():
            rows = _read(path)
            out.append({"name": name, "items": len(rows),
                        "labelled": sum(1 for x in rows if x.get("claims") is not None)})  # fmt: skip
        return {"sets": out, "writable": calibrate}

    @r.get("/api/labels/{name}")
    def label_set(name: str):
        rows = _read(path_for(name))
        return {"name": name, "writable": calibrate, "vocabulary": vocabulary(),
                "items": [{"id": x["id"], "text": x["text"], "claims": x.get("claims"),
                           "proposed": x.get("proposed"), "proposed_by": x.get("proposed_by"),
                           "blind": bool(x.get("blind")),
                           "source": x.get("source")} for x in rows]}  # fmt: skip

    @r.put("/api/labels/{name}/{item_id}")
    def save_label(name: str, item_id: str, label: Label):
        if not calibrate:
            raise HTTPException(403, "start the app with --calibrate to save labels")
        if label.claims is not None:
            problems = check_claims(label.claims)
            if problems:
                raise HTTPException(400, "; ".join(problems))
        path = path_for(name)
        with lock:
            rows = _read(path)
            row = next((x for x in rows if x["id"] == item_id), None)
            if row is None:
                raise HTTPException(404, f"no item {item_id!r} in {name}")
            before = row.get("claims")
            if label.claims is None and before is not None:
                row["labelled_before"] = True  # clearing and relabelling isn't a fresh blind label
            row["source"] = _source(row, label.claims, before)
            row["claims"] = label.claims
            _write(path, rows)
        return {"id": item_id, "labelled": label.claims is not None, "source": row["source"]}

    @r.get("/label")
    def label_page():
        return FileResponse(static / "label" / "index.html")

    return r
