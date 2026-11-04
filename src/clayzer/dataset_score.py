"""Dataset diagnostics and reproducible stratified sampling; no uncalibrated quality verdict.

Wilson intervals apply ONLY to binary caption-level outcomes with known evidence. Repeats of
one Case are not independent samples. Continuous/partial scores get means, never Wilson CIs.
"""

import hashlib
import math
from collections import Counter, defaultdict


def wilson(successes: int, n: int) -> list[float] | None:
    if not 0 <= successes <= n:
        raise ValueError("Invalid binomial counts")
    if n == 0:
        return None
    z = 1.959963984540054
    p, denom = successes / n, 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return [max(0.0, centre - half), min(1.0, centre + half)]


def _strata(row):
    classes = sorted(
        {o["object"] for o in row.get("objects", [])}
        | {lb["object"] for lb in (row.get("reference_labels") or []) if lb.get("count") != 0}
    ) or ["unknown"]
    return [(c, row.get("region", "unknown"), row.get("terrain", "unknown")) for c in classes]


def stratified_sample(rows: list[dict], per_stratum=100, seed="clayzer-output-1") -> dict:
    if per_stratum < 1 or len({r["id"] for r in rows}) != len(rows):
        raise ValueError("Positive sample size and unique ids required")
    groups = defaultdict(list)
    for r in rows:
        for stratum in _strata(r):
            groups[stratum].append(r["id"])
    return {
        "seed": seed,
        "per_stratum": per_stratum,
        "strata": [
            {
                "class": key[0],
                "region": key[1],
                "terrain": key[2],
                "population": len(ids),
                "ids": sorted(
                    ids, key=lambda cid: hashlib.sha256(f"{seed}:{cid}".encode()).hexdigest()
                )[:per_stratum],
            }
            for key, ids in sorted(groups.items())
        ],
        "note": "Multi-class strata overlap. Unweighted sample means do not estimate population quality.",
    }


def dataset_report(rows: list[dict], results: list[dict]) -> dict:
    if len(rows) != len(results) or len({r["id"] for r in rows}) != len(rows):
        raise ValueError("Expected one result per unique caption id")
    groups = defaultdict(list)
    for row, result in zip(rows, results, strict=True):
        for stratum in _strata(row):
            groups[stratum].append(
                {**result, "grounding": result.get("grounding_by_class", {}).get(stratum[0])}
            )

    def stats(rs):
        evaluated, errors, unknown, scores = 0, 0, 0, []
        for r in rs:
            g = r.get("grounding")
            if not g:
                unknown += 1
                continue
            if g["correctness"] is not None:
                scores.append(g["correctness"])
            if any(x["outcome"] == "contradicted" for x in g["rows"]) or any(
                not r["ok"] for r in g["relation_rows"]
            ):
                errors += 1
                evaluated += 1
            elif (
                g["rows"]
                and all(x["outcome"] == "supported" for x in g["rows"])
                and not g["unscored"]
                and not any(
                    x.get("unknown_fields") or x.get("class_credit", 1) < 1 for x in g["rows"]
                )
                and g["denominators"]["counts_evaluated"] == len(g["counts"])
                and all(x.get("position") is not None for x in g["rows"])
                and not g["relations_unscored"]
            ):
                evaluated += 1
            else:
                unknown += 1
        return {
            "captions": len(rs),
            "evaluated_binary": evaluated,
            "unknown_binary": unknown,
            "captions_with_contradiction": errors,
            "contradiction_rate": errors / evaluated if evaluated else None,
            "wilson95": wilson(errors, evaluated),
            "correctness_n": len(scores),
            "mean_correctness": sum(scores) / len(scores) if scores else None,
        }

    texts = Counter(r["text"].strip().casefold() for r in rows)
    return {
        "overall": stats(results),
        "strata": [
            {"class": s[0], "region": s[1], "terrain": s[2], **stats(rs)}
            for s, rs in sorted(groups.items())
        ],
        "duplicate_captions": sum(n - 1 for n in texts.values()),
        "sample": stratified_sample(rows),
        "limitations": [
            "Conditional rates describe evaluated evidence, not all caption claims",
            "Wilson intervals assume independent captions; spatial correlation can invalidate coverage",
            "No population verdict or confidence interval for continuous correctness",
        ],
    }
