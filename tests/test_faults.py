"""Fault attribution (ADR-0003): each failed Step is the Harness's, the environment's, or the
Sandbox's, from what the Trace records."""

import pytest
from test_loop import SOLAR, WIND, env, expired, run, throttled  # noqa: F401

from clayzer.faults import attribute, classify
from clayzer.trace import Step, loads, trace_key


def step(kind="llm", error=None, output=None, **attributes):
    return Step("r#1", 0, kind, "x", 0.0, 1.0, {}, output, error, attributes)


TOOL_CALL = {"content": [{"toolUse": {"name": "submit_caption", "input": {}}}]}
NO_CALL = {"content": [{"text": "I can't"}]}


@pytest.mark.parametrize("code", ["ThrottlingException", "ServiceUnavailableException",
                                  "ReadTimeoutError", "ExpiredTokenException", "AccessDeniedException",
                                  "AuthorizationRequired"])  # fmt: skip
def test_environment_failures_dont_count_against_the_harness(code):
    fault = classify(step(error="boom", error_code=code))
    assert fault["attribution"] == "environment"


def test_http_429_and_5xx_are_environment():
    assert (
        classify(step(error="x", error_code="Weird", http_status=503))["attribution"]
        == "environment"
    )
    assert (
        classify(step(error="x", error_code="Weird", http_status=429))["attribution"]
        == "environment"
    )


def test_a_bad_request_and_an_unknown_failure_are_the_harness():
    assert classify(step(error="x", error_code="ValidationException"))["attribution"] == "harness"
    unknown = classify(step(error="x", error_code="SomethingNew", http_status=400))
    assert unknown["attribution"] == "harness" and "defaults to harness" in unknown["reason"]


def test_a_missing_tool_call_is_the_harness_for_the_captioner_and_the_sandbox_for_the_judge():
    assert classify(step(output=NO_CALL, expects_tool="submit_caption"))["attribution"] == "harness"
    assert classify(step(output=TOOL_CALL, expects_tool="submit_caption")) is None
    judge = classify(step(kind="judge", output=NO_CALL, expects_tool="submit_verdict"))
    assert judge["attribution"] == "sandbox"
    assert (
        classify(step(kind="judge", error="x", error_code="ThrottlingException"))["attribution"]
        == "sandbox"
    )


def test_soft_failures_are_caught_from_a_successful_tool_response():
    soft = classify(step(kind="tool", output={"text": "Error: dataset not found"}))
    assert soft["soft"] is True and soft["attribution"] == "harness"
    assert classify(step(kind="tool", output={"text": "3 items, all ok"})) is None


def test_attribute_counts_and_marks_steps():
    steps = [
        step(error="x", error_code="ThrottlingException"),
        step(output=NO_CALL, expects_tool="submit_caption"),
        step(kind="tool", output="permission denied"),
        step(output=TOOL_CALL, expects_tool="submit_caption"),
    ]
    counts = attribute(steps)
    assert counts == {"harness": 2, "environment": 1, "sandbox": 0, "soft": 1}
    assert (
        "fault" not in steps[3].attributes
        and steps[0].attributes["fault"]["attribution"] == "environment"
    )


def test_faults_reach_the_trace_the_run_result_and_the_batch_summary(env):  # noqa: F811
    # solar#1's caption is throttled; wind never calls submit_caption.
    b = run(env, no_caption={"c-wind"}, fail={1: throttled()})
    bid = b["config"].batch_id
    info, steps = loads(env[0].get(trace_key(bid, SOLAR["id"], 1)))
    assert steps[0].attributes["fault"]["attribution"] == "environment"
    assert info.metadata["faults"]["environment"] == 1
    info, steps = loads(env[0].get(trace_key(bid, WIND["id"], 1)))
    assert steps[0].attributes["fault"]["attribution"] == "harness"
    by_run = {r["run_id"]: r for r in b["results"]}
    assert by_run[f"{WIND['id']}#2"]["faults"]["harness"] == 1
    totals = b["summary"]["batch"]["step_faults"]
    assert totals["environment"] == 1 and totals["harness"] == 3  # 3 wind Runs
