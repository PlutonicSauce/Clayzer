"""Answer Keys: USGS for solar and wind, OSM for everything else (caption-plan.md §3).

Each function returns Reference Labels for one Chip, one label per object type:

    {"object", "count", "position", "cells", "attributes", "source", "source_ids"}

`position` is the cell holding most of the object; `cells` is every cell it covers, so a road
crossing the Chip is in the right place wherever a Claim puts it along the road. `count` is
None where counting isn't meaningful (roads, water, fields).

Only the Case builder and scoring may call these (ADR-0006); never the caption Harness.
"""

import os
import time
from collections import Counter, defaultdict

import httpx
from shapely.geometry import LineString, Polygon, box

from clayzer.chips import Chip
from clayzer.grid import GRID

USPVDB = "https://energy.usgs.gov/api/uspvdb/v1/projects"
USWTDB = "https://energy.usgs.gov/api/uswtdb/v1/turbines"
OVERPASS = os.environ.get("CLAYZER_OVERPASS_URL", "https://overpass-api.de/api/interpreter")
USER_AGENT = "clayzer-caption-eval/0.1 (+https://github.com/PlutonicSauce/Clayzer)"


def _get(url: str, params: list[tuple[str, str]]) -> list[dict]:
    # The USGS APIs return 502 and time out in bursts; back off and retry, like Overpass.
    for attempt in range(4):
        try:
            r = httpx.get(url, params=params, timeout=60, headers={"User-Agent": USER_AGENT})
        except httpx.TransportError:
            if attempt == 3:
                raise
        else:
            if r.status_code not in (429, 502, 503, 504) or attempt == 3:
                r.raise_for_status()
                return r.json()
        time.sleep(5 * 2**attempt)
    raise AssertionError("unreachable")


def _bbox_params(bbox, buffer_deg: float = 0.0) -> list[tuple[str, str]]:
    w, s, e, n = bbox
    b = buffer_deg
    return [
        ("xlong", f"gte.{w - b}"), ("xlong", f"lte.{e + b}"),
        ("ylat", f"gte.{s - b}"), ("ylat", f"lte.{n + b}"),
    ]  # fmt: skip


# ── USGS ────────────────────────────────────────────────────────────────────────────────


def uspvdb_site(case_id: int) -> dict:
    rows = _get(USPVDB, [("case_id", f"eq.{case_id}")])
    if not rows:
        raise LookupError(f"USPVDB has no site {case_id}")
    return rows[0]


def uswtdb_turbine(case_id: int) -> dict:
    rows = _get(USWTDB, [("case_id", f"eq.{case_id}")])
    if not rows:
        raise LookupError(f"USWTDB has no turbine {case_id}")
    return rows[0]


def usgs_near(bbox, buffer_deg: float) -> tuple[list[dict], list[dict]]:
    """Solar sites and turbines whose points fall in `bbox` grown by `buffer_deg`."""
    params = _bbox_params(bbox, buffer_deg)
    return _get(USPVDB, params), _get(USWTDB, params)


def solar_size(area_m2: float) -> str:
    """Draft thresholds (caption-plan.md §5.2), from USPVDB's array area."""
    if area_m2 < 50_000:
        return "small"
    return "medium" if area_m2 < 500_000 else "large"


def _point_label(obj: str, points: list[tuple[str, str]], source: str, ids: list[str]) -> dict:
    counts = Counter(cell for cell, _ in points)
    return {
        "object": obj,
        "count": len(points),
        "position": counts.most_common(1)[0][0],
        "cells": sorted(counts, key=GRID.index),
        "attributes": {},
        "source": source,
        "source_ids": ids,
    }


def usgs_labels(chip: Chip, solar: list[dict], turbines: list[dict]) -> list[dict]:
    labels = []
    sites = [s for s in solar if chip.inside(s["xlong"], s["ylat"])]
    if sites:
        label = _point_label(
            "solar_array",
            [(chip.cell(s["xlong"], s["ylat"]), s) for s in sites],
            "uspvdb",
            [str(s["case_id"]) for s in sites],
        )
        largest = max(sites, key=lambda s: s.get("p_area") or 0)
        if largest.get("p_area"):
            label["attributes"]["size"] = solar_size(largest["p_area"])
        labels.append(label)
    here = [t for t in turbines if chip.inside(t["xlong"], t["ylat"])]
    if here:
        labels.append(
            _point_label(
                "wind_turbine",
                [(chip.cell(t["xlong"], t["ylat"]), t) for t in here],
                "uswtdb",
                [str(t["case_id"]) for t in here],
            )
        )
    return labels


