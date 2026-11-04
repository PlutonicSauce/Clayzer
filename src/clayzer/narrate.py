"""Model-written Trace summaries, for readability (REQ-05), saved so replays need no model
(REQ-09).

A model reads only the Run's Trace, as a compact digest, plus the facts summarize.py computed
from the same Trace, and writes three short sections: what the Harness did, where it struggled
and whose fault, and a one-line verdict. That meets REQ-05 ("from the Trace alone"): nothing else
goes in, not the Case, its Reference Labels, or the scores.

The narrative is generated once and saved next to the Trace, with the model, tokens, time, and a
hash of the Trace it was written from. Reports and replays read the saved file and never call
the model again, the same way Judge verdicts are replayed (REQ-09). When there's no narrative
(offline, or the call failed), reports fall back to summarize.py's code-written summary.

The narration call is not recorded in the Trace it describes: that would be circular.

Follows the Sandbox's summarizer and digest (breaking-barriers summarize.py, digest.py).
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import UTC, datetime

from clayzer.summarize import summarize
from clayzer.trace import RunInfo, Step

DEFAULT_MODEL = "us.amazon.nova-pro-v1:0"
MAX_OUTPUT_CHARS = 2000

SYSTEM = """You summarize the Trace of one Run of an AI captioner that describes aerial images.
Readers are evaluators who need to know quickly what happened, without reading the Trace.

Write markdown with exactly these three sections:
### What the Harness did
2 to 6 bullets, in order: each model call or tool call, what it was asked, and what came back
(for a Caption, what it claimed). Name tools and models.
### Where it struggled
A bullet for each failed step, retry, missing tool call, or thing the Caption left uncertain.
Name a fault only where a step has a "fault:" line, and use exactly that line's attribution:
harness means Harness Fault, environment means Environment Fault, sandbox means Sandbox Failure.
If no step has a fault line, don't use any of those three terms. Write "Nothing notable." if
there is nothing.
### Verdict
One sentence: did the Run produce a Caption, and if not, why.

Use only what is in the Trace below. Don't judge whether the Caption is correct or complete:
scoring is done elsewhere and isn't shown to you. Be specific and brief."""


def narrative_key(batch_id: str, case_id: str, repeat: int) -> str:
    return f"batches/{batch_id}/traces/{case_id}--r{repeat}.narrative.json"


def _clip(text: str, limit: int = MAX_OUTPUT_CHARS) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[:limit] + f" ...[{len(text) - limit} chars cut]"


def digest(info: RunInfo, steps: list[Step]) -> str:
    """The Trace as compact text: the evidence the model is given, and nothing else."""
    lines = [f"## Run {info.run_id} (status: {info.status}; Harness model: {info.model_id})"]
    if info.error:
        lines.append(f"Run error: {_clip(info.error, 300)}")
    lines += ["", "## Steps"]
    for s in steps:
        a = s.attributes or {}
        head = (f"[{s.index}] {s.kind} {s.name} · model {a.get('model_id', '?')} · "
                f"{a.get('latency_ms', '?')} ms · {(a.get('usage') or {}).get('totalTokens', '?')} tokens"
                f" · retries {a.get('retries', 0)}")  # fmt: skip
        if s.kind == "judge":
            # The evaluation's verdict isn't the Harness's activity, and including it invites
            # the narrative to judge the Caption, which isn't its job.
            head += " · role: scoring (the evaluation, not the Harness; its verdict isn't shown)"
            lines.append(head)
            if a.get("fault"):
                lines.append(f"    fault: {a['fault']['attribution']}: {a['fault']['reason']}")
            continue
        lines.append(head)
        fault = a.get("fault")
        if fault:
            soft = " (Soft Failure)" if fault["soft"] else ""
            lines.append(f"    fault: {fault['attribution']}{soft}: {fault['reason']}")
        if s.error:
            lines.append(f"    error: {_clip(s.error, 400)}")
        for attempt in a.get("failed_attempts") or []:
            lines.append(f"    failed attempt {attempt.get('attempt')}: {attempt.get('error')}")
        if s.kind == "tool":
            lines.append(f"    arguments: {_clip(json.dumps(s.input, default=str), 600)}")
            lines.append(f"    output: {_clip(json.dumps(s.output, default=str))}")
            continue
        if isinstance(s.input, dict) and s.name == "caption":
            lines.append(f"    asked about image {s.input.get('image', {}).get('key', '?')}")
        out = s.output if isinstance(s.output, dict) else {}
        for block in out.get("content", []):
            if "toolUse" in block:
                lines.append(f"    submitted {block['toolUse'].get('name')}: "
                             f"{_clip(json.dumps(block['toolUse'].get('input'), default=str))}")  # fmt: skip
            elif "text" in block:
                lines.append(f"    said: {_clip(block['text'], 400)}")
        if out.get("stop_reason"):
            lines.append(f"    stop reason: {out['stop_reason']}")
    lines += ["", "## Final answer", info.final_answer or "(no Caption)"]
    facts = summarize(info, steps)
    lines += ["", "## Facts computed from the Trace", f"verdict: {facts['verdict']}"]
    lines += [f"struggled: {x}" for x in facts["struggled"]]
    return "\n".join(lines)


