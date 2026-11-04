"""The Case builder: one Chip plus its Reference Labels (caption-plan.md §3, §5.1).

Positives start from an Answer Key record and cut the Chip around it, in a NAIP image taken
after the site was built, with the Chip's centre offset so the site can land in any grid cell.
Negatives must show no USGS record inside the Chip plus a buffer.
Hand corrections from label-corrections.toml are applied to every Case built, so a fix for an
OSM gap survives a rebuild.
`prep_seconds` records label preparation time (CAP-13).

A Chip's `uri` is its store key (`chips/<id>.png`), so a Case file works against any
teammate's store.
"""

import json
import time
import tomllib

from clayzer import answer_keys as ak
from clayzer.chips import Chip, cut_chip, find_naip, offset_for
from clayzer.config import REPO
from clayzer.grid import GRID

# About 300 m at these latitudes: negatives need USGS-free surroundings, not just a clear Chip.
NEGATIVE_BUFFER_DEG = 0.003
CORRECTIONS = REPO / "fixtures" / "caption" / "cases" / "label-corrections.toml"


def load_corrections(path=CORRECTIONS) -> list[dict]:
    return tomllib.loads(path.read_text())["correction"] if path.exists() else []


def apply_corrections(case_id: str, labels: list[dict], corrections: list[dict]) -> list[dict]:
    """The labels with this Case's hand corrections applied: drops removed, adds merged in."""
    out = [dict(lb) for lb in labels]
    for c in (c for c in corrections if c["case"] == case_id):
        if c["action"] == "drop":
            out = [lb for lb in out if lb["object"] != c["object"]]
            continue
        if c["action"] != "add" or not c.get("cells") or set(c["cells"]) - set(GRID):
            raise ValueError(f"bad label correction for {case_id}: {c}")
        lb = next((lb for lb in out if lb["object"] == c["object"]), None)
        if lb is None:
            out.append({"object": c["object"], "count": c.get("count"), "position": c["cells"][0],
                        "cells": [g for g in GRID if g in c["cells"]], "attributes": {},
                        "source": "manual", "source_ids": []})  # fmt: skip
        else:  # applying twice changes nothing
            lb["cells"] = [g for g in GRID if g in set(lb["cells"]) | set(c["cells"])]
            lb["count"] = c.get("count")
            if not lb["source"].endswith("manual"):
                lb["source"] += "+manual"
    return out


def _labels(chip: Chip) -> list[dict]:
    # Wider than the Chip: a large array centred outside it can still cover part of it.
    solar, turbines = ak.usgs_near(chip.bbox, ak.SOLAR_SEARCH_DEG, turbine_buffer_deg=0.0)
    return ak.usgs_labels(chip, solar, turbines) + ak.osm_labels(chip, ak.overpass(chip.bbox))


def _solar_nearby(chip: Chip) -> list[str]:
    """USPVDB sites whose array polygon reaches within NEGATIVE_BUFFER_DEG of the Chip."""
    from shapely.geometry import box

    w, s, e, n = chip.bbox
    around = box(w, s, e, n).buffer(NEGATIVE_BUFFER_DEG)
    solar, _ = ak.usgs_near(chip.bbox, ak.SOLAR_SEARCH_DEG, turbine_buffer_deg=0.0)
    outlines = ak.uspvdb_outlines()[1] if solar else {}
    return [f"uspvdb {x['case_id']}" for x in solar
            if x["case_id"] in outlines and outlines[x["case_id"]].intersects(around)]  # fmt: skip


def _chip_record(chip: Chip) -> dict:
    return {"id": chip.id, "uri": f"chips/{chip.png}", "date": chip.date,
            "bbox": list(chip.bbox), "source": chip.source}  # fmt: skip


def _case(case_id: str, region: str, chip: Chip, labels: list[dict], started: float) -> dict:
    return {
        "id": case_id,
        "task": "caption",
        "kind": "fixed",
        "region": region,
        "chips": [
            {
                "id": chip.id,
                "uri": f"chips/{chip.png}",
                "date": chip.date,
                "bbox": list(chip.bbox),
                "source": chip.source,
            }
        ],
        "reference_labels": apply_corrections(case_id, labels, load_corrections()),
        # Which release of each Answer Key the labels came from, where it's versioned.
        "answer_keys": {"uspvdb": ak.uspvdb_outlines()[0]}
        if any(lb["source"] == "uspvdb" for lb in labels)
        else {},
        "prep_seconds": round(time.monotonic() - started, 1),
    }


def build_positive(
    answer_key: str, source_id: int, region: str, store, naip_source: str = "pc"
) -> dict:
    started = time.monotonic()
    if answer_key == "uspvdb":
        rec = ak.uspvdb_site(source_id)
        if "ground" not in (rec.get("p_sys_type") or "ground"):
            raise ValueError(f"USPVDB {source_id} isn't ground-mounted ({rec['p_sys_type']})")
        state = rec["p_state"]
    elif answer_key == "uswtdb":
        rec = ak.uswtdb_turbine(source_id)
        state = rec["t_state"]
    else:
        raise ValueError(f"unknown Answer Key {answer_key!r}")
    lon, lat = rec["xlong"], rec["ylat"]
    prefix = f"{state.lower()}-{answer_key}-{source_id}"
    # Offset so the site lands anywhere in the 3×3 grid, not always in the centre cell.
    offset = offset_for(f"{answer_key}-{source_id}")
    item = find_naip(lon, lat, after_year=rec.get("p_year"), offset_m=offset)
    chip = cut_chip(item, lon, lat, prefix, store, naip_source, offset)
    try:
        labels = _labels(chip)
    except Exception:
        _discard(store, chip)
        raise
    return _case(f"fixed-{region}-{answer_key}-{source_id}", region, chip, labels, started)


