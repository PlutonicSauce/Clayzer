"""Setting spread: how varied the surroundings of a region's Cases are, and which are missing.

LGND found their wind seeds accurate but narrow (nearly all turbines on dry rangeland), and that
narrowness capped what fine-tuning could learn; their solar misses were mostly rooftop, car-park
and woodland arrays the seeds never showed. A Case set has the same risk: if every solar Case
sits in open desert, a captioner change that breaks woodland or rooftop arrays scores as no
change. So for each Case, one cell of its Chip that doesn't hold the Case's subject is labelled
with a settings classifier (LGND, built from the text examples below), and each group of Cases
(solar, wind, negatives) gets:
- counts per setting, and the settings with none (gaps)
- evenness: the Shannon entropy of the counts over its maximum, 0 (all one setting) to 1 (even)

With `suggest`, each gap gets an LGND search in the region for that subject in that setting,
and the nearest USGS site to each match becomes a `clayzer case` command. Matches within 1 km of
an existing Case are dropped, as Case building requires. Every new Case is still checked by eye.

Costs one lookup per Case (cached: lgnd.Lookups), one classifier apply, and with `suggest` one
search per gap.
"""

from __future__ import annotations

import math
import re

from clayzer import lgnd
from clayzer.verify import cell_centre

# Settings a NAIP Chip in the US Southwest (and the Texas test region) sits in. 5 examples each,
# so LGND trains a linear SVM per label.
SETTINGS = {
    "desert_scrub": ["desert scrub", "sparse desert shrubs", "creosote desert", "dry desert basin",
                     "joshua tree desert"],
    "farmland": ["farm fields", "cropland", "irrigated fields", "orchard", "center pivot fields"],
    "grassland": ["grassland", "rangeland", "pasture", "dry grassy hills", "prairie"],
    "woodland": ["woodland", "forest", "oak woodland", "pine trees", "trees on hills"],
    "town": ["residential neighborhood", "suburb", "houses with yards", "town streets",
             "downtown"],
    "industrial": ["industrial area", "warehouses", "factory", "large parking lots", "rail yard"],
    "mountains": ["rocky mountains", "steep rocky slopes", "mountain ridge", "rocky hills",
                  "canyon"],
}  # fmt: skip
GROUPS = {"uspvdb": "solar_array", "uswtdb": "wind_turbine", "neg": "negative"}
SUBJECT_TEXT = {"solar_array": "solar farm", "wind_turbine": "wind turbines"}
ORDER = ("north_west", "north_east", "south_west", "south_east",
         "north", "west", "east", "south", "centre")  # fmt: skip
MIN_DISTANCE_KM = 1.0


def classifier() -> str:
    return lgnd.classifier_name("clayzer-settings", SETTINGS)


def group(case: dict) -> str | None:
    m = re.match(r"^fixed-[^-]+-(uspvdb|uswtdb|neg)-", case["id"])
    return GROUPS[m.group(1)] if m else None


def context_cell(case: dict, subject: str, cached=lambda lat, lon: False) -> str:
    """A cell of the Chip without the Case's subject: corners first, an already looked-up one
    before others. Falls back to the first corner when the subject fills the Chip."""
    held = {cell for lb in case["reference_labels"] if lb["object"] == subject
            for cell in lb.get("cells") or [lb["position"]]}  # fmt: skip
    free = [c for c in ORDER if c not in held] or [ORDER[0]]
    bbox = case["chips"][0]["bbox"]
    return next((c for c in free if cached(*cell_centre(bbox, c))), free[0])


def evenness(counts: dict[str, int]) -> float | None:
    n = sum(counts.values())
    if n == 0:
        return None
    h = -sum(c / n * math.log(c / n) for c in counts.values() if c)
    return h / math.log(len(counts))


def measure(cases: list[dict], call, store=None) -> dict:
    """{"groups": {group: {"n", "counts", "evenness", "gaps"}}, "cases": [...], "calls"}."""
    calls = {"n": 0}

    def counted(name, args, **kw):
        calls["n"] += 1
        return call(name, args, **kw)

    lookups = lgnd.Lookups(counted, store)

    def cached(lat, lon):
        return f"{lgnd.INDEX}:{lat:.6f},{lon:.6f}" in lookups.cache

    rows = []
    for case in cases:
        g = group(case)
        if g is None:
            continue
        cell = context_cell(case, g, cached)
        lat, lon = cell_centre(case["chips"][0]["bbox"], cell)
        found = lookups(lat, lon)
        rows.append({"case_id": case["id"], "group": g, "cell": cell,
                     "node": (found or {}).get("node")})  # fmt: skip
    lookups.save()

    error = lgnd.ensure_classifier(counted, classifier(), SETTINGS)
    labels, apply_error = (
        ({}, error)
        if error
        else lgnd.apply(counted, classifier(), [r["node"] for r in rows if r["node"]])
    )
    for r in rows:
        label = labels.get(r["node"]) if r["node"] else None
        r["setting"] = label["label"] if label else None
        r["fit"] = label.get("fit") if label else None

    groups = {}
    for g in dict.fromkeys(r["group"] for r in rows):
        mine = [r for r in rows if r["group"] == g]
        counts = {s: sum(r["setting"] == s for r in mine) for s in SETTINGS}
        groups[g] = {"n": len(mine), "unlabelled": sum(r["setting"] is None for r in mine),
                     "counts": counts, "evenness": evenness(counts),
                     "gaps": [s for s, n in counts.items() if n == 0]}  # fmt: skip
    return {"groups": groups, "cases": rows, "calls": calls["n"], "error": apply_error,
            "classifier": classifier()}  # fmt: skip


