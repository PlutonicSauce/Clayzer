"""The committed development Cases: complete, licensed, nothing private, and loadable by push."""

import re

from test_loop import CAPTIONS, FakeBedrock

from clayzer import batch as batches
from clayzer.cases import load_cases, parse_jsonl
from clayzer.cli import _push
from clayzer.config import REPO, Settings
from clayzer.store import LocalStore

ROOT = REPO / "fixtures" / "caption"
CASES = parse_jsonl((ROOT / "cases" / "caption-dev.jsonl").read_bytes())
# The held-out Texas set: scored once at the end, never tuned on (caption-plan.md §3).
TEST_CASES = parse_jsonl((ROOT / "cases" / "caption-test.jsonl").read_bytes())


def test_every_case_has_its_chip_and_no_chip_is_orphaned():
    uris = {chip["uri"] for case in CASES + TEST_CASES for chip in case["chips"]}
    assert all(u.startswith("chips/") for u in uris)
    on_disk = {f"chips/{f.name}" for f in (ROOT / "chips").glob("*.png")}
    assert uris == on_disk
    assert all((ROOT / u.replace(".png", ".json")).exists() for u in uris)


def test_the_set_is_the_planned_mix():
    kinds = [case["id"].split("-")[2] for case in CASES]
    assert len({c["id"] for c in CASES}) == len(CASES)
    assert kinds.count("neg") >= 20 and kinds.count("uspvdb") + kinds.count("uswtdb") >= 40


def test_change_cases_are_a_pair_of_one_footprint_with_a_known_change():
    pairs = [case for case in CASES if case["kind"] == "change"]
    assert pairs
    for case in pairs:
        before, after = case["chips"]
        assert before["bbox"] == after["bbox"] and before["date"] < after["date"]
        assert any(lb["change"] in ("appeared", "disappeared", "unchanged")
                   for lb in case["reference_labels"]), case["id"]  # fmt: skip


def test_osm_labels_carry_the_odbl_notice():
    assert any(lbl["source"] == "osm" for case in CASES for lbl in case["reference_labels"])
    notice = (ROOT / "cases" / "NOTICE.md").read_text()
    assert "© OpenStreetMap contributors" in notice and "ODbL" in notice


def test_nothing_private_or_signed_is_committed():
    pattern = re.compile(r"https?://|s3://|amazonaws|\b\d{12}\b|sig=|token", re.IGNORECASE)
    for f in [*(ROOT / "cases").glob("*.jsonl"), *(ROOT / "chips").glob("*.json")]:
        assert not pattern.search(f.read_text()), f.name


def test_push_fills_an_empty_store_and_a_batch_runs_on_it(tmp_path, monkeypatch):
    store = LocalStore(tmp_path / "data", tmp_path / "batches")
    case_files = list((ROOT / "cases").glob("*.jsonl"))
    assert _push(store, ROOT) == len(list((ROOT / "chips").glob("*"))) + len(case_files)
    cases = load_cases(store, "cases/caption-dev.jsonl")
    assert len(cases) == len(CASES)
    settings = Settings(
        caption_model="cap", judge_model="judge", embed_model="embed",
        bedrock_endpoint_url=None, data_dir=tmp_path / "data",
        batches_dir=tmp_path / "batches", baselines_dir=tmp_path / "baselines",
        store_url=None, naip_source="pc",
    )  # fmt: skip
    # The fake Bedrock reads a Chip's id from its image bytes, so stand ids in for the PNGs.
    for case in cases[:3]:
        chip = case["chips"][0]
        store.put(chip["uri"], chip["id"].encode())
        monkeypatch.setitem(CAPTIONS, chip["id"], CAPTIONS["c-solar"])
    monkeypatch.setattr(batches, "bedrock", lambda s: FakeBedrock())
    bid = batches.start(cases[:3], settings, store, 1, "", "dev", progress=lambda _: None)
    runs = batches.load(store, bid)["summary"]["batch"]["runs"]
    assert runs["planned"] == 3 and runs["sandbox_failures"] == 0


def test_no_chip_is_partly_blank():
    import numpy as np
    from PIL import Image

    from clayzer.chips import MAX_BLANK, blank_share

    for case in CASES + TEST_CASES:
        for chip in case["chips"]:  # both Chips of a Change Case's pair
            img = np.asarray(Image.open(ROOT / chip["uri"]).convert("RGB"))
            assert blank_share(np.moveaxis(img, -1, 0)) <= MAX_BLANK, chip["id"]


def test_the_committed_cases_carry_every_hand_correction():
    from clayzer.cases import apply_corrections, load_corrections

    corrections = load_corrections()
    ids = {case["id"] for case in CASES + TEST_CASES}
    assert corrections and all(c["case"] in ids for c in corrections)
    for case in CASES + TEST_CASES:
        labels = case["reference_labels"]
        assert apply_corrections(case["id"], labels, corrections) == labels, case["id"]


def test_label_corrections_drop_add_and_merge_once():
    import pytest

    from clayzer.cases import apply_corrections

    labels = [
        {"object": "building", "count": 2, "position": "north_east", "cells": ["north_east"],
         "attributes": {}, "source": "osm", "source_ids": ["way/1"]},
        {"object": "water", "count": None, "position": "south", "cells": ["south"],
         "attributes": {}, "source": "osm", "source_ids": ["way/2"]},
    ]  # fmt: skip
    corrections = [
        {"case": "c", "object": "water", "action": "drop"},
        {"case": "c", "object": "building", "action": "add", "cells": ["south", "north_east"]},
        {"case": "c", "object": "parking_lot", "action": "add", "cells": ["centre"]},
        {"case": "other", "object": "building", "action": "drop"},
    ]
    once = apply_corrections("c", labels, corrections)
    assert [lb["object"] for lb in once] == ["building", "parking_lot"]
    assert once[0]["cells"] == ["north_east", "south"] and once[0]["count"] is None
    assert once[0]["source"] == "osm+manual" and once[0]["position"] == "north_east"
    assert once[1]["source"] == "manual" and once[1]["position"] == "centre"
    assert apply_corrections("c", once, corrections) == once
    assert labels[0]["count"] == 2  # the input is left alone
    with pytest.raises(ValueError):
        apply_corrections(
            "c", [], [{"case": "c", "object": "x", "action": "add", "cells": ["middle"]}]
        )


def test_the_texas_test_set_is_held_apart_from_development():
    assert TEST_CASES and all(c["region"] == "test" for c in TEST_CASES)
    assert all(c["region"] == "dev" for c in CASES)
    for case in TEST_CASES:
        w, s, e, n = case["chips"][0]["bbox"]
        assert -106.7 < w and e < -93.5 and 25.8 < s and n < 36.6, case["id"]  # Texas
    kinds = [case["id"].split("-")[2] for case in TEST_CASES]
    assert kinds.count("neg") >= 15 and kinds.count("uspvdb") + kinds.count("uswtdb") >= 35


def test_a_correction_can_give_the_corrected_count():
    from clayzer.cases import apply_corrections

    labels = [{"object": "wind_turbine", "count": 17, "position": "north", "cells": ["north"],
               "attributes": {}, "source": "uswtdb", "source_ids": []}]  # fmt: skip
    fix = [{"case": "c", "object": "wind_turbine", "action": "add", "cells": ["south_east"],
            "count": 18}]  # fmt: skip
    once = apply_corrections("c", labels, fix)
    assert once[0]["count"] == 18 and once[0]["cells"] == ["north", "south_east"]
    assert once[0]["source"] == "uswtdb+manual" and apply_corrections("c", once, fix) == once
