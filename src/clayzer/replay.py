"""Non-destructive replay of a local recorded Batch. No providers or store discovery.

The input is a batch directory, with images in an explicitly local data directory. Output
is a fresh standalone LocalStore; source files and accepted Baselines are never written.
"""

import hashlib
import json
import re
import tempfile
from dataclasses import asdict, replace
from pathlib import Path

from clayzer import batch
from clayzer.cases import parse_jsonl, to_jsonl
from clayzer.grounding import grounding
from clayzer.report_safety import redact
from clayzer.store import LocalStore
from clayzer.summarize import SummarySink
from clayzer.trace import dumps, loads, trace_key
from clayzer.workflow import score as workflow_score

SAFE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,120}\Z")


def _id(value):
    if not isinstance(value, str) or not SAFE.fullmatch(value) or ".." in value:
        raise ValueError("Unsafe or missing recording id")
    return value


def _rows(source, name, required=False):
    path = source / name
    if not path.exists() and not required:
        return []
    try:
        return parse_jsonl(path.read_bytes())
    except (OSError, ValueError, TypeError) as exc:
        raise ValueError(f"Invalid or missing {name}") from exc


def _indexed(rows, case_ids, repeats, kind):
    seen = set()
    for row in rows:
        key = (row.get("case_id"), row.get("repeat"))
        if (
            key in seen
            or key[0] not in case_ids
            or type(key[1]) is not int
            or not 1 <= key[1] <= repeats
        ):
            raise ValueError(f"Duplicate or mismatched {kind} Run")
        seen.add(key)
    return {(r["case_id"], r["repeat"]): r for r in rows}


def _load_recording(source):
    try:
        raw = json.loads((source / "batch.json").read_text())
        cfg = batch.config_from(raw)
        _id(cfg.batch_id)
        if type(cfg.repeats) is not int or cfg.repeats < 1:
            raise ValueError("Invalid repeat count")
        cases = _rows(source, "cases.jsonl", True)
        ids = [_id(c["id"]) for c in cases]
        if (
            len(set(ids)) != len(ids)
            or len(set(cfg.case_ids)) != len(cfg.case_ids)
            or set(ids) != set(cfg.case_ids)
        ):
            raise ValueError("Frozen Cases do not match Batch configuration")
        for case in cases:
            if not case.get("chips"):
                raise ValueError("Case has no Chip metadata")
            for chip in case["chips"]:
                _id(chip["id"])
                if chip.get("uri") != f"chips/{chip['id']}.png":
                    raise ValueError("Chip must use a local chips/<id>.png key")
        results = _rows(source, "results.jsonl")
        captions = _rows(source, "captions.jsonl")
        _indexed(results, ids, cfg.repeats, "result")
        caps = _indexed(captions, ids, cfg.repeats, "Caption")
        if any(
            not isinstance(c.get("text"), str)
            or not isinstance(c.get("objects"), list)
            or not isinstance(c.get("relations", []), list)
            for c in captions
        ):
            raise ValueError("Malformed recorded Caption")
        for c in captions:
            c.setdefault("relations", [])
            c.setdefault("uncertain", [])
        if any(
            r.get("status") not in (batch.OK, batch.HARNESS_FAULT, batch.SANDBOX_FAILURE)
            or not isinstance(r.get("run_id"), str)
            for r in results
        ):
            raise ValueError("Invalid recorded Run status/id")
        if len({r["run_id"] for r in results}) != len(results):
            raise ValueError("Duplicate recorded Run id")
        retrieval = _rows(source, "retrieval.jsonl")
        if any(
            type(r.get("repeat")) is not int or not 1 <= r["repeat"] <= cfg.repeats
            for r in retrieval
        ) or len({r["repeat"] for r in retrieval}) != len(retrieval):
            raise ValueError("Duplicate or mismatched retrieval Repeat")
    except (OSError, KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"Invalid Batch recording: {exc}") from exc

    return cfg, cases, results, captions, caps, retrieval


def _load_images(cases, data, chip_hashes, warnings, manifest):
    images = {}
    for case in cases:
        for chip in case["chips"]:
            image = data / chip["uri"]
            if not image.is_file() or not image.resolve().is_relative_to(data):
                warnings.append(
                    f"{chip['id']}: image unavailable in local data; references can still be scored"
                )
                continue
            body = image.read_bytes()
            digest = hashlib.sha256(body).hexdigest()
            if chip_hashes.get(chip["uri"]) not in (None, digest):
                warnings.append(f"{chip['id']}: image hash mismatch; image withheld from report")
                continue
            images[chip["uri"]] = body
            manifest[f"images/{chip['id']}.png"] = digest
    return images