def change_labels(before: Chip, after: Chip) -> list[dict]:
    """Reference Labels for a Chip Pair. USGS records carry the year they were built, so each
    USGS label says whether its object appeared, disappeared, or was there on both dates; the
    count and position are those of the date it's present on (the later, unless it
    disappeared). A USGS record with no year is dated by GRW's construction quarter where it
    has one (grw.py), and otherwise counted on both dates. OSM is today's map with no history,
    so OSM labels are the later Chip's with `change: unknown`, which grounding doesn't score for
    change."""
    from clayzer import grw

    solar, turbines = ak.usgs_near(after.bbox, ak.SOLAR_SEARCH_DEG, turbine_buffer_deg=0.0)
    built = {"uspvdb": grw.built_on("uspvdb", solar), "uswtdb": grw.built_on("uswtdb", turbines)}

    def existed(records: list[dict], key: str, chip: Chip) -> list[dict]:
        dates = built[key]
        undated = [r for r in records if str(r["case_id"]) not in dates]
        return ak.existed_by(undated, int(chip.date[:4])) + [
            r for r in records if dates.get(str(r["case_id"]), "9999") <= chip.date
        ]

    def at(chip: Chip) -> dict[str, dict]:
        labels = ak.usgs_labels(
            chip, existed(solar, "uspvdb", chip), existed(turbines, "uswtdb", chip)
        )
        return {lb["object"]: lb for lb in labels}

    then, now = at(before), at(after)
    labels = []
    for obj in sorted(then.keys() | now.keys()):
        if obj in now:
            labels.append({**now[obj], "change": "unchanged" if obj in then else "appeared"})
        else:
            labels.append({**then[obj], "change": "disappeared"})
    osm = ak.osm_labels(after, ak.overpass(after.bbox))
    return labels + [{**lb, "change": "unknown"} for lb in osm]


def build_change(
    answer_key: str, source_id: int, region: str, store, naip_source: str = "pc",
    dated_by: str | None = None,
) -> dict:  # fmt: skip
    """A Change Case: the same place before and after a USGS site was built, a Chip Pair cut
    around the same point with the same offset, so both Chips share one footprint. The site is
    dated by USGS's install year, or by GRW's construction quarter when USGS has none
    (grw.dating). When the two disagree it refuses, until `dated_by` says which a person chose
    after a look; the Case records which dated it, and the flag."""
    from clayzer import grw

    started = time.monotonic()
    rec = ak.uspvdb_site(source_id) if answer_key == "uspvdb" else ak.uswtdb_turbine(source_id)
    dated = grw.dating(answer_key, rec, dated_by)
    state = rec.get("p_state") or rec.get("t_state")
    lon, lat = rec["xlong"], rec["ylat"]
    offset = offset_for(f"{answer_key}-{source_id}")
    prefix = f"{state.lower()}-{answer_key}-{source_id}"
    early = find_naip(lon, lat, before_date=dated["before"], offset_m=offset)
    late = find_naip(lon, lat, after_date=dated["after"], offset_m=offset)
    before = cut_chip(early, lon, lat, prefix, store, naip_source, offset)
    after = cut_chip(late, lon, lat, prefix, store, naip_source, offset)
    labels = change_labels(before, after)
    case = _case(f"change-{region}-{answer_key}-{source_id}", region, after, labels, started)
    case["kind"] = "change"
    case["chips"] = [_chip_record(before), _chip_record(after)]  # earlier first
    case["answer_keys"]["osm"] = "today's map: no history, so OSM labels have change unknown"
    case["answer_keys"]["grw"] = grw.VERSION
    case["dating"] = dated
    case["prep_seconds"] = round(time.monotonic() - started, 1)
    return case


def build_negative(
    lon: float, lat: float, n: int, state: str, region: str, store, naip_source: str = "pc"
) -> dict:
    started = time.monotonic()
    item = find_naip(lon, lat)
    chip = cut_chip(item, lon, lat, f"{state.lower()}-neg-{n}", store, naip_source)
    try:
        solar, turbines = ak.usgs_near(chip.bbox, NEGATIVE_BUFFER_DEG)
        found = [f"uspvdb {s['case_id']}" for s in solar]
        found += [f"uswtdb {t['case_id']}" for t in turbines]
        # A large array's centroid can be far away while its panels reach the Chip.
        found += [f for f in _solar_nearby(chip) if f not in found]
        if found:
            raise ValueError(f"not a negative: USGS records nearby ({', '.join(found[:5])})")
        labels = ak.osm_labels(chip, ak.overpass(chip.bbox))
    except Exception:
        _discard(store, chip)
        raise
    return _case(f"fixed-{region}-neg-{n}", region, chip, labels, started)


def _discard(store, chip: Chip) -> None:
    """Delete a Chip whose Case can't be built (refused, or an API failed), so none is orphaned."""
    for suffix in (".png", ".json"):
        store.delete(f"chips/{chip.id}{suffix}")


def cases_key(region: str) -> str:
    return f"cases/caption-{region}.jsonl"


def parse_jsonl(body: bytes) -> list[dict]:
    return [json.loads(line) for line in body.decode().splitlines() if line.strip()]


def to_jsonl(rows: list[dict]) -> bytes:
    return "".join(json.dumps(r) + "\n" for r in rows).encode()


def load_cases(store, key: str) -> list[dict]:
    return parse_jsonl(store.get(key)) if store.exists(key) else []


def save_case(store, key: str, case: dict) -> None:
    """Add a Case, replacing any earlier Case with the same id."""
    cases = [c for c in load_cases(store, key) if c["id"] != case["id"]] + [case]
    store.put(key, to_jsonl(cases), "application/x-ndjson")
