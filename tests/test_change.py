"""Change Cases: a Chip Pair, labels that say what changed, and the path through a Batch."""

import json
from typing import ClassVar

import pytest
from test_agentic import Scripted, turn, use
from test_loop import CAPTIONS, SOLAR, FakeBedrock

from clayzer import answer_keys as ak
from clayzer import batch as batches
from clayzer import harness, run_report
from clayzer.cases import change_labels
from clayzer.config import Settings
from clayzer.grounding import grounding
from clayzer.importer import footprint_chip
from clayzer.judge import fidelity
from clayzer.store import LocalStore
from clayzer.trace import loads, trace_key

W, S, E, N = -118.196, 35.228, -118.193, 35.231
BOX = {"type": "Polygon", "coordinates": [[[W, S], [E, S], [E, N], [W, N], [W, S]]]}


def chip(date):
    return footprint_chip({"chip_id": f"k-{date}", "geometry": BOX, "datetime": date,
                           "sensor": "naip", "stac_item": ""})  # fmt: skip


@pytest.fixture
def keys(monkeypatch):
    centre = ((W + E) / 2, (S + N) / 2)
    new = {"case_id": 7, "xlong": centre[0], "ylat": centre[1], "p_year": 2017, "p_area": 5e4}
    turbine = {"case_id": 9, "xlong": E - 3e-4, "ylat": N - 3e-4, "p_year": 2009}
    monkeypatch.setattr(ak, "usgs_near", lambda *a, **k: ([new], [turbine]))
    monkeypatch.setattr(ak, "uspvdb_outlines", lambda: ("v-test", {}))
    monkeypatch.setattr(ak, "overpass", lambda bbox: [])
    road = {"object": "road", "count": None, "position": "south", "cells": ["south"],
            "attributes": {}, "source": "osm", "source_ids": ["way/1"]}  # fmt: skip
    monkeypatch.setattr(ak, "osm_labels", lambda chip, elements: [road])


def test_labels_say_what_changed_between_the_two_dates(keys):
    labels = {lb["object"]: lb for lb in change_labels(chip("2016-06-01"), chip("2018-06-01"))}
    assert labels["solar_array"]["change"] == "appeared"  # built in 2017, between the two
    assert labels["solar_array"]["position"] == "centre"
    assert labels["wind_turbine"]["change"] == "unchanged"  # built in 2009, before both
    assert labels["road"]["change"] == "unknown"  # OSM is today's map, with no history


def test_a_site_gone_by_the_later_date_disappeared(keys, monkeypatch):
    gone = {"case_id": 3, "xlong": (W + E) / 2, "ylat": (S + N) / 2, "p_year": 2012}
    monkeypatch.setattr(ak, "usgs_near", lambda *a, **k: ([gone], []))
    real = ak.existed_by
    # Pretend the later Chip's year no longer has it (USGS doesn't record removals today).
    monkeypatch.setattr(
        ak, "existed_by", lambda recs, year: [] if year >= 2018 else real(recs, year)
    )
    (solar,) = [
        lb
        for lb in change_labels(chip("2016-06-01"), chip("2018-06-01"))
        if lb["object"] == "solar_array"
    ]
    assert solar["change"] == "disappeared"


def test_the_harness_captions_a_chip_pair():
    pair_caption = {**CAPTIONS["c-solar"], "relations": [], "uncertain": [],
                    "objects": [{"id": "o1", "object": "solar_array", "count": 1,
                                 "position": "centre", "change": "appeared"},
                                {"id": "o2", "object": "road", "count": 1, "position": "south",
                                 "change": "moved"}]}  # fmt: skip
    bedrock = Scripted(turn(use("submit_caption", pair_caption)))
    cap, _ = harness.caption(bedrock, "m", "k", [b"before", b"after"], harness.CHANGE_PROMPT,
                             image_key=["chips/k-2016.png", "chips/k-2018.png"])  # fmt: skip
    content = bedrock.requests[0]["messages"][0]["content"]
    assert [list(b) for b in content] == [["image"], ["image"], ["text"]]  # earlier, later, prompt
    assert "The first is the earlier date" in content[2]["text"]
    assert cap["objects"][0]["change"] == "appeared"
    assert "change" not in cap["objects"][1]  # "moved" isn't a change value: dropped


def test_the_judge_sees_both_images_and_is_told_it_is_a_change():
    bedrock = Scripted(turn(use("submit_verdict", {"score": 0.8, "issues": []})))
    cap = {"text": "A solar array appeared.", "objects": [], "relations": []}
    verdict, _ = fidelity(bedrock, "j", cap, [b"before", b"after"], image_key=["a", "b"])
    content = bedrock.requests[0]["messages"][0]["content"]
    assert sum("image" in b for b in content) == 2 and verdict["score"] == 0.8
    assert content[-1]["text"].startswith("There are two images of the same place")


