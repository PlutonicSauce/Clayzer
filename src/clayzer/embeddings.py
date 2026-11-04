"""LGND's Clay v1.5 embeddings for the Chips we score (CAP-18), joined Chip by Chip to the cell
each Chip lies in.

Caption reuse across near-duplicate Chips and Claims straight from embeddings (caption-design.md
§8, ideas 13 and 14) both start here. The embeddings are LGND's monthly-aggregated set on Source
Cooperative: one 256-dimension Clay v1.5 vector per Major TOM cell (1,280 m, Sentinel-2 at 10 m)
per month, from 2017. They're read anonymously: no LGND sign-in, no LGND Geo quota, no AWS
charge to the reader.

**Attribution (CC BY 4.0):** LGND embeddings (Clay v1.5), https://source.coop/clay/lgnd-embeddings.
Every row this module writes carries it, and anything built on them must too.

The data is GeoParquet, hive-partitioned by two-character geohash, year, and month, Hilbert
ordered, in ~240 MB row groups (geohash 9q in May 2022 is one 5.8 GB file of 24). So each
(geohash, month) is queried once, with a bounding-box filter around its Chips: DuckDB reads only
the row groups that box meets, never whole files.

A Chip (about 307 m) is joined to the cell whose box holds its centre, in the month of its NAIP
date; with no row there (clouds, or a gap) it takes the nearest month within MAX_MONTHS_AWAY,
and says how far. A Chip from before 2017 has no embedding.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from datetime import UTC

ROOT = "s3://us-west-2.opendata.source.coop/clay/lgnd-embeddings/monthly-aggregated"
MODEL, COLLECTION, CELL_M, DIMS = "v1.5", "sentinel-2-l2a", 1280, 256
FIRST = (2017, 1)  # the first month with embeddings
MAX_MONTHS_AWAY = 2
LICENSE = "CC BY 4.0"
ATTRIBUTION = "LGND embeddings (Clay v1.5), https://source.coop/clay/lgnd-embeddings, CC BY 4.0"
_BASE32 = "0123456789bcdefghjkmnpqrstuvwxyz"


def geohash(lon: float, lat: float, precision: int = 2) -> str:
    """The standard geohash of a point, `precision` characters long."""
    lo, la = [-180.0, 180.0], [-90.0, 90.0]
    bits, out, even = [], "", True
    while len(out) < precision:
        rng, v = (lo, lon) if even else (la, lat)
        mid = (rng[0] + rng[1]) / 2
        bits.append(int(v >= mid))
        rng[0 if v >= mid else 1] = mid
        even = not even
        if len(bits) == 5:
            out += _BASE32[int("".join(map(str, bits)), 2)]
            bits = []
    return out


def partition(gh: str, year: int, month: int) -> str:
    return (f"{ROOT}/model_version={MODEL}/collection={COLLECTION}/chip_size={CELL_M}m/"
            f"dims={DIMS}/geohash={gh}/year={year}/month={month:02d}/*.parquet")  # fmt: skip


def chip_points(cases: list[dict]) -> list[dict]:
    """Each distinct Chip in the Cases (a Change Case has two), with its centre and date."""
    out: dict[str, dict] = {}
    for case in cases:
        for chip in case["chips"]:
            if not chip.get("bbox") or not chip.get("date"):
                continue  # an unlocated imported Chip has no cell
            w, s, e, n = chip["bbox"]
            p = out.setdefault(chip["id"], {"chip_id": chip["id"], "case_ids": [],
                                            "lon": (w + e) / 2, "lat": (s + n) / 2,
                                            "date": chip["date"]})  # fmt: skip
            p["case_ids"].append(case["id"])
    return list(out.values())


def months_away(year: int, month: int, k: int) -> tuple[int, int]:
    i = year * 12 + month - 1 + k
    return i // 12, i % 12 + 1


def _connect():
    try:
        import duckdb
    except ImportError as e:
        raise RuntimeError(
            "embeddings need the embeddings extra: uv sync --extra embeddings"
        ) from e
    con = duckdb.connect()
    con.execute("INSTALL httpfs; LOAD httpfs;")
    # Anonymous: an empty key makes DuckDB send unsigned requests to the open-data bucket.
    con.execute(
        "CREATE SECRET (TYPE s3, PROVIDER config, REGION 'us-west-2', KEY_ID '', SECRET '')"
    )
    return con


def query(con, gh: str, year: int, month: int, points: list[dict]) -> list[dict]:
    """The cells of one (geohash, month) whose box meets the box around `points`."""
    x0, x1 = min(p["lon"] for p in points), max(p["lon"] for p in points)
    y0, y1 = min(p["lat"] for p in points), max(p["lat"] for p in points)
    try:
        rows = con.execute(
            f"select cell_id, chips_id, datetime, stac_item_id, bbox, embedding "
            f"from read_parquet('{partition(gh, year, month)}') "
            "where bbox.xmax >= ? and bbox.xmin <= ? and bbox.ymax >= ? and bbox.ymin <= ?",
            [x0, x1, y0, y1],
        ).fetchall()
    except Exception as e:  # a month with no file for this geohash
        if "No files found" in str(e):
            return []
        raise
    return [{"cell_id": c, "embedding_id": i, "datetime": t.astimezone(UTC).isoformat(),
             "stac_item_id": s, "bbox": [b["xmin"], b["ymin"], b["xmax"], b["ymax"]],
             "embedding": list(v)} for c, i, t, s, b, v in rows]  # fmt: skip


def match(point: dict, rows: list[dict]) -> dict | None:
    """The cell whose box holds the point; of two (cells' boxes can touch), the nearer centre."""
    inside = [r for r in rows if r["bbox"][0] <= point["lon"] <= r["bbox"][2]
              and r["bbox"][1] <= point["lat"] <= r["bbox"][3]]  # fmt: skip

    def off(r):
        w, s, e, n = r["bbox"]
        return ((w + e) / 2 - point["lon"]) ** 2 + ((s + n) / 2 - point["lat"]) ** 2

    return min(inside, key=off) if inside else None


def for_chips(points: list[dict], query_fn: Callable | None = None, progress=print) -> list[dict]:
    """One row per Chip: its cell's embedding and how it was found, or why there's none."""
    if query_fn is None:
        con = _connect()

        def query_fn(gh, y, m, pts):
            return query(con, gh, y, m, pts)

    found: dict[str, dict] = {}
    for k in sorted(range(-MAX_MONTHS_AWAY, MAX_MONTHS_AWAY + 1), key=lambda k: (abs(k), k)):
        groups = defaultdict(list)
        for p in points:
            y, m = months_away(int(p["date"][:4]), int(p["date"][5:7]), k)
            if p["chip_id"] not in found and (y, m) >= FIRST:
                groups[(geohash(p["lon"], p["lat"]), y, m)].append(p)
        for (gh, y, m), pts in sorted(groups.items()):
            rows = query_fn(gh, y, m, pts)
            hits = 0
            for p in pts:
                if r := match(p, rows):
                    found[p["chip_id"]] = {**r, "months_away": k, "partition": f"{gh}/{y}-{m:02d}"}
                    hits += 1
            progress(f"  {gh} {y}-{m:02d}: {hits} of {len(pts)} Chips"
                     + (f" ({k:+d} months from their NAIP date)" if k else ""))  # fmt: skip
    out = []
    for p in points:
        base = {"chip_id": p["chip_id"], "case_ids": p["case_ids"], "chip_date": p["date"],
                "model": f"clay-{MODEL}", "cell_size_m": CELL_M, "dims": DIMS,
                "license": LICENSE, "attribution": ATTRIBUTION}  # fmt: skip
        if p["chip_id"] in found:
            r = found[p["chip_id"]]
            out.append({**base, "cell_id": r["cell_id"], "cell_bbox": r["bbox"],
                        "embedding_id": r["embedding_id"], "embedding_datetime": r["datetime"],
                        "months_away": r["months_away"], "stac_item_id": r["stac_item_id"],
                        "partition": r["partition"], "embedding": r["embedding"]})  # fmt: skip
        elif (int(p["date"][:4]), int(p["date"][5:7])) < months_away(*FIRST, -MAX_MONTHS_AWAY):
            out.append({**base, "missing": f"the Chip is from {p['date'][:7]}, before the "
                                           f"embeddings start ({FIRST[0]}-{FIRST[1]:02d})"})  # fmt: skip
        else:
            out.append({**base, "missing": f"no cell holds the Chip within {MAX_MONTHS_AWAY} "
                                           "months of its date"})  # fmt: skip
    return out


def embeddings_key(region: str) -> str:
    return f"embeddings/caption-{region}.jsonl"
