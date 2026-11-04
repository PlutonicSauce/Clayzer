"""Output Score contracts, negative evidence and offline provider integration."""

import json

import pytest
from test_agentic import Scripted, turn, use
from test_grounding import caption, claim, label
from test_loop import CAPTIONS, SOLAR, FakeBedrock, env, run  # noqa: F401

from clayzer import batch
from clayzer.benchmarks import rsicd, vrsbench_boxes
from clayzer.calibration import blind_packet, calibration_metrics
from clayzer.cli import main
from clayzer.dataset_score import stratified_sample, wilson
from clayzer.extraction import PROMPT_SHA, extract, validate_claims
from clayzer.gate import gate
from clayzer.grid import GRID
from clayzer.grounding import grounding
from clayzer.imported_score import evaluate
from clayzer.judge import fidelity, self_judging, validate_verdict
from clayzer.output_score import cost_observation, preparation, score_caption
from clayzer.retrieval import freeze_queries, rank_recording, retrieval, synonym_queries
from clayzer.trace import RunInfo, Tracer


def test_missing_map_records_cannot_establish_absence():
    g = grounding(caption([claim("o", "building", "centre")]), [])
    assert g["correctness"] is None and g["coverage"] is None
    assert g["rows"][0]["outcome"] == "not_verifiable"
    assert g["unscored_share"] == 1 and g["denominators"]["unknown_claims"] == 1


@pytest.mark.parametrize("verified,expected", [(True, 0.0), (False, None)])
def test_only_explicit_independent_absence_can_contradict(verified, expected):
    ref = label("building", "centre", count=0)
    ref["absence_verified"] = verified
    g = grounding(caption([claim("o", "building", "centre")]), [ref])
    assert g["correctness"] == expected
    assert g["coverage"] is None


@pytest.mark.parametrize("cell", [c for c in GRID if c != "centre"])
def test_centre_is_not_a_safe_half_credit_guess(cell):
    g = grounding(caption([claim("o", "building", "centre")]), [label("building", cell)])
    assert g["position"] == 0


def test_unknown_counts_and_positions_are_not_guessed():
    cl = claim("o", "building", None, count=None)
    g = grounding(caption([cl]), [label("building", "north", count=8)])
    assert g["count"] is None and g["position"] is None
    assert g["precision"] == 1 and g["coverage"] == 1


@pytest.mark.parametrize("count,expected", [(1, 0.0), (2, None), (3, None)])
def test_partial_map_counts_are_lower_bounds(count, expected):
    ref = {**label("building", "centre", count=2), "source": "osm", "count_complete": False}
    g = grounding(caption([claim("o", "building", "centre", count=count)]), [ref])
    assert g["count"] == expected
    if expected is None:
        assert "count" in g["rows"][0]["unknown_fields"]


def test_exhaustive_counts_can_contradict_overcounts():
    ref = {**label("building", "centre", count=2), "source": "osm", "count_complete": True}
    g = grounding(caption([claim("o", "building", "centre", count=8)]), [ref])
    assert g["count"] == 0 and g["rows"][0]["outcome"] == "contradicted"


def test_duplicate_reference_classes_cannot_silently_overwrite_counts():
    with pytest.raises(ValueError, match="aggregate"):
        grounding(caption([]), [label("building", "north"), label("building", "south")])


def test_broad_reference_positions_do_not_prove_direction():
    refs = [
        label("road", "north", cells=["north", "south"], count=None),
        label("building", "centre"),
    ]
    cap = caption(
        [claim("a", "road", "north"), claim("b", "building", "centre")],
        [{"subject": "a", "relation": "north_of", "object": "b"}],
    )
    g = grounding(cap, refs)
    assert g["relations"] is None and len(g["relations_unscored"]) == 1


def test_parent_credit_is_semantic_not_sibling_similarity():
    parent = grounding(caption([claim("o", "building", "centre")]), [label("greenhouse", "centre")])
    assert parent["precision"] == 0.5 and parent["coverage"] == 0.5
    sibling = grounding(caption([claim("o", "railroad", "centre")]), [label("road", "centre")])
    assert sibling["correctness"] is None and sibling["coverage"] == 0
    child = grounding(caption([claim("o", "greenhouse", "centre")]), [label("building", "centre")])
    assert child["correctness"] is None


@pytest.mark.parametrize("score", [-0.1, 1.1, float("nan"), float("inf"), True, "0.5", None])
def test_invalid_judge_scores_are_unavailable_not_clamped(score):
    with pytest.raises(RuntimeError):
        validate_verdict({"score": score, "issues": []})


