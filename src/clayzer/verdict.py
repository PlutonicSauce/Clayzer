"""A dataset-level verdict on an imported Caption Set (CAP-21, caption-design.md §3.6).

How far can a whole caption set be trusted? Two Batches answer it:
- the whole set, scored with no Judge: the cheap checks (grounding against Answer Keys,
  duplication, vocabulary, Claims about objects too small for the imagery), on every caption;
- a stratified sample of it, judged for fidelity: the expensive check, on enough captions per
  stratum for a useful interval.

Every rate is the share of captions with a problem, reported with a 95% Wilson interval,
overall and per stratum. A rate is over the captions it applies to: grounding rates over located
captions, too-small over captions whose imagery resolution is known, fidelity over judged
captions with an image. Strata:
- class: each Object Class in the caption's Reference Labels or Claims (a caption is in every
  class it involves), or `none`;
- region: our Cases' region; an imported caption's UTM zone, or `unlocated`;
- terrain: the Case's setting or the source's scene class (RSICD's `airport`), else `unknown`.
  Terrain isn't recorded for most Cases yet: spread.py classifies settings but doesn't save them.

Sampling (decided 2026-11-04): up to `per_stratum` captions per primary class (a caption's first
class), at random with a fixed seed, so rare classes are judged as often as common ones. That
over-represents rare classes, so the overall fidelity rate weights each judged caption by its
class's share of the set over its share of the sample, and its interval uses the weighted
sample's effective size (Kish). Per-stratum rates need no weights. Region and terrain aren't
sampled for, so their judged rates may rest on few captions; their intervals show it.
"""

from __future__ import annotations

import math
import random
import re
from collections import Counter

Z95 = 1.96
UNFAITHFUL_BELOW = 0.5  # a fidelity score under this counts as an unfaithful caption
DIMENSIONS = ("class", "region", "terrain")


def wilson(k: float, n: float, z: float = Z95) -> dict:
    """A proportion with its Wilson score interval; n may be an effective (weighted) size."""
    if n <= 0:
        return {"k": k, "n": n, "p": None, "lo": None, "hi": None}
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return {"k": k, "n": n, "p": p, "lo": max(0.0, centre - half), "hi": min(1.0, centre + half)}


def _weighted(flags: list[tuple[bool, float]]) -> dict:
    """A weighted proportion, as Wilson over the Kish effective sample size."""
    if not flags:
        return wilson(0, 0)
    total = sum(w for _, w in flags)
    p = sum(w for f, w in flags if f) / total
    n_eff = total * total / sum(w * w for _, w in flags)
    return {**wilson(p * n_eff, n_eff), "k": sum(f for f, _ in flags), "n": len(flags)}


def _classes(case: dict, cap: dict | None) -> list[str]:
    found = {lb["object"] for lb in case.get("reference_labels", [])}
    found |= {o["object"] for o in (cap or {}).get("objects", [])}
    return sorted(found) or ["none"]


def _region(case: dict) -> str:
    if not case.get("imported"):
        return case.get("region") or "unknown"
    bbox = case["chips"][0].get("bbox")
    if not bbox:
        return "unlocated"
    return f"utm-{int(((bbox[0] + bbox[2]) / 2 + 180) // 6) + 1}"


def _terrain(case: dict) -> str:
    return case.get("setting") or (case.get("imported") or {}).get("scene") or "unknown"


def strata(case: dict, cap: dict | None) -> dict[str, list[str]]:
    return {"class": _classes(case, cap), "region": [_region(case)], "terrain": [_terrain(case)]}


