"""Which verifier checks each object class (ontology/verifiers.toml), and how one is chosen.

verify.py asks `method(class_id)`; calibrate.py measures each method on development Cases and
`choose` picks one per class. The file is the record of what worked, kept in git so the team
shares it and a Batch can say which version it ran with.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

from clayzer import lgnd

DEFAULT = Path(__file__).resolve().parents[2] / "ontology" / "verifiers.toml"
METHODS = ("imagery_check", "classifier", "none")  # tie order: today's verifier first
MIN_PROBES = 3  # fewer true or false probes than this and a class keeps its route
MIN_GAIN = 0.1  # a verifier must beat keeping everything (balanced 0.5) by this much


@dataclass(frozen=True)
class Routes:
    version: str
    default: str
    index: str
    examples: dict[str, list[str]]
    routes: dict[str, dict] = field(default_factory=dict)

    def method(self, class_id: str) -> str:
        return self.routes.get(class_id, {}).get("method", self.default)

    @property
    def classifier(self) -> str:
        return lgnd.classifier_name("clayzer-objects", self.examples)

    def uses_classifier(self) -> bool:
        return any(r.get("method") == "classifier" for r in self.routes.values())


@cache
def load(path: str | Path = DEFAULT) -> Routes:
    raw = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    routes = {
        r["class"]: {k: v for k, v in r.items() if k != "class"} for r in raw.get("route", [])
    }
    bad = {c: r["method"] for c, r in routes.items() if r.get("method") not in METHODS}
    if raw.get("default", "imagery_check") not in METHODS or bad:
        raise ValueError(f"unknown verifier method in {path}: {bad or raw.get('default')}")
    clf = raw.get("classifier", {})
    return Routes(
        version=str(raw.get("version", "")),
        default=raw.get("default", "imagery_check"),
        index=clf.get("index", lgnd.INDEX),
        examples={k: list(v) for k, v in clf.get("examples", {}).items()},
        routes=routes,
    )


def rates(tp: int, fn: int, tn: int, fp: int) -> dict:
    """kept: true Claims kept; removed: false Claims removed; balanced: their mean."""
    kept = tp / (tp + fn) if tp + fn else None
    removed = tn / (tn + fp) if tn + fp else None
    both = [x for x in (kept, removed) if x is not None]
    return {"tp": tp, "fn": fn, "tn": tn, "fp": fp, "kept": kept, "removed": removed,
            "balanced": sum(both) / len(both) if len(both) == 2 else None}  # fmt: skip


def choose(scores: dict[str, dict], current: str) -> tuple[str, str]:
    """The method for one class from each method's `rates`, and why.

    Keeping every Claim ("none") scores balanced 0.5: it keeps all true Claims and removes no
    false ones. A verifier earns the route only by beating that by MIN_GAIN."""
    some = next(iter(scores.values()))
    positives, negatives = some["tp"] + some["fn"], some["tn"] + some["fp"]
    if positives < MIN_PROBES or negatives < MIN_PROBES:
        return current, f"kept: {positives} true and {negatives} false probes, need {MIN_PROBES}"
    measured = {m: s["balanced"] for m, s in scores.items() if s["balanced"] is not None}
    best = max(measured, key=lambda m: (measured[m], -METHODS.index(m)), default=None)
    if best is None or measured[best] < 0.5 + MIN_GAIN:
        top = f"best {best} {measured[best]:.2f}" if best else "nothing measured"
        return "none", f"no verifier beats keeping every Claim by {MIN_GAIN} ({top})"
    s = scores[best]
    return best, f"keeps {s['kept']:.0%} of true Claims, removes {s['removed']:.0%} of false"


def _value(v) -> str:
    if isinstance(v, str):
        return '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float):
        return f"{v:.3f}"
    if isinstance(v, dict):
        return "{ " + ", ".join(f"{k} = {_value(x)}" for k, x in v.items() if x is not None) + " }"
    if isinstance(v, list):
        return "[" + ", ".join(_value(x) for x in v) + "]"
    return str(v)


def render(routes: Routes, path: str | Path = DEFAULT) -> str:
    """The file with new routes: everything above the first [[route]] is kept as written."""
    text = Path(path).read_text(encoding="utf-8")
    head = text.split("\n[[route]]", 1)[0].rstrip() + "\n"
    out = [head]
    for cls, r in routes.routes.items():
        out.append("\n[[route]]\n" + f"class = {_value(cls)}\n")
        out.extend(f"{k} = {_value(v)}\n" for k, v in r.items())
    return "".join(out)