@pytest.mark.parametrize("issues", [None, "error", [2], {}])
def test_judge_issues_schema(issues):
    with pytest.raises(RuntimeError):
        validate_verdict({"score": 0.5, "issues": issues})


def test_wrong_tool_is_not_a_verdict():
    fake = Scripted(turn(use("other", {"score": 1, "issues": []})))
    with pytest.raises(RuntimeError, match="submit_verdict"):
        fidelity(fake, "judge", caption([]), b"png")


def test_self_judging_profiles_and_absent_models():
    assert self_judging("us.anthropic.model", "global.anthropic.model") is True
    assert self_judging(None, "judge") is None
    assert self_judging("cap", "judge") is False


def recording():
    return {
        "documents": [{"case_id": x, "text": x} for x in ["c", "a", "b"]],
        "queries": [
            {"id": "q", "query": "find", "relevant": ["b", "c"], "relevance_complete": True}
        ],
        "document_vectors": {"a": [1.0, 0.0], "b": [0.8, 0.2], "c": [0.0, 1.0]},
        "query_vectors": {"q": [1.0, 0.0]},
    }


def test_recall_mrr_hit_rate_and_stable_ties_are_distinct():
    r = rank_recording(recording(), k=2)
    assert r["mrr"] == 0.5 and r["recall@2"] == 0.5 and r["hit@2"] == 1
    assert r["queries"][0]["ranked"] == ["a", "b", "c"]
    assert rank_recording(recording(), k=1)["recall@1"] == 0
    r0 = recording()
    r0["document_vectors"] = {x: [1.0, 0.0] for x in "abc"}
    assert rank_recording(r0)["queries"][0]["ranked"] == ["a", "b", "c"]


@pytest.mark.parametrize("k", [0, -1, True, 1.2])
def test_invalid_retrieval_k(k):
    with pytest.raises(ValueError):
        rank_recording(recording(), k)


def test_missing_relevant_documents_do_not_improve_scores():
    rec = recording()
    rec["documents"] = rec["documents"][1:]
    r = rank_recording(rec)
    assert r["mrr"] is None and r["skipped_queries"][0]["missing"] == ["c"]


def test_empty_and_trivial_query_warnings():
    rec = recording()
    rec["queries"][0]["relevance_complete"] = False
    r = rank_recording(rec, 3)
    assert r["recall@3"] == 1 and len(r["warnings"]) == 3
    rec["queries"][0]["relevant"] = []
    assert rank_recording(rec)["mrr"] is None


def test_synonym_comparison_and_saved_embedding_recalculation():
    docs = [
        {"case_id": "a", "text": "solar farm", "objects": ["solar_array"]},
        {"case_id": "b", "text": "wind turbines", "objects": ["wind_turbine"]},
    ]
    q = freeze_queries(docs)
    assert "PV plant" in synonym_queries(q)[0]["query"]
    result = retrieval(FakeBedrock(), "embed", docs, compare_synonyms=True)
    assert rank_recording(result["recording"])["mrr"] == result["mrr"]
    assert result["synonym_expanded"]["query_count"] == result["query_count"]
    assert result["recording"]["documents"] == [
        {"case_id": d["case_id"], "text": d["text"]} for d in docs
    ]


def test_zero_vectors_are_explicitly_unavailable():
    docs = [
        {"case_id": "a", "text": "xxx", "objects": ["solar_array"]},
        {"case_id": "b", "text": "wind", "objects": []},
    ]
    result = retrieval(FakeBedrock(), "embed", docs)
    assert result["mrr"] is None and "unavailable" in result["warnings"][0]


def extracted():
    return {
        "objects": [
            {
                "id": "o",
                "object": "building",
                "count": 2,
                "position": "north",
                "evidence": "Two buildings in the north",
            }
        ],
        "relations": [],
        "uncertain": [],
    }


def test_extraction_is_text_only_versioned_and_traced():
    text = "Two buildings in the north."
    client = Scripted(turn(use("submit_claims", extracted())))
    t = Tracer(RunInfo("r", "caption", "c", 1, "b", "m", "p"), [])
    cap = extract(client, "extractor", text, t)
    assert cap["objects"][0]["count"] == 2 and cap["text"] == text
    assert cap["extraction"]["prompt_sha256"] == PROMPT_SHA
    assert t.steps[0].name == "claim_extraction"
    req = json.dumps(client.requests)
    assert (
        "reference_labels" not in req
        and "image" not in client.requests[0]["messages"][0]["content"][0]
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("count", 3),
        ("position", "south"),
        ("object", "solar_array"),
        ("attributes", {"surface": "paved"}),
    ],
)
def test_extraction_rejects_invented_fields(field, value):
    raw = extracted()
    raw["objects"][0][field] = value
    with pytest.raises(ValueError):
        validate_claims(raw, "Two buildings in the north.")


