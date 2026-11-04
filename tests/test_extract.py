"""Claims from free text: extraction, its record, grounding without a guess, and calibration."""

import json

import pytest
from test_agentic import Scripted, turn, use
from test_loop import SOLAR, WIND, FakeBedrock

from clayzer import batch as batches
from clayzer.config import Settings
from clayzer.extract import agreement, batch_items, calibrate, extract
from clayzer.faults import classify
from clayzer.grounding import grounding
from clayzer.store import LocalStore
from clayzer.trace import RunInfo, Tracer, loads

SAID = {
    "objects": [
        {"id": "o1", "object": "solar_array", "count": 1, "position": "centre"},
        {"id": "o2", "object": "road", "count": None, "position": None},
        {"id": "o3", "object": "castle", "count": 1, "position": "north"},
        {"id": "o4", "object": "building", "count": 0, "position": "middle"},
    ],
    "relations": [
        {"subject": "o2", "relation": "west_of", "object": "o1"},
        {"subject": "o3", "relation": "north_of", "object": "o1"},
    ],
    "uncertain": ["possibly a pond"],
}


def tracer():
    run = RunInfo(run_id="r", task="extract", case_id="c", repeat=1, batch_id="b",
                  model_id="m", prompt_sha="")  # fmt: skip
    return Tracer(run, [])


def test_extraction_reads_only_the_text_and_keeps_what_it_doesnt_say_unsaid():
    bedrock, t = Scripted(turn(use("submit_claims", SAID))), tracer()
    claims, step = extract(bedrock, "m", "A solar farm in the middle, a road to its west.", t)
    assert claims["objects"] == [
        {"id": "o1", "object": "solar_array", "count": 1, "position": "centre"},
        {"id": "o2", "object": "road", "count": None, "position": None},
        {"id": "o4", "object": "building", "count": None, "position": None},
    ]  # an unknown type dropped; a bad count or cell becomes "not stated"
    assert claims["relations"] == [{"subject": "o2", "relation": "west_of", "object": "o1"}]
    assert claims["uncertain"] == ["possibly a pond"] and step["ok"]
    (request,) = bedrock.requests
    content = request["messages"][0]["content"]
    assert all("image" not in c for c in content) and "toolChoice" not in request["toolConfig"]
    prompt = content[0]["text"]
    assert "solar farm" in prompt and "train tracks" in prompt and "north_west" in prompt
    assert prompt.rstrip().endswith("A solar farm in the middle, a road to its west.")
    (s,) = t.steps
    assert (s.kind, s.name, s.attributes["role"]) == ("judge", "extract_claims", "scoring")


def test_no_claims_submitted_is_a_sandbox_failure():
    t = tracer()
    with pytest.raises(RuntimeError, match="no submit_claims"):
        extract(Scripted(turn(text="I can't.")), "m", "A field.", t)
    assert classify(t.steps[0])["attribution"] == "sandbox"


def test_grounding_skips_counts_and_positions_the_text_didnt_give():
    labels = [{"object": "solar_array", "count": 2, "position": "south_east",
               "cells": ["south_east"], "attributes": {}}]  # fmt: skip
    vague = {"objects": [{"id": "o1", "object": "solar_array", "count": None, "position": None}],
             "relations": []}  # fmt: skip
    g = grounding(vague, labels)
    assert g["position"] is None and g["count"] is None and g["counts"] == {}
    exact = {"objects": [{"id": "o1", "object": "solar_array", "count": 2,
                          "position": "south_east"}], "relations": []}  # fmt: skip
    assert grounding(exact, labels)["position"] == 1.0 and grounding(exact, labels)["count"] == 1.0
    assert g["coverage"] == grounding(exact, labels)["coverage"]  # presence still counts


