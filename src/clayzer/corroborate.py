"""Corroborate the USGS labels with OSM's own power tags, and list OSM's candidate classes.

USPVDB and USWTDB are the Answer Keys for solar and wind, and OSM for everything else, so the
one independent check we have is OSM's power mapping of the same sites (ontology osm_reference,
which the Answer Keys never use). A Case where the two disagree goes to an eye check: USGS
listed RE Gaskell West 5 and Samson Solar III years before their panels show in NAIP.

The same query lists OSM features of the ontology's candidate classes (substation, storage
tank, well pad, construction site) in each Chip: evidence for making one claimable, never a
Reference Label, since no Answer Key scores them.

OSM is read only to prepare Cases; the Harness never reads it (ADR-0006).
"""

from __future__ import annotations

import time

import httpx
from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import unary_union

from clayzer import answer_keys as ak

# Plant outlines are fetched this far around a Chip: a large plant's outline can lie wholly
# outside a 300 m Chip whose every pixel is panels (the same reason as SOLAR_SEARCH_DEG).
PLANT_SEARCH_DEG = ak.SOLAR_SEARCH_DEG

CANDIDATES = {
    "substation": lambda t: t.get("power") == "substation",
    "storage_tank": lambda t: t.get("man_made") == "storage_tank",
    "well_pad": lambda t: t.get("man_made") == "petroleum_well",
    "construction_site": lambda t: t.get("landuse") == "construction",
}


# Chips per Overpass query. The public server gives each IP address a couple of query slots,
# and behind a shared proxy the wait for one dwarfs the query, so many Chips share a query.
BATCH = 20


def query(bboxes) -> str:
    """One query for every Chip in `bboxes`; elements are sorted out to Chips by geometry."""
    d, parts = PLANT_SEARCH_DEG, []
    for w, s, e, n in bboxes:
        wide = f"({s - d},{w - d},{n + d},{e + d})"
        chip = f"({s},{w},{n},{e})"
        parts += [
            f'nwr["power"="plant"]["plant:source"~"solar|wind"]{wide};',
            f'nwr["power"="generator"]["generator:source"~"solar|wind"]{chip};',
            f'nwr["power"="substation"]{chip};',
            f'nwr["man_made"~"^(storage_tank|petroleum_well)$"]{chip};',
            f'nwr["landuse"="construction"]{chip};',
        ]
    return "[out:json][timeout:300];(" + "".join(parts) + ");out tags geom;"


def fetch(bboxes) -> list[dict]:
    # The public Overpass server sheds load with 429 and 50x; back off and retry.
    for attempt in range(5):
        r = httpx.post(ak.OVERPASS, data={"data": query(bboxes)}, timeout=360,
                       headers={"User-Agent": ak.USER_AGENT})  # fmt: skip
        if r.status_code not in (429, 502, 503, 504) or attempt == 4:
            break
        time.sleep(5 * 2**attempt)
    r.raise_for_status()
    return r.json()["elements"]


def _coords(geometry: list[dict]) -> list[tuple[float, float]]:
    return [(p["lon"], p["lat"]) for p in geometry]


def geometry(el: dict):
    """An element's shape in lon/lat: a point, a line, or an area; None if it has no geometry."""
    if el["type"] == "node":
        return Point(el["lon"], el["lat"])
    if el["type"] == "way" and el.get("geometry"):
        c = _coords(el["geometry"])
        return Polygon(c) if len(c) >= 4 and c[0] == c[-1] else LineString(c)
    if el["type"] == "relation":
        parts = [geometry({"type": "way", "geometry": m["geometry"]})
                 for m in el.get("members", []) if m.get("geometry") and m.get("role") != "inner"]  # fmt: skip
        parts = [p for p in parts if p is not None]
        return unary_union(parts) if parts else None
    return None


def _source(tags: dict) -> str | None:
    return tags.get("plant:source") or tags.get("generator:source")