@pytest.mark.parametrize(
    "text",
    [
        "No Two buildings in the north.",
        "There may be Two buildings in the north.",
        "Possibly Two buildings in the north.",
    ],
)
def test_extraction_cannot_trim_negation_or_uncertainty(text):
    with pytest.raises(ValueError):
        validate_claims(extracted(), text)


def test_extractor_cannot_replace_text_or_guess_unstated_counts():
    raw = extracted()
    raw["text"] = "invented"
    assert (
        validate_claims(raw, "Two buildings in the north.")["text"] == "Two buildings in the north."
    )
    raw["objects"][0].update(count=None, position=None, evidence="buildings")
    cap = validate_claims(raw, "Some buildings.")
    assert cap["objects"][0]["count"] is None and cap["objects"][0]["position"] is None


def test_cost_and_timings_preserve_unknowns_and_methods():
    c = cost_observation(seconds=1.5, tokens=20)
    assert c["gpu_seconds"] is None and c["latency_seconds"] == 1.5
    with pytest.raises(ValueError):
        cost_observation(gpu_seconds=1)
    with pytest.raises(ValueError):
        cost_observation("local", gpu_seconds=1)
    assert (
        cost_observation(
            "local", gpu_seconds=0, gpu_count=1, gpu_type="test", method="device profiler"
        )["gpu_seconds"]
        == 0
    )
    assert preparation({})["reference_preparation"]["value"] is None
    assert preparation({"prep_seconds": 0}, 2)["reference_preparation"]["value"] == 0
    assert preparation(SOLAR)["reference_preparation"]["scope"] == "case_build"


@pytest.mark.parametrize("value", [-1, True, float("nan")])
def test_invalid_measurements_rejected(value):
    with pytest.raises(ValueError):
        preparation({"prep_seconds": value})


def imported_row():
    return {
        "id": "one",
        "text": CAPTIONS["c-solar"]["text"],
        "objects": CAPTIONS["c-solar"]["objects"],
        "reference_labels": SOLAR["reference_labels"],
        "prep_seconds": 10.0,
    }


def test_native_and_imported_paths_share_grounding_engine():
    row = imported_row()
    imported = evaluate([row])
    native = score_caption({**row, "relations": []}, row)
    assert imported["results"][0]["grounding"] == native["grounding"]
    assert imported["results"][0]["fidelity"] is None
    assert imported["criteria"] == [
        "grounding",
        "fidelity",
        "retrieval",
        "cost",
        "label_preparation",
    ]
    assert "workflow" not in imported


def test_import_without_claims_is_unavailable_instead_of_zero_coverage():
    report = evaluate(
        [{"id": "x", "caption": "A road.", "reference_labels": [label("road", "north")]}]
    )
    assert report["results"][0]["grounding"] is None
    assert report["dataset"]["overall"]["unknown_binary"] == 1


def test_import_images_judge_failures_and_self_judging():
    row = imported_row() | {"image_uri": "test.png", "generator": "cap"}
    result = evaluate(
        [row], client=FakeBedrock(), judge_model="cap", image_loader=lambda _: b"c-solar"
    )
    assert result["results"][0]["fidelity"]["self_judged"] is True

    class Bad:
        def converse(self, **kwargs):
            raise RuntimeError("bad judge")

    result = evaluate([row], client=Bad(), judge_model="j", image_loader=lambda _: b"png")
    assert result["results"][0]["grounding"] is not None
    assert result["results"][0]["fidelity"] is None
    assert "failed" in result["results"][0]["fidelity_unavailable"]


def test_imported_cli_is_offline_and_escapes_html(tmp_path, monkeypatch):
    import socket

    def no_network(*args, **kwargs):
        raise AssertionError("offline evaluation attempted network")

    monkeypatch.setattr(socket, "create_connection", no_network)
    source = tmp_path / "input.jsonl"
    source.write_text(json.dumps(imported_row() | {"text": "<script>alert(1)</script>"}) + "\n")
    target = tmp_path / "report"
    assert main(["evaluate", str(source), "--output", str(target)]) == 0
    html = (target / "output-score.html").read_text()
    assert "<script>" not in html and "&lt;" in html
    assert json.loads((target / "output-score.json").read_text())["mode"] == "imported_no_harness"


