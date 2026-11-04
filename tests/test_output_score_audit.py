"""Independent audit regressions: score scope and consistent parent attribution."""

import json

import pytest
from test_grounding import caption, claim, label
from test_loop import env, run  # noqa: F401

from clayzer.grounding import grounding
from clayzer.imported_score import evaluate, write_evaluation
from clayzer.output_score import score_caption
from clayzer.report_html import _claim_table
from clayzer.run_report import run_keys


def vague_row():
    return {
        "id": "vague",
        "text": "Buildings are present.",
        "objects": [claim("b", "building", None, count=None)],
        "reference_labels": [label("building", "east", count=3)],
    }


def test_audit_vague_caption_keeps_metrics_but_discloses_omitted_detail():
    row = vague_row()
    g = grounding(caption(row["objects"]), row["reference_labels"])
    # These narrow definitions are intentional, not the bug to fix by penalizing unknowns.
    assert g["correctness"] == g["coverage"] == 1.0
    assert g["count"] is None and g["position"] is None
    assert g["specificity"]["count"] == {"available": 1, "stated": 0, "evaluated": 0}
    assert g["specificity"]["position"] == {"available": 1, "stated": 0, "evaluated": 0}
    assert g["specificity"]["share"] == 0.0
    assert g["rows"][0]["omitted_fields"] == ["count", "position"]


def test_audit_specificity_is_disclosure_not_another_accuracy_score():
    refs = [label("building", "east", count=3)]
    detailed = grounding(caption([claim("b", "building", "east", count=3)]), refs)
    wrong = grounding(caption([claim("b", "building", "west", count=9)]), refs)
    assert detailed["specificity"]["share"] == wrong["specificity"]["share"] == 1.0
    assert detailed["correctness"] == detailed["coverage"] == 1.0
    assert wrong["correctness"] < detailed["correctness"]
    assert wrong["coverage"] == 1.0


def test_audit_stated_counts_with_incomplete_evidence_are_not_evaluated():
    refs = [{**label("building", "east", count=3), "count_complete": False}]
    g = grounding(caption([claim("b", "building", "east", count=3)]), refs)
    assert g["count"] is None
    assert g["specificity"]["count"] == {"available": 1, "stated": 1, "evaluated": 0}
    assert g["specificity"]["share"] == 1.0


def test_audit_unavailable_reference_fields_do_not_become_missing_caption_detail():
    ref = {**label("road", "east", count=None), "cells": []}
    g = grounding(caption([claim("r", "road", None, count=None)]), [ref])
    assert g["specificity"]["count"]["available"] == 0
    assert g["specificity"]["position"]["available"] == 0
    assert g["specificity"]["share"] is None


def test_audit_parent_match_retains_credit_in_both_class_slices():
    cap = caption([claim("b", "building", "centre")])
    case = {"reference_labels": [label("greenhouse", "centre")]}
    result = score_caption(cap, case)
    overall = result["grounding"]
    assert overall["correctness"] == 0.75 and overall["coverage"] == 0.5
    for cls in ("building", "greenhouse"):
        part = result["grounding_by_class"][cls]
        assert part["correctness"] == overall["correctness"]
        assert part["coverage"] == overall["coverage"]
        assert part["precision"] == 0.5 and part["missed"] == []
        assert part["rows"][0]["reference_object"] == "greenhouse"
        assert part["rows"][0]["class_credit"] == 0.5


def test_audit_dataset_strata_preserve_parent_match():
    row = {
        "id": "parent",
        "text": "A building in the centre.",
        "objects": [claim("b", "building", "centre")],
        "reference_labels": [label("greenhouse", "centre")],
    }
    report = evaluate([row])
    for stratum in report["dataset"]["strata"]:
        assert stratum["mean_correctness"] == 0.75
        assert stratum["correctness_n"] == 1


def test_audit_class_slicing_cannot_invent_a_parent_match_or_change_count_evidence():
    cap = caption([claim("b", "building", "centre")])
    refs = [label("building", "west"), label("greenhouse", "centre")]
    result = score_caption(cap, {"reference_labels": refs})
    assert result["grounding_by_class"]["building"]["rows"][0]["reference_object"] == "building"
    assert result["grounding_by_class"]["building"]["position"] == 0.0
    assert result["grounding_by_class"]["greenhouse"]["coverage"] == 0.0
    assert result["grounding_by_class"]["greenhouse"]["rows"] == []


def test_audit_vague_import_report_prominently_explains_conditional_scores(tmp_path):
    report = evaluate([vague_row()])
    write_evaluation(report, tmp_path)
    html = (tmp_path / "output-score.html").read_text()
    # The qualifier must appear before the raw JSON, not be buried in its components.
    opening = html.split("<pre", 1)[0]
    assert "Count detail: 0/1 stated; 0/1 evaluated" in opening
    assert "Position detail: 0/1 stated; 0/1 evaluated" in opening
    assert "does not establish full caption quality" in opening
    assert "not comparable" in opening
    assert report["results"][0]["grounding"]["correctness"] == 1.0


def test_audit_claim_table_discloses_unspecified_count_and_position():
    row = vague_row()
    g = grounding(caption(row["objects"]), row["reference_labels"])
    html = _claim_table(g, row["reference_labels"])
    assert "not stated: count, position" in html
    assert "Count detail: 0/1 stated; 0/1 evaluated" in html
    assert "None" not in html


def test_audit_native_run_reports_retain_specificity_and_scope(env):  # noqa: F811
    batch = run(env, repeats=1)
    store = env[0]
    result = batch["results"][0]
    hkey, jkey = run_keys(batch["config"].batch_id, result["case_id"], 1)
    record = json.loads(store.get(jkey))
    assert record["scores"]["grounding"]["specificity"] == result["grounding"]["specificity"]
    assert "does not establish full caption quality" in store.get(hkey).decode()


@pytest.mark.parametrize("missing", ["count", "position"])
def test_audit_partial_omission_is_reported_without_changing_correctness(missing):
    obj = claim("b", "building", "east", count=3)
    obj[missing] = None
    g = grounding(caption([obj]), [label("building", "east", count=3)])
    assert g["correctness"] == g["coverage"] == 1.0
    assert g["specificity"]["share"] == 0.5
    assert g["specificity"][missing]["stated"] == 0