def osm_in_chip(bbox, elements: list[dict]) -> dict:
    """What OSM maps inside the Chip: solar present, wind turbines counted, candidate classes."""
    chip = box(*bbox)
    solar, turbines, plants, extra = False, 0, [], {}
    for el in elements:
        tags, geom = el.get("tags", {}), geometry(el)
        if geom is None or not geom.intersects(chip):
            continue
        kind = _source(tags)
        if tags.get("power") in ("plant", "generator") and kind and "solar" in kind:
            solar = True
            if tags.get("power") == "plant":
                plants.append(tags.get("name") or f"{el['type']}/{el['id']}")
        elif tags.get("power") == "generator" and kind and "wind" in kind:
            turbines += 1
        else:
            for cls, match in CANDIDATES.items():
                if match(tags):
                    extra[cls] = extra.get(cls, 0) + 1
    return {"solar": solar, "turbines": turbines, "solar_plants": plants, "candidates": extra}


def compare(case: dict, osm: dict) -> dict:
    """USGS's labels against OSM's power mapping, for one Case."""
    labels = {lb["object"]: lb for lb in case["reference_labels"]}
    usgs_solar = "solar_array" in labels
    usgs_turbines = (labels.get("wind_turbine") or {}).get("count") or 0
    findings = []
    if usgs_solar and not osm["solar"]:
        findings.append("solar: USGS only")
    elif osm["solar"] and not usgs_solar:
        findings.append("solar: OSM only")
    if usgs_turbines != osm["turbines"]:
        findings.append(f"wind: USGS {usgs_turbines}, OSM {osm['turbines']}")
    return {
        "case": case["id"],
        "usgs_solar": usgs_solar,
        "osm_solar": osm["solar"],
        "usgs_turbines": usgs_turbines,
        "osm_turbines": osm["turbines"],
        "solar_plants": osm["solar_plants"],
        "candidates": osm["candidates"],
        "findings": findings,
    }


def corroborate(
    cases: list[dict],
    fetch=fetch,
    pause: float = 1.0,
    progress=print,
    done: dict | None = None,
    save=lambda rows: None,
    batch: int = BATCH,
) -> list[dict]:
    """One row per fixed Case, BATCH Chips per query. `done` holds rows from an earlier run, by
    Case id, so a rerun resumes; `save` is called after every query. Cases whose query fails
    get error rows and the run goes on: the public Overpass server sheds load for minutes."""
    done = dict(done or {})
    fixed = [c for c in cases if c.get("kind", "fixed") == "fixed"]
    todo = [c for c in fixed if c["id"] not in done or "error" in done[c["id"]]]
    for start in range(0, len(todo), batch):
        group = todo[start : start + batch]
        bboxes = [c["chips"][0]["bbox"] for c in group]
        try:
            elements = fetch(bboxes)
            for case, bbox in zip(group, bboxes, strict=True):
                done[case["id"]] = compare(case, osm_in_chip(bbox, elements))
        except httpx.HTTPError as e:
            for case in group:
                done[case["id"]] = {"case": case["id"], "error": str(e)[:200]}
        save([done[c["id"]] for c in fixed if c["id"] in done])
        for case in group:
            row = done[case["id"]]
            note = (
                "failed, run again to retry"
                if "error" in row
                else "; ".join(row["findings"]) or "agree"
            )
            progress(f"  {case['id']}: {note}")
        time.sleep(pause)
    return [done[c["id"]] for c in fixed if c["id"] in done]


def summary(rows: list[dict]) -> dict:
    failed = [r["case"] for r in rows if "error" in r]
    rows = [r for r in rows if "error" not in r]
    solar = [r for r in rows if r["usgs_solar"] or r["osm_solar"]]
    wind = [r for r in rows if r["usgs_turbines"] or r["osm_turbines"]]

    def count(rs, key):
        return sum(any(f.startswith(key) for f in r["findings"]) for r in rs)

    candidates: dict[str, int] = {}
    for r in rows:
        for cls in r["candidates"]:
            candidates[cls] = candidates.get(cls, 0) + 1
    return {
        "cases": len(rows),
        "solar_cases": len(solar),
        "solar_agree": len(solar) - count(solar, "solar"),
        "wind_cases": len(wind),
        "wind_agree": len(wind) - count(wind, "wind"),
        "to_check": [r["case"] for r in rows if r["findings"]],
        "candidate_cases": candidates,
        "failed": failed,
    }