def test_imported_retrieval_recording_must_match_inputs():
    with pytest.raises(ValueError, match="match"):
        evaluate([imported_row()], recording=recording())


def test_blind_calibration_has_no_model_answers_and_requires_real_labels():
    packet = blind_packet(
        [{"id": "x", "text": "A road", "image_uri": "x.png", "score": 0.8, "issues": ["secret"]}]
    )
    assert "score" not in packet["items"][0] and "issues" not in packet["items"][0]
    labels = [
        {
            "id": "x",
            "annotator": "human",
            "blind": True,
            "rubric_sha": packet["rubric_sha"],
            "score": 0.5,
            "issues": [],
        }
    ]
    metrics = calibration_metrics(
        labels, {"x": {"score": 0.75, "issues": []}}, packet["rubric_sha"]
    )
    assert metrics["mae"] == 0.25 and metrics["pairs"] == 1
    with pytest.raises(ValueError):
        calibration_metrics(
            [labels[0] | {"blind": False}], {"x": {"score": 1, "issues": []}}, packet["rubric_sha"]
        )
    assert calibration_metrics([], {}, packet["rubric_sha"])["mae"] is None


def test_wilson_intervals_only_for_binary_rates():
    assert wilson(0, 0) is None
    lo, hi = wilson(5, 10)
    assert lo == pytest.approx(0.236593, abs=1e-6) and hi == pytest.approx(0.763407, abs=1e-6)
    rows = [imported_row() | {"region": "r", "terrain": "t"}]
    report = evaluate(rows)["dataset"]
    assert "wilson95" in report["overall"]
    assert "correctness_ci" not in report["overall"]
    assert report["overall"]["unknown_binary"] == 1  # incomplete USGS counts
    assert stratified_sample(rows) == stratified_sample(list(reversed(rows)))


def test_class_scores_do_not_repeat_whole_caption_score():
    row = {
        "id": "x",
        "text": "buildings and roads",
        "objects": [claim("b", "building", "north"), claim("r", "road", "south")],
        "reference_labels": [label("building", "north"), label("road", "north", count=None)],
    }
    report = evaluate([row])
    strata = {s["class"]: s for s in report["dataset"]["strata"]}
    assert strata["building"]["mean_correctness"] == 1
    assert strata["road"]["mean_correctness"] < 1


def test_synthetic_rsicd_adapter_deduplicates_queries_and_preserves_unknown_grounding():
    raw = {
        "images": [
            {
                "filename": f"fixture{i}.jpg",
                "split": "test",
                "sentences": [{"raw": "a synthetic road"}] * 2,
            }
            for i in range(110)
        ]
    }
    r = rsicd(raw, version="synthetic-v1", license_note="synthetic fixture only")
    assert len(r["rows"]) == 100 and len(r["queries"]) == 1
    assert len(r["queries"][0]["relevant"]) == 100
    assert r["rows"][0]["reference_labels"] is None
    with pytest.raises(ValueError):
        rsicd(raw, version="", license_note="")


def test_vrsbench_box_adapter_crosswalk_and_coverage():
    boxes = [
        {"id": "b1", "category": "house", "bbox": [0, 0, 200, 100]},
        {"id": "b2", "category": "plane", "bbox": [200, 200, 300, 300]},
    ]
    r = vrsbench_boxes(
        boxes, 300, 300, {"house": "building"}, version="synthetic-v1", license_note="synthetic"
    )
    lb = r["reference_labels"][0]
    assert lb["count"] == 1 and lb["cells"] == ["north_west", "north"]
    assert lb["count_complete"] is False and r["unsupported_categories"] == ["plane"]
    with pytest.raises(ValueError):
        vrsbench_boxes(
            [boxes[0], boxes[0]], 300, 300, {"house": "building"}, version="x", license_note="x"
        )


def test_native_batch_five_criteria_and_version_warnings(env):  # noqa: F811
    b = run(env, repeats=1)
    r = b["results"][0]
    assert (
        r["cost"]["gpu_seconds"] is None
        and r["label_preparation"]["reference_preparation"]["scope"] == "case_build"
    )
    from dataclasses import replace

    old = {**b, "config": replace(b["config"], scorer_version="grounding-3")}
    assert any("scorer_version" in w for w in gate(old, b).warnings)
    assert env[0].exists(f"batches/{b['config'].batch_id}/retrieval-queries.jsonl")
    assert b["retrieval"][0]["recording"]["queries"]


