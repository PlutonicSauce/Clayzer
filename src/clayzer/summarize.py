"""Trace summaries: what the Harness did, where it struggled and whose fault, and a one-line
verdict, from the Trace alone (REQ-05).

Written by code, not a model: a recorded Run must be reportable with no model, credentials, or
network (REQ-09), and the same Trace always gets the same summary. The Sandbox summarizes with a
model instead; a model-written narrative can sit on top of this one once agentic Traces are long
enough to need it.

Faults come from the attribution already on each Step (faults.py, ADR-0003).
"""

from __future__ import annotations

import json

from clayzer.trace import RunInfo, Step

_STATUS_VERDICT = {
    "harness_fault": "Harness Fault",
    "sandbox_failure": "Sandbox Failure",
    "stopped": "Stopped",
    "running": "Didn't finish",
}


def _secs(ms) -> str:
    return "?" if ms is None else f"{ms / 1000:.1f} s"


def _tokens(step: Step) -> str:
    n = (step.attributes.get("usage") or {}).get("totalTokens")
    return f", {n:,} tokens" if n else ""


def _model(step: Step) -> str:
    return (step.attributes.get("model_id") or "the model").removeprefix("us.")


SUBMIT = {"caption": "submit_caption", "fidelity": "submit_verdict"}


def _tool_calls(step: Step) -> list[dict]:
    out = step.output if isinstance(step.output, dict) else {}
    return [b["toolUse"] for b in out.get("content", []) if "toolUse" in b]


def _submitted(step: Step) -> dict | None:
    """What a model step submitted through its final tool (submit_caption or submit_verdict).
    Calls to other tools, such as MCP tools in an agentic Run, aren't submissions."""
    want = SUBMIT.get(step.name)
    for call in _tool_calls(step):
        if call.get("name") == want:
            return call.get("input") or {}
    return None


def _describe(step: Step) -> str:
    """One plain-language line for a Step."""
    took = f" ({_secs(step.attributes.get('latency_ms'))}{_tokens(step)})"
    if step.kind == "tool":
        args = ", ".join(f"{k}={json.dumps(v)[:40]}" for k, v in (step.input or {}).items())
        result = "failed" if step.error else "returned"
        return f"Called the tool {step.name}({args}): {result}{took}"
    image = (step.input or {}).get("image") or {}
    # A Change Case's Step records its Chip Pair as a list, earlier first.
    if isinstance(image, list):
        image = "the Chip Pair " + " → ".join(i.get("key", "?") for i in image)
    else:
        image = image.get("key", "the Chip")
    if step.name == "caption":
        if step.error:
            return f"Asked {_model(step)} to caption {image}: the call failed{took}"
        cap = _submitted(step)
        others = [c.get("name") for c in _tool_calls(step) if c.get("name") != SUBMIT["caption"]]
        if cap is None and others:
            return f"Asked {_model(step)} about {image}: it called {', '.join(others)}{took}"
        if cap is None:
            return f"Asked {_model(step)} to caption {image}: it answered without submitting a Caption{took}"
        n, unsure = len(cap.get("objects", [])), len(cap.get("uncertain", []))
        return (f"Asked {_model(step)} to caption {image}: it submitted a Caption with "
                f"{n} Claim{'s' if n != 1 else ''}"
                + (f", {unsure} thing{'s' if unsure != 1 else ''} left uncertain" if unsure else "")
                + took)  # fmt: skip
    if step.name == "fidelity":
        verdict = _submitted(step)
        if step.error or verdict is None:
            return f"The Judge ({_model(step)}) failed to rate the Caption{took}"
        return f"The Judge ({_model(step)}) rated the Caption {verdict.get('score', '?')}{took}"
    return f"{step.kind} step {step.name}{took}"


def _struggles(info: RunInfo, steps: list[Step]) -> list[str]:
    out = []
    for s in steps:
        fault = s.attributes.get("fault")
        if fault:
            who = {"harness": "Harness Fault", "environment": "Environment Fault",
                   "sandbox": "Sandbox Failure"}[fault["attribution"]]  # fmt: skip
            soft = " (a Soft Failure: the call reported success)" if fault["soft"] else ""
            out.append(f"Step {s.index} ({s.name}): {who}{soft}. {fault['reason']}.")
        retries = s.attributes.get("retries") or 0
        if retries:
            codes = sorted(
                {
                    a.get("error")
                    for a in s.attributes.get("failed_attempts") or []
                    if a.get("error")
                }
            )
            why = f" after {', '.join(codes)}" if codes else ""
            outcome = "then failed" if s.error else "then succeeded"
            out.append(f"Step {s.index} ({s.name}) was retried {retries} time{'s' if retries != 1 else ''}{why}, "
                       f"{outcome}. Retries are the environment's, not the Harness's.")  # fmt: skip
    if info.status == "stopped":
        out.append(f"The Run stopped before finishing: {info.error}.")
    return out


