"""The ontology file (ADR-0008): well-formed, its crosswalks real, and the code's vocabularies
read from it, so adding a class is a one-file change.
"""

import subprocess
import sys
import textwrap

import pytest

from clayzer import answer_keys, grounding, harness, ontology, retrieval
from clayzer.ontology import load

ONT = load()

# RSICD's 30 scene classes, taken from the filenames in RSICD_optimal's dataset_rsicd.json.
RSICD_SCENES = {
    "airport", "bareland", "baseballfield", "beach", "bridge", "center", "church", "commercial",
    "denseresidential", "desert", "farmland", "forest", "industrial", "meadow",
    "mediumresidential", "mountain", "park", "parking", "playground", "pond", "port",
    "railwaystation", "resort", "river", "school", "sparseresidential", "square", "stadium",
    "storagetanks", "viaduct",
}  # fmt: skip

# The published legends, as each names its classes: the MRLC NLCD legend (including the
# Alaska-only 51, 72 to 74) and ESA WorldCover's v2.0 user manual.
NLCD_CLASSES = {
    "11 Open Water", "12 Perennial Ice/Snow", "21 Developed, Open Space",
    "22 Developed, Low Intensity", "23 Developed, Medium Intensity",
    "24 Developed High Intensity", "31 Barren Land (Rock/Sand/Clay)", "41 Deciduous Forest",
    "42 Evergreen Forest", "43 Mixed Forest", "51 Dwarf Scrub", "52 Shrub/Scrub",
    "71 Grassland/Herbaceous", "72 Sedge/Herbaceous", "73 Lichens", "74 Moss",
    "81 Pasture/Hay", "82 Cultivated Crops", "90 Woody Wetlands",
    "95 Emergent Herbaceous Wetlands",
}  # fmt: skip
WORLDCOVER_CLASSES = {
    "Tree cover", "Shrubland", "Grassland", "Cropland", "Built-up", "Bare / sparse vegetation",
    "Snow and ice", "Permanent water bodies", "Herbaceous wetland", "Mangroves",
    "Moss and lichen",
}  # fmt: skip


def test_hierarchy_is_well_formed():
    for cls in ONT.classes.values():
        chain = ONT.ancestors(cls.id)
        assert len(chain) == len(set(chain)), f"{cls.id}: cycle in parents"
        assert len(chain) <= 3, f"{cls.id}: deeper than three levels"
        assert set(cls.confusers) <= set(ONT.classes), f"{cls.id}: unknown confuser"


def test_the_code_reads_its_vocabularies_from_the_file():
    assert harness.OBJECTS == tuple(ONT.claimable())
    assert grounding.KEYED == ONT.keyed()
    assert retrieval.QUERIES == ONT.queries()
    assert set(ONT.queries().values()) <= set(ONT.claimable())


HELIPAD = """
[[class]]
id = "helipad"
name = "Helipad"
parent = "transportation"
claimable = true
definition = "A marked landing pad for helicopters."
keyed_by = ["osm"]
osm = [{ aeroway = "helipad" }]
queries = ["find helipads"]
"""


def test_a_class_added_to_the_file_reaches_the_prompt_scoring_retrieval_and_osm(tmp_path):
    # A fresh interpreter, so module-level vocabularies are read from the edited copy.
    path = tmp_path / "objects.toml"
    path.write_text(ontology.DEFAULT.read_text(encoding="utf-8") + HELIPAD, encoding="utf-8")
    script = textwrap.dedent(f"""
        from clayzer import ontology
        real = ontology.load
        ontology.load = lambda path={str(path)!r}: real(path)
        from clayzer import answer_keys, grounding, harness, retrieval
        assert "helipad" in harness.OBJECTS
        assert "helipad" in harness.CAPTION_TOOL["toolSpec"]["inputSchema"]["json"]["properties"][
            "objects"]["items"]["properties"]["object"]["enum"]
        assert "helipad" in harness.PROMPT.format(grid="", objects=", ".join(harness.OBJECTS),
                                                  relations="")
        label = {{"object": "helipad", "count": 1, "position": "centre", "cells": ["centre"],
                  "attributes": {{}}}}
        claim = {{"id": "o1", "object": "helipad", "count": 1, "position": "centre"}}
        g = grounding.grounding({{"text": "", "objects": [claim], "relations": []}}, [label])
        assert g["correctness"] == 1.0 and g["unscored"] == []
        assert retrieval.QUERIES["find helipads"] == "helipad"
        assert answer_keys.osm_object({{"aeroway": "helipad"}}) == "helipad"
        assert 'way["aeroway"~"^(helipad)$"]' in answer_keys.overpass_filters()
    """)
    subprocess.run([sys.executable, "-c", script], check=True)