FAULT_TERMS = {"harness": "Harness Fault", "environment": "Environment Fault",
               "sandbox": "Sandbox Failure"}  # fmt: skip


def unsupported_faults(markdown: str, steps: list[Step]) -> list[str]:
    """Fault types the narrative names that no Step in the Trace has: grounds to reject it."""
    present = {(s.attributes.get("fault") or {}).get("attribution") for s in steps}
    return [term for key, term in FAULT_TERMS.items()
            if term.lower() in markdown.lower() and key not in present]  # fmt: skip


def trace_sha(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()[:16]


def narrate(client, model: str, info: RunInfo, steps: list[Step], trace_body: bytes) -> dict:
    """Ask the model for the narrative. Returns the record to save."""
    started = time.monotonic()
    resp = client.converse(
        modelId=model,
        system=[{"text": SYSTEM}],
        messages=[{"role": "user", "content": [{"text": digest(info, steps)}]}],
        inferenceConfig={"maxTokens": 700},
    )
    blocks = resp["output"]["message"]["content"]
    text = "\n".join(b["text"] for b in blocks if "text" in b).strip()
    return {
        "run_id": info.run_id,
        "markdown": text,
        "model": model,
        "usage": resp.get("usage", {}),
        "seconds": round(time.monotonic() - started, 2),
        "created": datetime.now(UTC).isoformat(timespec="seconds"),
        "trace_sha": trace_sha(trace_body),
    }


def summary_model() -> str:
    return os.environ.get("CLAYZER_SUMMARY_MODEL", DEFAULT_MODEL)


def narrate_batch(client, store, batch_id: str, results: list[dict], force: bool = False,
                  progress=print, workers: int = 4) -> dict:  # fmt: skip
    """Write a narrative for every Run that has a Trace and no narrative yet (or all, with
    `force`). Failures are reported and skipped: the code-written summary stays the fallback."""
    from concurrent.futures import ThreadPoolExecutor

    from clayzer.trace import loads, trace_key

    model = summary_model()

    def one(r):
        tkey = trace_key(batch_id, r["case_id"], r["repeat"])
        nkey = narrative_key(batch_id, r["case_id"], r["repeat"])
        if not store.exists(tkey):
            return "no trace"
        body = store.get(tkey)
        info, steps = loads(body)
        # A resumed Run gets a new Trace; a narrative of the old one would be wrong.
        if (
            not force
            and store.exists(nkey)
            and json.loads(store.get(nkey)).get("trace_sha") == trace_sha(body)
        ):
            return "skipped"
        try:
            record = narrate(client, model, info, steps, body)
        except Exception as e:  # noqa: BLE001 -- the code-written summary is the fallback
            return f"failed: {type(e).__name__}: {str(e)[:120]}"
        bad = unsupported_faults(record["markdown"], steps)
        if bad:
            # Don't save a narrative that invents faults; reports use the facts instead.
            if store.exists(nkey):
                store.delete(nkey)
            return f"rejected: names {', '.join(bad)}, which the Trace doesn't have"
        store.put(nkey, (json.dumps(record, indent=2) + "\n").encode(), "application/json")
        return "written"

    with ThreadPoolExecutor(max_workers=workers) as pool:
        outcomes = list(pool.map(one, results))
    counts = {k: sum(o == k for o in outcomes) for k in ("written", "skipped", "no trace")}
    failures = [o for o in outcomes if o.startswith("failed")]
    rejected = [o for o in outcomes if o.startswith("rejected")]
    counts["failed"], counts["rejected"] = len(failures), len(rejected)
    if rejected:
        progress(f"  {len(rejected)} narratives rejected ({rejected[0]}); "
                 "reports show the code-written summary for those Runs")  # fmt: skip
    if failures:
        progress(f"  {len(failures)} narratives failed (first: {failures[0]}); "
                 "reports show the code-written summary for those Runs")  # fmt: skip
    return counts
