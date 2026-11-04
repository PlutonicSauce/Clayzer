"""The caption importer (CAP-20): a Caption Set from any source becomes Cases.

Clay's business driver is that its caption data is untested, so the Sandbox scores captions it
didn't write. A Caption Set is one row per caption in the format assumed in caption-design.md
§3.6 (JSON Lines, or GeoParquet with the `import` extra). Each row becomes a Case:

- Answer Keys attach by the row's footprint and date, exactly as for our own Chips. A USGS site
  only counts if it existed by the acquisition year (USPVDB and USWTDB `p_year`). OSM has no
  history here, so OSM labels are today's map; the Case records that.
- A row with no footprint (RSICD and similar sets have no locations) still becomes a Case, with
  no Reference Labels and `located: false`: it can be judged for fidelity and retrieval but not
  grounded.
- Claims about objects too small for the row's imagery are flagged: an Object Class whose
  `min_visible_m` (the smallest it can be identified in NAIP) is below the row's `gsd_m` may not
  be visible at all, a wind turbine in 10 m Sentinel-2 for example. A flag is a warning, not a
  verdict. With `gsd_m` unknown (null, as for RSICD) the check can't be made: `too_small` is null.

The caption itself is kept on the Case (`imported`), never shown to anything that builds labels
(ADR-0006). Captions of one chip share one footprint, so its labels are built once.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

REQUIRED = ("caption_id", "chip_id", "caption", "kind", "geometry", "datetime", "sensor", "gsd_m")
GRID_SIZE = 512  # the virtual pixel grid a footprint is divided into for the 3×3 cells


@dataclass
class ImportResult:
    cases: list[dict] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)  # {"caption_id", "reason"}


def read_rows(path: Path) -> list[dict]:
    """Rows of a Caption Set: JSON Lines, or GeoParquet (geometry as WKB) with pyarrow."""
    if path.suffix in (".parquet", ".geoparquet"):
        try:
            import pyarrow.parquet as pq
        except ImportError as e:
            raise RuntimeError("GeoParquet needs the import extra: uv sync --extra import") from e
        from shapely import wkb
        from shapely.geometry import mapping

        rows = pq.read_table(path).to_pylist()
        for r in rows:
            if isinstance(r.get("geometry"), bytes | bytearray):
                r["geometry"] = mapping(wkb.loads(bytes(r["geometry"])))
            if isinstance(r.get("claims"), str):
                r["claims"] = json.loads(r["claims"])
        return rows
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def problems(row: dict) -> list[str]:
    """What makes a row unusable, as reasons; empty when it can be imported."""
    out = [f"missing {k}" for k in REQUIRED if k not in row]
    if out:
        return out
    if row["kind"] != "fixed":
        out.append(
            f"kind {row['kind']!r}: only fixed captions are imported; a change row would need a Chip Pair"
        )
    if not str(row["caption"]).strip():
        out.append("empty caption")
    gsd = row["gsd_m"]
    if gsd is not None and (not isinstance(gsd, int | float) or gsd <= 0):
        out.append("gsd_m must be a positive number, or null when unknown")
    g = row["geometry"]
    if g is not None and (
        not isinstance(g, dict) or g.get("type") not in ("Polygon", "MultiPolygon")
    ):
        out.append("geometry must be a GeoJSON Polygon, or null for an unlocated caption")
    elif g is not None and not row["datetime"]:
        out.append("a located caption needs its datetime: Answer Keys attach by date")
    return out


def footprint_chip(row: dict):
    """A Chip for the row's footprint, so Answer Keys place labels in its 3×3 cells as they do
    for our own Chips: a north-up grid of GRID_SIZE pixels in the footprint's UTM zone."""
    from rasterio.warp import transform
    from shapely.geometry import shape

    from clayzer.chips import Chip

    w, s, e, n = shape(row["geometry"]).bounds
    lon, lat = (w + e) / 2, (s + n) / 2
    crs = f"EPSG:{(32600 if lat >= 0 else 32700) + int((lon + 180) // 6) + 1}"
    xs, ys = transform("EPSG:4326", crs, [w, e, w, e], [s, s, n, n])
    left, top = min(xs), max(ys)
    side = max(max(xs) - left, top - min(ys))  # square grid over the footprint's longer side
    return Chip(
        id=str(row["chip_id"]), date=str(row["datetime"])[:10], bbox=(w, s, e, n), crs=crs,
        left=left, top=top, source=str(row["sensor"]), naip_item=str(row.get("stac_item") or ""),
        size=GRID_SIZE, res=side / GRID_SIZE,
    )  # fmt: skip


