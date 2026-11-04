"""Opus 5.5 as a second captioner (issue #16): when the captioner is also the Judge, every report
that shows Fidelity says so (REQ-19), and Compare sets the two models side by side."""

import json
from dataclasses import replace

import pytest
from botocore.exceptions import ClientError
from test_agentic import Scripted, turn, use
from test_loop import SOLAR, WIND, FakeBedrock
from test_verify import FOOTPRINT, FakeLgnd, draft

from clayzer import batch as batches
from clayzer import harness, provenance
from clayzer.config import Settings
from clayzer.gate import compare, gate, render_compare
from clayzer.report import render
from clayzer.store import LocalStore
from clayzer.trace import RunInfo, Tracer

OPUS = "us.anthropic.claude-opus-5-5"
NOVA = "us.amazon.nova-pro-v1:0"


def refuse_forced_choice(model_id, tool_config):
    """What the real Opus 5.5 does with a forced tool choice (found by running it live)."""
    choice = (tool_config or {}).get("toolChoice", {})
    if "claude-opus-5" in model_id and ("tool" in choice or "any" in choice):
        message = 'tool_choice: type "tool" and "any" are not supported for this model.'
        raise ClientError(
            {"Error": {"Code": "ValidationException", "Message": message}}, "Converse"
        )


class StrictBedrock(FakeBedrock):
    """FakeBedrock that refuses what Opus 5.5 refuses, so a Run that forces the tool fails here
    as it does on Bedrock."""

    def converse(self, modelId, messages, toolConfig=None, inferenceConfig=None, system=None):
        refuse_forced_choice(modelId, toolConfig)
        return super().converse(modelId, messages, toolConfig, inferenceConfig, system)


class StrictScripted(Scripted):
    def converse(self, **request):
        refuse_forced_choice(request["modelId"], request.get("toolConfig"))
        return super().converse(**request)


def tracer():
    run = RunInfo(run_id="r", task="caption", case_id="c", repeat=1, batch_id="b",
                  model_id="m", prompt_sha="p")  # fmt: skip
    return Tracer(run, [])


@pytest.fixture
def env(tmp_path, monkeypatch):
    store = LocalStore(tmp_path / "data", tmp_path / "batches")
    for case in (SOLAR, WIND):
        store.put(f"chips/{case['chips'][0]['id']}.png", case["chips"][0]["id"].encode())
    settings = Settings(
        caption_model=NOVA, judge_model=OPUS, embed_model="embed",
        bedrock_endpoint_url=None, data_dir=tmp_path / "data",
        batches_dir=tmp_path / "batches", baselines_dir=tmp_path / "baselines",
        store_url=None, naip_source="pc",
    )  # fmt: skip
    monkeypatch.setattr(batches, "bedrock", lambda s: StrictBedrock())
    return store, settings


def run(env, caption_model, judge_model=OPUS, label="x"):
    store, settings = env
    settings = replace(settings, caption_model=caption_model, judge_model=judge_model)
    bid = batches.start([SOLAR, WIND], settings, store, 3, label, "dev", narrate=False,
                        progress=lambda _: None)  # fmt: skip
    return batches.load(store, bid)


def test_the_same_model_is_recognised_whatever_its_inference_profile_prefix():
    assert provenance.self_graded(OPUS, OPUS)
    assert provenance.self_graded(OPUS, "anthropic.claude-opus-5-5")  # no "us." prefix
    assert provenance.self_graded("global.anthropic.claude-opus-5-5", OPUS)
    assert not provenance.self_graded(NOVA, OPUS)
    assert not provenance.self_graded(OPUS, "us.anthropic.claude-haiku-4-5")
    assert not provenance.self_graded(OPUS, None)  # no Judge, nothing to be self-graded
    assert not provenance.self_graded(None, None)


