"""Independent grounding with explicit evidence limits; never infer absence from a missing row.

Correctness is the mean of available component scores, coverage is separate type recall.
USGS and OSM records are incomplete. Unknown components have no weight. Counts from incomplete maps are lower bounds. Relations
require all covered-cell pairs to agree. Exact cells only: centre gets no neighbour bonus.
"""

from clayzer.grid import DIRECTIONAL, directions
from clayzer.ontology import load

KEYED = load().keyed()

SCORE_SCOPE_NOTE = (
    "Correctness evaluates asserted facts; coverage is reference type recall. "
    "A score of 1.0 does not establish full caption quality."
)
COMPARABILITY_NOTE = (
    "Batches measured with different scorers, queries or Judge rubrics are not comparable; "
    "a gate PASS alone does not establish performance improvement."
)


def specificity_note(g: dict) -> str:
    """An explicit score qualifier, also safe for historical results without diagnostics."""
    detail = g.get("specificity")
    if detail is None:
        return SCORE_SCOPE_NOTE + " Count and position completeness was not recorded."
    parts = [SCORE_SCOPE_NOTE]
    for name in ("count", "position"):
        field = detail[name]
        parts.append(
            f"{name.capitalize()} detail: {field['stated']}/{field['available']} stated; "
            f"{field['evaluated']}/{field['available']} evaluated."
        )
    parts.append(
        "Field coverage describes specificity, not accuracy; omitted fields are unevaluated."
    )
    return " ".join(parts)


def _specificity(rows: list[dict], refs: dict, count_scores: dict) -> dict:
    """Reference-type count/position fields stated and checked, independent of correctness.

    A split type's field is stated/evaluated only if every matching Claim supplies it/can be
    checked. Missing reference fields are ineligible, not omissions by the captioner.
    """
    fields = {name: {"available": 0, "stated": 0, "evaluated": 0} for name in ("count", "position")}
    for obj, ref in refs.items():
        matches = [r for r in rows if r.get("reference_object") == obj]
        for name, field in fields.items():
            available = ref.get("count") is not None if name == "count" else bool(ref.get("cells"))
            if not available:
                continue
            field["available"] += 1
            stated = bool(matches) and all(r["claim"].get(name) is not None for r in matches)
            field["stated"] += int(stated)
            if name == "count":
                evaluated = (
                    stated
                    and count_scores.get(obj) is not None
                    and all(
                        r["claim"]["object"] == obj and "count" not in r.get("unknown_fields", [])
                        for r in matches
                    )
                )
            else:
                evaluated = stated and all(r.get("position") is not None for r in matches)
            field["evaluated"] += int(evaluated)
    available = sum(f["available"] for f in fields.values())
    stated = sum(f["stated"] for f in fields.values())
    return {
        **fields,
        "share": stated / available if available else None,
        "definition": "Count/position reference-type fields stated / available; not an accuracy score",
    }


def _mean(xs):
    values = [x for x in xs if x is not None]
    return sum(values) / len(values) if values else None


def _count_score(claimed: int, ref: int) -> float:
    if claimed == ref:
        return 1.0
    if ref == 0:
        return 0.0
    return 0.5 if abs(claimed - ref) / ref <= 0.34 else 0.0


def _position_score(claimed: str | None, cells: list[str]) -> float | None:
    return float(claimed in cells) if claimed is not None and cells else None


def _score_positive_fields(row, cl, ref):
    row["unknown_fields"] = []
    row["position"] = _position_score(cl.get("position"), ref.get("cells", []))
    # Preserve upstream Change Case scoring only where temporal evidence is known.
    if ref.get("change") in ("appeared", "disappeared", "unchanged"):
        row["change"] = float(cl.get("change") == ref["change"])
        if row["change"] == 0:
            row["outcome"] = "contradicted"
    if cl.get("position") is not None and row["position"] is None:
        row["unknown_fields"].append("position")
    for key, value in (cl.get("attributes") or {}).items():
        if key in ref.get("attributes", {}):
            ok = float(value == ref["attributes"][key])
            row.setdefault("attributes", {})[key] = ok
        else:
            row["unknown_fields"].append(f"attributes.{key}")
    if row["position"] == 0 or any(v == 0 for v in row.get("attributes", {}).values()):
        row["outcome"] = "contradicted"


def _score_counts(claimed_counts, refs, rows):
    counts, count_by_type, count_scores = [], {}, {}
    for obj, values in claimed_counts.items():
        ref = refs[obj]
        n, expected = sum(v for v in values if v is not None), ref.get("count")
        complete = ref.get("count_complete", False)
        score = None
        if expected is not None and all(v is not None for v in values):
            if complete:
                score = _count_score(n, expected)
            elif n < expected:
                score = 0.0  # even the independently established lower bound is missed
        if score is None:
            for row in rows:
                if row["claim"]["object"] == obj and row["claim"].get("count") is not None:
                    row["unknown_fields"].append("count")
        count_scores[obj] = score
        if expected is not None:
            count_by_type[obj] = {
                "claimed": n if all(v is not None for v in values) else None,
                "reference": expected,
            }
            counts.append(score)
            if score is not None and score < 1:
                for row in rows:
                    if row["claim"]["object"] == obj:
                        row["outcome"] = "contradicted"

    return counts, count_by_type, count_scores


