"""Negatives declare their checked solar absence, so a solar Claim on one is a false positive."""

import json

from clayzer.cases import SOLAR_ABSENCE, declare_solar_absence
from clayzer.config import REPO
from clayzer.grounding import grounding

CASES = REPO / "fixtures" / "caption" / "cases"
BUILDING = {"object": "building", "count": 1, "position": "centre", "cells": ["centre"],
            "attributes": {}, "source": "osm", "source_ids": []}  # fmt: skip


def caption(*objects):
    claims = [{"id": f"o{i}", "object": o, "count": 1, "position": "centre", "attributes": {}}
              for i, o in enumerate(objects)]  # fmt: skip
    return {"text": "", "objects": claims, "relations": [], "uncertain": []}


def test_only_negatives_get_the_label_and_only_once():
    neg = {"id": "fixed-dev-neg-1", "reference_labels": [BUILDING]}
    once = declare_solar_absence(neg)
    assert once["reference_labels"] == [BUILDING, SOLAR_ABSENCE]
    assert declare_solar_absence(once) is once
    solar = {"id": "fixed-dev-uspvdb-1", "reference_labels": [BUILDING]}
    assert declare_solar_absence(solar) is solar


def test_a_solar_claim_on_a_declared_negative_is_a_false_positive():
    labels = declare_solar_absence({"id": "x-neg-1", "reference_labels": [BUILDING]})[
        "reference_labels"
    ]
    g = grounding(caption("building", "solar_array"), labels)
    verdicts = {row["claim"]["object"]: row["verdict"] for row in g["rows"]}
    assert verdicts["solar_array"] == "false positive"
    assert g["coverage"] == 1.0  # absence is not something a Caption has to mention
    without = grounding(caption("building", "solar_array"), [BUILDING])
    assert {r["claim"]["object"]: r["verdict"] for r in without["rows"]}["solar_array"] == (
        "not verifiable"
    )


def test_every_committed_negative_declares_it():
    for name in ("caption-dev.jsonl", "caption-test.jsonl"):
        for line in (CASES / name).read_text().splitlines():
            case = json.loads(line)
            if "-neg-" in case["id"]:
                assert SOLAR_ABSENCE in case["reference_labels"], case["id"]