def estimate(cases: list[dict], lookups: lgnd.Lookups, suggest_too: bool = False) -> int:
    """LGND calls `measure` will make at most (and `suggest`, one search per possible gap)."""

    def cached(lat, lon):
        return f"{lgnd.INDEX}:{lat:.6f},{lon:.6f}" in lookups.cache

    todo = 0
    for case in cases:
        g = group(case)
        if g is not None:
            cell = context_cell(case, g, cached)
            todo += not cached(*cell_centre(case["chips"][0]["bbox"], cell))
    groups = {group(c) for c in cases} - {None}
    return todo + 3 + (len(groups) * len(SETTINGS) if suggest_too else 0)


def _km(lat1, lon1, lat2, lon2) -> float:
    dy = (lat2 - lat1) * 111.0
    dx = (lon2 - lon1) * 111.0 * math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot(dx, dy)


def _matches(result: dict) -> list[dict]:
    """The first table in a search result whose rows have a position."""
    for value in result.values():
        rows = lgnd.table(value)
        if rows and "lat" in rows[0] and "lon" in rows[0]:
            return rows
    return []


def region_box(cases: list[dict], pad: float = 0.05) -> dict:
    boxes = [c["chips"][0]["bbox"] for c in cases]
    return {"west": min(b[0] for b in boxes) - pad, "south": min(b[1] for b in boxes) - pad,
            "east": max(b[2] for b in boxes) + pad, "north": max(b[3] for b in boxes) + pad}  # fmt: skip


def suggest(cases: list[dict], measured: dict, call, near=None, per_gap: int = 3) -> list[dict]:
    """For each group's gaps, LGND matches in the region and a command to build a Case there.

    `near(lat, lon)` returns the nearest USGS site's "uspvdb <id>" / "uswtdb <id>" or None;
    by default it asks the USGS APIs."""
    near = near or _nearest_usgs
    area = region_box(cases)
    centres = [cell_centre(c["chips"][0]["bbox"], "centre") for c in cases]
    # A match can be over 1 km from every Chip and still be nearest a site that's a Case.
    have = {f"{m.group(1)} {m.group(2)}" for c in cases
            if (m := re.match(r"^[a-z]+-[^-]+-(uspvdb|uswtdb)-(\d+)$", c["id"]))}  # fmt: skip
    out = []
    for g, info in measured["groups"].items():
        for setting in info["gaps"]:
            phrase = SETTINGS[setting][0]
            text = [SUBJECT_TEXT[g], phrase] if g in SUBJECT_TEXT else [phrase]
            r = call("search_place_find",
                     {"scope": {"index": lgnd.INDEX, "area": area}, "text": text, "limit": 10})  # fmt: skip
            result = lgnd.parse(r.text) if not r.is_error else None
            found = []
            for m in _matches(result) if result else []:
                lat, lon = m["lat"], m["lon"]
                if any(_km(lat, lon, a, b) < MIN_DISTANCE_KM for a, b in centres):
                    continue
                if g == "negative":
                    command = f"clayzer case neg {lon:.5f} {lat:.5f} --n <next>"
                else:
                    site = near(lat, lon, g)
                    if site is None or site in have:
                        continue
                    command = f"clayzer case {site}"
                if any(f["command"] == command for f in found):
                    continue  # two matches near one USGS site
                found.append({"lat": lat, "lon": lon, "similarity": m.get("similarity"),
                              "command": command})  # fmt: skip
                if len(found) == per_gap:
                    break
            out.append({"group": g, "setting": setting, "query": text, "matches": found,
                        "error": None if result else r.text[:200]})  # fmt: skip
    return out


def _nearest_usgs(lat: float, lon: float, subject: str, within_deg: float = 0.01) -> str | None:
    from clayzer import answer_keys as ak

    solar, turbines = ak.usgs_near((lon, lat, lon, lat), within_deg)
    rows, key = (solar, "uspvdb") if subject == "solar_array" else (turbines, "uswtdb")
    if not rows:
        return None
    best = min(rows, key=lambda x: _km(lat, lon, x["ylat"], x["xlong"]))
    return f"{key} {best['case_id']}"


def to_markdown(measured: dict, suggestions: list[dict] | None = None) -> str:
    names = list(SETTINGS)
    lines = [
        "# Setting spread", "",
        f"Classifier `{measured['classifier']}`, {measured['calls']} LGND calls"
        + (f"; **unavailable**: {measured['error']}" if measured["error"] else "") + ".", "",
        "| Group | Cases | " + " | ".join(names) + " | Evenness | Gaps |",
        "|---|---|" + "---|" * len(names) + "---|---|",
    ]  # fmt: skip
    for g, info in measured["groups"].items():
        ev = "—" if info["evenness"] is None else f"{info['evenness']:.2f}"
        un = f" ({info['unlabelled']} unlabelled)" if info["unlabelled"] else ""
        lines.append(f"| {g} | {info['n']}{un} | "
                     + " | ".join(str(info["counts"][s]) for s in names)
                     + f" | {ev} | {', '.join(info['gaps']) or 'none'} |")  # fmt: skip
    if suggestions:
        lines += ["", "## To fill the gaps", "",
                  ("LGND matches in the region, 1 km or more from every Case. Check each by "
                   "eye before keeping it."), ""]  # fmt: skip
        for s in suggestions:
            lines.append(f"- **{s['group']} in {s['setting']}** (`{' + '.join(s['query'])}`)"
                         + (f": search failed, {s['error']}" if s["error"] else ""))  # fmt: skip
            lines += [
                f"  - `{m['command']}`  ({m['lat']:.4f}, {m['lon']:.4f})" for m in s["matches"]
            ] or ["  - no usable match"]
    return "\n".join(lines) + "\n"
