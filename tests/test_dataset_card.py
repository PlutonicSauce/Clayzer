"""The Caption dataset card (CAP-22): duplication, coverage, vocabulary, per-class error patterns
from the Object Ontology's look-alikes, and its stated limits. Offline: no model is called."""

import json

import pytest
from fastapi.testclient import TestClient
from test_loop import SOLAR, env, run  # noqa: F401

from clayzer import batch as batches
from clayzer.dataset_card import THIN, build, card_key, from_batch, to_html, to_markdown


def label(obj, count=1, position="centre", cells=None):
    return {"object": obj, "count": count, "position": position, "cells": cells or [position],
            "attributes": {}, "source": "osm", "source_ids": []}  # fmt: skip


def claim(obj, count=1, position="centre", id_="o1"):
    return {"id": id_, "object": obj, "count": count, "position": position}


def record(cid, chip, text, objects, labels, region="dev"):
    return {"caption_id": cid, "chip_id": chip, "case_id": chip, "region": region, "text": text,
            "objects": objects, "relations": [], "labels": labels}  # fmt: skip


SOURCE = {"kind": "batch", "id": "b"}


def test_a_greenhouse_called_a_solar_array_is_a_look_alike_confusion():
    card = build(
        [record("g#1", "g", "A solar farm.", [claim("solar_array")], [label("greenhouse")])],
        SOURCE,
    )
    assert card["confusions"] == [{"labelled": "greenhouse", "claimed": "solar_array",
                                   "captions": 1, "of_labelled": 1.0, "example": "g#1"}]  # fmt: skip
    assert card["errors"]["solar_array"]["false_positive_rate"] == 1.0
    assert card["errors"]["greenhouse"]["miss_rate"] == 1.0


def test_a_false_positive_beside_an_unrelated_class_is_not_a_confusion():
    # Wind turbines don't look like greenhouses: a plain false positive and a plain miss.
    card = build(
        [record("g#1", "g", "Turbines.", [claim("wind_turbine")], [label("greenhouse")])], SOURCE
    )
    assert card["confusions"] == []
    assert card["errors"]["wind_turbine"]["false_positive"] == 1


def test_miscounts_and_misplacements_per_class():
    records = [
        record("a#1", "a", "Five turbines.", [claim("wind_turbine", 5)], [label("wind_turbine", 3)]),
        record("b#1", "b", "Two turbines.", [claim("wind_turbine", 2)], [label("wind_turbine", 2)]),
        record("c#1", "c", "Two turbines north.", [claim("wind_turbine", 2, "north_west")],
               [label("wind_turbine", 2, "south_east")]),
    ]  # fmt: skip
    e = build(records, SOURCE)["errors"]["wind_turbine"]
    assert (e["labelled"], e["claimed"], e["over_count"], e["under_count"]) == (3, 3, 1, 0)
    assert e["miscount_rate"] == pytest.approx(1 / 3)
    assert e["mean_count_error"] == pytest.approx(2 / 3)
    assert e["misplaced_rate"] == pytest.approx(1 / 3)
    assert e["thin"] is (3 < THIN)


def test_misplaced_counts_claims_on_both_sides_when_a_class_is_split():
    # "10 turbines north-west, 5 north-west": two Claims for one class in one Caption, both in the
    # wrong cell. Counting Claims against Captions made this 200%.
    split = record(
        "a#1", "a", "Turbines.",
        [claim("wind_turbine", 10, "north_west"), claim("wind_turbine", 5, "north_west", id_="o2")],
        [label("wind_turbine", 15, "south_east")],
    )  # fmt: skip
    e = build([split], SOURCE)["errors"]["wind_turbine"]
    assert (e["matched_claims"], e["misplaced"]) == (2, 2)
    assert e["misplaced_rate"] == 1.0
    assert all(0 <= v <= 1 for k, v in e.items() if k.endswith("_rate") and v is not None), (
        "a rate above 100% means its two sides count different things"
    )


def test_duplication_counts_across_chips_not_between_repeats():
    same = "A solar farm covers the centre of the tile beside a road."
    records = [
        record("a#1", "a", same, [claim("solar_array")], [label("solar_array")]),
        record("a#2", "a", same, [claim("solar_array")], [label("solar_array")]),  # a Repeat
        record("b#1", "b", "Rows of greenhouses.", [claim("greenhouse")], [label("greenhouse")]),
    ]
    d = build(records, SOURCE)["duplication"]
    assert d["exact_across_chips"] == 0 and d["near_across_chips"] == 0
    records.append(record("c#1", "c", same.upper(), [claim("solar_array")], [label("solar_array")]))
    d = build(records, SOURCE)["duplication"]
    assert d["exact_across_chips"] == 3  # both of a's Captions, and c's
    assert d["exact_rate"] == pytest.approx(3 / 4)
    near = record("d#1", "d", same.replace("road", "road too"), [], [])
    assert build([records[0], near], SOURCE)["duplication"]["near_across_chips"] == 2


def test_repeats_count_once_as_chips_and_each_as_captions():
    repeats = [
        record(f"g#{i}", "g", "A solar farm.", [claim("solar_array")], [label("greenhouse")])
        for i in (1, 2, 3)
    ]
    card = build(repeats, SOURCE)
    e = card["errors"]["greenhouse"]
    assert (e["chips"], e["labelled"], e["missed"]) == (1, 3, 3)
    status = {c["class"]: c for c in card["coverage"]["classes"]}["greenhouse"]
    assert status["labelled"] == 1  # Chips with it, in the coverage table
    assert "Fewer than 10 labelled Chips for greenhouse" in " ".join(card["limits"])