def _norm(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", text.lower()))


def _checks(case: dict, result: dict, cap: dict, duplicates: set[str]) -> dict[str, bool | None]:
    """Each cheap check for one caption: True when it has the problem, None when it can't say."""
    g = result.get("grounding") or {}
    located = not g.get("not_grounded")
    small = (case.get("imported") or {}).get("too_small")
    return {
        "false_claim": any(r["verdict"] == "false positive" for r in g["rows"]) if located else None,
        "miscount": any(c["claimed"] != c["reference"] for c in g["counts"].values())
        if located else None,
        "misplaced": any(r.get("position") == 0.0 for r in g["rows"]) if located else None,
        "missed_label": bool(g["missed"]) if located else None,
        "too_small": bool(small) if small is not None else None,
        "duplicate": _norm(cap["text"]) in duplicates,
    }  # fmt: skip


def _scored(b: dict) -> list[tuple[dict, dict, dict]]:
    """(case, result, caption) for every scored caption of a Batch."""
    cases = {c["id"]: c for c in b["cases"]}
    caps = {(c["case_id"], c["repeat"]): c for c in b["captions"]}
    return [(cases[r["case_id"]], r, caps[(r["case_id"], r["repeat"])])
            for r in b["results"]
            if r["status"] == "ok" and (r["case_id"], r["repeat"]) in caps]  # fmt: skip


def sample(b: dict, per_stratum: int, seed: int = 0) -> list[str]:
    """Case ids for the Judge: up to `per_stratum` captions per primary class, at random."""
    by_class: dict[str, list[str]] = {}
    for case, _, cap in _scored(b):
        by_class.setdefault(_classes(case, cap)[0], []).append(case["id"])
    rng = random.Random(seed)
    picked = []
    for cls in sorted(by_class):
        ids = sorted(by_class[cls])
        picked += rng.sample(ids, min(per_stratum, len(ids)))
    return sorted(picked)


def _vocabulary(texts: list[str]) -> dict:
    words = [w for t in texts for w in _norm(t).split()]
    counts = Counter(words)
    return {"words": len(words), "distinct": len(counts),
            "per_caption": len(words) / len(texts) if texts else None,
            "type_token_ratio": len(counts) / len(words) if words else None,
            "top": [w for w, _ in counts.most_common(15)]}  # fmt: skip


def build(full: dict, judged: dict | None = None) -> dict:
    """The verdict from the whole set's Batch (no Judge) and, optionally, a judged sample."""
    rows = _scored(full)
    texts = Counter(_norm(cap["text"]) for _, _, cap in rows)
    duplicates = {t for t, n in texts.items() if n > 1}
    items = []
    for case, result, cap in rows:
        items.append({"strata": strata(case, cap), "checks": _checks(case, result, cap, duplicates),
                      "primary": _classes(case, cap)[0]})  # fmt: skip
    checks = list(items[0]["checks"]) if items else []

    def rates(group: list[dict]) -> dict:
        out = {}
        for name in checks:
            flags = [i["checks"][name] for i in group if i["checks"][name] is not None]
            out[name] = wilson(sum(flags), len(flags))
        return out

    verdict = {
        "set": full["config"].region,
        "full_batch": full["config"].batch_id,
        "judged_batch": judged["config"].batch_id if judged else None,
        "captions": len(rows),
        "rates": rates(items),
        "strata": {
            d: {v: {"captions": len(g), "rates": rates(g)} for v, g in _group(items, d).items()}
            for d in DIMENSIONS
        },
        "vocabulary": _vocabulary([cap["text"] for _, _, cap in rows]),
        "duplicate_texts": len(duplicates),
    }
    if judged:
        _add_fidelity(verdict, items, judged)
    return verdict


def _group(items: list[dict], dim: str) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for i in items:
        for v in i["strata"][dim]:
            out.setdefault(v, []).append(i)
    return dict(sorted(out.items()))


def _add_fidelity(verdict: dict, items: list[dict], judged: dict) -> None:
    """The unfaithful rate from the judged sample, weighted back to the set's class mix."""
    share = Counter(i["primary"] for i in items)
    sampled = []
    for case, result, cap in _scored(judged):
        fid = (result.get("fidelity") or {}).get("score")
        if fid is not None:
            sampled.append({"strata": strata(case, cap), "primary": _classes(case, cap)[0],
                            "unfaithful": fid < UNFAITHFUL_BELOW})  # fmt: skip
    in_sample = Counter(s["primary"] for s in sampled)
    weight = {c: share[c] / in_sample[c] for c in in_sample}
    verdict["judged"] = len(sampled)
    verdict["rates"]["unfaithful"] = _weighted([(s["unfaithful"], weight[s["primary"]])
                                                for s in sampled])  # fmt: skip
    for dim in DIMENSIONS:
        for value, group in _group(sampled, dim).items():
            stratum = verdict["strata"][dim].setdefault(value, {"captions": 0, "rates": {}})
            stratum["judged"] = len(group)
            stratum["rates"]["unfaithful"] = wilson(sum(s["unfaithful"] for s in group), len(group))


def _pct(r: dict) -> str:
    if r["p"] is None:
        return "—"
    return f"{100 * r['p']:.0f}% [{100 * r['lo']:.0f}–{100 * r['hi']:.0f}] of {r['n']:.0f}"


LABELS = {
    "false_claim": "Claims a class the Answer Key doesn't have",
    "miscount": "Miscounts a labelled class",
    "misplaced": "Places a labelled class in the wrong cell",
    "missed_label": "Misses a labelled class",
    "too_small": "Claims an object too small for its imagery",
    "duplicate": "Repeats another caption's text",
    "unfaithful": f"Unfaithful to the image (fidelity under {UNFAITHFUL_BELOW})",
}


def render(v: dict) -> str:
    """The verdict as Markdown: every rate with its 95% interval and the captions it's over."""
    lines = [
        f"# Verdict: {v['set']}",
        "",
        f"{v['captions']} captions checked without a Judge (Batch `{v['full_batch']}`)"
        + (
            f"; {v['judged']} judged for fidelity (Batch `{v['judged_batch']}`)."
            if v.get("judged_batch")
            else "; no judged sample yet."
        ),
        "",
        (
            "Each rate: share of captions with the problem, [95% Wilson interval], of the captions "
            "it applies to."
        ),
        "",
        "| Problem | Overall |",
        "|---|---|",
        *(f"| {LABELS[k]} | {_pct(r)} |" for k, r in v["rates"].items()),
    ]
    for dim in DIMENSIONS:
        names = list(v["rates"])
        lines += ["", f"## By {dim}", "",
                  "| " + dim.capitalize() + " | Captions | " + " | ".join(names) + " |",
                  "|---" * (len(names) + 2) + "|"]  # fmt: skip
        for value, s in v["strata"][dim].items():
            cells = [_pct(s["rates"][n]) if n in s["rates"] else "—" for n in names]
            lines.append(f"| {value} | {s['captions']} | " + " | ".join(cells) + " |")
    voc = v["vocabulary"]
    lines += ["", "## Vocabulary", "",
              (f"{voc['distinct']} distinct words in {voc['words']}; "
              f"{voc['per_caption'] or 0:.1f} per caption; {v['duplicate_texts']} texts repeated. "
              f"Most used: {', '.join(voc['top'])}."), ""]  # fmt: skip
    return "\n".join(lines)


def verdict_key(name: str) -> str:
    return f"verdicts/{name}.json"
