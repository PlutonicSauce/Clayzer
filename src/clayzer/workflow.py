"""The Workflow Score: how well the Harness worked, from its Trace alone (REQ-06).

The brief's first score dimension, beside the Output Score. Deterministic: no model call, so it
replays from a recorded Trace. A weighted mean of components, each in [0, 1] with a one-line
reason. A component that doesn't apply (no tools, no Harness Faults to recover from, no budget)
is left out of the mean rather than counted as a pass or a fail. Environment Faults never lower
it (ADR-0003). The components and weights are the Sandbox's (breaking-barriers
scoring/workflow.py), so the two Tasks' Workflow Scores mean the same thing; the checks are
defined for caption Runs.

Judge Steps (`role: scoring`) are the evaluation's work, not the Harness's, and are ignored.
"""

from __future__ import annotations

import os

from clayzer.trace import RunInfo, Step

WEIGHTS = {
    "completion": 0.20,
    "tool_plan": 0.30,
    "tool_success": 0.20,
    "recovery": 0.15,
    "efficiency": 0.15,
    "cost": 0.10,
}

# MCP servers the caption Harness must never call: they read an Answer Key (ADR-0006,
# caption-plan.md §3). Matched against a tool Step's server and tool name.
FORBIDDEN = ("openstreetmap", "osm", "nominatim", "overture")

# Runs without a valid score get no Workflow Score either.
NO_SCORE = {"sandbox_failure", "stopped", "running"}


def _component(score, reason) -> dict:
    return {"score": score, "reason": reason}


def _submitted(step: Step) -> bool:
    out = step.output if isinstance(step.output, dict) else {}
    return any(b.get("toolUse", {}).get("name") == "submit_caption" for b in out.get("content", []))


def _fault(step: Step) -> str | None:
    return (step.attributes.get("fault") or {}).get("attribution")


def _completion(info: RunInfo, llm: list[Step]) -> dict:
    if info.status == "ok" and any(_submitted(s) for s in llm):
        return _component(1.0, "submitted a Caption")
    return _component(0.0, f"ended as {info.status.replace('_', ' ')} without a Caption")


def _tool_plan(info: RunInfo, llm: list[Step], tools: list[Step]) -> dict:
    if not info.tools and not tools:
        return _component(None, "single-call Harness: no tool plan to judge")
    checks = [(bool(llm) and _submitted(llm[-1]), "finished through submit_caption")]
    bad = sorted({
        s.attributes.get("server") or s.name for s in tools
        if any(f in f"{s.attributes.get('server', '')} {s.name}".lower() for f in FORBIDDEN)
    })  # fmt: skip
    checks.append((not bad, "called no forbidden MCP server" if not bad
                   else f"called {', '.join(bad)}, which reads an Answer Key (ADR-0006)"))  # fmt: skip
    failed = [label for ok, label in checks if not ok]
    reason = "all checks passed" if not failed else "failed: " + "; ".join(failed)
    return _component(sum(ok for ok, _ in checks) / len(checks), reason)


def _tool_success(tools: list[Step]) -> dict:
    ok = sum(1 for s in tools if _fault(s) is None)
    harness = sum(1 for s in tools if _fault(s) == "harness")
    env = sum(1 for s in tools if _fault(s) == "environment")
    if ok + harness == 0:
        return _component(None, "no tool calls to judge" if not env
                          else f"only Environment Faults ({env}), which don't count")  # fmt: skip
    extra = f"; {env} Environment Faults excluded" if env else ""
    return _component(ok / (ok + harness), f"{ok} ok, {harness} Harness Faults{extra}")


def _recovery(tools: list[Step]) -> dict:
    faults = [i for i, s in enumerate(tools) if _fault(s) == "harness"]
    if not faults:
        return _component(None, "no Harness Faults to recover from")
    recovered = sum(
        1 for i in faults
        if any(_fault(t) is None and t.name == tools[i].name for t in tools[i + 1:])
    )  # fmt: skip
    return _component(recovered / len(faults),
                      f"{recovered} of {len(faults)} Harness Faults followed by a successful call "
                      "to the same tool")  # fmt: skip


def _efficiency(info: RunInfo, llm: list[Step]) -> dict:
    budget = info.metadata.get("turn_budget")
    if not budget:
        return _component(None, "single-call Harness: no turn budget")
    turns, max_turns = budget.get("turns", len(llm)), budget["max_turns"]
    if budget.get("exhausted"):
        return _component(0.0, f"used all {max_turns} turns without submitting")
    return _component(1.0, f"{turns} of {max_turns} turns")


def _cost(llm: list[Step], token_budget: int | None) -> dict:
    if not token_budget:
        return _component(None, "no token budget (set CLAYZER_TOKEN_BUDGET)")
    used = sum((s.attributes.get("usage") or {}).get("totalTokens") or 0 for s in llm)
    if used <= token_budget:
        return _component(1.0, f"{used:,} tokens within the budget of {token_budget:,}")
    return _component(token_budget / used, f"{used:,} tokens, over the budget of {token_budget:,}")


def score(info: RunInfo, steps: list[Step], token_budget: int | None = None) -> dict | None:
    """The Run's Workflow Score, or None when the Run has no valid score."""
    if info.status in NO_SCORE:
        return None
    if token_budget is None:
        token_budget = int(os.environ.get("CLAYZER_TOKEN_BUDGET") or 0) or None
    harness = [s for s in steps if s.kind != "judge"]
    llm = [s for s in harness if s.kind == "llm"]
    tools = [s for s in harness if s.kind == "tool"]
    components = {
        "completion": _completion(info, llm),
        "tool_plan": _tool_plan(info, llm, tools),
        "tool_success": _tool_success(tools),
        "recovery": _recovery(tools),
        "efficiency": _efficiency(info, llm),
        "cost": _cost(llm, token_budget),
    }
    used = {k: c["score"] for k, c in components.items() if c["score"] is not None}
    weight = sum(WEIGHTS[k] for k in used)
    overall = sum(WEIGHTS[k] * v for k, v in used.items()) / weight if weight else None
    return {
        "score": round(overall, 4) if overall is not None else None,
        "components": components,
        "environment_faults": sum(1 for s in harness if _fault(s) == "environment"),
    }
