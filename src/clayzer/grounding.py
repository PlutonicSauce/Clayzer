"""Grounding: Claims compared with Reference Labels, deterministically (caption-plan.md §1.4).

The formula is the walkthrough's proposal (prototype/flow-walkthrough.html), with two changes
for real Answer Keys:
- Position is right if the Claim's cell is any cell the object covers (a road crosses several);
  any other cell scores 0. Neighbour credit was dropped (decided 2026-11-04): the centre cell
  neighbours all eight others, so "centre" was a safe guess worth at least 0.5.
- Relations are scored as precision only: each directional relation the Caption asserts between
  two labelled types is checked against the labels' positions. Real OSM labels imply many
  relations, so recall would punish every Caption for not listing them all.

Grounding is two numbers, reported and gated separately (decided 2026-11-04):
- correctness: of what the Caption claimed, how much is right. The mean of the parts that
  apply: precision (claimed types the Answer Key has), count, position, attributes, relations.
- coverage: how much of the Answer Key the Caption mentions (recall over the Case's labels).

One averaged number let a terse Caption win: one correct Claim scored 0.88 on a two-label
Case while detailed Captions with a few mistakes scored lower. Two numbers make that trade-off
visible instead of hiding it in a formula. Claims about types no Answer Key covers (vegetation,
bare ground) are reported as unscored, not counted.
"""

from clayzer.grid import DIRECTIONAL, cell_distance, directions

KEYED = {
    "solar_array", "wind_turbine",  # USGS
    "road", "railroad", "building", "water", "field", "parking_lot", "greenhouse",  # OSM
}  # fmt: skip


def _mean(xs):
    v = [x for x in xs if x is not None]
    return sum(v) / len(v) if v else None


def _count_score(claimed: int, ref: int) -> float:
    if claimed == ref:
        return 1.0
    return 0.5 if abs(claimed - ref) / ref <= 0.34 else 0.0


def _position_score(claimed: str, cells: list[str]) -> float:
    d = min(cell_distance(claimed, c) for c in cells)
    return 1.0 if d == 0 else 0.0


def grounding(caption: dict, labels: list[dict]) -> dict:
    refs = {lb["object"]: lb for lb in labels}
    claims = [o for o in caption["objects"] if o["object"] in KEYED]
    unkeyed = [o for o in caption["objects"] if o["object"] not in KEYED]

    rows, counts, positions, attributes = [], [], [], []
    for cl in claims:
        ref = refs.get(cl["object"])
        if ref is None:
            rows.append({"claim": cl, "verdict": "false positive"})
            continue
        row = {"claim": cl, "verdict": "matched", "ref_position": ref["position"]}
        # A Claim extracted from free text may not say where (extract.py): skip, don't guess.
        if cl.get("position") is not None:
            row["position"] = _position_score(cl["position"], ref["cells"])
            positions.append(row["position"])
        for key, value in (cl.get("attributes") or {}).items():
            if key in ref["attributes"]:
                ok = 1.0 if value == ref["attributes"][key] else 0.0
                row.setdefault("attributes", {})[key] = ok
                attributes.append(ok)
        rows.append(row)

    # A Caption may split one type over several Claims ("3 turbines north, 2 south"); the
    # count is their total against the label's.
    # Likewise a type with any Claim that doesn't say how many isn't count-scored.
    claimed_counts: dict[str, int | None] = {}
    for cl in claims:
        n, total = cl.get("count"), claimed_counts.get(cl["object"], 0)
        claimed_counts[cl["object"]] = None if n is None or total is None else total + n
    count_by_type = {}
    for obj, n in claimed_counts.items():
        ref = refs.get(obj)
        if ref is not None and ref["count"] is not None and n is not None:
            count_by_type[obj] = {"claimed": n, "reference": ref["count"]}
            counts.append(_count_score(n, ref["count"]))

    claimed_types = set(claimed_counts)
    missed = [lb["object"] for lb in labels if lb["object"] not in claimed_types]
    matched = sum(r["verdict"] == "matched" for r in rows)
    # With no gradable Claims, precision is perfect on an empty Chip and undefined otherwise
    # (recall carries the miss).
    precision = matched / len(claims) if claims else (None if labels else 1.0)
    recall = (len(labels) - len(missed)) / len(labels) if labels else None

    type_of = {o["id"]: o["object"] for o in caption["objects"]}
    rel_rows, rel_unscored = [], []
    for r in caption["relations"]:
        s, o = type_of.get(r["subject"]), type_of.get(r["object"])
        if r["relation"] not in DIRECTIONAL or s not in refs or o not in refs or s == o:
            rel_unscored.append(r)
            continue
        ok = r["relation"] in directions(refs[s]["position"], refs[o]["position"])
        rel_rows.append({"subject": s, "relation": r["relation"], "object": o, "ok": ok})
    relations = _mean([1.0 if x["ok"] else 0.0 for x in rel_rows])

    components = {
        "precision": precision,
        "recall": recall,
        "count": _mean(counts),
        "position": _mean(positions),
        "attributes": _mean(attributes),
        "relations": relations,
    }
    total = len(caption["objects"])
    return {
        "correctness": _mean(v for k, v in components.items() if k != "recall"),
        "coverage": recall,
        **components,
        "unscored_share": len(unkeyed) / total if total else 0.0,
        "rows": rows,
        "counts": count_by_type,
        "missed": missed,
        "unscored": [o["object"] for o in unkeyed],
        "relation_rows": rel_rows,
        "relations_unscored": rel_unscored,
    }