def _verdict(info: RunInfo, harness: list[Step]) -> str:
    took = sum(s.attributes.get("latency_ms") or 0 for s in harness)
    if info.status == "ok":
        # The last turn that submitted a Caption is the Run's answer.
        cap = next((_submitted(s) for s in reversed(harness)
                    if s.name == "caption" and _submitted(s) is not None), None)  # fmt: skip
        if cap is not None:
            n, unsure = len(cap.get("objects", [])), len(cap.get("uncertain", []))
            extra = f", {unsure} left uncertain" if unsure else ""
            return f"Captioned in {_secs(took)}: {n} Claim{'s' if n != 1 else ''}{extra}."
        return f"Finished in {_secs(took)}."
    failed = next((s for s in harness if s.attributes.get("fault")), None)
    if failed:
        label = {"harness": "Harness Fault", "environment": "Environment Fault",
                 "sandbox": "Sandbox Failure"}[failed.attributes["fault"]["attribution"]]  # fmt: skip
        why = failed.attributes["fault"]["reason"]
    else:
        label = _STATUS_VERDICT.get(info.status, info.status)
        why = info.error or "no reason recorded"
    caption = (
        " No Caption."
        if info.status in ("harness_fault", "stopped")
        or (info.status == "sandbox_failure" and not info.final_answer)
        else ""
    )
    return f"{label}: {why}.{caption}"


def summarize(info: RunInfo, steps: list[Step]) -> dict:
    """A Run's summary from its Trace alone."""
    harness = [s for s in steps if s.kind != "judge"]
    evaluation = [s for s in steps if s.kind == "judge"]
    faults = info.metadata.get("faults") or {}
    if info.status == "sandbox_failure" and not any(s.attributes.get("fault") for s in harness):
        # The Harness did its part; the evaluation failed.
        verdict = (
            f"Sandbox Failure: {info.error or 'the evaluation failed'}. The Run has no valid score."
        )
    else:
        verdict = _verdict(info, harness)
    struggled = _struggles(info, steps)
    return {
        "run_id": info.run_id,
        "status": info.status,
        "verdict": verdict,
        "did": [_describe(s) for s in harness] or ["Nothing: the Run has no Harness Steps."],
        "struggled": struggled or ["Nothing notable."],
        "evaluation": [_describe(s) for s in evaluation],
        "stats": {
            "steps": len(harness),
            "tool_calls": sum(s.kind == "tool" for s in harness),
            "retries": sum(s.attributes.get("retries") or 0 for s in steps),
            "harness_faults": faults.get("harness", 0),
            "environment_faults": faults.get("environment", 0),
            "seconds": round(sum(s.attributes.get("latency_ms") or 0 for s in harness) / 1000, 2),
            "tokens": sum(
                (s.attributes.get("usage") or {}).get("totalTokens") or 0 for s in harness
            ),
        },
    }


def to_markdown(summary: dict) -> str:
    lines = [f"**{summary['verdict']}**", "", "What the Harness did:"]
    lines += [f"- {x}" for x in summary["did"]]
    lines += ["", "Where it struggled:"] + [f"- {x}" for x in summary["struggled"]]
    if summary["evaluation"]:
        lines += ["", "Evaluation:"] + [f"- {x}" for x in summary["evaluation"]]
    return "\n".join(lines) + "\n"


def summary_key(batch_id: str, case_id: str, repeat: int) -> str:
    return f"batches/{batch_id}/traces/{case_id}--r{repeat}.summary.json"


class SummarySink:
    """Writes each Run's summary next to its Trace, so reports can show it without a model."""

    def __init__(self, store):
        self.store = store

    def write(self, run: RunInfo, steps: list[Step]) -> None:
        body = json.dumps(summarize(run, steps), indent=2) + "\n"
        self.store.put(summary_key(run.batch_id, run.case_id, run.repeat), body.encode(),
                       "application/json")  # fmt: skip
