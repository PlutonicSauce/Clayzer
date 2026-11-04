import json

import pytest
from fastapi.testclient import TestClient
from test_loop import env  # noqa: F401

from clayzer.dataset_card import build
from clayzer.imported_score import evaluate, write_evaluation
from clayzer.ui.app import create_app


def caption(cid, text="Buildings.", obj="building", refs=None):
    row = {
        "id": cid,
        "text": text,
        "objects": [{"id": "o1", "object": obj, "count": None, "position": None}],
    }
    if refs is not None:
        row["reference_labels"] = refs
    return row


def test_empty_card_has_null_rates_and_no_invented_metadata():
    card = build(evaluate([]))
    assert card["counts"]["captions"] == 0
    assert card["duplication"]["rate"] is None
    assert card["vocabulary"]["type_token_ratio"] is None
    assert card["grounding"]["correctness"] == {"mean": None, "n": 0}
    assert card["dataset"]["source"] is None


def test_duplicate_vocabulary_unknown_metadata_and_partial_references():
    refs = [
        {
            "object": "building",
            "position": "east",
            "cells": ["east"],
            "count": 3,
            "source": "reviewed",
        }
    ]
    report = evaluate(
        [caption("a", refs=refs), caption("b", " buildings. "), caption("c", "Water.", "water")]
    )
    card = build(report)
    assert card["duplication"]["exact_duplicate_captions"] == 1
    assert card["duplication"]["rate"] == 1 / 3
    assert card["vocabulary"]["unique_tokens"] == 2
    assert card["terrain"] == {"unknown": 3}
    assert card["counts"]["captions_missing_image_identity"] == 3
    assert card["grounding"]["correctness"]["n"] == 1
    assert card["grounding"]["field_gaps"] == {"omitted_count": 1, "omitted_position": 1}
    assert card["grounding"]["binary_caption_evidence"]["unknown_binary"] == 3
    assert card["per_class_claim_outcomes"]["building"]["claims"] == 1
    assert card["per_class_claim_outcomes"]["building"]["supported"] == 1


def test_parent_credit_and_overlapping_strata_are_retained():
    refs = [
        {
            "object": "greenhouse",
            "position": "east",
            "cells": ["east"],
            "count": 1,
            "source": "test",
        }
    ]
    report = evaluate([caption("a", refs=refs)])
    card = build(report)
    assert len(card["strata"]) == 2
    assert card["per_class_claim_outcomes"]["building"]["class_credit_sum"] == 0.5
    assert card["observed_class_mappings"][0]["reference"] == "greenhouse"
    assert all(s["mean_correctness"] == 0.5 for s in card["strata"])


def test_unknown_ontology_class_remains_diagnostic_not_a_fake_confusion():
    report = evaluate([])
    report["captions"] = [{"id": "x", "text": "Something.", "objects": [{"object": "unmapped"}]}]
    card = build(report)
    assert card["class_caption_counts"] == {"unmapped": 1}
    assert card["ontology_confusers"] == {"unmapped": []}
    assert card["observed_class_mappings"] == []


def test_dataset_card_html_json_and_readonly_ui(env, tmp_path):  # noqa: F811
    settings = env[1]
    target = settings.data_dir / "datasets" / "review-set"
    report = evaluate([caption("a", "<script>alert(1)</script> Buildings.")])
    report["dataset_metadata"] = {"name": "Review set", "split": "synthetic", "source": "fixture"}
    write_evaluation(report, target)
    card = json.loads((target / "dataset-card.json").read_text())
    assert card["dataset"]["name"] == "Review set"
    html = (target / "dataset-card.html").read_text()
    assert (
        "<script>alert" not in html and "&lt;script&gt;" not in html
    )  # raw captions aren't in the card
    assert "dataset-card.html" in (target / "output-score.html").read_text()
    client = TestClient(create_app(settings))
    assert client.get("/api/datasets").json()[0]["captions"] == 1
    assert client.get("/api/datasets/review-set/dataset-card.html").status_code == 200
    assert client.get("/api/datasets/review-set/dataset-card.json").json() == card
    assert client.get("/api/datasets/review-set/private.txt").status_code == 404
    assert client.get("/api/datasets/bad..id/dataset-card.json").status_code == 400
    assert client.post("/api/batches", json={}).status_code in (403, 404, 405)


@pytest.mark.parametrize("path", ["dataset-card.json", "output-score.json", "output-score.html"])
def test_report_redaction_preserves_internal_inputs(tmp_path, path):
    report = evaluate([caption("x", "Buildings.")])
    report["captions"][0]["authorization"] = "private-value"
    report["captions"][0]["image_uri"] = (
        "https://example.com/image.png?X-Amz-Signature=private-value"
    )
    write_evaluation(report, tmp_path)
    assert "private-value" not in (tmp_path / path).read_text()
    assert report["captions"][0]["authorization"] == "private-value"
