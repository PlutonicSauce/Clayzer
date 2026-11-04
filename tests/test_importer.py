"""The caption importer: rows checked, footprints gridded, Answer Keys by location and date."""

import importlib.util
import json
from types import SimpleNamespace

import pytest

from clayzer import answer_keys as ak
from clayzer import importer
from clayzer.answer_keys import existed_by
from clayzer.importer import footprint_chip, import_rows, problems, read_rows, too_small

# A 0.003° square near Mojave: about 270 m × 330 m, UTM zone 11.
W, S, E, N = -118.196, 35.228, -118.193, 35.231
BOX = {"type": "Polygon", "coordinates": [[[W, S], [E, S], [E, N], [W, N], [W, S]]]}


def row(i="c1", chip="k1", **kw):
    return {"caption_id": i, "chip_id": chip, "caption": "A solar farm.", "kind": "fixed",
            "geometry": BOX, "datetime": "2014-06-01", "sensor": "naip", "gsd_m": 0.6, **kw}  # fmt: skip


@pytest.fixture
def keys(monkeypatch):
    """Fake Answer Keys: one solar site built 2010 at the footprint's centre, one built 2015."""
    calls = {"usgs": 0, "osm": 0}
    centre = ((W + E) / 2, (S + N) / 2)
    old = {"case_id": 1, "xlong": centre[0], "ylat": centre[1], "p_year": 2010, "p_area": 5e4}
    new = {"case_id": 2, "xlong": centre[0], "ylat": centre[1], "p_year": 2015, "p_area": 5e4}

    def usgs_near(bbox, *a, **k):
        calls["usgs"] += 1
        return [old, new], []

    def overpass(bbox):
        calls["osm"] += 1
        return []

    monkeypatch.setattr(ak, "usgs_near", usgs_near)
    monkeypatch.setattr(ak, "overpass", overpass)
    monkeypatch.setattr(ak, "uspvdb_outlines", lambda: ("v-test", {}))  # centroids only
    return calls


def test_rows_are_checked():
    assert problems(row()) == []
    assert problems(row(geometry=None)) == []  # unlocated is allowed
    assert "missing gsd_m" in problems({k: v for k, v in row().items() if k != "gsd_m"})
    assert "only fixed captions" in problems(row(kind="change"))[0]
    assert "GeoJSON Polygon" in problems(row(geometry={"type": "Point", "coordinates": [0, 0]}))[0]
    assert problems(row(gsd_m=0)) == ["gsd_m must be a positive number"]


def test_a_footprint_becomes_a_grid_in_its_utm_zone():
    chip = footprint_chip(row())
    assert chip.crs == "EPSG:32611" and chip.size == 512 and chip.date == "2014-06-01"
    assert chip.cell((W + E) / 2, (S + N) / 2) == "centre"
    assert chip.cell(E - 1e-4, N - 1e-4) == "north_east"
    assert chip.cell(W + 1e-4, S + 1e-4) == "south_west"


def test_only_sites_built_by_the_acquisition_year_count():
    recs = [{"p_year": 2010}, {"p_year": 2015}, {"p_year": None}]
    assert existed_by(recs, 2014) == [{"p_year": 2010}, {"p_year": None}]


def test_import_attaches_labels_by_location_and_date(keys):
    rows = [
        row("c1", "k1"),
        row("c2", "k1", caption="Panels in rows."),
        row("c3", "k2", geometry=None),
    ]
    result = import_rows(rows, "t", progress=lambda _: None)
    c1, c2, c3 = result.cases
    assert c1["id"] == "import-t-c1" and c1["located"] and c1["region"] == "import-t"
    (solar,) = [lb for lb in c1["reference_labels"] if lb["object"] == "solar_array"]
    assert (
        solar["source_ids"] == ["1"] and solar["position"] == "centre"
    )  # the 2015 site isn't there
    assert c1["answer_keys"]["usgs_after_date"] == 1 and "today's map" in c1["answer_keys"]["osm"]
    assert (
        c2["reference_labels"] == c1["reference_labels"] and keys["usgs"] == 1
    )  # one chip, built once
    assert not c3["located"] and c3["reference_labels"] == [] and c3["chips"][0]["bbox"] is None
    assert c1["imported"]["caption"] == "A solar farm." and c1["chips"][0]["gsd_m"] == 0.6


def test_unusable_rows_are_skipped_with_a_reason(keys):
    result = import_rows([row(), row("bad", kind="change")], "t", progress=lambda _: None)
    assert len(result.cases) == 1 and result.skipped[0]["caption_id"] == "bad"


def test_claims_too_small_for_the_imagery_are_flagged():
    claims = {"objects": [{"id": "o1", "object": "wind_turbine"}, {"id": "o2", "object": "field"}]}
    flagged = too_small(claims, 10)
    assert [f["object"] for f in flagged] == ["wind_turbine"] and flagged[0]["min_visible_m"] < 10
    assert too_small(claims, 0.6) == [] and too_small(None, 10) == []


@pytest.mark.skipif(importlib.util.find_spec("pyarrow") is None, reason="needs the import extra")
def test_geoparquet_rows_read_like_json_lines(tmp_path):
    import pyarrow as pa
    import pyarrow.parquet as pq
    from shapely.geometry import shape

    r = row(claims=json.dumps({"objects": [], "relations": [], "uncertain": []}))
    r["geometry"] = shape(BOX).wkb
    path = tmp_path / "set.parquet"
    pq.write_table(pa.Table.from_pylist([r]), path)
    (got,) = read_rows(path)
    assert got["geometry"]["type"] == "Polygon" and got["claims"]["objects"] == []
    assert problems(got) == []


def test_a_batch_becomes_a_caption_set():
    batch = {
        "config": SimpleNamespace(caption_model="cap-model"),
        "cases": [{"id": "case-a", "chips": [{"id": "k1", "bbox": [W, S, E, N], "date": "2022-07-02"}]}],
        "captions": [{"case_id": "case-a", "repeat": 2, "text": "A solar farm.", "relations": [],
                      "objects": [{"id": "o1", "object": "solar_array", "count": 1, "position": "centre"}],
                      "uncertain": []}],
    }  # fmt: skip
    (r,) = importer.caption_rows(batch)
    assert problems(r) == [] and r["caption_id"] == "case-a--r2" and r["generator"] == "cap-model"
    assert r["claims"]["objects"][0]["object"] == "solar_array" and r["datetime"] == "2022-07-02"
