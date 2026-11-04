from clayzer.grid import cell_at, cell_distance, directions
from clayzer.grounding import grounding


def label(obj, position, cells=None, count=1, **attributes):
    return {
        "object": obj, "count": count, "position": position, "cells": cells or [position],
        "attributes": attributes, "source": "test", "source_ids": [],
    }  # fmt: skip


def claim(i, obj, position, count=1, **attributes):
    return {"id": i, "object": obj, "count": count, "position": position, "attributes": attributes}


def caption(objects, relations=()):
    return {"text": "", "objects": list(objects), "relations": list(relations), "uncertain": []}


def test_cells_follow_the_3x3_grid():
    assert cell_at(0, 0, 512) == "north_west"
    assert cell_at(256, 256, 512) == "centre"
    assert cell_at(511, 511, 512) == "south_east"
    assert cell_at(600, -5, 512) == "north_east"
    assert cell_distance("north_west", "south_east") == 2
    assert directions("north", "south") == {"north_of"}
    assert directions("north_west", "centre") == {"north_of", "west_of"}


def test_perfect_caption_scores_one():
    labels = [label("solar_array", "centre", size="large"), label("road", "north", count=None)]
    cap = caption(
        [claim("o1", "solar_array", "centre", size="large"), claim("o2", "road", "north")],
        [{"subject": "o2", "relation": "north_of", "object": "o1"}],
    )
    g = grounding(cap, labels)
    assert g["correctness"] == 1.0 and g["coverage"] == 1.0
    assert g["count"] == 1.0  # the road's count isn't scored, only the array's
    assert g["relations"] == 1.0


def test_road_position_counts_anywhere_along_the_road():
    labels = [label("road", "north", cells=["north_west", "north", "north_east"], count=None)]
    g = grounding(caption([claim("o1", "road", "north_east")]), labels)
    assert g["position"] == 1.0


def test_false_positive_miss_and_neighbouring_cell():
    labels = [label("wind_turbine", "west", count=3), label("building", "east", count=2)]
    cap = caption(
        [claim("o1", "wind_turbine", "centre", count=2), claim("o2", "greenhouse", "south")]
    )
    g = grounding(cap, labels)
    assert g["precision"] == 0.5
    assert g["recall"] == 0.5
    assert g["missed"] == ["building"]
    assert g["position"] == 0.5
    assert g["count"] == 0.5


def test_claims_split_over_cells_are_counted_together():
    labels = [label("solar_array", "centre", count=1)]
    cap = caption(
        [claim("o1", "solar_array", "centre"), claim("o2", "solar_array", "north"),
         claim("o3", "solar_array", "south")]
    )  # fmt: skip
    g = grounding(cap, labels)
    assert g["counts"] == {"solar_array": {"claimed": 3, "reference": 1}}
    assert g["count"] == 0.0
    assert g["position"] == (1.0 + 0.5 + 0.5) / 3


def test_unkeyed_claims_are_reported_not_scored():
    cap = caption([claim("o1", "vegetation", "south"), claim("o2", "bare_ground", "north")])
    g = grounding(cap, [])
    assert g["precision"] == 1.0  # nothing gradable was claimed on an empty Chip
    assert g["unscored_share"] == 1.0
    assert g["unscored"] == ["vegetation", "bare_ground"]


def test_wrong_attribute_and_wrong_relation():
    labels = [label("solar_array", "centre", size="large"), label("road", "south", count=None)]
    cap = caption(
        [claim("o1", "solar_array", "centre", size="small"), claim("o2", "road", "south")],
        [{"subject": "o2", "relation": "north_of", "object": "o1"},
         {"subject": "o2", "relation": "adjacent_to", "object": "o1"}],
    )  # fmt: skip
    g = grounding(cap, labels)
    assert g["attributes"] == 0.0
    assert g["relations"] == 0.0
    assert len(g["relations_unscored"]) == 1


def test_a_terse_correct_caption_is_correct_but_not_covering():
    labels = [label("solar_array", "centre"), label("road", "north", count=None),
              label("building", "east", count=2)]  # fmt: skip
    terse = grounding(caption([claim("o1", "solar_array", "centre")]), labels)
    assert terse["correctness"] == 1.0
    assert terse["coverage"] == 1 / 3
    detailed = grounding(
        caption([claim("o1", "solar_array", "centre"), claim("o2", "road", "north"),
                 claim("o3", "building", "west", count=3)]),
        labels,
    )  # fmt: skip
    assert detailed["coverage"] == 1.0
    assert detailed["correctness"] < 1.0  # the building's count and cell are off