def _score_relations(caption, rows, resolved, class_id):
    rel_rows, rel_unscored = [], []
    selected_ids = {r["claim"]["id"] for r in rows}
    for relation in caption["relations"]:
        if class_id is not None and not {relation["subject"], relation["object"]} <= selected_ids:
            continue
        a, b = resolved.get(relation["subject"]), resolved.get(relation["object"])
        if (
            relation["relation"] not in DIRECTIONAL
            or not a
            or not b
            or a is b
            or not a.get("cells")
            or not b.get("cells")
        ):
            rel_unscored.append(relation)
            continue
        possibilities = {
            relation["relation"] in directions(x, y) for x in a["cells"] for y in b["cells"]
        }
        if len(possibilities) != 1:
            rel_unscored.append(relation)
            continue
        rel_rows.append(
            {
                "subject": a["object"],
                "relation": relation["relation"],
                "object": b["object"],
                "ok": possibilities.pop(),
            }
        )

    return rel_rows, rel_unscored


def grounding(caption: dict, labels: list[dict], *, class_id: str | None = None) -> dict:
    """A class slice retains the full matching context, including exact-class precedence.

    Parent matches appear in both the claimed and matched reference class slices. These
    diagnostic groups overlap and must not be summed as disjoint populations.
    """
    ontology = load()
    refs = {lb["object"]: lb for lb in labels}
    if len(refs) != len(labels):
        raise ValueError("Reference Labels must contain one aggregate row per object class")
    present = {obj: lb for obj, lb in refs.items() if lb.get("count") != 0}
    rows, positions, attributes, presence, changes = [], [], [], [], []
    unscored, matched_types = [], {}
    claimed_counts: dict[str, list[int | None]] = {}
    resolved = {}
    for cl in caption["objects"]:
        obj = cl["object"]
        ref = refs.get(obj)
        # A greenhouse is a building; neither a road nor a sibling class implies a railroad.
        parent_match = False
        if ref is None and obj in ontology.classes:
            candidates = [
                lb
                for name, lb in present.items()
                if name in ontology.classes and ontology.classes[name].parent == obj
            ]
            if len(candidates) == 1:
                ref, parent_match = candidates[0], True
        if class_id is not None and class_id not in (obj, (ref or {}).get("object")):
            continue
        row = {
            "claim": cl,
            "verdict": "not verifiable",
            "outcome": "not_verifiable",
            "omitted_fields": [name for name in ("count", "position") if cl.get(name) is None],
        }
        if ref is None:
            row["reason"] = (
                "No independent evidence for this class; missing map records are not absence"
            )
            unscored.append(obj)
        elif ref.get("count") == 0:
            if not ref.get("absence_verified") or not ref.get("source"):
                row["reason"] = "Zero count without explicit independently verified absence"
                unscored.append(obj)
            else:
                row |= {
                    "verdict": "false positive",
                    "outcome": "contradicted",
                    "reason": "Explicit absence evidence",
                    "presence": 0.0,
                }
                presence.append(0.0)
        else:
            credit = 0.5 if parent_match else 1.0
            row |= {
                "verdict": "matched",
                "outcome": "supported",
                "presence": credit,
                "reference_object": ref["object"],
                "ref_position": ref.get("position"),
                "class_credit": credit,
            }
            presence.append(credit)
            matched_types[ref["object"]] = max(matched_types.get(ref["object"], 0), credit)
            resolved[cl["id"]] = ref
            _score_positive_fields(row, cl, ref)
            positions.append(row["position"])
            attributes.extend(row.get("attributes", {}).values())
            if "change" in row:
                changes.append(row["change"])
            if parent_match and cl.get("count") is not None:
                row["unknown_fields"].append("count")
            if not parent_match:
                claimed_counts.setdefault(obj, []).append(cl.get("count"))
        rows.append(row)

    counts, count_by_type, count_scores = _score_counts(claimed_counts, refs, rows)

    rel_rows, rel_unscored = _score_relations(caption, rows, resolved, class_id)

    if class_id is not None:
        present = {
            obj: ref for obj, ref in present.items() if obj == class_id or obj in matched_types
        }
    missed = sorted(set(present) - set(matched_types))
    recall = sum(matched_types.values()) / len(present) if present else None
    components = {
        "precision": _mean(presence),
        "recall": recall,
        "count": _mean(counts),
        "position": _mean(positions),
        "attributes": _mean(attributes),
        "relations": _mean(float(r["ok"]) for r in rel_rows),
        "change": _mean(changes),
    }
    total = len(rows)
    return {
        "correctness": _mean(v for k, v in components.items() if k != "recall"),
        "coverage": recall,
        "specificity": _specificity(rows, present, count_scores),
        **components,
        "unscored_share": len(unscored) / total if total else 0.0,
        "rows": rows,
        "counts": count_by_type,
        "missed": missed,
        "unscored": unscored,
        "relation_rows": rel_rows,
        "relations_unscored": rel_unscored,
        "denominators": {
            "claims": total,
            "presence_evaluated": len(presence),
            "unknown_claims": len(unscored),
            "reference_types": len(present),
            "counts_evaluated": sum(x is not None for x in counts),
            "positions_evaluated": sum(x is not None for x in positions),
            "attributes_evaluated": len(attributes),
            "relations_evaluated": len(rel_rows),
        },
        "evidence_policy": "open-world; map counts lower bounds unless count_complete; exact cells",
    }
