"""The look-alike negatives in the development set: labelled honestly, and counted in reports."""

from pathlib import Path

from clayzer.batch import _lookalikes
from clayzer.cases import SOLAR_ABSENCE, parse_jsonl

ROOT = Path(__file__).parents[1] / "fixtures" / "caption"
DEV = parse_jsonl((ROOT / "cases" / "caption-dev.jsonl").read_bytes())
LOOKALIKES = [c for c in DEV if c.get("lookalike")]


def test_the_development_set_has_its_lookalikes():
    assert len(LOOKALIKES) >= 8
    assert {c["lookalike"]["kind"] for c in LOOKALIKES} == {
        "greenhouse",
        "parking_lot",
        "reflective_roof",
    }
    for c in LOOKALIKES:
        assert (
            c["lookalike"]["of"] == "solar_array"
            and "search_place_find" in c["lookalike"]["found_by"]
        )
        assert c["id"].startswith("fixed-dev-lookalike-neg-") and c["region"] == "dev"


def test_none_has_a_solar_or_wind_label():
    for c in LOOKALIKES:
        present = {lb["object"] for lb in c["reference_labels"] if lb.get("count") != 0}
        assert not present & {"solar_array", "wind_turbine"}, c["id"]


def test_each_declares_its_checked_solar_absence():
    for c in LOOKALIKES:
        solar = [lb for lb in c["reference_labels"] if lb["object"] == "solar_array"]
        assert solar == [SOLAR_ABSENCE], c["id"]


def test_chip_names_are_unique_across_the_set():
    ids = [c["chips"][0]["id"] for c in DEV]
    assert len(ids) == len(set(ids))


def test_a_batch_summary_counts_each_kind_it_fooled():
    greenhouse, roof = (
        LOOKALIKES[0],
        next(c for c in LOOKALIKES if c["lookalike"]["kind"] == "reflective_roof"),
    )
    solar = {"verdict": "false positive", "claim": {"object": "solar_array"}}
    results = [
        {"case_id": greenhouse["id"], "status": "ok", "grounding": {"rows": [solar]}},
        {"case_id": greenhouse["id"], "status": "ok", "grounding": {"rows": []}},
        {"case_id": roof["id"], "status": "ok", "grounding": {"rows": []}},
        {"case_id": roof["id"], "status": "sandbox_failure"},  # no valid score: left out
        {
            "case_id": DEV[0]["id"],
            "status": "ok",
            "grounding": {"rows": [solar]},
        },  # not a look-alike
    ]
    got = _lookalikes(DEV, results)
    assert got[greenhouse["lookalike"]["kind"]] == {
        "of": "solar_array",
        "cases": 1,
        "runs": 2,
        "fooled": 1,
    }
    assert got["reflective_roof"] == {"of": "solar_array", "cases": 1, "runs": 1, "fooled": 0}
    assert _lookalikes([c for c in DEV if not c.get("lookalike")], results) is None
