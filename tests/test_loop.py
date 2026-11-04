"""The evaluation loop offline: Batches, Repeats, resume, compare, Baselines, regression gate.

A fake Bedrock client stands in for the Harness, the Judge, and the embedding model.
"""

import io
import json

import pytest
from botocore.exceptions import ClientError

from clayzer import batch as batches
from clayzer.cases import save_case
from clayzer.config import Settings
from clayzer.gate import accept_baseline, compare, gate, load_baseline, render_compare
from clayzer.store import LocalStore

SOLAR = {
    "id": "fixed-dev-solar",
    "chips": [{"id": "c-solar", "uri": "chips/c-solar.png", "date": "2022-07-02",
               "bbox": [0, 0, 1, 1], "source": "naip-pc"}],
    "reference_labels": [{"object": "solar_array", "count": 1, "position": "centre",
                          "cells": ["centre"], "attributes": {}, "source": "uspvdb",
                          "source_ids": ["1"]}],
    "prep_seconds": 10.0,
}  # fmt: skip
WIND = {
    **SOLAR,
    "id": "fixed-dev-wind",
    "chips": [{**SOLAR["chips"][0], "id": "c-wind", "uri": "chips/c-wind.png"}],
    "reference_labels": [{**SOLAR["reference_labels"][0], "object": "wind_turbine", "count": 2}],
}

CAPTIONS = {
    "c-solar": {"text": "A solar farm.", "objects": [
        {"id": "o1", "object": "solar_array", "count": 1, "position": "centre"}]},
    "c-wind": {"text": "Two wind turbines.", "objects": [
        {"id": "o1", "object": "wind_turbine", "count": 2, "position": "centre"}]},
}  # fmt: skip


class FakeBedrock:
    """Captions from CAPTIONS (keyed by the Chip's image bytes), fixed Judge verdicts, and
    bag-of-words embeddings. `fail` maps a call number to an exception to raise."""

    def __init__(self, fail=None, wrong=False, no_caption=()):
        self.calls, self.fail = 0, fail or {}
        self.wrong, self.no_caption = wrong, set(no_caption)

    def converse(self, modelId, messages, toolConfig, inferenceConfig):
        self.calls += 1
        if self.calls in self.fail:
            raise self.fail[self.calls]
        content = messages[0]["content"]
        chip = content[0]["image"]["source"]["bytes"].decode()
        name = toolConfig["tools"][0]["toolSpec"]["name"]
        usage = {"totalTokens": 100}
        if name == "submit_caption":
            if chip in self.no_caption:
                return {"output": {"message": {"content": [{"text": "no"}]}}, "usage": usage}
            cap = dict(CAPTIONS[chip], relations=[], uncertain=[])
            if self.wrong:
                cap["objects"] = [dict(cap["objects"][0], position="north_west", count=9)]
            tool_input = cap
        else:
            tool_input = {"score": 0.8, "issues": []}
        block = {"toolUse": {"toolUseId": "t", "name": name, "input": tool_input}}
        return {"output": {"message": {"content": [block]}}, "usage": usage}

    def invoke_model(self, modelId, body):
        text = json.loads(body)["inputText"].lower()
        vec = [float(w in text) for w in ("solar", "wind", "turbines", "farm", "find")]
        return {"body": io.BytesIO(json.dumps({"embedding": vec}).encode())}


def expired():
    return ClientError({"Error": {"Code": "ExpiredTokenException", "Message": "expired"}}, "x")


def throttled():
    return ClientError({"Error": {"Code": "ThrottlingException", "Message": "slow"}}, "x")


@pytest.fixture
def env(tmp_path, monkeypatch):
    store = LocalStore(tmp_path / "data", tmp_path / "batches")
    for case in (SOLAR, WIND):
        chip = case["chips"][0]["id"]
        store.put(f"chips/{chip}.png", chip.encode())
        save_case(store, "cases/caption-dev.jsonl", case)
    settings = Settings(
        caption_model="cap", judge_model="judge", embed_model="embed",
        bedrock_endpoint_url=None, data_dir=tmp_path / "data",
        batches_dir=tmp_path / "batches", baselines_dir=tmp_path / "baselines",
        store_url=None, naip_source="pc",
    )  # fmt: skip
    fake = {"client": FakeBedrock()}
    monkeypatch.setattr(batches, "bedrock", lambda s: fake["client"])
    return store, settings, fake


def run(env, label="", repeats=3, **fake_kwargs):
    store, settings, fake = env
    fake["client"] = FakeBedrock(**fake_kwargs)
    bid = batches.start([SOLAR, WIND], settings, store, repeats, label, "dev")
    return batches.load(store, bid)


def test_batch_runs_every_case_every_repeat_and_summarizes(env):
    b = run(env, "base")
    s = b["summary"]
    assert s["batch"]["runs"] == {"planned": 6, "ok": 6, "harness_faults": 0, "sandbox_failures": 0}
    assert s["cases"]["fixed-dev-solar"]["correctness"] == {"mean": 1.0, "spread": 0.0}
    assert s["cases"]["fixed-dev-solar"]["coverage"] == {"mean": 1.0, "spread": 0.0}
    assert s["cases"]["fixed-dev-wind"]["fidelity"]["mean"] == pytest.approx(0.8)
    assert s["batch"]["retrieval_mrr"]["mean"] == 1.0
    assert s["batch"]["label_prep_seconds"] == 20.0
    assert len(b["retrieval"]) == 3  # one corpus per Repeat
    store = env[0]
    assert store.exists(f"batches/{b['config'].batch_id}/report.html")
    assert "Repeat 3" in store.get(f"batches/{b['config'].batch_id}/report.html").decode()