def _load_trace(body, cid, repeat, cfg, r):
    info, steps = loads(body)
    events = [json.loads(line) for line in body.splitlines() if line.strip()]
    if (
        events[0]["event"] != "run_start"
        or events[-1]["event"] != "run_end"
        or sum(e["event"] == "run_start" for e in events) != 1
        or sum(e["event"] == "run_end" for e in events) != 1
        or info.status == "running"
        or info.ended_at is None
        or (info.case_id, info.repeat, info.batch_id, info.run_id)
        != (cid, repeat, cfg.batch_id, r["run_id"])
        or any(s.run_id != info.run_id for s in steps)
        or len({s.index for s in steps}) != len(steps)
    ):
        raise ValueError("incomplete or mismatched Trace")
    return info, steps


def _load_narrative(source, cid, repeat, recorded, narratives, warnings):
    narrative = source / "traces" / f"{cid}--r{repeat}.narrative.json"
    if narrative.is_file():
        try:
            value = json.loads(recorded(narrative))
            if (
                not isinstance(value, dict)
                or not isinstance(value.get("markdown"), str)
                or not isinstance(value.get("model"), str)
            ):
                raise TypeError("Invalid narrative envelope")
            narratives[narrative.name] = value
        except (ValueError, TypeError):
            warnings.append(
                f"{cid} r{repeat}: recorded narrative unavailable (malformed); deterministic summary used"
            )


def _replay_result(r, caps, by_id, source, cfg, recorded, traces, narratives, warnings):
    cid, repeat = r["case_id"], r["repeat"]
    cap = caps.get((cid, repeat))
    labels = by_id[cid].get("reference_labels")
    mode = {
        "grounding": "unavailable",
        "workflow": "unavailable",
        "fidelity": "retained recorded model opinion" if r.get("fidelity") else "unavailable",
    }
    g = grounding({"objects": [], "relations": []}, [])
    if r["status"] == batch.OK and cap is not None and labels is not None:
        g = grounding(cap, labels)
        mode["grounding"] = "recomputed from frozen Caption and references"
    elif r["status"] == batch.HARNESS_FAULT:
        g = grounding({"objects": [], "relations": []}, labels or [])
        g.update(correctness=0.0, coverage=0.0 if labels else None)
        mode["grounding"] = "preserved Harness Fault scoring rule"
    elif r["status"] == batch.OK:
        warnings.append(
            f"{cid} r{repeat}: Caption/reference evidence missing; grounding unavailable"
        )
    r["grounding"] = g
    if not r.get("fidelity"):
        warnings.append(f"{cid} r{repeat}: Judge verdict unavailable (not recorded)")
    r["workflow"] = None
    path = source / "traces" / f"{cid}--r{repeat}.jsonl"
    try:
        body = recorded(path)
        info, steps = _load_trace(body, cid, repeat, cfg, r)
        if r["status"] != batch.SANDBOX_FAILURE:
            r["workflow"] = workflow_score(info, steps)
            mode["workflow"] = "recomputed from recorded Trace"
        traces.append((info, steps))
        _load_narrative(source, cid, repeat, recorded, narratives, warnings)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        warnings.append(
            f"{cid} r{repeat}: Trace unavailable ({type(exc).__name__}); workflow unavailable"
        )
    r["replay"] = mode


def _write_trace_exports(store, bid, images, traces):
    for uri, body in images.items():
        store.put(uri, body)
    for info, steps in traces:
        # Redact the exported copy, retaining IDs and times; internal originals stay untouched.
        safe_info, safe_steps = loads(
            to_jsonl(redact([json.loads(line) for line in dumps(info, steps).splitlines()]))
        )
        store.put(trace_key(bid, info.case_id, info.repeat), dumps(safe_info, safe_steps))
        SummarySink(store).write(safe_info, safe_steps)


def _write_recorded_text(store, bid, source):
    for name in ("prompt.txt", "judge-prompt.txt", "retrieval-queries.jsonl", "chips.json"):
        path = source / name
        if path.exists():
            store.put(f"batches/{bid}/{name}", redact(path.read_text()).encode())