def test_opus_is_asked_for_the_caption_tool_not_forced_to_use_it():
    # Run live, Opus 5.5 refused every Run: it rejects a forced tool choice. So for it the tool is
    # asked for in the prompt, as the Judge already does, and the choice is left to the model.
    assert not harness.forces_caption_tool(OPUS)
    assert not harness.forces_caption_tool("anthropic.claude-opus-5-5")
    assert harness.forces_caption_tool(NOVA)
    assert "toolChoice" not in harness.caption_tool_config(OPUS)
    assert harness.caption_tool_config(NOVA)["toolChoice"] == {"tool": {"name": "submit_caption"}}

    for model, recorded in ((OPUS, "auto"), (NOVA, "submit_caption")):
        t = tracer()
        cap, step = harness.caption(StrictBedrock(), model, "c-solar", b"c-solar", tracer=t)
        assert step["ok"] and cap["objects"][0]["object"] == "solar_array"
        assert t.steps[0].input["tool_choice"] == recorded  # the Trace says which it was


def test_the_rewrite_after_verification_does_not_force_the_tool_for_opus_either():
    d = draft()
    rewritten = {**d, "text": "A solar array and two buildings; a road west."}
    bedrock = StrictScripted(turn(use("submit_caption", d)),
                             turn(use("submit_caption", rewritten, "t2")))  # fmt: skip
    lgnd = FakeLgnd({"solar": "supported", "wind": "not supported", "building": "supported",
                     "road": "supported"})  # fmt: skip
    t = tracer()
    cap, _ = harness.caption(bedrock, OPUS, "chip", b"png", tracer=t, verifier=lgnd,
                             footprint=FOOTPRINT)  # fmt: skip
    assert cap["text"] == rewritten["text"]
    assert [s.input["tool_choice"] for s in t.steps if s.kind == "llm"] == ["auto", "auto"]


def test_a_whole_batch_can_use_opus_as_the_captioner(env):
    own = run(env, OPUS)
    assert [r["status"] for r in own["results"]] == ["ok"] * 6  # none refused
    assert own["summary"]["batch"]["correctness"] is not None
    assert provenance.self_graded(own["config"].caption_model, own["config"].judge_model)


def test_a_self_graded_batch_says_so_in_its_markdown_and_html_reports(env):
    own = run(env, OPUS)
    assert provenance.SELF_GRADED_NOTE in render(own)
    html = env[0].get(f"batches/{own['config'].batch_id}/report.html").decode()
    assert "Self-graded" in html


def test_a_batch_judged_by_a_different_model_is_not_flagged(env):
    other = run(env, NOVA)
    assert "Self-graded" not in render(other)
    html = env[0].get(f"batches/{other['config'].batch_id}/report.html").decode()
    assert "Self-graded" not in html


def test_each_runs_report_is_flagged_too(env):
    own = run(env, OPUS)
    store, cfg = env[0], own["config"]
    page = store.get(f"batches/{cfg.batch_id}/runs/{SOLAR['id']}--r1.html").decode()
    assert "Self-graded" in page
    detail = json.loads(store.get(f"batches/{cfg.batch_id}/runs/{SOLAR['id']}--r1.json"))
    assert detail["config"]["self_graded"] is True


def test_compare_sets_nova_against_opus_per_criterion_and_per_case_and_flags_the_self_graded(env):
    nova, opus = run(env, NOVA, label="nova"), run(env, OPUS, label="opus")
    c = compare(nova, opus)
    assert c["self_graded"] == {"a": False, "b": True}
    assert {s["setting"]: s["kind"] for s in c["settings"]}["caption_model"] == "captioner"
    # Per criterion and per Case, as the issue asks.
    assert {r["metric"] for r in c["batch"]} >= {
        "Grounding correctness",
        "Fidelity",
        "Retrieval (MRR)",
    }
    assert {(r["case_id"], r["metric"]) for r in c["cases"]} >= {
        (SOLAR["id"], "fidelity"), (WIND["id"], "correctness")}  # fmt: skip
    assert "Batch B is self-graded" in render_compare(c)


def test_the_gate_warns_when_only_one_side_is_self_graded(env):
    nova, opus = run(env, NOVA, label="nova"), run(env, OPUS, label="opus")
    warnings = gate(nova, opus).warnings
    assert any("candidate is self-graded" in w for w in warnings)
    assert not any("self-graded" in w for w in gate(nova, run(env, NOVA, label="again")).warnings)