def test_harness_fault_scores_zero_and_sandbox_failure_is_excluded(env):
    # Call 1 is solar#1's caption; call 3 is wind#1's caption; call 5 throttles solar#2.
    b = run(env, no_caption={"c-wind"}, fail={5: throttled()})
    runs = b["summary"]["batch"]["runs"]
    assert runs["harness_faults"] == 3 and runs["sandbox_failures"] == 1
    wind = b["summary"]["cases"]["fixed-dev-wind"]
    assert wind["correctness"]["mean"] == 0.0 and wind["coverage"]["mean"] == 0.0
    assert wind["harness_faults"] == 3
    assert b["summary"]["cases"]["fixed-dev-solar"]["runs"] == 2


def test_expired_credentials_stop_the_batch_and_resume_finishes_it(env):
    store, settings, fake = env
    b = run(env, fail={3: expired()})
    assert b["summary"]["stopped"].startswith("credentials expired after 1 of 6 Runs")
    assert len(b["results"]) == 1
    fake["client"] = FakeBedrock()
    summary = batches.resume(b["config"].batch_id, settings, store, progress=lambda _: None)
    assert summary["stopped"] is None
    assert summary["batch"]["runs"]["ok"] == 6


def test_resume_reruns_only_sandbox_failures(env):
    store, settings, fake = env
    b = run(env, fail={1: throttled()})
    assert b["summary"]["batch"]["runs"]["sandbox_failures"] == 1
    fake["client"] = FakeBedrock()
    summary = batches.resume(b["config"].batch_id, settings, store, progress=lambda _: None)
    assert summary["batch"]["runs"] == {
        "planned": 6, "ok": 6, "harness_faults": 0, "sandbox_failures": 0,
    }  # fmt: skip
    assert fake["client"].calls == 2  # one caption and one Judge call, nothing else re-run


def test_gate_passes_identical_batches_and_fails_a_regression(env):
    _, settings, _ = env
    base = run(env, "base")
    accept_baseline(base, settings.baselines_dir)
    baseline = load_baseline(settings.baselines_dir)

    same = gate(baseline, run(env, "same"))
    assert same.verdict == "pass" and same.exit_code == 0

    worse = gate(baseline, run(env, "worse", wrong=True))
    assert worse.verdict == "fail" and worse.exit_code == 1
    regressed = {(c.case_id, c.metric) for c in worse.checks if c.status == "regressed"}
    assert ("fixed-dev-solar", "correctness") in regressed
    assert ("fixed-dev-solar", "coverage") not in regressed  # it still mentions the array


def test_gate_is_inconclusive_with_sandbox_failures(env):
    _, settings, _ = env
    accept_baseline(run(env, "base"), settings.baselines_dir)
    result = gate(load_baseline(settings.baselines_dir), run(env, fail={1: throttled()}))
    assert result.verdict == "inconclusive" and result.exit_code == 2


def test_gate_fails_when_a_baseline_case_is_missing(env):
    store, settings, fake = env
    accept_baseline(run(env, "base"), settings.baselines_dir)
    fake["client"] = FakeBedrock()
    bid = batches.start([SOLAR], settings, store, 3, "solar-only", "dev")
    result = gate(load_baseline(settings.baselines_dir), batches.load(store, bid))
    assert result.verdict == "fail"
    assert any("missing" in r for r in result.reasons)


def test_baseline_refuses_incomplete_batches_and_keeps_scores_only(env):
    _, settings, _ = env
    with pytest.raises(ValueError, match="incomplete"):
        accept_baseline(run(env, fail={1: throttled()}), settings.baselines_dir)
    target = accept_baseline(run(env, "base"), settings.baselines_dir)
    row = json.loads((target / "results.jsonl").read_text().splitlines()[0])
    assert "rows" not in row["grounding"]  # no Claim rows, so no OSM-derived data


def test_compare_reports_setting_changes_and_deltas(env):
    a = run(env, "base")
    b = run(env, "worse", wrong=True)
    c = compare(a, b)
    assert c["settings"] == []  # same models and prompt; only the fake changed
    solar = next(
        r for r in c["cases"] if r["case_id"] == "fixed-dev-solar" and r["metric"] == "correctness"
    )
    assert solar["delta"] < 0
    assert "No settings changed" in render_compare(c)


def _summary(cases: dict) -> dict:
    """A minimal Batch summary for gate tests: {case_id: {metric: (mean, spread)}}."""
    return {
        "batch": {"retrieval_mrr": {"mean": None, "spread": None}, "tokens_per_caption": 100,
                  "runs": {"sandbox_failures": 0}},
        "cases": {cid: {m: {"mean": v[0], "spread": v[1]} for m, v in ms.items()}
                  for cid, ms in cases.items()},
    }  # fmt: skip


def _cfg(repeats=3):
    return batches.BatchConfig("id", "", "", "dev", repeats, [], "c", "cap", "j", "e", "p", "b")


def test_a_noisy_candidate_cannot_loosen_its_own_gate():
    base = {"config": _cfg(), "summary": _summary({"x": {"correctness": (0.6, 0.05)}})}
    noisy = {"config": _cfg(), "summary": _summary({"x": {"correctness": (0.3, 0.45)}})}
    result = gate(base, noisy)
    check = next(c for c in result.checks if c.metric == "correctness")
    assert check.allowed_drop == 0.05  # the Baseline's Spread, not the candidate's 0.45
    assert result.verdict == "fail"
    assert any("became erratic" in w for w in result.warnings)


def test_a_steady_candidate_is_not_warned_about_spread():
    base = {"config": _cfg(), "summary": _summary({"x": {"correctness": (0.6, 0.10)}})}
    same = {"config": _cfg(), "summary": _summary({"x": {"correctness": (0.62, 0.12)}})}
    result = gate(base, same)
    assert result.verdict == "pass"
    assert not any("erratic" in w for w in result.warnings)