def reference_labels(chip) -> tuple[list[dict], dict]:
    """Reference Labels for a footprint at its date, and what they were built from."""
    from clayzer import answer_keys as ak

    year = int(chip.date[:4])
    solar, turbines = ak.usgs_near(chip.bbox, ak.SOLAR_SEARCH_DEG, turbine_buffer_deg=0.0)
    built_solar, built_turbines = ak.existed_by(solar, year), ak.existed_by(turbines, year)
    labels = ak.usgs_labels(chip, built_solar, built_turbines)
    labels += ak.osm_labels(chip, ak.overpass(chip.bbox))
    sources = {
        "uspvdb": ak.uspvdb_outlines()[0] if built_solar else None,
        "usgs_after_date": len(solar) + len(turbines) - len(built_solar) - len(built_turbines),
        "osm": "today's map: OSM history isn't used",
    }
    return labels, sources


def too_small(claims: dict | None, gsd_m: float | None) -> list[dict] | None:
    """Claimed objects whose class may be too small to see at `gsd_m` (ontology min_visible_m).
    None when `gsd_m` is unknown: the check can't be made, which isn't the same as passing it."""
    from clayzer.ontology import load

    if gsd_m is None:
        return None
    if not claims:
        return []
    classes = load().classes
    out = []
    for o in claims.get("objects", []):
        c = classes.get(o.get("object"))
        if c and c.min_visible_m is not None and c.min_visible_m < gsd_m:
            out.append({"id": o.get("id"), "object": o["object"],
                        "min_visible_m": c.min_visible_m, "gsd_m": gsd_m})  # fmt: skip
    return out


def import_rows(rows: list[dict], name: str, progress=print) -> ImportResult:
    """Cases from a Caption Set's rows. Labels are built once per located chip."""
    result, by_chip = ImportResult(), {}
    for i, row in enumerate(rows, 1):
        reasons = problems(row)
        if reasons:
            result.skipped.append(
                {"caption_id": row.get("caption_id"), "reason": "; ".join(reasons)}
            )
            continue
        started = time.monotonic()
        located = row["geometry"] is not None
        date = str(row["datetime"])[:10] if row["datetime"] else None
        chip_record = {"id": str(row["chip_id"]), "uri": row.get("image_uri"),
                       "date": date, "bbox": None, "source": row["sensor"],
                       "gsd_m": row["gsd_m"]}  # fmt: skip
        labels, sources = [], {"located": False}
        if located:
            key = (str(row["chip_id"]), chip_record["date"])
            if key not in by_chip:
                chip = footprint_chip(row)
                by_chip[key] = (chip, *reference_labels(chip))
            chip, labels, sources = by_chip[key]
            chip_record["bbox"] = list(chip.bbox)
        claims = row.get("claims")
        case = {
            "id": f"import-{name}-{row['caption_id']}",
            "task": "caption",
            "kind": "fixed",
            "region": f"import-{name}",
            "located": located,
            "chips": [chip_record],
            "reference_labels": labels,
            "answer_keys": sources,
            "imported": {
                "caption_id": str(row["caption_id"]), "caption": row["caption"],
                "claims": claims, "generator": row.get("generator"),
                "stac_item": row.get("stac_item"), "scene": row.get("scene"),
                "too_small": too_small(claims, row["gsd_m"]),
            },
            "prep_seconds": round(time.monotonic() - started, 1),
        }  # fmt: skip
        result.cases.append(case)
        progress(f"  [{i}/{len(rows)}] {case['id']}: {len(labels)} labels"
                 + ("" if located else " (no location: grounding not possible)"))  # fmt: skip
    return result


def import_key(name: str) -> str:
    return f"cases/import-{name}.jsonl"


def caption_rows(batch: dict) -> list[dict]:
    """A Batch's Captions as a Caption Set, so the importer can be checked on captions whose
    Cases we already have: same footprint and date, so the labels should come out the same."""
    cases = {c["id"]: c for c in batch["cases"]}
    rows = []
    for cap in batch["captions"]:
        chip = cases[cap["case_id"]]["chips"][0]
        w, s, e, n = chip["bbox"]
        rows.append({
            "caption_id": f"{cap['case_id']}--r{cap['repeat']}",
            "chip_id": chip["id"],
            "caption": cap["text"],
            "kind": "fixed",
            "geometry": {"type": "Polygon",
                         "coordinates": [[[w, s], [e, s], [e, n], [w, n], [w, s]]]},
            "datetime": chip["date"],
            "sensor": "naip",
            "gsd_m": 0.6,
            "generator": batch["config"].caption_model,
            "claims": {"objects": cap["objects"], "relations": cap.get("relations", []),
                       "uncertain": cap.get("uncertain", [])},
        })  # fmt: skip
    return rows