def test_grounding_scores_change_only_where_it_is_known():
    labels = [
        {"object": "solar_array", "count": 1, "position": "centre", "cells": ["centre"],
         "attributes": {}, "change": "appeared"},
        {"object": "road", "count": None, "position": "south", "cells": ["south"],
         "attributes": {}, "change": "unknown"},
    ]  # fmt: skip
    right = {"objects": [{"id": "o1", "object": "solar_array", "count": 1, "position": "centre",
                          "change": "appeared"},
                         {"id": "o2", "object": "road", "count": 1, "position": "south",
                          "change": "unchanged"}], "relations": []}  # fmt: skip
    wrong = json.loads(json.dumps(right).replace('"appeared"', '"unchanged"'))
    assert grounding(right, labels)["change"] == 1.0  # the road's change isn't scored
    assert grounding(wrong, labels)["change"] == 0.0
    fixed = [{**labels[0]}]
    del fixed[0]["change"]
    assert grounding(right, fixed)["change"] is None  # a Fixed Case has none to score


class PairBedrock(FakeBedrock):
    """FakeBedrock for a Chip Pair: it captions from the later image and keeps each request."""

    requests: ClassVar[list] = []

    def converse(self, modelId, messages, toolConfig, inferenceConfig):
        type(self).requests.append(messages[0]["content"])
        content = [b for b in messages[0]["content"] if "image" in b]
        if len(content) == 2:  # caption or judge a pair from its later image
            messages = [{**messages[0], "content": [content[1], messages[0]["content"][-1]]}]
        return super().converse(modelId, messages, toolConfig, inferenceConfig)


def test_a_change_case_runs_end_to_end(tmp_path, monkeypatch):
    store = LocalStore(tmp_path / "data", tmp_path / "batches")
    store.put("chips/c-solar-2016.png", b"c-before")
    store.put("chips/c-solar.png", b"c-solar")
    case = {**SOLAR, "id": "change-dev-solar", "kind": "change",
            "chips": [{**SOLAR["chips"][0], "id": "c-solar-2016", "uri": "chips/c-solar-2016.png",
                       "date": "2016-06-01"}, SOLAR["chips"][0]],
            "reference_labels": [{**SOLAR["reference_labels"][0], "change": "appeared"}]}  # fmt: skip
    settings = Settings(
        caption_model="cap", judge_model="judge", embed_model="embed",
        bedrock_endpoint_url=None, data_dir=tmp_path / "data",
        batches_dir=tmp_path / "batches", baselines_dir=tmp_path / "baselines",
        store_url=None, naip_source="pc",
    )  # fmt: skip
    PairBedrock.requests = []
    monkeypatch.setattr(batches, "bedrock", lambda s: PairBedrock())
    bid = batches.start([case], settings, store, 1, "change", "dev", progress=lambda _: None)
    (result,) = batches.load(store, bid)["results"]
    assert result["status"] == "ok" and "change" in result["grounding"]
    caption_req, judge_req = PairBedrock.requests[0], PairBedrock.requests[1]
    assert sum("image" in b for b in caption_req) == 2 and sum("image" in b for b in judge_req) == 2
    assert "The first is the earlier date" in caption_req[-1]["text"]
    # The Run records the change prompt's hash, not the Batch's one-Chip prompt.
    cfg = batches.load_config(store, bid)
    assert cfg.change_prompt_sha == batches._sha(harness.CHANGE_PROMPT.encode())
    run, _ = loads(store.get(trace_key(bid, case["id"], 1)))
    assert run.prompt_sha == cfg.change_prompt_sha != cfg.prompt_sha
    # Its report shows the change score and the prompt the Run actually used.
    html, record = run_report.build(store, batches.load(store, bid), result)
    assert record["config"]["prompt_sha"] == cfg.change_prompt_sha
    assert "Grounding: change" in html and record["scores"]["grounding"]["change"] is not None


def test_a_chip_pair_step_is_summarized_and_digested():
    from clayzer.narrate import digest
    from clayzer.summarize import summarize
    from clayzer.trace import RunInfo, Step

    run = RunInfo(run_id="r", task="caption", case_id="c", repeat=1, batch_id="b",
                  model_id="m", prompt_sha="p", status="ok")  # fmt: skip
    pair = [
        {"key": "chips/a.png", "sha256": "x", "bytes": 1},
        {"key": "chips/b.png", "sha256": "y", "bytes": 1},
    ]
    step = Step(
        "r",
        0,
        "llm",
        "caption",
        0.0,
        1.0,
        {"prompt": "p", "image": pair},
        {"content": [], "stop_reason": "end_turn"},
        None,
        {"latency_ms": 1000},
    )
    assert "the Chip Pair chips/a.png → chips/b.png" in json.dumps(
        summarize(run, [step]), ensure_ascii=False
    )
    assert "chips/a.png then chips/b.png" in digest(run, [step])
