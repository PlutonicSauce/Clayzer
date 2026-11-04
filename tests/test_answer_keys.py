"""The Answer Key clients: retries on the public APIs, and solar labels from polygons."""

import httpx
import pytest
from rasterio.warp import transform
from shapely.geometry import Polygon

from clayzer import answer_keys as ak
from clayzer.chips import Chip


@pytest.fixture
def calls(monkeypatch):
    monkeypatch.setattr(ak.time, "sleep", lambda s: None)
    seen, script = [], []

    def get(url, **kw):
        seen.append(url)
        step = script.pop(0)
        if isinstance(step, Exception):
            raise step
        return httpx.Response(step, json=[{"case_id": 1}], request=httpx.Request("GET", url))

    monkeypatch.setattr(ak.httpx, "get", get)
    return seen, script


def test_usgs_requests_retry_502s_and_timeouts(calls):
    seen, script = calls
    script += [502, httpx.ConnectTimeout("slow"), 200]
    assert ak._get(ak.USWTDB, []) == [{"case_id": 1}]
    assert len(seen) == 3


def test_usgs_requests_give_up_after_four_tries(calls):
    seen, script = calls
    script += [502] * 4
    with pytest.raises(httpx.HTTPStatusError):
        ak._get(ak.USWTDB, [])
    assert len(seen) == 4


def test_a_client_error_is_not_retried(calls):
    seen, script = calls
    script += [404]
    with pytest.raises(httpx.HTTPStatusError):
        ak._get(ak.USWTDB, [])
    assert len(seen) == 1


# ── Solar arrays from USPVDB polygons ──────────────────────────────────────────────────

CHIP = Chip(id="c", date="2022-06-18", bbox=(0, 0, 0, 0), crs="EPSG:32611", left=400_000.0,
            top=3_900_000.0, source="test", naip_item="x")  # fmt: skip


def lonlat(*pixels):
    """A lon/lat polygon from Chip pixel corners (col, row)."""
    xs = [CHIP.left + c * CHIP.res for c, _ in pixels]
    ys = [CHIP.top - r * CHIP.res for _, r in pixels]
    lons, lats = transform(CHIP.crs, "EPSG:4326", xs, ys)
    return Polygon(zip(lons, lats, strict=True))


def site(case_id, col, row, area=50_000):
    (lon,), (lat,) = transform(
        CHIP.crs, "EPSG:4326", [CHIP.left + col * CHIP.res], [CHIP.top - row * CHIP.res]
    )
    return {"case_id": case_id, "xlong": lon, "ylat": lat, "p_area": area}


def test_an_array_covering_the_south_half_is_labelled_in_every_cell_it_covers():
    # Panels over the bottom row and half the middle row; the centroid is in one cell.
    outline = lonlat((0, 256), (512, 256), (512, 512), (0, 512))
    [label] = ak.usgs_labels(CHIP, [site(1, 400, 450)], [], outlines={1: outline})
    assert label["cells"] == ["west", "centre", "east", "south_west", "south", "south_east"]
    assert label["position"] in ("south_west", "south", "south_east")
    assert label["count"] == 1


def test_an_array_centred_outside_the_chip_still_counts_where_it_covers_it():
    outline = lonlat((350, -400), (512, -400), (512, 120), (350, 120))
    [label] = ak.usgs_labels(CHIP, [site(2, 400, -200)], [], outlines={2: outline})
    assert label["cells"] == ["north_east"] and label["source_ids"] == ["2"]


def test_a_site_without_a_polygon_falls_back_to_its_centroid():
    [label] = ak.usgs_labels(CHIP, [site(3, 50, 50)], [], outlines={})
    assert label["cells"] == ["north_west"]


def test_a_sliver_along_the_edge_is_not_a_cell():
    outline = lonlat((0, -300), (512, -300), (512, 2), (0, 2))  # 2 px inside the top edge
    assert ak.usgs_labels(CHIP, [site(4, 256, -150)], [], outlines={4: outline}) == []
