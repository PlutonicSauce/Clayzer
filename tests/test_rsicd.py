"""RSICD's human captions converted to a Caption Set, and imported as unlocated Cases."""

from clayzer import rsicd
from clayzer.importer import import_rows, problems

DATASET = {"images": [
    {"filename": "airport_348.jpg", "imgid": 276, "split": "test", "sentences": [
        {"raw": "the airport is very large .", "sentid": 1380},
        {"raw": "the airport is very large .", "sentid": 1381},
    ]},
    {"filename": "00623.jpg", "imgid": 9, "split": "test", "sentences": [
        {"raw": " many buildings and green trees . ", "sentid": 45},
    ]},
    {"filename": "beach_1.jpg", "imgid": 1, "split": "train", "sentences": [
        {"raw": "a beach .", "sentid": 5},
    ]},
]}  # fmt: skip


def test_each_human_caption_of_the_split_becomes_one_row():
    rows = rsicd.rows(DATASET, "test")
    assert [r["caption_id"] for r in rows] == ["rsicd-276-1380", "rsicd-276-1381", "rsicd-9-45"]
    assert rows[0]["chip_id"] == rows[1]["chip_id"] == "rsicd-airport_348"
    assert rows[0]["caption"] == rows[1]["caption"]  # repeats kept, for the dataset card
    assert rows[2]["caption"] == "many buildings and green trees ."
    assert [r["scene"] for r in rows] == ["airport", "airport", None]  # numbered: no scene
    assert all(r["geometry"] is None and r["gsd_m"] is None for r in rows)
    assert all(problems(r) == [] for r in rows)
    assert len(rsicd.rows(DATASET, "test", limit=1)) == 2  # the first image only


def test_rsicd_rows_import_as_unlocated_cases_that_cant_be_grounded():
    result = import_rows(rsicd.rows(DATASET, "test"), "rsicd-test", progress=lambda _: None)
    assert not result.skipped and len(result.cases) == 3
    case = result.cases[0]
    assert case["id"] == "import-rsicd-test-rsicd-276-1380" and not case["located"]
    assert case["reference_labels"] == [] and case["chips"][0]["date"] is None
    assert case["imported"]["scene"] == "airport" and case["imported"]["too_small"] is None
    assert case["imported"]["generator"] == rsicd.GENERATOR