def replay(source: Path, *, data: Path | None = None, output: Path | None = None) -> Path:
    """Recompute deterministic metrics, retain recorded opinions, and rebuild local reports.

    Invalid Batch identities fail before writing. Missing/malformed individual Traces are
    quarantined with warnings, so a partial Batch remains inspectable without invented scores.
    Output paths must be new and disjoint from both input roots (including symlinks).
    """
    source = Path(source).resolve()
    data = (Path(data) if data else source.parent.parent / "data").resolve()
    if output is not None:
        output = Path(output).resolve()
        if output.exists() or any(
            output.is_relative_to(p) or p.is_relative_to(output) for p in (source, data)
        ):
            raise ValueError("Replay output must be a new directory outside the recording/data")
    cfg, cases, results, captions, caps, retrieval = _load_recording(source)

    warnings, traces, narratives = [], [], {}
    by_id = {c["id"]: c for c in cases}
    manifest = {}

    def recorded(path):
        body = path.read_bytes()
        manifest[str(path.relative_to(source))] = hashlib.sha256(body).hexdigest()
        return body

    for name in (
        "batch.json",
        "cases.jsonl",
        "results.jsonl",
        "captions.jsonl",
        "retrieval.jsonl",
        "summary.json",
        "prompt.txt",
        "judge-prompt.txt",
        "retrieval-queries.jsonl",
        "chips.json",
    ):
        if (source / name).is_file():
            recorded(source / name)
    chip_hashes = (
        json.loads((source / "chips.json").read_text()) if (source / "chips.json").exists() else {}
    )
    images = _load_images(cases, data, chip_hashes, warnings, manifest)
    for r in results:
        _replay_result(r, caps, by_id, source, cfg, recorded, traces, narratives, warnings)
    for case in cases:
        if case.get("reference_labels") is None:
            case["reference_labels"] = []
            case["reference_status"] = "unavailable in recording; no absence inference"
    if not retrieval:
        warnings.append("Retrieval unavailable: no recorded embedding/retrieval evidence")
    original = cfg.scorer_version
    metadata = {
        "version": "replay-1",
        "mode": "OFFLINE REPLAY",
        "network": "disabled by design: local files only",
        "original_scorer": original,
        "current_scorer": batch.SCORER_VERSION,
        "historical_scores_comparable": original == batch.SCORER_VERSION,
        "pending_runs": len(cases) * cfg.repeats - len(results),
        "metrics": {
            "grounding": "recomputed where frozen evidence available",
            "workflow": "recomputed where complete Trace available",
            "fidelity": "retained recorded model opinion",
            "retrieval": "retained recorded measurement" if retrieval else "unavailable",
        },
        "warnings": warnings,
        "input_sha256": dict(sorted(manifest.items())),
    }
    if original != batch.SCORER_VERSION:
        warnings.append(
            "Evaluator changed: historical and replayed scores are not directly comparable"
        )
    cfg = replace(cfg, scorer_version=batch.SCORER_VERSION, extra={**cfg.extra, "replay": metadata})
    summary = batch.summarize(cfg, cases, results, retrieval)
    summary["replay"] = metadata
    original_summary = (
        json.loads((source / "summary.json").read_text())
        if (source / "summary.json").exists()
        else {}
    )
    summary["stopped"] = original_summary.get("stopped")
    if metadata["pending_runs"] and not summary["stopped"]:
        summary["stopped"] = "Recorded partial Batch; pending Runs were not executed by replay"
    output = output or Path(tempfile.mkdtemp(prefix="clayzer-replay-"))
    output.mkdir(parents=True, exist_ok=True)
    store = LocalStore(output / "data", output / "batches")
    bid = cfg.batch_id

    def put(name, body):
        store.put(f"batches/{bid}/{name}", body)

    def put_json(name, value):
        put(name, (json.dumps(redact(value), indent=2, allow_nan=False) + "\n").encode())

    put_json("batch.json", asdict(cfg))
    put("cases.jsonl", to_jsonl(redact(cases)))
    put("results.jsonl", to_jsonl(redact(results)))
    put("captions.jsonl", to_jsonl(redact(captions)))
    put("retrieval.jsonl", to_jsonl(redact(retrieval)))
    put_json("summary.json", summary)
    put_json("replay.json", metadata)
    _write_trace_exports(store, bid, images, traces)
    for name, value in narratives.items():
        put_json(f"traces/{name}", value)
    _write_recorded_text(store, bid, source)
    batch.write_reports(store, bid)
    return output
