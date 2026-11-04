"""Trace summaries (REQ-05): from the Trace alone, with no model."""

import json

from test_loop import SOLAR, WIND, env, expired, run, throttled  # noqa: F401

from clayzer import batch as batches
from clayzer.faults import attribute
from clayzer.summarize import summarize, summary_key, to_markdown
from clayzer.trace import RunInfo, Step

CAP = {"content": [{"toolUse": {"name": "submit_caption", "input": {
    "text": "t", "objects": [{"object": "solar_array"}, {"object": "road"}], "uncertain": ["x"]}}}]}  # fmt: skip
VERDICT = {"content": [{"toolUse": {"name": "submit_verdict", "input": {"score": 0.75}}}]}


def info(status="ok", error=None):
    return RunInfo("c#1", "caption", "c", 1, "b", "nova", "p", status=status, error=error)


def step(i, kind, name, output=None, error=None, **attrs):
    base = {"latency_ms": 3000.0, "model_id": "us.amazon.nova-pro-v1:0",
            "usage": {"totalTokens": 2500}}  # fmt: skip
    return Step("c#1", i, kind, name, 0, 3, {"image": {"key": "chips/c.png"}}, output, error,
                {**base, **attrs})  # fmt: skip


def finished(run_info, steps):
    run_info.metadata["faults"] = attribute(steps)
    return summarize(run_info, steps)


def test_a_clean_run():
    s = finished(info(), [step(0, "llm", "caption", CAP, expects_tool="submit_caption"),
                          step(1, "judge", "fidelity", VERDICT, expects_tool="submit_verdict")])  # fmt: skip
    assert s["verdict"] == "Captioned in 3.0 s: 2 Claims, 1 left uncertain."
    assert "submitted a Caption with 2 Claims, 1 thing left uncertain" in s["did"][0]
    assert "chips/c.png" in s["did"][0] and "2,500 tokens" in s["did"][0]
    assert s["struggled"] == ["Nothing notable."]
    assert "rated the Caption 0.75" in s["evaluation"][0]
    assert s["stats"]["steps"] == 1 and s["stats"]["tokens"] == 2500  # the Judge isn't counted


def test_a_harness_fault_says_whose_fault_and_why():
    s = finished(info("harness_fault"), [step(0, "llm", "caption", {"content": [{"text": "no"}]},
                                              expects_tool="submit_caption")])  # fmt: skip
    assert s["verdict"].startswith("Harness Fault: the model didn't call submit_caption")
    assert s["verdict"].endswith("No Caption.")
    assert "Harness Fault" in s["struggled"][0]


def test_throttling_is_the_environment_with_its_retries():
    s = finished(info("sandbox_failure", "throttled"), [step(
        0, "llm", "caption", None, "ClientError: slow", error_code="ThrottlingException", retries=3,
        failed_attempts=[{"attempt": 1, "error": "ThrottlingException"}])])  # fmt: skip
    assert s["verdict"].startswith("Environment Fault: ThrottlingException")
    assert any(
        "retried 3 times after ThrottlingException, then failed" in x for x in s["struggled"]
    )
    assert "the call failed" in s["did"][0]


def test_a_failed_judge_is_a_sandbox_failure_not_the_harness():
    s = finished(info("sandbox_failure", "judge: boom"), [
        step(0, "llm", "caption", CAP, expects_tool="submit_caption"),
        step(1, "judge", "fidelity", None, "ClientError: x", error_code="ThrottlingException")])  # fmt: skip
    assert s["verdict"].startswith("Sandbox Failure: judge: boom")
    assert s["stats"]["harness_faults"] == 0


def test_a_stopped_run():
    s = finished(info("stopped", "credentials expired: x"), [])
    assert s["verdict"].startswith("Stopped")
    assert any("stopped before finishing" in x for x in s["struggled"])
    assert "Verdict" not in to_markdown(s) and "**Stopped" in to_markdown(s)