def test_missing_preparation_is_not_zero(env):  # noqa: F811
    b = run(env, repeats=1)
    cases = [{k: v for k, v in c.items() if k != "prep_seconds"} for c in b["cases"]]
    summary = batch.summarize(b["config"], cases, b["results"], b["retrieval"])
    assert summary["batch"]["label_prep_seconds"] is None


def test_extraction_default_records_a_trace_and_conserves_text():
    from clayzer.trace import loads

    cap = extract(
        Scripted(turn(use("submit_claims", extracted()))), "fixture", "Two buildings in the north."
    )
    info, steps = loads(cap["extraction"]["trace"].encode())
    assert info.status == "ok" and steps[0].name == "claim_extraction"


def test_extractor_cannot_attach_another_objects_count():
    raw = extracted()
    raw["objects"][0].update(count=3, position=None, evidence="Three roads and buildings")
    with pytest.raises(ValueError, match="attached"):
        validate_claims(raw, "Three roads and buildings.")


def test_extractor_cannot_turn_relative_direction_into_grid_position():
    raw = extracted()
    raw["objects"][0].update(count=None, evidence="buildings north of a road")
    with pytest.raises(ValueError, match="absolute"):
        validate_claims(raw, "buildings north of a road")


def test_extractor_cannot_reverse_relation_endpoints():
    text = "Buildings north of a road."
    raw = {
        "objects": [
            {
                "id": "b",
                "object": "building",
                "count": None,
                "position": None,
                "evidence": "Buildings",
            },
            {"id": "r", "object": "road", "count": 1, "position": None, "evidence": "a road"},
        ],
        "relations": [{"subject": "r", "object": "b", "relation": "north_of", "evidence": text}],
        "uncertain": [],
    }
    with pytest.raises(ValueError, match="endpoint"):
        validate_claims(raw, text)
    raw["relations"][0].update(subject="b", object="r")
    assert validate_claims(raw, text)["relations"][0]["subject"] == "b"


def test_extraction_calibration_accepts_only_imported_blind_labels():
    from clayzer.calibration import claim_calibration
    from clayzer.extraction import VERSION

    text = "Two buildings in the north."
    model = validate_claims(extracted(), text)
    row = {
        "id": "x",
        "annotator": "human",
        "blind": True,
        "extraction_version": VERSION,
        "text": text,
        "claims": extracted(),
    }
    result = claim_calibration([row], {"x": model})
    assert result["precision"] == result["recall"] == 1
    with pytest.raises(ValueError):
        claim_calibration([row | {"blind": False}], {"x": model})


def test_official_query_interface_and_imported_recording_are_reproducible():
    rows = [imported_row(), imported_row() | {"id": "two", "text": "Wind turbines."}]
    queries = [
        {
            "id": "clay-query-id",
            "query": "official placeholder fixture",
            "relevant": ["one"],
            "relevance_complete": True,
        }
    ]
    client = FakeBedrock()
    # The fixture query deliberately has no known words: its zero embedding is unavailable.
    result = evaluate(rows, client=client, embed_model="fixture", queries=queries)
    rec = result["retrieval"]["recording"]
    rec["query_vectors"]["clay-query-id"] = [1.0, 0.0, 0.0, 0.0, 0.0]
    report = evaluate(rows, queries=queries, recording=rec)
    assert report["retrieval"]["mrr"] == 1
    assert report["queries"] == queries


def test_frozen_retrieval_queries_cannot_change_on_resume(env):  # noqa: F811
    b = run(env, repeats=1)
    store, settings, _ = env
    store.put(f"batches/{b['config'].batch_id}/retrieval-queries.jsonl", b"{}\n")
    with pytest.raises(ValueError, match="missing or changed"):
        batch.resume(b["config"].batch_id, settings, store, narrate=False)


@pytest.mark.parametrize(
    "response",
    [
        {},
        {"output": None},
        {"output": {"message": {"content": "bad"}}},
        {"output": {"message": {"content": [{"toolUse": None}]}}},
    ],
)
def test_judge_malformed_envelope_is_a_provider_failure(response):
    class Bad:
        def converse(self, **kwargs):
            return response

    with pytest.raises(RuntimeError):
        fidelity(Bad(), "judge", caption([]), b"png")


def test_import_freezes_reference_and_ontology_provenance():
    r = evaluate([imported_row()])
    assert r["ontology"]["version"] and len(r["references_sha256"]) == 64
    assert r["references"]["one"]["reference_labels"] == SOLAR["reference_labels"]