def test_agreement_compares_types_counts_and_positions():
    def objs(*o):
        return {"objects": [{"id": f"o{i}", "object": t, "count": n, "position": p}
                            for i, (t, n, p) in enumerate(o)]}  # fmt: skip

    pairs = [
        (objs(("solar_array", 1, "centre"), ("road", None, "west")),
         objs(("solar_array", 1, "centre"), ("road", 1, "north_west"))),
        (objs(("building", 3, None), ("water", 1, "south")),
         objs(("building", 2, "east"), ("field", 1, "north"))),
    ]  # fmt: skip
    a = agreement(pairs)
    assert a["captions"] == 2
    assert (a["type_precision"], a["type_recall"]) == (0.75, 0.75)  # 3 shared, 1 extra, 1 missed
    assert a["count_exact"] == 0.5  # solar 1=1; building 3≠2; road not stated
    assert (a["position_exact"], a["position_within_one"]) == (
        0.5,
        1.0,
    )  # centre; west vs north_west
    assert (a["count_not_stated"], a["position_not_stated"]) == (0.333, 0.333)


class ExtractingBedrock(FakeBedrock):
    """FakeBedrock that also extracts: it echoes the Claims named in the text."""

    def converse(self, modelId, messages, toolConfig, inferenceConfig):
        names = [t["toolSpec"]["name"] for t in toolConfig["tools"]]
        if names != ["submit_claims"]:
            return super().converse(modelId, messages, toolConfig, inferenceConfig)
        text = messages[0]["content"][0]["text"].split("Caption:")[-1].lower()
        objects = [{"id": f"o{i}", "object": t, "count": None, "position": None}
                   for i, t in enumerate(("solar_array", "wind_turbine"), 1)
                   if t.split("_")[0] in text]  # fmt: skip
        block = {
            "toolUse": {
                "toolUseId": "x",
                "name": "submit_claims",
                "input": {"objects": objects, "relations": [], "uncertain": []},
            }
        }
        return {"output": {"message": {"content": [block]}}, "usage": {"totalTokens": 5}}


def test_a_batch_is_calibrated_against_its_own_claims(tmp_path, monkeypatch):
    store = LocalStore(tmp_path / "data", tmp_path / "batches")
    for case in (SOLAR, WIND):
        store.put(f"chips/{case['chips'][0]['id']}.png", case["chips"][0]["id"].encode())
    settings = Settings(
        caption_model="cap", judge_model="judge", embed_model="embed",
        bedrock_endpoint_url=None, data_dir=tmp_path / "data",
        batches_dir=tmp_path / "batches", baselines_dir=tmp_path / "baselines",
        store_url=None, naip_source="pc",
    )  # fmt: skip
    monkeypatch.setattr(batches, "bedrock", lambda s: FakeBedrock())
    bid = batches.start([SOLAR, WIND], settings, store, 1, "x", "dev", narrate=False,
                        progress=lambda _: None)  # fmt: skip
    items = batch_items(store, bid)
    assert {i["text"] for i in items} == {"A solar farm.", "Two wind turbines."}
    prefix = f"batches/{bid}/extraction"
    r = calibrate(ExtractingBedrock(), "judge", items, store, prefix, progress=lambda _: None)
    assert (r["type_precision"], r["type_recall"], r["failed"]) == (1.0, 1.0, 0)
    assert r["count_not_stated"] == 1.0  # the fake never gives a count
    saved = json.loads(store.get(f"{prefix}/agreement.json"))
    assert saved["captions"] == 2 and len(saved["items"]) == 2
    run, steps = loads(store.get(f"{prefix}/{items[0]['id']}.jsonl"))
    assert run.task == "extract" and [s.name for s in steps] == ["extract_claims"]


def test_calibration_reports_each_label_source_and_the_edit_rate():
    solar = {"objects": [{"id": "o1", "object": "solar_array", "count": None, "position": None}],
             "relations": [], "uncertain": []}  # fmt: skip
    items = [
        {"id": "a", "text": "A solar farm.", "claims": solar, "source": "proposal accepted"},
        {"id": "b", "text": "A solar farm.", "claims": solar, "source": "proposal edited"},
        {"id": "c", "text": "A solar farm.", "claims": solar, "source": "proposal accepted"},
        {"id": "d", "text": "A solar farm.", "claims": solar, "source": "blind"},
    ]
    r = calibrate(ExtractingBedrock(), "judge", items, progress=lambda _: None)
    assert set(r["by_source"]) == {"blind", "proposal accepted", "proposal edited"}
    assert r["by_source"]["proposal accepted"]["captions"] == 2
    assert r["edit_rate"] == 0.333  # 1 of 3 proposals changed