def test_batches_write_summaries_and_rebuild_them_offline(env, monkeypatch):  # noqa: F811
    store = env[0]
    b = run(env, no_caption={"c-wind"}, fail={1: throttled()})
    bid = b["config"].batch_id
    s1 = json.loads(store.get(summary_key(bid, SOLAR["id"], 1)))
    assert s1["verdict"].startswith("Environment Fault")
    s2 = json.loads(store.get(summary_key(bid, WIND["id"], 2)))
    assert s2["verdict"].startswith("Harness Fault")

    store.delete(summary_key(bid, SOLAR["id"], 2))

    # Rebuilding needs no model: make any Bedrock call fail loudly.
    def no_model(*_):
        raise AssertionError("summaries must not call a model")

    monkeypatch.setattr(batches, "bedrock", no_model)
    assert batches.resummarize(bid, store) == 6
    assert store.exists(summary_key(bid, SOLAR["id"], 2))
    html = store.get(f"batches/{bid}/report.html").decode()
    assert "What the Harness did" in html and "Environment Fault" in html


def test_narratives_are_written_once_saved_and_replayed_without_a_model(env, monkeypatch):  # noqa: F811
    from clayzer.narrate import narrative_key

    store, _, fake = env
    b = run(env)
    bid = b["config"].batch_id
    first = fake["client"].narrations
    assert first == 6  # one per Run
    n = json.loads(store.get(narrative_key(bid, SOLAR["id"], 1)))
    assert n["markdown"].startswith("### What the Harness did") and n["trace_sha"]
    html = store.get(f"batches/{bid}/report.html").decode()
    assert "Written by" in html and "Facts from the Trace" in html

    # Replaying (rebuilding summaries and reports) never calls a model.
    def no_model(*_):
        raise AssertionError("replay must not call a model")

    monkeypatch.setattr(batches, "bedrock", no_model)
    batches.resummarize(bid, store)
    assert fake["client"].narrations == first


def test_the_digest_holds_only_the_trace(env):  # noqa: F811
    from clayzer.narrate import digest
    from clayzer.trace import loads, trace_key

    b = run(env, repeats=1)
    info_, steps = loads(env[0].get(trace_key(b["config"].batch_id, SOLAR["id"], 1)))
    text = digest(info_, steps)
    assert "submitted submit_caption" in text and "role: scoring" in text
    assert "reference_labels" not in text and "uspvdb" not in text  # no Answer Key data


def test_a_resumed_run_gets_a_fresh_narrative(env):  # noqa: F811
    from clayzer.narrate import narrative_key

    store, settings, fake = env
    b = run(env, fail={1: throttled()})
    bid = b["config"].batch_id
    old = json.loads(store.get(narrative_key(bid, SOLAR["id"], 1)))
    assert "sandbox_failure" in old["markdown"]
    fake["client"] = __import__("test_loop").FakeBedrock()
    batches.resume(bid, settings, store, progress=lambda _: None)
    new = json.loads(store.get(narrative_key(bid, SOLAR["id"], 1)))
    assert new["trace_sha"] != old["trace_sha"] and "ok" in new["markdown"]


def test_a_narrative_that_invents_a_fault_is_rejected():
    from clayzer.narrate import unsupported_faults

    clean = [step(0, "llm", "caption", CAP, expects_tool="submit_caption")]
    attribute(clean)
    assert unsupported_faults("- **Environment Fault:** the Judge disliked it", clean) == [
        "Environment Fault"
    ]
    assert unsupported_faults("### Where it struggled\n- Nothing notable.", clean) == []
    faulty = [step(0, "llm", "caption", None, "x", error_code="ThrottlingException")]
    attribute(faulty)
    assert unsupported_faults("An Environment Fault: throttled.", faulty) == []


def test_the_digest_hides_the_judges_verdict(env):  # noqa: F811
    from clayzer.narrate import digest
    from clayzer.trace import loads, trace_key

    b = run(env, repeats=1)
    info_, steps = loads(env[0].get(trace_key(b["config"].batch_id, SOLAR["id"], 1)))
    text = digest(info_, steps)
    assert "submit_verdict" not in text and "its verdict isn't shown" in text
