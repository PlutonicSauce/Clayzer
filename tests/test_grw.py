"""Global Renewables Watch: reading its GeoPackages, and dating Change Cases with it."""

import sqlite3
import struct

import pytest
from shapely import wkb
from shapely.geometry import Point, box
from shapely.ops import transform

from clayzer import answer_keys as ak
from clayzer import grw
from clayzer.cases import change_labels
from clayzer.importer import footprint_chip

W, S, E, N = -118.196, 35.228, -118.193, 35.231
BOX = {"type": "Polygon", "coordinates": [[[W, S], [E, S], [E, N], [W, N], [W, S]]]}


def _mercator(x, y, z=None):
    return grw._to_mercator(x, y)


def gpkg(path, kind, features):
    """A minimal GeoPackage like GRW's: a features table, its R-tree, Web Mercator geometries
    with a "GP" header and no envelope."""
    table = f"{kind}_test"
    con = sqlite3.connect(path)
    con.execute("create table gpkg_contents (table_name text, data_type text)")
    con.execute("insert into gpkg_contents values (?, 'features')", (table,))
    con.execute(f'create table "{table}" (fid integer primary key, geom blob, '
                "construction_year real, construction_quarter real)")  # fmt: skip
    con.execute(
        f'create virtual table "rtree_{table}_geom" using rtree(id, minx, maxx, miny, maxy)'
    )
    for fid, (geom, year, quarter) in enumerate(features, 1):
        merc = transform(_mercator, geom)
        blob = b"GP" + bytes([0, 0b00000001]) + struct.pack("<i", 3857) + wkb.dumps(merc)
        con.execute(f'insert into "{table}" values (?, ?, ?, ?)', (fid, blob, year, quarter))
        x0, y0, x1, y1 = merc.bounds
        con.execute(
            f'insert into "rtree_{table}_geom" values (?, ?, ?, ?, ?)', (fid, x0, x1, y0, y1)
        )
    con.commit()
    con.close()


@pytest.fixture
def grw_files(tmp_path, monkeypatch):
    """GRW with one solar array (2019 Q3) and two turbines (2018 Q2, and by 2017 Q4)."""
    files = {"solar": tmp_path / "solar.gpkg", "wind": tmp_path / "wind.gpkg"}
    gpkg(files["solar"], "solar", [(box(W, S, (W + E) / 2, N), 2019, 3)])
    gpkg(
        files["wind"],
        "wind",
        [(Point(E - 3e-4, N - 3e-4), 2018, 2), (Point(W + 3e-4, S + 3e-4), 2017, 4)],
    )
    monkeypatch.setattr(grw, "path", lambda kind: files[kind])
    grw._db.cache_clear()
    yield files
    grw._db.cache_clear()


def test_quarters_have_a_first_and_last_day():
    assert grw.quarter_start(2018, 2).isoformat() == "2018-04-01"
    assert grw.quarter_end(2018, 2).isoformat() == "2018-06-30"
    assert grw.quarter_end(2019, 4).isoformat() == "2019-12-31"


def test_a_geopackage_is_read_back_in_lon_lat(grw_files):
    (array,) = grw.near("solar", (W, S, E, N))
    assert array.label == "2019Q3" and not array.censored
    assert array.geometry.bounds == pytest.approx((W, S, (W + E) / 2, N), abs=1e-9)
    turbines = grw.near("wind", (W, S, E, N))
    assert sorted(t.label for t in turbines) == ["2018Q2", "by 2017Q4"]
    assert grw.near("wind", (W - 1, S - 1, W - 0.9, S - 0.9)) == []


def turbine(case_id=9, p_year=None, at=(E - 3e-4, N - 3e-4)):
    return {"case_id": case_id, "xlong": at[0], "ylat": at[1], "p_year": p_year}


def test_grw_dates_a_turbine_usgs_has_no_year_for(grw_files):
    d = grw.dating("uswtdb", turbine())
    assert d["source"] == "grw" and d["grw"] == ["2018Q2"] and d["flag"] is None
    assert (d["before"], d["after"]) == ("2018-03-31", "2018-07-01")  # either side of Q2


def test_usgs_years_come_first_and_grw_checks_them(grw_files):
    agree = grw.dating("uswtdb", turbine(p_year=2019))
    assert agree["source"] == "uswtdb" and agree["before"] == "2018-12-31" and agree["flag"] is None
    with pytest.raises(grw.Flagged, match="USGS says 2021, GRW says 2018Q2"):
        grw.dating("uswtdb", turbine(p_year=2021))  # a person looks first
    with pytest.raises(grw.Flagged, match="GRW saw it by 2017Q4"):
        grw.dating("uswtdb", turbine(p_year=2020, at=(W + 3e-4, S + 3e-4)))  # still contradicts
    fine = grw.dating("uswtdb", turbine(p_year=2015, at=(W + 3e-4, S + 3e-4)))
    assert fine["flag"] is None


def test_after_a_look_a_person_chooses_which_date(grw_files):
    by_grw = grw.dating("uswtdb", turbine(p_year=2021), dated_by="grw")
    assert by_grw["source"] == "grw" and by_grw["before"] == "2018-03-31"
    assert by_grw["flag"] and by_grw["chosen_by"].startswith("a person")
    by_usgs = grw.dating("uswtdb", turbine(p_year=2021), dated_by="usgs")
    assert by_usgs["source"] == "uswtdb" and by_usgs["after"] == "2022-01-01"
    with pytest.raises(ValueError, match="can't date the pair"):
        grw.dating("uswtdb", turbine(p_year=2020, at=(W + 3e-4, S + 3e-4)), dated_by="grw")


def test_nothing_to_bracket_is_an_error(grw_files):
    with pytest.raises(ValueError, match="only says built by 2017Q4"):
        grw.dating("uswtdb", turbine(at=(W + 3e-4, S + 3e-4)))
    with pytest.raises(ValueError, match="GRW has no match"):
        grw.dating("uswtdb", turbine(at=(W - 0.5, S)))


def test_a_solar_site_matches_the_arrays_touching_its_polygon(grw_files, monkeypatch):
    site = {"case_id": 7, "xlong": W + 1e-4, "ylat": S + 1e-4, "p_year": None}
    monkeypatch.setattr(ak, "uspvdb_outlines", lambda: ("v", {7: box(W, S, W + 5e-4, S + 5e-4)}))
    assert [f.label for f in grw.matches("uspvdb", site)] == ["2019Q3"]
    assert grw.built_on("uspvdb", [site, {**site, "p_year": 2016}]) == {"7": "2019-09-30"}


def test_change_labels_use_grw_for_a_turbine_with_no_usgs_year(grw_files, monkeypatch):
    monkeypatch.setattr(ak, "usgs_near", lambda *a, **k: ([], [turbine()]))
    monkeypatch.setattr(ak, "uspvdb_outlines", lambda: ("v", {}))
    monkeypatch.setattr(ak, "overpass", lambda bbox: [])
    monkeypatch.setattr(ak, "osm_labels", lambda chip, elements: [])

    def chip(day):
        return footprint_chip({"chip_id": f"k-{day}", "geometry": BOX, "datetime": day,
                               "sensor": "naip", "stac_item": ""})  # fmt: skip

    (wind,) = change_labels(chip("2016-06-01"), chip("2020-06-01"))
    assert wind["object"] == "wind_turbine" and wind["change"] == "appeared"  # GRW: 2018 Q2
    (wind,) = change_labels(chip("2018-08-01"), chip("2020-06-01"))
    assert wind["change"] == "unchanged"
