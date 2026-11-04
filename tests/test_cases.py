"""The Case builder leaves no orphaned Chip when a Case can't be built."""

import httpx
import pytest

from clayzer import cases
from clayzer.chips import Chip
from clayzer.store import LocalStore

CHIP = Chip(id="tx-uspvdb-1-20220101", date="2022-01-01", bbox=(-100.0, 30.0, -99.99, 30.01),
            crs="EPSG:32614", left=0.0, top=0.0, source="naip-aws", naip_item="item")  # fmt: skip


@pytest.fixture
def store(tmp_path, monkeypatch):
    store = LocalStore(tmp_path / "data", tmp_path / "batches")

    def cut_chip(*args, **kwargs):
        for suffix in (".png", ".json"):
            store.put(f"chips/{CHIP.id}{suffix}", b"x")
        return CHIP

    monkeypatch.setattr(cases, "find_naip", lambda *a, **k: "item")
    monkeypatch.setattr(cases, "cut_chip", cut_chip)
    monkeypatch.setattr(cases.ak, "uspvdb_site", lambda i: {
        "p_sys_type": "ground", "p_state": "TX", "xlong": -100.0, "ylat": 30.0, "p_year": 2020})  # fmt: skip
    monkeypatch.setattr(cases.ak, "usgs_near", lambda *a, **k: ([], []))
    monkeypatch.setattr(cases, "_solar_nearby", lambda chip: [])
    return store


def _overpass_down(bbox):
    raise httpx.HTTPStatusError("502 Bad Gateway", request=None, response=None)


def _chips(store) -> list[str]:
    return [f"{CHIP.id}{s}" for s in (".png", ".json") if store.exists(f"chips/{CHIP.id}{s}")]


def test_a_positive_whose_labels_fail_leaves_no_chip(store, monkeypatch):
    monkeypatch.setattr(cases.ak, "overpass", _overpass_down)
    with pytest.raises(httpx.HTTPStatusError):
        cases.build_positive("uspvdb", 1, "test", store)
    assert _chips(store) == []


def test_a_negative_whose_labels_fail_leaves_no_chip(store, monkeypatch):
    monkeypatch.setattr(cases.ak, "overpass", _overpass_down)
    with pytest.raises(httpx.HTTPStatusError):
        cases.build_negative(-100.0, 30.0, 1, "TX", "test", store)
    assert _chips(store) == []


def test_a_refused_negative_leaves_no_chip(store, monkeypatch):
    monkeypatch.setattr(cases.ak, "usgs_near", lambda *a, **k: ([{"case_id": 7}], []))
    with pytest.raises(ValueError, match="not a negative"):
        cases.build_negative(-100.0, 30.0, 1, "TX", "test", store)
    assert _chips(store) == []


def test_a_built_case_keeps_its_chip(store, monkeypatch):
    monkeypatch.setattr(cases.ak, "overpass", lambda bbox: [])
    monkeypatch.setattr(cases.ak, "usgs_labels", lambda *a: [])
    monkeypatch.setattr(cases, "load_corrections", list)
    case = cases.build_positive("uspvdb", 1, "test", store)
    assert case["id"] == "fixed-test-uspvdb-1" and len(_chips(store)) == 2
