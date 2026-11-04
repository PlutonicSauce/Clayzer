"""The object ontology (ontology/objects.toml): every class a Claim can name (ADR-0008).

Small and read-only: the classes, their is-a hierarchy, and the crosswalks to Answer Keys,
retrieval queries, and benchmarks. The code's vocabularies come from here, not from lists of
their own (decided 2026-11-04): the Harness's allowed objects (`claimable`), grounding's scored
classes (`keyed`), the OSM mapping (`osm_object`), and the retrieval queries (`queries`), so
adding a class is a one-file change. Grounding uses `distance` for partial credit when a Claim
names a parent or child of the Reference Label's class.
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

    def osm_rules(self) -> list[tuple[str, dict]]:
        """(class id, tag rule) for every OSM rule the code maps, the most specific class
        first (a greenhouse before a building), then in file order."""
        rules = [(c.id, dict(r)) for c in self.classes.values() for r in c.osm]
        return sorted(rules, key=lambda cr: -len(self.ancestors(cr[0])))

    def osm_object(self, tags: dict) -> str | None:
        """The class an OSM way maps to, or None. Power features are left to USGS, and a way
        tagged intermittent=yes is never water (OSM maps dry desert washes as streams)."""
        if "power" in tags:
            return None
        dry = tags.get("intermittent") == "yes"
        for class_id, rule in self.osm_rules():
            if dry and self.is_a(class_id, "hydrography"):
                continue
            if all(k in tags and v in ("*", tags[k]) for k, v in rule.items()):
                return class_id
        return None


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
        )
        if cls.id in classes:
            raise ValueError(f"duplicate class {cls.id!r}")
        classes[cls.id] = cls
    for cls in classes.values():
        if cls.parent and cls.parent not in classes:
            raise ValueError(f"{cls.id}: unknown parent {cls.parent!r}")
    return Ontology(version=str(raw.get("version", "")), classes=classes)
