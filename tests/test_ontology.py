"""Keeps the code's object lists in step with ontology/objects.toml (ADR-0008).

If one of these fails, either the ontology or the code changed alone: update the other, or
change both together.
"""

import pytest

from clayzer import answer_keys, grounding, harness, retrieval
from clayzer.ontology import load, prompt_context

ONT = load()

# RSICD's 30 scene classes, taken from the filenames in RSICD_optimal's dataset_rsicd.json.
RSICD_SCENES = {
    "airport", "bareland", "baseballfield", "beach", "bridge", "center", "church", "commercial",
    "denseresidential", "desert", "farmland", "forest", "industrial", "meadow",
    "mediumresidential", "mountain", "park", "parking", "playground", "pond", "port",
    "railwaystation", "resort", "river", "school", "sparseresidential", "square", "stadium",
    "storagetanks", "viaduct",
}  # fmt: skip


def test_hierarchy_is_well_formed():
    for cls in ONT.classes.values():
        chain = ONT.ancestors(cls.id)
        assert len(chain) == len(set(chain)), f"{cls.id}: cycle in parents"
        assert len(chain) <= 3, f"{cls.id}: deeper than three levels"
        assert set(cls.confusers) <= set(ONT.classes), f"{cls.id}: unknown confuser"


def test_claimable_classes_match_the_harness_vocabulary():
    assert set(ONT.claimable()) == set(harness.OBJECTS)


def test_keyed_classes_match_grounding():
    assert ONT.keyed() == grounding.KEYED


def test_retrieval_queries_match():
    assert ONT.queries() == retrieval.QUERIES
    assert set(ONT.queries().values()) <= set(ONT.claimable())


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


# ── Layer C exemplars and the prompt context (ADR-0010) ───────────────────────────────────


def test_every_keyed_class_has_caption_exemplars():
    for cid in ONT.keyed():
        assert ONT.classes[cid].caption_exemplars, f"{cid} has no Layer C exemplar"


def test_prompt_context_has_lookalikes_and_bounded_exemplars():
    ctx = prompt_context(ONT, max_total=4)
    assert "look-alikes" in ctx
    assert ctx.count('\n- "') <= 4  # exemplar lines are capped by max_total


def test_prompt_context_focus_narrows_to_those_classes():
    ctx = prompt_context(ONT, focus=["solar_array", "greenhouse"], max_total=4)
    assert "Solar array vs Greenhouse" in ctx or "Greenhouse vs Solar array" in ctx
    # An exemplar from a class outside the focus must not appear.
    assert "wind turbines" not in ctx.lower()


def test_prompt_context_is_empty_when_nothing_applies():
    # A focus of classes with no confusers and no exemplars yields no block.
    assert prompt_context(ONT, focus=["vegetation"], include_confusers=False) == ""
