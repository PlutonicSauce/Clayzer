"""The object ontology (ontology/objects.toml): every class a Claim can name (ADR-0008).

Small and read-only: the classes, their is-a hierarchy, and the crosswalks to Answer Keys,
retrieval queries, and benchmarks. Grounding can use `distance` for partial credit when a Claim
names a parent or sibling of the Reference Label's class.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

DEFAULT = Path(__file__).resolve().parents[2] / "ontology" / "objects.toml"


@dataclass(frozen=True)
class ObjectClass:
    id: str
    name: str
    parent: str
    claimable: bool
    definition: str = ""
    keyed_by: tuple[str, ...] = ()
    osm: tuple[dict, ...] = ()
    osm_reference: tuple[dict, ...] = ()
    synonyms: tuple[str, ...] = ()
    confusers: tuple[str, ...] = ()
    min_visible_m: float | None = None
    attributes: dict = field(default_factory=dict)
    queries: tuple[str, ...] = ()
    rsicd_scenes: tuple[str, ...] = ()
    land_cover: dict = field(default_factory=dict)
    caption_exemplars: tuple[str, ...] = ()


@dataclass(frozen=True)
class Ontology:
    version: str
    classes: dict[str, ObjectClass]

    def claimable(self) -> list[str]:
        return [c.id for c in self.classes.values() if c.claimable]

    def keyed(self) -> set[str]:
        """Claimable classes some Answer Key can verify; Claims about the rest are unscored."""
        return {c.id for c in self.classes.values() if c.claimable and c.keyed_by}

    def ancestors(self, class_id: str) -> list[str]:
        out, cur = [], self.classes[class_id].parent
        while cur:
            out.append(cur)
            cur = self.classes[cur].parent
        return out

    def is_a(self, class_id: str, other: str) -> bool:
        return class_id == other or other in self.ancestors(class_id)

    def distance(self, a: str, b: str) -> int | None:
        """Steps between two classes through their nearest common ancestor; None if unrelated."""
        chain_a, chain_b = [a, *self.ancestors(a)], [b, *self.ancestors(b)]
        for i, node in enumerate(chain_a):
            if node in chain_b:
                return i + chain_b.index(node)
        return None

    def queries(self) -> dict[str, str]:
        return {q: c.id for c in self.classes.values() for q in c.queries}

    def name_of(self, class_id: str) -> str:
        c = self.classes.get(class_id)
        return c.name if c else class_id

    def confuser_pairs(self, class_ids: list[str] | None = None) -> list[tuple[str, str]]:
        """Distinct look-alike pairs among the given claimable classes (both ends claimable),
        for a prompt caution. Defaults to all claimable classes."""
        focus = set(class_ids) if class_ids is not None else set(self.claimable())
        claimable = set(self.claimable())
        seen, pairs = set(), []
        for cid in self.claimable():
            if cid not in focus:
                continue
            for other in self.classes[cid].confusers:
                if other in claimable and (key := frozenset((cid, other))) not in seen:
                    seen.add(key)
                    pairs.append((cid, other))
        return pairs


# ── prompt context (Layers A and C, ADR-0010) ─────────────────────────────────────────────
#
# Token-bounded by construction: the confuser note is at most one line per claimable class, and
# exemplars are capped by `max_total`. The whole block is a fixed, cacheable prefix when `focus`
# is None, so Bedrock prompt caching can absorb it (caption-design.md §16). Pass a small `focus`
# (e.g. the Layer B nearest classes) to keep it tight and on-point when a Chip is ambiguous.


def prompt_context(
    ont: Ontology,
    focus: list[str] | None = None,
    *,
    include_confusers: bool = True,
    confusers: list[tuple[str, str]] | None = None,
    per_class: int = 1,
    max_total: int = 4,
) -> str:
    """Class-level guidance for the captioner: look-alikes (Layer A) and example phrasings
    (Layer C). General knowledge only — never a Case's Answer Key (ADR-0006). Returns "" when
    there is nothing to add.

    `confusers`, when given, overrides the hand-curated look-alikes from the ontology file with
    pairs measured from embeddings (prototypes.learned_confuser_pairs) — that is what makes
    Layer A data-driven (ADR-0010). Falls back to the ontology file when None."""
    order = focus if focus else ont.claimable()
    lines: list[str] = []
    if include_confusers:
        pairs = confusers if confusers is not None else ont.confuser_pairs(focus)
        if pairs:
            joined = "; ".join(f"{ont.name_of(a)} vs {ont.name_of(b)}" for a, b in pairs)
            lines.append(f"Easily-confused look-alikes to tell apart: {joined}.")
    examples: list[str] = []
    for cid in order:
        cls = ont.classes.get(cid)
        if cls:
            examples.extend(cls.caption_exemplars[:per_class])
        if len(examples) >= max_total:
            break
    examples = examples[:max_total]
    if examples:
        lines.append("Example phrasings (house style only — NOT claims about this image):")
        lines += [f'- "{e}"' for e in examples]
    if not lines:
        return ""
    header = ("Guidance from the object ontology (general knowledge about these classes, not a "
              "description of this image):")  # fmt: skip
    return header + "\n" + "\n".join(lines)


def _tuple(raw: dict, key: str) -> tuple:
    return tuple(raw.get(key, ()))


@cache
def load(path: str | Path = DEFAULT) -> Ontology:
    raw = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    classes = {}
    for entry in raw["class"]:
        cls = ObjectClass(
            id=entry["id"],
            name=entry["name"],
            parent=entry.get("parent", ""),
            claimable=bool(entry.get("claimable", False)),
            definition=entry.get("definition", ""),
            keyed_by=_tuple(entry, "keyed_by"),
            osm=_tuple(entry, "osm"),
            osm_reference=_tuple(entry, "osm_reference"),
            synonyms=_tuple(entry, "synonyms"),
            confusers=_tuple(entry, "confusers"),
            min_visible_m=entry.get("min_visible_m"),
            attributes=dict(entry.get("attributes", {})),
            queries=_tuple(entry, "queries"),
            rsicd_scenes=_tuple(entry, "rsicd_scenes"),
            land_cover=dict(entry.get("land_cover", {})),
            caption_exemplars=_tuple(entry, "caption_exemplars"),
        )
        if cls.id in classes:
            raise ValueError(f"duplicate class {cls.id!r}")
        classes[cls.id] = cls
    for cls in classes.values():
        if cls.parent and cls.parent not in classes:
            raise ValueError(f"{cls.id}: unknown parent {cls.parent!r}")
    return Ontology(version=str(raw.get("version", "")), classes=classes)
