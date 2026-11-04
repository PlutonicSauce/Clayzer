"""Per-Chip embeddings for Layer B of the data-driven ontology (ADR-0010).

Layer B matches a Chip's embedding against class prototypes. Those embeddings are computed ONCE,
at Case-preparation time, and stored on the Case (`chip["embedding"]`) — never per caption — so a
caption still costs only a dot product (the cost guard in prototypes.py and ADR-0010).

Two sources, behind one `EmbeddingSource` interface so the rest of the code doesn't care which:

- `PrecomputedEmbedding`: the **Clay/LGND reuse** path (the project's chosen path). Reads vectors
  someone already published, keyed by Chip id or by a location key, from a JSONL or Parquet file.
  No model call, so it rides on Clay's own asset. This is preferred when the data is available.
- `TitanImageEmbedding`: a **fallback that runs today** on Bedrock (Amazon Titan multimodal image
  embeddings). One embedding call per Chip, at prep time only. Use it when the Clay/LGND export
  isn't to hand; it costs more than reuse but keeps per-caption cost unchanged.

Both produce a plain list[float]; prototypes.py normalises.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Protocol


class EmbeddingSource(Protocol):
    def embed_chip(self, chip: dict, png: bytes | None) -> list[float] | None:
        """A vector for one Chip, or None when this source can't supply one (then Layer B is
        simply skipped for that Chip)."""
        ...


class PrecomputedEmbedding:
    """Clay/LGND reuse: look a Chip's published embedding up from a mapping. The mapping is keyed
    by Chip id; a `key` callable can derive a different key (e.g. a geohash+date location key)
    from the Chip when ids don't line up with the export."""

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

        table = pq.read_table(path)
        rows = table.to_pylist()
        for rec in rows:
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
