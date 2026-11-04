"""Chip embeddings, two complementary jobs in one module.

1. **LGND's published Clay v1.5 embeddings, joined Chip by Chip (CAP-18).** LGND's monthly-
   aggregated set on Source Cooperative: one 256-dimension Clay v1.5 vector per Major TOM cell
   (1,280 m, Sentinel-2 at 10 m) per month, from 2017, read anonymously (no sign-in, no quota, no
   AWS charge). GeoParquet, hive-partitioned by two-character geohash, year, and month; each
   (geohash, month) is queried once with a bounding-box filter. A Chip (~307 m) joins the cell
   whose box holds its centre in the month of its NAIP date, else the nearest month within
   MAX_MONTHS_AWAY; a Chip before 2017 has no embedding. Caption reuse across near-duplicates and
   Claims straight from embeddings (caption-design.md §8, ideas 13–14) start here.

   **Attribution (CC BY 4.0):** LGND embeddings (Clay v1.5), https://source.coop/clay/lgnd-embeddings.
   Every row this module writes carries it, and anything built on them must too.

2. **An `EmbeddingSource` for Layer B of the data-driven ontology (ADR-0010).** Per-Chip vectors
   computed ONCE at Case-preparation time and stored on the Case (`chip["embedding"]`) — never per
   caption, so a caption still costs only a dot product. Behind one interface so the rest of the
   code doesn't care which source produced them:
   - `PrecomputedEmbedding`: reuse vectors someone already published (e.g. the Clay run or the
     LGND join above), keyed by Chip id or a location key, from JSONL or Parquet. No model call.
   - `TitanImageEmbedding`: a fallback that embeds the Chip image on Bedrock (Titan multimodal),
     one call per Chip at prep time only.
   Both produce a plain list[float]; prototypes.py normalises.
"""

from __future__ import annotations

import base64
import json
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC
from pathlib import Path
from typing import Protocol

# ── 1. LGND published embeddings (geohash/partition join) ───────────────────────────────────

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


# ── 2. EmbeddingSource for Layer B (ADR-0010) ───────────────────────────────────────────────


class EmbeddingSource(Protocol):
    def embed_chip(self, chip: dict, png: bytes | None) -> list[float] | None:
        """A vector for one Chip, or None when this source can't supply one (then Layer B is
        simply skipped for that Chip)."""
        ...


class PrecomputedEmbedding:
    """Reuse: look a Chip's published embedding up from a mapping. The mapping is keyed by Chip
    id; a `key` callable can derive a different key (e.g. a geohash+date location key) from the
    Chip when ids don't line up with the export."""

    def __init__(self, mapping: dict[str, list[float]], key=None):
        self.mapping = mapping
        self.key = key or (lambda chip: chip["id"])

    def embed_chip(self, chip: dict, png: bytes | None) -> list[float] | None:
        return self.mapping.get(self.key(chip))


class TitanImageEmbedding:
    """Fallback: embed the Chip image with Bedrock Titan multimodal embeddings. One call per Chip,
    at prep time only (never per caption)."""

    def __init__(self, client, model: str = "amazon.titan-embed-image-v1"):
        self.client, self.model = client, model

    def embed_chip(self, chip: dict, png: bytes | None) -> list[float] | None:
        if not png:
            return None
        body = json.dumps({"inputImage": base64.b64encode(png).decode()})
        resp = self.client.invoke_model(modelId=self.model, body=body)
        return json.loads(resp["body"].read())["embedding"]


def load_precomputed(path: str | Path, key=None) -> PrecomputedEmbedding:
    """Build a PrecomputedEmbedding from a JSONL (`{"chip_id"|"id": ..., "embedding": [...]}` per
    line) or a GeoParquet with `chip_id`/`id` and `embedding` columns."""
    path = Path(path)
    mapping: dict[str, list[float]] = {}
    if path.suffix in (".jsonl", ".ndjson", ".json"):
        for line in path.read_text().splitlines():
            if line.strip():
                rec = json.loads(line)
                cid = rec.get("chip_id") or rec["id"]
                mapping[cid] = [float(x) for x in rec["embedding"]]
    elif path.suffix in (".parquet", ".pq"):
        import pyarrow.parquet as pq  # optional dep; only for the Parquet reuse path

        for rec in pq.read_table(path).to_pylist():
            cid = rec.get("chip_id") or rec.get("id")
            mapping[cid] = [float(x) for x in rec["embedding"]]
    else:
        raise ValueError(f"unsupported embeddings file: {path.suffix} (use .jsonl or .parquet)")
    return PrecomputedEmbedding(mapping, key=key)


def attach_to_cases(cases: list[dict], source: EmbeddingSource, store=None) -> int:
    """Set `chip["embedding"]` on every Chip a source can embed. Returns how many were set.

    `store` is needed only by sources that read the image (Titan); the reuse path ignores it."""
    n = 0
    for case in cases:
        for chip in case["chips"]:
            png = None
            if store is not None and chip.get("uri", "").startswith("chips/"):
                try:
                    png = store.get(chip["uri"])
                except Exception:  # noqa: BLE001 -- a missing image just means no embedding
                    png = None
            vec = source.embed_chip(chip, png)
            if vec:
                chip["embedding"] = list(map(float, vec))
                n += 1
    return n


def pairs_from_cases(cases: list[dict]) -> list[tuple[str, list[float]]]:
    """(class_id, embedding) pairs for building prototypes from embedded Cases: each Case
    contributes its Chip's embedding to every object class its Reference Labels name. Multi-class
    Chips contribute to several centroids; curate with a hand JSONL if that's too coarse. Classes
    outside LAYER_B_CLASSES are dropped later by prototypes.build.
    """
    pairs: list[tuple[str, list[float]]] = []
    for case in cases:
        for chip in case["chips"]:
            emb = chip.get("embedding")
            if not emb:
                continue
            classes = {lb["object"] for lb in case.get("reference_labels", [])}
            for cid in classes:
                pairs.append((cid, [float(x) for x in emb]))
    return pairs
