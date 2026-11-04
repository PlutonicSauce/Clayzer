"""Layer B of the data-driven Object Ontology (ADR-0010): class prototypes in embedding space.

The idea: embed each claimable class as the centroid of a few confirmed example Chips' Clay/LGND
embeddings, built once from a held-out **development** region. At caption time, the Chip's own
(already-published) embedding is matched against those centroids, and the nearest classes become
a short hint in the prompt ("this tile's embedding is closest to solar_array (0.82) and
greenhouse (0.74) — tell them apart"). It disambiguates look-alikes without a second vision call.

Two guards are first-class here, because they are what make the idea safe and cheap:

- CIRCULARITY (ADR-0006). Prototypes are built from a *disjoint* region than the one scored, and
  from Clay/LGND embeddings, which are NOT one of the Answer Keys we grade against (USGS, OSM).
  `guard_scoring_region` refuses to use prototypes to caption the region they were built on.
- COST / LATENCY (nonprofit constraint). Layer B adds NO model call: it reuses an embedding the
  caller already has (from Clay/LGND), so each caption costs one in-memory dot product and a few
  prompt tokens. `LAYER_B_CLASSES` restricts it to classes that survive Sentinel-2's 10 m (small,
  thin objects like turbines and roads are excluded), and a hint is emitted only when the match
  is confident, so we don't spend tokens — or invite anchoring — on noise.

The index has two backends: a tiny committed JSON file (`LocalPrototypes`) so demos replay
offline (REQ-09), and Amazon S3 Vectors (`S3VectorsBackend`) for the cloud path. Both store the
same small set of per-class unit centroids.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import cache
from pathlib import Path

from clayzer.ontology import Ontology

# Classes Layer B builds prototypes for — set by the resolution of the embeddings you feed it.
# Clay embeddings of NAIP chips are 0.6 m, so every claimable class is resolvable, including thin
# objects (wind_turbine, road, railroad) and individual buildings. If you ever build from 10 m
# Sentinel-2 embeddings instead, narrow this back to the large classes (solar_array, water, field,
# parking_lot, bare_ground, greenhouse) — a 10 m centroid can't separate the thin ones (ADR-0010).
LAYER_B_CLASSES = (
    "solar_array", "wind_turbine", "road", "railroad", "building", "water", "field",
    "parking_lot", "greenhouse", "vegetation", "bare_ground",
)  # fmt: skip

TOP_K = 3  # classes a query returns; a prompt hint names at most this many
SIM_FLOOR = 0.15  # below this best cosine, the Chip isn't near any prototype: emit no hint
AMBIGUOUS_MARGIN = 0.06  # when the top two are this close, the prompt says to tell them apart


def _unit(v: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v))
    return [x / n for x in v] if n else list(v)


def _cos(a: list[float], b: list[float]) -> float:
    # Centroids are stored as unit vectors; the query need not be, so normalise by both norms.
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(x * x for x in b)) or 1.0
    return dot / (na * nb)


class CircularityError(Exception):
    """Prototypes built on a region may not be used to caption that same region (ADR-0006)."""


@dataclass(frozen=True)
class Prototypes:
    ontology_version: str
    dim: int
    build_region: str
    source: str  # where the exemplar embeddings came from, e.g. "lgnd-embeddings"
    embedding_model: str
    centroids: dict[str, list[float]]  # class_id -> unit vector
    counts: dict[str, int]  # class_id -> number of exemplars averaged
    learned_confusers: dict[str, list[str]] = field(default_factory=dict)
    created: str = ""

    def nearest(self, embedding: list[float], k: int = TOP_K) -> list[tuple[str, float]]:
        """The k class centroids most similar to `embedding`, most similar first."""
        if not embedding or len(embedding) != self.dim:
            return []
        scored = [(cid, _cos(embedding, c)) for cid, c in self.centroids.items()]
        scored.sort(key=lambda t: t[1], reverse=True)
        return scored[:k]

    def to_json(self) -> bytes:
        payload = {
            "ontology_version": self.ontology_version,
            "dim": self.dim,
            "build_region": self.build_region,
            "source": self.source,
            "embedding_model": self.embedding_model,
            "centroids": self.centroids,
            "counts": self.counts,
            "learned_confusers": self.learned_confusers,
            "created": self.created,
        }
        return (json.dumps(payload, indent=2) + "\n").encode()

    @classmethod
    def from_json(cls, body: bytes) -> Prototypes:
        d = json.loads(body)
        return cls(
            ontology_version=d["ontology_version"],
            dim=d["dim"],
            build_region=d["build_region"],
            source=d["source"],
            embedding_model=d["embedding_model"],
            centroids={k: list(map(float, v)) for k, v in d["centroids"].items()},
            counts=dict(d["counts"]),
            learned_confusers=dict(d.get("learned_confusers", {})),
            created=d.get("created", ""),
        )


def build(
    pairs: list[tuple[str, list[float]]],
    *,
    ontology_version: str,
    build_region: str,
    source: str,
    embedding_model: str,
    classes: tuple[str, ...] = LAYER_B_CLASSES,
) -> Prototypes:
    """Average exemplar embeddings per class into unit centroids.

    `pairs` is (class_id, embedding) for confirmed exemplars from the development region. Classes
    outside `classes` (the 10 m-discriminable set) are dropped. Each exemplar should already have
    been verified (e.g. through LGND's imagery check) before it gets here. `learned_confusers`
    records, per class, the other classes whose centroids sit closest — a measured replacement
    for the hand-guessed `confusers` list in objects.toml.
    """
    allowed = set(classes)
    groups: dict[str, list[list[float]]] = {}
    dim = None
    for cid, emb in pairs:
        if cid not in allowed or not emb:
            continue
        if dim is None:
            dim = len(emb)
        if len(emb) != dim:
            raise ValueError(f"embedding dim mismatch: {len(emb)} != {dim}")
        groups.setdefault(cid, []).append(emb)
    if dim is None:
        raise ValueError("no usable (class, embedding) pairs for the Layer B classes")

    centroids, counts = {}, {}
    for cid, embs in groups.items():
        mean = [sum(col) / len(embs) for col in zip(*embs, strict=False)]
        centroids[cid] = _unit(mean)
        counts[cid] = len(embs)

    learned: dict[str, list[str]] = {}
    for cid, c in centroids.items():
        others = sorted(
            ((o, _cos(c, oc)) for o, oc in centroids.items() if o != cid),
            key=lambda t: t[1],
            reverse=True,
        )
        learned[cid] = [o for o, _ in others[:2]]

    return Prototypes(
        ontology_version=ontology_version,
        dim=dim,
        build_region=build_region,
        source=source,
        embedding_model=embedding_model,
        centroids=centroids,
        counts=counts,
        learned_confusers=learned,
        created=datetime.now(UTC).isoformat(timespec="seconds"),
    )


def guard_scoring_region(prototypes: Prototypes, scoring_region: str) -> None:
    """Raise if prototypes built on `build_region` would be used to caption that same region.

    This is the mechanical half of the circularity rule (ADR-0006, ADR-0010): the captioner may
    read class-level knowledge, but it must not be knowledge distilled from the very Chips it is
    being scored against."""
    if scoring_region and prototypes.build_region == scoring_region:
        raise CircularityError(
            f"prototypes were built on region {prototypes.build_region!r}; captioning the same "
            "region with them is circular (ADR-0006). Build on a disjoint development region."
        )


def hint(prototypes: Prototypes, embedding: list[float], ont: Ontology, k: int = TOP_K) -> str:
    """A one-line Layer B prompt hint, or "" when the match is too weak to be worth tokens.

    No model call: a dot product over a handful of centroids. Names the nearest classes with
    their similarity, and, when the top two are close, asks the model to tell them apart (the
    look-alike case this feature exists for)."""
    ranked = [(cid, s) for cid, s in prototypes.nearest(embedding, k) if s >= SIM_FLOOR]
    if not ranked:
        return ""
    named = ", ".join(f"{ont.name_of(cid)} ({s:.2f})" for cid, s in ranked)
    line = (
        "Embedding similarity (from Clay/LGND, a hint only — trust the image over this): "
        f"this tile is closest to {named}."
    )
    if len(ranked) >= 2 and (ranked[0][1] - ranked[1][1]) <= AMBIGUOUS_MARGIN:
        a, b = ont.name_of(ranked[0][0]), ont.name_of(ranked[1][0])
        line += f" {a} and {b} look alike here; decide carefully which the image actually shows."
    return line


def learned_confuser_pairs(
    prototypes: Prototypes, class_ids: list[str] | None = None
) -> list[tuple[str, str]]:
    """Distinct look-alike pairs MEASURED from embeddings (each class with the nearest other
    class centroids), for a data-driven Layer A. Defaults to every class in the prototype file.
    Restrict with `class_ids` (e.g. the Layer B focus)."""
    focus = set(class_ids) if class_ids is not None else set(prototypes.learned_confusers)
    seen, pairs = set(), []
    for cid, others in prototypes.learned_confusers.items():
        if cid not in focus:
            continue
        for other in others:
            if cid != other and (key := frozenset((cid, other))) not in seen:
                seen.add(key)
                pairs.append((cid, other))
    return pairs


def caption_context(
    ont: Ontology,
    prototypes: Prototypes | None,
    embedding: list[float] | None,
    *,
    scoring_region: str | None = None,
) -> str:
    """The full ontology guidance block for one Chip:
    - Layer A look-alikes: MEASURED from embeddings when a prototype file is present (data-driven,
      ADR-0010), otherwise the hand-curated ontology pairs.
    - Layer C caption exemplars (ontology file), narrowed to the focus classes when there is one.
    - Layer B nearest-class hint, only when prototypes AND a Chip embedding are both present.

    When there are no prototypes at all, only the hand-curated A + C are returned. When prototypes
    exist, the circularity guard applies (they must not be used to caption their build region),
    whether or not this Chip has an embedding (the learned look-alikes are built from that region
    too)."""
    from clayzer.ontology import prompt_context

    focus = None
    layer_b = ""
    confusers = None
    if prototypes is not None:
        if scoring_region:
            guard_scoring_region(prototypes, scoring_region)
        if embedding:
            ranked = [cid for cid, s in prototypes.nearest(embedding) if s >= SIM_FLOOR]
            focus = ranked or None
            layer_b = hint(prototypes, embedding, ont)
        pairs = learned_confuser_pairs(prototypes, focus)
        confusers = pairs or None  # fall back to hand-curated if the focus has no measured pair
    block = prompt_context(ont, focus=focus, confusers=confusers)
    return f"{block}\n{layer_b}".strip() if layer_b else block


# ── backends ──────────────────────────────────────────────────────────────────────────────


def default_path(ontology_version: str, root: Path | None = None) -> Path:
    root = root or Path(__file__).resolve().parents[2] / "ontology" / "prototypes"
    return root / f"v{ontology_version}.json"


class LocalPrototypes:
    """The committed JSON file. Tiny (a few unit vectors), so demos replay with no network."""

    def __init__(self, path: Path):
        self.path = path

    def exists(self) -> bool:
        return self.path.exists()

    def load(self) -> Prototypes:
        return Prototypes.from_json(self.path.read_bytes())

    def save(self, prototypes: Prototypes) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_bytes(prototypes.to_json())


@cache
def load_local(path: str) -> Prototypes:
    """Load a committed prototype file, cached by path so a Batch reads it once, not once per
    Chip (there is no model call either way; this just avoids re-parsing the JSON per Run)."""
    return LocalPrototypes(Path(path)).load()


class S3VectorsBackend:
    """Amazon S3 Vectors: the cloud path. Stores each class centroid as one vector keyed by the
    class id, with the build provenance as metadata; a query returns the nearest class centroids.

    Written defensively: the s3vectors client isn't in every boto3 version, and the service needs
    a vector bucket and index created first (by the CDK app, AWS-03). Raises a clear error rather
    than failing obscurely when it's unavailable."""

    def __init__(self, vector_bucket: str, index: str, region: str | None = None):
        import boto3
        from botocore.exceptions import UnknownServiceError

        self.bucket, self.index = vector_bucket, index
        try:
            self.client = boto3.client("s3vectors", region_name=region)
        except UnknownServiceError as e:  # boto3 too old for S3 Vectors
            raise RuntimeError(
                "this boto3 has no 's3vectors' client; upgrade boto3 or use LocalPrototypes"
            ) from e

    def save(self, prototypes: Prototypes) -> None:
        vectors = [
            {
                "key": cid,
                "data": {"float32": centroid},
                "metadata": {
                    "class_id": cid,
                    "ontology_version": prototypes.ontology_version,
                    "build_region": prototypes.build_region,
                    "count": prototypes.counts.get(cid, 0),
                },
            }
            for cid, centroid in prototypes.centroids.items()
        ]
        self.client.put_vectors(vectorBucketName=self.bucket, indexName=self.index, vectors=vectors)

    def nearest(self, embedding: list[float], k: int = TOP_K) -> list[tuple[str, float]]:
        resp = self.client.query_vectors(
            vectorBucketName=self.bucket,
            indexName=self.index,
            queryVector={"float32": embedding},
            topK=k,
            returnDistance=True,
        )
        # S3 Vectors returns a distance; cosine similarity ≈ 1 - distance for cosine indexes.
        return [(v["key"], 1.0 - float(v.get("distance", 0.0))) for v in resp.get("vectors", [])]
