"""LGND Geo's responses, read the way the server writes them, and the calls that several modules
make: an image lookup at a point (cached in the store), a classifier built once per account,
and a classifier applied to many images in one call.

LGND writes tables as {"columns": [...], "rows": [[...], ...]}: `places` in an imagery check,
`results` in a classifier's labels. `table` reads them, and lists of objects too.
"""

from __future__ import annotations

import hashlib
import json

INDEX = "naip"
APPLY_LIMIT = 200  # toolbox_classifier_apply lists at most 200 targets
BUILD_TIMEOUT = 300.0  # seconds: eleven labels of five text examples took over a minute


def parse(text: str) -> dict | None:
    try:
        value = json.loads(text)
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def table(value) -> list[dict]:
    """Rows of an LGND table as dicts; a list of dicts passes through."""
    if isinstance(value, dict) and "columns" in value:
        return [dict(zip(value["columns"], row)) for row in value.get("rows") or []]
    if isinstance(value, list):
        return [v for v in value if isinstance(v, dict)]
    return []


def answers(result: dict) -> dict[str, dict]:
    """An imagery check's judged places by node: {"answer": "yes"|"no"|"maybe", "reason"}."""
    return {p["node"]: p for p in table(result.get("places")) if p.get("node")}


def classifier_name(prefix: str, examples: dict[str, list[str]]) -> str:
    """A name that changes when the examples do (LGND names are at most 32 characters)."""
    body = json.dumps(examples, sort_keys=True).encode()
    return f"{prefix}-{hashlib.sha256(body).hexdigest()[:8]}"


def ensure_classifier(call, name: str, examples: dict[str, list[str]], index: str = INDEX):
    """Build the classifier in this account unless it's there. Returns None, or the error.

    `call(name, arguments)` returns a ToolResult. Classifiers are saved per LGND account, so
    each teammate's first Batch or calibration builds it from the committed examples. A build
    that timed out may still finish on LGND's side, so a failed one is followed by a list."""

    def have() -> bool:
        r = call("toolbox_classifier_list", {})
        listed = parse(r.text) if not r.is_error else None
        return bool(listed) and any(c.get("name") == name for c in table(listed.get("data")))

    if have():
        return None
    r = call("toolbox_classifier_build", {
        "scope": {"index": index}, "name": name,
        "examples": {label: [{"text": t} for t in texts] for label, texts in examples.items()},
    }, timeout=BUILD_TIMEOUT)  # fmt: skip
    built = parse(r.text) if not r.is_error else None
    if built and built.get("name") == name:
        return None
    return None if have() else r.text[:300]


def apply(call, classifier: str, nodes: list[str]) -> tuple[dict[str, dict], str | None]:
    """Label images with a classifier: {node: {"label", "margin", "fit"}}, and an error or None.
    Calls once per 200 images."""
    labels: dict[str, dict] = {}
    unique = list(dict.fromkeys(nodes))
    for i in range(0, len(unique), APPLY_LIMIT):
        part = unique[i : i + APPLY_LIMIT]
        r = call("toolbox_classifier_apply",
                 {"classifier": classifier, "nodes": part, "limit": APPLY_LIMIT})  # fmt: skip
        result = parse(r.text) if not r.is_error else None
        if not result or "results" not in result:
            return labels, r.text[:300]
        for row in table(result["results"]):
            labels[row["node"]] = {k: row.get(k) for k in ("label", "margin", "fit")}
    return labels, None


class Lookups:
    """The newest NAIP image at a point, cached in the store under lgnd/lookups.json.

    A lookup is one of LGND's daily calls and its answer doesn't change, so calibration and
    `clayzer spread` share them across runs and teammates."""

    KEY = "lgnd/lookups.json"

    def __init__(self, call, store=None):
        self.call, self.store, self.calls = call, store, 0
        self.cache: dict[str, dict] = {}
        if store is not None and store.exists(self.KEY):
            self.cache = json.loads(store.get(self.KEY))

    def __call__(self, lat: float, lon: float) -> dict | None:
        """{"node", "observed", ...} for the image at (lat, lon), or None if LGND has none."""
        key = f"{INDEX}:{lat:.6f},{lon:.6f}"
        if key not in self.cache:
            self.calls += 1
            r = self.call("search_chip_lat_lon", {"index": INDEX, "lat": lat, "lon": lon})
            found = parse(r.text) if not r.is_error else None
            if r.is_error:
                return None  # an outage isn't an answer: don't cache it
            self.cache[key] = found if found and found.get("node") else {}
        return self.cache[key] or None

    def save(self) -> None:
        if self.store is not None:
            body = (json.dumps(self.cache, indent=1, sort_keys=True) + "\n").encode()
            self.store.put(self.KEY, body, "application/json")
