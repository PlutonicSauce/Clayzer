"""The Workflow Score (REQ-06): from the Trace alone, deterministic, Environment Faults excluded."""

import json

import pytest
from test_loop import SOLAR, env, run  # noqa: F401

from clayzer import batch as batches
from clayzer.faults import attribute
from clayzer.run_report import run_keys
from clayzer.trace import RunInfo, Step
from clayzer.workflow import score

SUBMIT = {"content": [{"toolUse": {"name": "submit_caption", "input": {}}}]}
CALL = {"content": [{"toolUse": {"name": "search_datasets", "input": {}}}]}
NO_CALL = {"content": [{"text": "hmm"}]}


def info(status="ok", tools=(), turns=None):
    i = RunInfo("c#1", "caption", "c", 1, "b", "nova", "p", tools=list(tools), status=status)
    if turns:
        i.metadata["turn_budget"] = turns
    return i


def llm(i, output, **a):
    return Step("c#1", i, "llm", "caption", 0, 1, {}, output, None,
                {"usage": {"totalTokens": 1000}, **a})  # fmt: skip


def tool(i, name, output="ok", error=None, server="roda", **a):
    return Step("c#1", i, "tool", name, 0, 1, {}, output, error, {"server": server, **a})


def scored(run_info, steps, **kw):
    attribute(steps)
    return score(run_info, steps, **kw)


def test_the_single_call_harness_is_scored_on_completion_alone():
    wf = scored(info(), [llm(0, SUBMIT, expects_tool="submit_caption")])
    assert wf["score"] == 1.0
    parts = {k: c["score"] for k, c in wf["components"].items()}
    assert parts["completion"] == 1.0
    assert all(
        parts[k] is None for k in ("tool_plan", "tool_success", "recovery", "efficiency", "cost")
    )
    assert "single-call" in wf["components"]["tool_plan"]["reason"]


def test_a_harness_fault_run_scores_zero():
    wf = scored(info("harness_fault"), [llm(0, NO_CALL, expects_tool="submit_caption")])
    assert wf["score"] == 0.0


@pytest.mark.parametrize("status", ["sandbox_failure", "stopped"])
def test_runs_without_a_valid_score_get_no_workflow_score(status):
    assert scored(info(status), [llm(0, SUBMIT)]) is None


def test_a_good_tool_using_run():
    steps = [
        llm(0, CALL),
        tool(1, "search_datasets"),
        llm(2, SUBMIT, expects_tool="submit_caption"),
    ]
    wf = scored(info(tools=["roda"], turns={"max_turns": 8, "turns": 2, "exhausted": False}), steps)
    c = wf["components"]
    assert c["tool_plan"]["score"] == 1.0 and c["tool_success"]["score"] == 1.0
    assert c["efficiency"]["score"] == 1.0 and c["recovery"]["score"] is None
    assert wf["score"] == 1.0


def test_harness_faults_count_and_recovery_is_credited():
    steps = [llm(0, CALL), tool(1, "search_datasets", "Error: not found"),
             tool(2, "search_datasets", "3 datasets"), llm(3, SUBMIT)]  # fmt: skip
    wf = scored(info(tools=["roda"]), steps)
    c = wf["components"]
    assert c["tool_success"]["score"] == 0.5  # one ok, one Soft Failure
    assert c["recovery"]["score"] == 1.0 and "1 of 1" in c["recovery"]["reason"]


def test_environment_faults_never_lower_the_score():
    steps = [llm(0, CALL), tool(1, "search_datasets", None, "x", error_code="ThrottlingException",
                                is_error=True), tool(2, "search_datasets"), llm(3, SUBMIT)]  # fmt: skip
    wf = scored(info(tools=["roda"]), steps)
    assert wf["components"]["tool_success"]["score"] == 1.0
    assert wf["environment_faults"] == 1


def test_calling_a_forbidden_server_fails_the_plan():
    steps = [llm(0, CALL), tool(1, "search", server="openstreetmap-mcp-server"), llm(2, SUBMIT)]
    plan = scored(info(tools=["osm"]), steps)["components"]["tool_plan"]
    assert plan["score"] == 0.5 and "Answer Key" in plan["reason"]


def test_running_out_of_turns_and_a_token_budget():
    steps = [llm(i, CALL) for i in range(3)]
    wf = scored(info(tools=["roda"], turns={"max_turns": 3, "turns": 3, "exhausted": True}),
                steps, token_budget=2000)  # fmt: skip
    c = wf["components"]
    assert c["efficiency"]["score"] == 0.0
    assert c["cost"]["score"] == pytest.approx(2000 / 3000)


def test_batches_record_summarize_gate_and_report_it(env):  # noqa: F811
    store = env[0]
    b = run(env, repeats=2)
    bid = b["config"].batch_id
    assert all(r["workflow"]["score"] == 1.0 for r in b["results"])
    assert b["summary"]["cases"][SOLAR["id"]]["workflow"] == {"mean": 1.0, "spread": 0.0}
    assert b["summary"]["batch"]["workflow"] == 1.0
    html = store.get(run_keys(bid, SOLAR["id"], 1)[0]).decode()
    assert "How the Harness worked" in html and "submitted a Caption" in html
    rec = json.loads(store.get(run_keys(bid, SOLAR["id"], 1)[1]))
    assert rec["workflow"]["score"] == 1.0

    # Rescoring recomputes it from the stored Traces.
    for r in b["results"]:
        r.pop("workflow")
    store.put(
        f"batches/{bid}/results.jsonl", "".join(json.dumps(r) + "\n" for r in b["results"]).encode()
    )
    summary = batches.rescore(bid, store)
    assert summary["batch"]["workflow"] == 1.0

    from clayzer.gate import accept_baseline, gate, load_baseline

    _, settings, _ = env
    accept_baseline(batches.load(store, bid), settings.baselines_dir)
    result = gate(load_baseline(settings.baselines_dir), batches.load(store, bid))
    assert any(c.metric == "workflow" for c in result.checks) and result.verdict == "pass"
