"""The look-alike negatives (fixtures/caption-lookalike): complete, labelled honestly, shareable."""

import json
from pathlib import Path

from clayzer.cases import parse_jsonl

ROOT = Path(__file__).parents[1] / "fixtures" / "caption-lookalike"
CASES = parse_jsonl((ROOT / "cases" / "caption-dev-lookalike.jsonl").read_bytes())


def test_there_are_enough_and_each_has_its_chip():
    assert len(CASES) >= 8
    uris = {c["chips"][0]["uri"] for c in CASES}
    on_disk = {f"chips/{f.name}" for f in (ROOT / "chips").glob("*.png")}
    assert uris == on_disk, "every Case has its Chip and no Chip is orphaned"
    for c in CASES:
        assert (ROOT / "chips" / f"{c['chips'][0]['id']}.json").exists()


def test_each_says_what_it_imitates_and_how_it_was_found():
    kinds = {c["lookalike"]["kind"] for c in CASES}
    assert kinds == {"greenhouse", "parking_lot", "reflective_roof"}
    for c in CASES:
        assert (
            c["lookalike"]["of"] == "solar_array"
            and "search_place_find" in c["lookalike"]["found_by"]
        )
        assert c["id"].startswith("fixed-dev-lookalike-neg-") and c["region"] == "dev-lookalike"


def test_none_has_a_solar_or_wind_label():
    for c in CASES:
        assert not {lb["object"] for lb in c["reference_labels"]} & {
            "solar_array",
            "wind_turbine",
        }, c["id"]


def test_chip_names_never_collide_with_the_development_negatives():
    dev = parse_jsonl((ROOT.parent / "caption" / "cases" / "caption-dev.jsonl").read_bytes())
    assert not {c["chips"][0]["id"] for c in CASES} & {c["chips"][0]["id"] for c in dev}


def test_nothing_private_or_signed_is_committed():
    for f in [ROOT / "cases" / "caption-dev-lookalike.jsonl", *(ROOT / "chips").glob("*.json")]:
        text = f.read_text()
        for bad in (
            "sig=",
            "token",
            "X-Amz",
            "amazonaws.com",
            "planetarycomputer.microsoft.com/api/sas",
        ):
            assert bad not in text, (f.name, bad)
    json.loads((ROOT / "chips" / f"{CASES[0]['chips'][0]['id']}.json").read_text())