def test_coverage_and_vocabulary():
    records = [
        record("a#1", "a", "A solar farm beside a road.", [claim("solar_array"), claim("road",
               id_="o2")], [label("solar_array")], region="dev"),
        record("b#1", "b", "Desert scrub and bare soil.", [claim("vegetation")], [],
               region="texas"),
    ]  # fmt: skip
    card = build(records, SOURCE)
    classes = {c["class"]: c["status"] for c in card["coverage"]["classes"]}
    assert classes["solar_array"] == "covered"
    assert classes["road"].startswith("claimed, but no Chip")
    assert classes["railroad"].startswith("missing")
    assert classes["vegetation"].startswith("no Answer Key")
    assert "railroad" in card["coverage"]["missing"] and "road" not in card["coverage"]["missing"]
    assert card["coverage"]["regions"] == {"dev": {"captions": 1, "chips": 1},
                                           "texas": {"captions": 1, "chips": 1}}  # fmt: skip
    v = card["vocabulary"]
    assert v["classes_in_text"]["solar_array"] == 1  # "solar farm" is a synonym
    assert v["classes_in_text"]["bare_ground"] == 1  # "bare soil"
    assert v["distinct_openings"] == 2
    assert card["claims"] == {"claims": 3, "unscored": 1}


def test_the_card_states_its_limits():
    card = build([record("a#1", "a", "A solar farm.", [claim("solar_array")],
                         [label("solar_array")])], SOURCE)  # fmt: skip
    limits = " ".join(card["limits"])
    assert "improve Clay v2" in limits and "proxy" in limits
    assert "confidence intervals" in limits and "Wilson" in limits
    assert "Terrain" in limits and "importer" in limits
    assert "solar_array" in limits  # one labelled Chip is thin
    for rendered in (to_markdown(card), to_html(card)):
        assert "can't show" in rendered and "improve Clay v2" in rendered


def _unchecked(card):
    return next(x for x in card["limits"] if x.startswith("Error patterns"))


def test_the_unchecked_classes_limit_reads_right_at_zero_and_above():
    clean = build(
        [record("a#1", "a", "A solar farm.", [claim("solar_array")], [label("solar_array")])],
        SOURCE,
    )
    text = _unchecked(clean)
    # The classes come from the ontology, and nothing is claimed about them here.
    assert "Mistakes about vegetation and bare ground" in text
    assert text.endswith("No Claim in this set names a class without an Answer Key.")
    assert "0 of" not in text

    scrub = build(
        [record("a#1", "a", "Scrub.", [claim("vegetation"), claim("solar_array", id_="o2")],
                [label("solar_array")])],
        SOURCE,
    )  # fmt: skip
    assert _unchecked(scrub).endswith(
        "In this set, 1 of 2 Claims name a class no Answer Key covers."
    )


def test_the_unchecked_classes_follow_the_ontology():
    from dataclasses import replace

    from clayzer import ontology as onto

    base = onto.load()
    keyed = replace(base.classes["vegetation"], keyed_by=("osm",))
    changed = onto.Ontology(base.version, {**base.classes, "vegetation": keyed})
    card = build([record("a#1", "a", "Scrub.", [], [])], SOURCE, ontology=changed)
    assert "Mistakes about bare ground," in _unchecked(card)
    assert "vegetation" not in _unchecked(card)


def test_rendered_text_is_escaped():
    card = build([record("<x>#1", "a", "<script>alert(1)</script>", [], [])], SOURCE)
    assert "<script>" not in to_html(card)


def test_a_batch_gets_a_card_in_its_reports_and_replay_rebuilds_it(env):  # noqa: F811
    store = env[0]
    b = run(env, "card", repeats=2)
    bid = b["config"].batch_id
    card = json.loads(store.get(card_key(bid)))
    assert card["source"] == {"kind": "batch", "id": bid, "generator": "cap"}
    assert card["size"] == {"captions": 4, "chips": 2, "claims": 4, "claims_per_caption": 1.0}
    assert card["errors"]["solar_array"]["miss_rate"] == 0.0
    assert "## Caption dataset card" in store.get(f"batches/{bid}/report.md").decode()
    assert "id='dataset-card'" in store.get(f"batches/{bid}/report.html").decode()
    # Built from records the Harness's Runs produced: the Repeats of one Chip share it.
    assert {r["chip_id"] for r in from_batch(b)} == {"c-solar", "c-wind"}
    store.delete(card_key(bid))
    batches.rescore(bid, store)  # no model: the fake client would count a call
    assert json.loads(store.get(card_key(bid)))["size"]["captions"] == 4


def test_a_harness_fault_leaves_no_caption_in_the_set(env):  # noqa: F811
    b = run(env, "fault", repeats=1, no_caption={"c-wind"})
    records = from_batch(b)
    assert [r["chip_id"] for r in records] == ["c-solar"]


def test_the_web_app_serves_the_card(env):  # noqa: F811
    from clayzer.ui.app import create_app

    store, settings, _ = env
    bid = run(env, "web", repeats=1)["config"].batch_id
    c = TestClient(create_app(settings))
    assert c.get(f"/api/batches/{bid}/dataset-card").json()["size"]["captions"] == 2
    # A Batch reported before cards existed still gets one, built on the fly and not written.
    store.delete(card_key(bid))
    assert c.get(f"/api/batches/{bid}/dataset-card").json()["size"]["chips"] == 2
    assert not store.exists(card_key(bid))
    assert c.get(f"/api/batches/{bid}/files/dataset-card.json").status_code == 404
    batches.write_reports(store, bid)
    assert c.get(f"/api/batches/{bid}/files/dataset-card.json").status_code == 200
    assert c.get("/api/batches/x..y/dataset-card").status_code == 400
