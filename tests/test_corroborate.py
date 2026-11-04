"""Corroboration: USGS labels against OSM's power mapping, with fake Overpass elements."""

from clayzer import corroborate

BBOX = (-118.0, 35.0, -117.997, 35.003)  # about 300 m


def ring(w, s, e, n):
    return [{"lon": x, "lat": y} for x, y in [(w, s), (e, s), (e, n), (w, n), (w, s)]]


def plant(source, w, s, e, n, name="Plant"):
    return {"type": "way", "id": 1, "geometry": ring(w, s, e, n),
            "tags": {"power": "plant", "plant:source": source, "name": name}}  # fmt: skip


def turbine(lon, lat, i=2):
    return {"type": "node", "id": i, "lon": lon, "lat": lat,
            "tags": {"power": "generator", "generator:source": "wind"}}  # fmt: skip


def case(*labels):
    return {"id": "fixed-dev-x", "kind": "fixed", "chips": [{"bbox": list(BBOX)}],
            "reference_labels": [{"object": o, "count": n} for o, n in labels]}  # fmt: skip


def test_a_plant_whose_outline_surrounds_the_chip_counts_as_solar():
    osm = corroborate.osm_in_chip(BBOX, [plant("solar", -118.01, 34.99, -117.99, 35.01)])
    assert osm["solar"] and osm["solar_plants"] == ["Plant"]


def test_a_plant_outside_the_chip_does_not():
    osm = corroborate.osm_in_chip(BBOX, [plant("solar", -117.98, 35.01, -117.97, 35.02)])
    assert not osm["solar"]


def test_a_multipolygon_plant_counts_through_its_outer_ways():
    rel = {"type": "relation", "id": 9, "tags": {"power": "plant", "plant:source": "solar"},
           "members": [{"role": "outer", "geometry": ring(-118.01, 34.99, -117.99, 35.01)}]}  # fmt: skip
    assert corroborate.osm_in_chip(BBOX, [rel])["solar"]


def test_turbines_are_counted_inside_the_chip_only():
    els = [turbine(-117.999, 35.001), turbine(-117.998, 35.002, 3), turbine(-117.9, 35.1, 4)]
    assert corroborate.osm_in_chip(BBOX, els)["turbines"] == 2


def test_candidate_classes_are_listed_not_labelled():
    tank = {"type": "node", "id": 5, "lon": -117.999, "lat": 35.001,
            "tags": {"man_made": "storage_tank"}}  # fmt: skip
    well = {"type": "node", "id": 6, "lon": -117.998, "lat": 35.001,
            "tags": {"man_made": "petroleum_well"}}  # fmt: skip
    osm = corroborate.osm_in_chip(BBOX, [tank, well])
    assert osm["candidates"] == {"storage_tank": 1, "well_pad": 1}


def test_compare_flags_each_disagreement():
    agree = corroborate.compare(case(("solar_array", 1)), {
        "solar": True, "turbines": 0, "solar_plants": [], "candidates": {}})  # fmt: skip
    assert agree["findings"] == []
    usgs_only = corroborate.compare(case(("solar_array", 1)), {
        "solar": False, "turbines": 0, "solar_plants": [], "candidates": {}})  # fmt: skip
    assert usgs_only["findings"] == ["solar: USGS only"]
    osm_only = corroborate.compare(case(), {
        "solar": True, "turbines": 0, "solar_plants": [], "candidates": {}})  # fmt: skip
    assert osm_only["findings"] == ["solar: OSM only"]
    wind = corroborate.compare(case(("wind_turbine", 2)), {
        "solar": False, "turbines": 1, "solar_plants": [], "candidates": {}})  # fmt: skip
    assert wind["findings"] == ["wind: USGS 2, OSM 1"]


def test_corroborate_and_summary_over_cases():
    solar = case(("solar_array", 1))
    neg = {**case(), "id": "fixed-dev-neg"}
    change = {**case(), "id": "change-dev-y", "kind": "change"}
    fake = {tuple(BBOX): [plant("solar", -118.01, 34.99, -117.99, 35.01)]}
    rows = corroborate.corroborate([solar, neg, change], fetch=lambda bs: fake[tuple(bs[0])],
                                   pause=0, progress=lambda _: None)  # fmt: skip
    assert [r["case"] for r in rows] == ["fixed-dev-x", "fixed-dev-neg"]  # Change Cases skipped
    s = corroborate.summary(rows)
    assert s["solar_cases"] == 2 and s["solar_agree"] == 1 and s["to_check"] == ["fixed-dev-neg"]


def test_a_failed_query_is_recorded_and_a_rerun_resumes():
    import httpx

    a, b = case(("solar_array", 1)), {**case(), "id": "fixed-dev-neg"}
    calls = []

    def flaky(bboxes):
        calls.append(bboxes)
        if len(calls) == 2:
            raise httpx.HTTPStatusError("502", request=None, response=None)
        return []

    saved = []
    rows = corroborate.corroborate([a, b], fetch=flaky, pause=0, progress=lambda _: None,
                                   save=saved.append, batch=1)  # fmt: skip
    assert "error" in rows[1] and len(saved) == 2
    assert corroborate.summary(rows)["failed"] == ["fixed-dev-neg"]
    again = corroborate.corroborate([a, b], fetch=lambda _: [], pause=0, progress=lambda _: None,
                                    done={r["case"]: r for r in rows}, batch=1)  # fmt: skip
    assert "error" not in again[1] and len(calls) == 2  # only the failed Case was fetched again


def test_one_query_covers_a_batch_of_chips_and_each_gets_only_its_own():
    other = (-117.9, 35.1, -117.897, 35.103)
    a, b = case(("wind_turbine", 1)), {**case(("wind_turbine", 1)), "id": "fixed-dev-y",
                                         "chips": [{"bbox": list(other)}]}  # fmt: skip
    queries = []

    def one_query(bboxes):
        queries.append(bboxes)
        return [turbine(-117.999, 35.001), turbine(-117.899, 35.101, 3)]

    rows = corroborate.corroborate([a, b], fetch=one_query, pause=0, progress=lambda _: None)
    assert len(queries) == 1 and [r["osm_turbines"] for r in rows] == [1, 1]
    q = corroborate.query([BBOX, other])
    assert q.count('"power"="substation"') == 2 and q.startswith("[out:json]")