@pytest.mark.parametrize(
    "class_id,rule",
    [(c.id, rule) for c in ONT.classes.values() for rule in c.osm],
    ids=lambda v: v if isinstance(v, str) else ",".join(f"{k}={x}" for k, x in v.items()),
)
def test_osm_rules_map_to_their_class(class_id, rule):
    assert answer_keys.osm_object(dict(rule)) == class_id


def test_power_features_are_left_to_usgs():
    for cls in ONT.classes.values():
        for rule in cls.osm_reference:
            if "power" in rule:
                assert answer_keys.osm_object(dict(rule)) is None, cls.id


def test_rsicd_crosswalk_uses_real_scene_classes():
    used = {s for c in ONT.classes.values() for s in c.rsicd_scenes}
    assert used <= RSICD_SCENES, sorted(used - RSICD_SCENES)


def test_attributes_are_ones_the_harness_prompt_offers():
    for cls in ONT.classes.values():
        for name, values in cls.attributes.items():
            for value in values:
                assert value in harness.PROMPT, f"{cls.id}.{name}={value} not in the prompt"


def test_hierarchy_gives_distances_for_partial_credit():
    assert ONT.is_a("greenhouse", "building")
    assert ONT.distance("greenhouse", "building") == 1
    assert ONT.distance("road", "railroad") == 2  # siblings under transportation
    assert ONT.distance("solar_array", "water") is None  # different roots


def test_every_class_says_what_it_covers():
    for cls in ONT.classes.values():
        assert cls.definition, f"{cls.id} has no definition"


@pytest.mark.parametrize(
    "tags,class_id",
    [
        ({"building": "yes", "highway": "service"}, "building"),  # buildings before roads
        ({"building": "yes", "amenity": "parking"}, "building"),  # a parking garage
        ({"building": "yes", "landuse": "greenhouse_horticulture"}, "greenhouse"),  # deeper class
        ({"landuse": "farmland", "intermittent": "yes"}, "field"),  # only water is dried out
        ({"highway": "footway"}, None),
    ],
)
def test_osm_precedence_matches_the_mapping_before_the_ontology_drove_it(tags, class_id):
    assert answer_keys.osm_object(tags) == class_id


def test_overpass_asks_for_every_key_the_rules_use():
    filters = "".join(answer_keys.overpass_filters())
    for _, rule in ONT.osm_rules():
        for key in rule:
            assert f'way["{key}"' in filters
    assert 'way["building"]' in filters  # any value


@pytest.mark.parametrize(
    "tags",
    [
        {"waterway": "stream", "intermittent": "yes"},  # a dry desert wash
        {"waterway": "stream"},
        {"waterway": "ditch"},
        {"waterway": "drain"},
        {"natural": "water", "intermittent": "yes"},  # a playa or seasonal pond
        {"waterway": "canal", "intermittent": "yes"},
    ],
)
def test_water_is_only_water_there_all_year(tags):
    assert answer_keys.osm_object(tags) is None


def test_land_cover_crosswalks_use_the_published_legend_names():
    legends = {"nlcd": NLCD_CLASSES, "worldcover": WORLDCOVER_CLASSES}
    seen = {"nlcd": [], "worldcover": []}
    for cls in ONT.classes.values():
        for legend, names in cls.land_cover.items():
            if legend == "note":
                assert isinstance(names, str) and names, cls.id
                continue
            assert legend in legends, f"{cls.id}: unknown legend {legend}"
            assert set(names) <= legends[legend], (
                f"{cls.id}: {sorted(set(names) - legends[legend])}"
            )
            seen[legend] += names
    for legend, names in seen.items():  # a legend class belongs to one Object Class at most
        assert len(names) == len(set(names)), f"{legend} class listed twice: {names}"
