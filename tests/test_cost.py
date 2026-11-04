"""Verified Claims per dollar and per GPU-second: the Batch report, Compare, and a vaguer prompt
scoring worse on it than a specific one even though its grounding correctness is the same."""

import json

import pytest
from test_loop import SOLAR, FakeBedrock, env  # noqa: F401

from clayzer import batch as batches
from clayzer import cost
from clayzer.cases import save_case
from clayzer.gate import compare, render_compare
from clayzer.grounding import grounding
from clayzer.trace import Step

FARM = {
    **SOLAR,
    "id": "fixed-dev-farm",
    "chips": [{**SOLAR["chips"][0], "id": "c-farm", "uri": "chips/c-farm.png"}],
    "reference_labels": [
        SOLAR["reference_labels"][0],
        {**SOLAR["reference_labels"][0], "object": "road", "count": None, "position": "north",
         "cells": ["north"], "source": "osm"},
    ],
}  # fmt: skip
SPECIFIC = {"text": "A solar array with a road to the north.", "objects": [
    {"id": "o1", "object": "solar_array", "count": 1, "position": "centre"},
    {"id": "o2", "object": "road", "count": 1, "position": "north"}],
    "relations": [], "uncertain": []}  # fmt: skip
VAGUE = {"text": "A solar array.", "objects": [
    {"id": "o1", "object": "solar_array", "count": 1, "position": "centre"}],
    "relations": [], "uncertain": []}  # fmt: skip


class PricedBedrock(FakeBedrock):
    """Reports input and output tokens, and captions FARM specifically or vaguely by prompt."""

    def converse(self, modelId, messages, toolConfig=None, inferenceConfig=None, system=None):
        resp = super().converse(modelId, messages, toolConfig, inferenceConfig, system)
        vague = any("Be brief." in b.get("text", "") for m in messages for b in m["content"])
        resp["usage"] = {"inputTokens": 1000, "outputTokens": 60 if vague else 100,
                         "totalTokens": 1060 if vague else 1100}  # fmt: skip
        for block in resp["output"]["message"]["content"]:
            use = block.get("toolUse")
            if use and use["name"] == "submit_caption":
                use["input"] = dict(VAGUE if vague else SPECIFIC)
        return resp


def step(model="cap", role=None, n_in=1000, n_out=100, gpu=None):
    attrs = {"model_id": model, "cost": {"input_tokens": n_in, "output_tokens": n_out,
                                         "gpu_seconds": gpu}}  # fmt: skip
    if role:
        attrs["role"] = role
    return Step("r#1", 0, "llm", "caption", 0.0, 1.0, attributes=attrs)


def test_a_claim_is_verified_only_when_every_scored_part_is_right():
    labels = FARM["reference_labels"]
    assert cost.verified_claims(grounding(SPECIFIC, labels)) == 2
    wrong_cell = {**SPECIFIC, "objects": [dict(SPECIFIC["objects"][0], position="south"),
                                          SPECIFIC["objects"][1]]}  # fmt: skip
    assert cost.verified_claims(grounding(wrong_cell, labels)) == 1
    miscounted = {**SPECIFIC, "objects": [dict(SPECIFIC["objects"][0], count=4),
                                          SPECIFIC["objects"][1]]}  # fmt: skip
    assert cost.verified_claims(grounding(miscounted, labels)) == 1
    unlabelled = {**VAGUE, "objects": [{"id": "o1", "object": "building", "count": 1,
                                        "position": "centre"}]}  # fmt: skip
    assert cost.verified_claims(grounding(unlabelled, labels)) == 0


def test_run_cost_counts_the_harness_and_leaves_the_judge_out():
    steps = [step("us.amazon.nova-pro-v1:0"), step("judge", role="scoring", n_out=5000)]
    c = cost.run_cost(steps)
    assert (c["input_tokens"], c["output_tokens"]) == (1000, 100)
    assert c["usd"] == pytest.approx((1000 * 0.80 + 100 * 3.20) / 1e6)
    assert c["gpu_seconds"] is None
    assert cost.run_cost([step("an-unpriced-model")])["usd"] is None
    assert cost.run_cost([step("us.amazon.nova-pro-v1:0", gpu=2.5)])["gpu_seconds"] == 2.5


def test_a_vaguer_prompt_scores_worse_per_dollar_with_the_same_correctness(env, monkeypatch):  # noqa: F811
    store, settings, fake = env
    monkeypatch.setitem(cost.PRICES, "cap", (1.0, 10.0))
    store.put("chips/c-farm.png", b"c-solar")  # the fake keys its Caption on the image bytes
    save_case(store, "cases/caption-dev.jsonl", FARM)

    def run(prompt, label):
        fake["client"] = PricedBedrock()
        bid = batches.start([FARM], settings, store, 2, label, "dev", prompt=prompt)
        return batches.load(store, bid)

    from clayzer.harness import PROMPT

    specific, vague = run(PROMPT, "specific"), run(PROMPT + "\nBe brief.", "vague")
    s, v = specific["summary"]["batch"], vague["summary"]["batch"]
    assert s["correctness"] == v["correctness"] == 1.0
    assert v["usd_per_caption"] < s["usd_per_caption"]  # cheaper per Caption...
    assert v["verified_claims_per_dollar"] < s["verified_claims_per_dollar"]  # ...but worse
    assert s["verified_claims_per_caption"] == 2.0 and v["verified_claims_per_caption"] == 1.0
    assert s["verified_claims_per_gpu_second"] is None  # Bedrock has no GPU time

    report = store.get(f"batches/{specific['config'].batch_id}/report.md").decode()
    assert "| Verified Claims per dollar |" in report
    html = store.get(f"batches/{specific['config'].batch_id}/report.html").decode()
    assert "Verified Claims per dollar" in html

    rows = {r["metric"]: r for r in compare(specific, vague)["batch"]}
    per_dollar = rows["Verified Claims per dollar"]
    assert per_dollar["delta"] == pytest.approx(
        v["verified_claims_per_dollar"] - s["verified_claims_per_dollar"])  # fmt: skip
    assert rows["Dollars per 1,000 Captions"]["a"] == pytest.approx(1000 * s["usd_per_caption"])
    assert "| Verified Claims per dollar |" in render_compare(compare(specific, vague))


def test_rescore_backfills_cost_from_the_trace(env, monkeypatch):  # noqa: F811
    store, settings, fake = env
    monkeypatch.setitem(cost.PRICES, "cap", (1.0, 10.0))
    fake["client"] = PricedBedrock()
    bid = batches.start([SOLAR], settings, store, 1, "old", "dev")
    results = batches.load(store, bid)["results"]
    for r in results:
        r.pop("cost"), r.pop("verified_claims")
    store.put(f"batches/{bid}/results.jsonl",
              "".join(json.dumps(r) + "\n" for r in results).encode())  # fmt: skip
    summary = batches.rescore(bid, store)
    assert summary["batch"]["verified_claims_per_caption"] == 1.0
    assert summary["batch"]["usd_per_caption"] == pytest.approx((1000 * 1.0 + 100 * 10.0) / 1e6)
