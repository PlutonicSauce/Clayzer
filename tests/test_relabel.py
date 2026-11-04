"""water-relabel: only the water label is rebuilt, with hand corrections applied again."""

from clayzer import answer_keys as ak
from clayzer.cases import relabel_water
from clayzer.chips import Chip

CHIP = Chip(id="k", date="2022-06-07", bbox=(0, 0, 1, 1), crs="EPSG:32611", left=0, top=0,
            source="naip", naip_item="")  # fmt: skip


def label(obj, source="osm", cells=("centre",)):
    return {"object": obj, "count": None, "position": cells[0], "cells": list(cells),
            "attributes": {}, "source": source, "source_ids": []}  # fmt: skip


def case(*labels, kind="fixed"):
    return {"id": "c", "kind": kind, "reference_labels": list(labels)}


def test_a_dry_wash_loses_its_water_and_nothing_else_moves(monkeypatch):
    road = label("road", cells=("south",))
    monkeypatch.setattr(ak, "osm_labels", lambda chip, el: [label("road", cells=("north",))])
    got = relabel_water(case(road, label("water"), label("solar_array", "uspvdb")), CHIP, [], [])
    # No water under the new rule; the road keeps its old label, not today's OSM.
    assert got["reference_labels"] == [road, label("solar_array", "uspvdb")]


def test_water_that_is_there_all_year_stays_where_it_was(monkeypatch):
    lake = label("water", cells=("west",))
    monkeypatch.setattr(ak, "osm_labels", lambda chip, el: [lake])
    got = relabel_water(
        case(label("road"), label("water", cells=("west", "east")), label("field")), CHIP, [], []
    )
    assert [lb["object"] for lb in got["reference_labels"]] == ["road", "water", "field"]
    assert got["reference_labels"][1]["cells"] == ["west"]  # shrank to the lake


def test_hand_corrections_apply_again(monkeypatch):
    monkeypatch.setattr(ak, "osm_labels", lambda chip, el: [])
    add = [{"case": "c", "object": "water", "action": "add", "cells": ["north_west", "north"]}]
    got = relabel_water(case(label("water")), CHIP, [], add)
    (w,) = got["reference_labels"]
    assert (w["source"], w["cells"]) == ("manual", ["north_west", "north"])


def test_a_change_case_keeps_its_water_change_unknown(monkeypatch):
    monkeypatch.setattr(ak, "osm_labels", lambda chip, el: [label("water")])
    got = relabel_water(case(label("water"), kind="change"), CHIP, [], [])
    assert got["reference_labels"][0]["change"] == "unknown"
