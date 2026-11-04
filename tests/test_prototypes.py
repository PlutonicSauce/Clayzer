"""Layer B of the data-driven ontology: prototypes, the cost guards, and the circularity guard
(ADR-0010)."""

import json

import pytest

from clayzer import prototypes as proto
from clayzer.ontology import load

ONT = load()


def _build(**kw):
    pairs = [
        ("solar_array", [1.0, 0.0, 0.0]),
        ("solar_array", [0.9, 0.1, 0.0]),
        ("greenhouse", [0.8, 0.6, 0.0]),
        ("water", [0.0, 0.0, 1.0]),
        ("substation", [0.0, 1.0, 0.0]),  # not a Layer B class (a non-claimable candidate): dropped
    ]
    return proto.build(
        pairs, ontology_version="test", build_region="dev", source="unit",
        embedding_model="fake", **kw,
    )  # fmt: skip


def test_build_averages_and_normalises_centroids():
    p = _build()
    assert p.counts["solar_array"] == 2
    assert pytest.approx(sum(x * x for x in p.centroids["solar_array"]), abs=1e-9) == 1.0


def test_build_keeps_only_layer_b_classes():
    p = _build()
    assert "substation" not in p.centroids  # outside LAYER_B_CLASSES
    assert set(p.centroids) <= set(proto.LAYER_B_CLASSES)


def test_nearest_ranks_by_cosine():
    p = _build()
    ranked = p.nearest([1.0, 0.0, 0.0], k=3)
    assert ranked[0][0] == "solar_array"
    assert ranked[0][1] > ranked[1][1]


def test_nearest_ignores_wrong_dimension():
    assert _build().nearest([1.0, 0.0], k=3) == []


def test_hint_is_empty_below_the_similarity_floor():
    p = _build()
    # Orthogonal to every centroid except water, which it is also far from: nothing clears SIM_FLOOR.
    assert proto.hint(p, [0.0, 0.0, 0.0], ONT) == ""


def test_hint_flags_ambiguous_lookalikes():
    p = _build()
    line = proto.hint(p, [0.9, 0.3, 0.0], ONT)  # equidistant from solar and greenhouse
    assert "Solar array" in line and "Greenhouse" in line
    assert "look alike" in line


def test_hint_is_quiet_when_one_class_clearly_wins():
    p = _build()
    line = proto.hint(p, [1.0, 0.0, 0.0], ONT)
    assert "Solar array" in line
    assert "look alike" not in line


def test_circularity_guard_refuses_the_build_region():
    p = _build()
    with pytest.raises(proto.CircularityError):
        proto.guard_scoring_region(p, "dev")
    proto.guard_scoring_region(p, "test-region")  # a disjoint region is fine


def test_caption_context_without_layer_b_is_just_a_and_c():
    ctx = proto.caption_context(ONT, None, None)
    assert "look-alike" in ctx.lower() or "Example phrasings" in ctx
    assert "Embedding similarity" not in ctx


def test_caption_context_adds_layer_b_and_honours_circularity():
    p = _build()
    ctx = proto.caption_context(ONT, p, [1.0, 0.0, 0.0], scoring_region="held-out")
    assert "Embedding similarity" in ctx
    with pytest.raises(proto.CircularityError):
        proto.caption_context(ONT, p, [1.0, 0.0, 0.0], scoring_region="dev")


def test_layer_b_fires_end_to_end_through_the_batch_path(tmp_path, monkeypatch):
    """embed Cases → build prototypes → a Batch on a DISJOINT region gets the Layer B hint."""
    from clayzer import batch as batches
    from clayzer import embeddings as emb

    # A development region (NOT scored): one solar Case, one water Case, each with an embedding.
    dev = [
        {"id": "fixed-dev-solar", "chips": [{"id": "d1", "embedding": [1.0, 0.0, 0.0]}],
         "reference_labels": [{"object": "solar_array", "count": 1, "position": "centre"}]},
        {"id": "fixed-dev-water", "chips": [{"id": "d2", "embedding": [0.0, 0.0, 1.0]}],
         "reference_labels": [{"object": "water", "count": 1, "position": "centre"}]},
    ]  # fmt: skip
    pairs = emb.pairs_from_cases(dev)
    protos = proto.build(pairs, ontology_version=ONT.version, build_region="dev",
                         source="lgnd-embeddings", embedding_model="clay-v1")  # fmt: skip
    path = tmp_path / f"v{ONT.version}.json"
    proto.LocalPrototypes(path).save(protos)
    monkeypatch.setattr(proto, "default_path", lambda version, root=None: path)

    cfg = batches.BatchConfig(
        batch_id="b", label="", created="", region="held-out", repeats=1, case_ids=[],
        cases_sha="", caption_model="m", judge_model=None, embed_model="e", prompt_sha="",
        prompt_source="built-in", ontology_version=ONT.version, ontology_context=True,
    )  # fmt: skip

    # A test-region Chip whose embedding is nearest the solar prototype: the hint must name it.
    ctx = batches._ontology_context(cfg, {"id": "t1", "embedding": [1.0, 0.0, 0.0]})
    assert ctx and "Embedding similarity" in ctx and "Solar array" in ctx

    # A Chip with no embedding gets Layers A + C only, no Layer B line (zero extra cost).
    a_and_c = batches._ontology_context(cfg, {"id": "t2"})
    assert "Embedding similarity" not in (a_and_c or "")

    # Scoring the region the prototypes were built on is refused (circularity guard).
    circular = batches.BatchConfig(**{**cfg.__dict__, "region": "dev"})
    with pytest.raises(proto.CircularityError):
        batches._ontology_context(circular, {"id": "t1", "embedding": [1.0, 0.0, 0.0]})


def test_layer_a_confusers_are_data_driven_when_prototypes_exist():
    """With a prototype file, the look-alike line uses MEASURED pairs, not the hand-curated ones."""
    p = _build()  # centroids for solar_array, greenhouse, water; wind_turbine dropped
    # Embedding nearest solar; its measured nearest other class drives the confuser line.
    ctx = proto.caption_context(ONT, p, [1.0, 0.0, 0.0], scoring_region="held-out")
    assert "Easily-confused look-alikes" in ctx
    assert "Solar array vs" in ctx
    # The hand-curated ontology pairs solar with parking_lot; the measured set here does not.
    assert "Parking lot" not in ctx.split("Example phrasings")[0]


def test_learned_confuser_pairs_are_distinct():
    p = _build()
    pairs = proto.learned_confuser_pairs(p)
    assert all(a != b for a, b in pairs)
    assert len({frozenset(pr) for pr in pairs}) == len(pairs)  # no duplicates


def test_local_backend_roundtrips(tmp_path):
    p = _build()
    path = tmp_path / "v-test.json"
    backend = proto.LocalPrototypes(path)
    assert not backend.exists()
    backend.save(p)
    assert backend.exists()
    loaded = backend.load()
    assert loaded.centroids.keys() == p.centroids.keys()
    assert loaded.build_region == "dev"
    assert json.loads(path.read_text())["embedding_model"] == "fake"