# ── OSM ─────────────────────────────────────────────────────────────────────────────────

ROAD_TYPES = {
    "motorway", "trunk", "primary", "secondary", "tertiary", "unclassified", "residential",
    "service", "track", "motorway_link", "trunk_link", "primary_link", "secondary_link",
}  # fmt: skip
PAVED = {"asphalt", "concrete", "paved", "chipseal", "paving_stones", "concrete:plates"}
UNPAVED = {"unpaved", "gravel", "dirt", "ground", "compacted", "fine_gravel", "sand", "earth"}
COUNTED = {"building", "greenhouse", "parking_lot"}


def osm_object(tags: dict) -> str | None:
    """The Caption object type an OSM way maps to, or None. Power features are left to USGS."""
    if "power" in tags:
        return None
    if tags.get("building") == "greenhouse" or tags.get("landuse") == "greenhouse_horticulture":
        return "greenhouse"
    if "building" in tags:
        return "building"
    if tags.get("highway") in ROAD_TYPES:
        return "road"
    if tags.get("railway") == "rail":
        return "railroad"
    if tags.get("amenity") == "parking":
        return "parking_lot"
    if tags.get("natural") == "water" or "waterway" in tags:
        return "water"
    if tags.get("landuse") in {"farmland", "meadow", "orchard", "vineyard"}:
        return "field"
    return None


def overpass(bbox) -> list[dict]:
    w, s, e, n = bbox
    b = f"({s},{w},{n},{e})"
    query = (
        "[out:json][timeout:60];("
        f'way["highway"]{b};way["railway"="rail"]{b};way["building"]{b};'
        f'way["natural"="water"]{b};way["waterway"]{b};way["amenity"="parking"]{b};'
        f'way["landuse"~"farmland|meadow|orchard|vineyard|greenhouse_horticulture"]{b};'
        ");out tags geom;"
    )
    # The public Overpass server sheds load with 429 and 50x; back off and retry.
    for attempt in range(4):
        r = httpx.post(
            OVERPASS, data={"data": query}, timeout=90, headers={"User-Agent": USER_AGENT}
        )
        if r.status_code not in (429, 502, 503, 504) or attempt == 3:
            break
        time.sleep(5 * 2**attempt)
    r.raise_for_status()
    return r.json()["elements"]


def _cell_boxes(size: int):
    third = size / 3
    for i, cell in enumerate(GRID):
        c, r = i % 3, i // 3
        yield cell, box(c * third, r * third, (c + 1) * third, (r + 1) * third)


def osm_labels(chip: Chip, elements: list[dict]) -> list[dict]:
    frame = box(0, 0, chip.size, chip.size)
    by_object: dict[str, list] = defaultdict(list)
    for el in elements:
        obj = osm_object(el.get("tags", {}))
        coords = [(p["lon"], p["lat"]) for p in el.get("geometry", [])]
        if obj is None or len(coords) < 2:
            continue
        closed = coords[0] == coords[-1] and len(coords) >= 4
        geom = Polygon(coords) if closed and obj != "road" else LineString(coords)
        geom = chip.to_pixels(geom).intersection(frame)
        if not geom.is_empty:
            by_object[obj].append((el, geom))

    labels = []
    for obj, feats in by_object.items():
        measure: Counter = Counter()
        for _, geom in feats:
            for cell, cbox in _cell_boxes(chip.size):
                part = geom.intersection(cbox)
                # Length for lines, area for polygons; ignore slivers along cell edges.
                m = part.area if part.area else part.length
                if m > (100 if part.area else 10):
                    measure[cell] += m
        if not measure:
            continue
        label = {
            "object": obj,
            "count": len(feats) if obj in COUNTED else None,
            "position": measure.most_common(1)[0][0],
            "cells": sorted(measure, key=GRID.index),
            "attributes": {},
            "source": "osm",
            "source_ids": [f"way/{el['id']}" for el, _ in feats],
        }
        if obj == "road":
            surface: Counter = Counter()
            for el, geom in feats:
                s = el["tags"].get("surface")
                kind = "paved" if s in PAVED else "unpaved" if s in UNPAVED else None
                if kind:
                    surface[kind] += geom.length
            if surface:
                label["attributes"]["surface"] = surface.most_common(1)[0][0]
        labels.append(label)
    return sorted(labels, key=lambda lb: lb["object"])
