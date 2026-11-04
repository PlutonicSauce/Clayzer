"""The Caption dataset card (CAP-22, caption-design.md §3.6): one report per Caption Set.

It describes a Caption Set as data, not one Caption at a time: how big it is and how much of it
repeats, which Object Classes and regions it covers, how varied its wording is, and where it goes
wrong for each Object Class, including look-alike confusions from the Object Ontology (a
greenhouse called a solar array). It also says what it can't show.

The card is built from caption records, so any Caption Set can have one. Today the only source is
a Batch's Captions (`from_batch`); the importer (CAP-20) will produce the same records from a
Caption Set in the import format. Everything here is deterministic and needs no model, so the
card rebuilds offline with the rest of a Batch's reports (REQ-09).

A caption record:
    caption_id   unique per Caption
    chip_id      the image it describes; Repeats of one Case share one
    case_id, region
    text, objects, relations     the Caption and its Claims (ADR-0007)
    labels       the Case's Reference Labels, for scoring only (ADR-0006: never the Harness's)
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from html import escape

from clayzer import ontology as onto
from clayzer.grounding import KEYED, grounding

# Near-duplicate search compares every pair of Captions from different Chips; above this many
# Captions it's skipped, and the card says so.
NEAR_DUPLICATE_LIMIT = 2000
NEAR_DUPLICATE_JACCARD = 0.8
# Fewer labelled Chips than this and a class's error rates are flagged as thin.
THIN = 10
STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has", "have", "in", "into",
    "is", "it", "its", "of", "on", "or", "that", "the", "their", "there", "this", "to", "with",
    "which", "while", "near", "along", "across", "around", "image", "tile", "chip", "area",
    "shows", "visible",
}  # fmt: skip


def card_key(batch_id: str) -> str:
    return f"batches/{batch_id}/dataset-card.json"


def from_batch(b: dict) -> list[dict]:
    """A Batch's Captions as caption records: every Run that produced a Caption."""
    cases = {c["id"]: c for c in b["cases"]}
    ok = {(r["case_id"], r["repeat"]) for r in b["results"] if r["status"] == "ok"}
    records = []
    for cap in b["captions"]:
        key = (cap["case_id"], cap["repeat"])
        case = cases.get(cap["case_id"])
        if key not in ok or case is None or not (cap.get("text") or "").strip():
            continue
        records.append({
            "caption_id": f"{cap['case_id']}#{cap['repeat']}",
            "chip_id": case["chips"][0]["id"],
            "case_id": case["id"],
            "region": case.get("region") or b["config"].region,
            "text": cap["text"],
            "objects": cap.get("objects") or [],
            "relations": cap.get("relations") or [],
            "labels": case["reference_labels"],
        })  # fmt: skip
    return records


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+(?:'[a-z]+)?", text.lower())


def _shingles(words: list[str]) -> set[tuple[str, ...]]:
    return {tuple(words[i : i + 3]) for i in range(max(len(words) - 2, 1))} if words else set()


def _duplication(records: list[dict]) -> dict:
    """Duplication across Chips. Repeats of one Chip repeat by design, so they don't count."""
    norm = [" ".join(_words(r["text"])) for r in records]
    chips_with_text: dict[str, set[str]] = defaultdict(set)
    for r, t in zip(records, norm):
        chips_with_text[t].add(r["chip_id"])
    exact = [i for i, t in enumerate(norm) if len(chips_with_text[t]) > 1]

    near, checked = set(), len(records) <= NEAR_DUPLICATE_LIMIT
    if checked:
        sh = [_shingles(t.split()) for t in norm]
        for i in range(len(records)):
            for j in range(i + 1, len(records)):
                if records[i]["chip_id"] == records[j]["chip_id"] or not sh[i] or not sh[j]:
                    continue
                if len(sh[i] & sh[j]) / len(sh[i] | sh[j]) >= NEAR_DUPLICATE_JACCARD:
                    near.update((i, j))
    per_chip: dict[str, set[str]] = defaultdict(set)
    for r, t in zip(records, norm):
        per_chip[r["chip_id"]].add(t)
    n = len(records)
    examples = sorted({norm[i] for i in exact})[:3]
    return {
        "exact_across_chips": len(exact),
        "exact_rate": len(exact) / n if n else None,
        "near_across_chips": len(near) if checked else None,
        "near_rate": (len(near) / n if n else None) if checked else None,
        "near_checked": checked,
        "distinct_texts_per_chip": (
            sum(len(v) for v in per_chip.values()) / len(per_chip) if per_chip else None
        ),
        "examples": examples,
    }


def _terms(cls) -> list[str]:
    return [cls.name.lower(), cls.id.replace("_", " "), *(s.lower() for s in cls.synonyms)]


def _mentions(text: str, terms: list[str]) -> bool:
    low = " ".join(_words(text))
    return any(re.search(rf"\b{re.escape(' '.join(_words(t)))}s?\b", low) for t in terms if t)


def _vocabulary(records: list[dict], ontology) -> dict:
    words = [w for r in records for w in _words(r["text"])]
    content = Counter(w for w in words if w not in STOPWORDS and not w.isdigit())
    openings = Counter(" ".join(_words(r["text"])[:3]) for r in records)
    n = len(records)
    return {
        "words": len(words),
        "distinct_words": len(set(words)),
        "type_token_ratio": len(set(words)) / len(words) if words else None,
        "words_per_caption": len(words) / n if n else None,
        "top_words": content.most_common(12),
        # How many ways Captions start: a template shows up as one opening for most Captions.
        "distinct_openings": len(openings),
        "top_opening": openings.most_common(1)[0] if openings else None,
        "classes_in_text": {
            c.id: sum(_mentions(r["text"], _terms(c)) for r in records)
            for c in ontology.classes.values()
            if c.claimable
        },
    }


def _confusers(ontology, a: str, b: str) -> bool:
    """Look-alikes, either way round: the ontology lists confusers on one side or both."""
    ca, cb = ontology.classes.get(a), ontology.classes.get(b)
    return bool((ca and b in ca.confusers) or (cb and a in cb.confusers))


def _errors(records: list[dict], ontology) -> tuple[dict, list[dict], dict]:
    """Per Object Class: how often it's missed, claimed wrongly, miscounted, or misplaced, and
    which look-alikes it's confused with. Returns (per class, confusions, Claim totals)."""
    per: dict[str, Counter] = defaultdict(Counter)
    count_errors: dict[str, list[int]] = defaultdict(list)
    chips: dict[str, set[str]] = defaultdict(set)
    confusions: Counter = Counter()
    examples: dict[tuple[str, str], str] = {}
    claims = unscored = 0
    for r in records:
        g = grounding({"objects": r["objects"], "relations": r["relations"]}, r["labels"])
        labelled = {lb["object"] for lb in r["labels"]}
        claimed = {o["object"] for o in r["objects"]}
        claims += len(r["objects"])
        unscored += len(g["unscored"])
        for cls in labelled:
            per[cls]["labelled"] += 1
            chips[cls].add(r["chip_id"])
        for cls in claimed:
            per[cls]["claimed"] += 1
        for cls in labelled & claimed & KEYED:
            per[cls]["matched"] += 1
        for cls in set(g["missed"]):
            per[cls]["missed"] += 1
        false_pos = {row["claim"]["object"] for row in g["rows"] if row["verdict"] != "matched"}
        for cls in false_pos:
            per[cls]["false_positive"] += 1
            # A false positive beside a look-alike that was really there, and missed: the
            # Caption named the wrong one of the two.
            for real in labelled - claimed:
                if _confusers(ontology, cls, real):
                    confusions[(real, cls)] += 1
                    examples.setdefault((real, cls), r["caption_id"])
        for cls, c in g["counts"].items():
            diff = c["claimed"] - c["reference"]
            count_errors[cls].append(diff)
            per[cls][
                "over_count" if diff > 0 else "under_count" if diff < 0 else "exact_count"
            ] += 1
        # Position is judged per Claim: a Caption can split one class over several Claims
        # ("10 turbines south-east, 5 south-west"), so both sides of the rate count Claims.
        for row in g["rows"]:
            if row["verdict"] == "matched":
                cls = row["claim"]["object"]
                per[cls]["matched_claims"] += 1
                if row["position"] < 1:
                    per[cls]["misplaced"] += 1

    def rate(a, b):
        return a / b if b else None

    out = {}
    for cls, c in per.items():
        known = cls in ontology.classes
        counted = c["over_count"] + c["under_count"] + c["exact_count"]
        out[cls] = {
            "name": ontology.classes[cls].name if known else cls,
            "keyed": cls in KEYED,
            # Distinct Chips with the class; `labelled` and `claimed` count Captions, so a
            # Chip captioned in three Repeats counts three times there and once here.
            "chips": len(chips[cls]),
            **{
                k: c[k]
                for k in (
                    "labelled",
                    "claimed",
                    "matched",
                    "matched_claims",
                    "missed",
                    "false_positive",
                    "over_count",
                    "under_count",
                    "misplaced",
                )
            },
            "miss_rate": rate(c["missed"], c["labelled"]),
            "false_positive_rate": rate(c["false_positive"], c["claimed"]),
            "miscount_rate": rate(c["over_count"] + c["under_count"], counted),
            "mean_count_error": (
                sum(abs(d) for d in count_errors[cls]) / len(count_errors[cls])
                if count_errors[cls]
                else None
            ),
            "misplaced_rate": rate(c["misplaced"], c["matched_claims"]),
            "thin": len(chips[cls]) < THIN,
        }
    pairs = [
        {
            "labelled": real, "claimed": said, "captions": n,
            "of_labelled": n / per[real]["labelled"] if per[real]["labelled"] else None,
            "example": examples[(real, said)],
        }
        for (real, said), n in confusions.most_common()
    ]  # fmt: skip
    return dict(sorted(out.items())), pairs, {"claims": claims, "unscored": unscored}


def _coverage(records: list[dict], ontology, per_class: dict) -> dict:
    regions = Counter(r["region"] for r in records)
    chips_by_region: dict[str, set] = defaultdict(set)
    for r in records:
        chips_by_region[r["region"]].add(r["chip_id"])
    classes = []
    for c in ontology.classes.values():
        if not c.claimable:
            continue
        e = per_class.get(c.id, {})
        labelled, claimed = e.get("chips", 0), e.get("claimed", 0)
        if not c.keyed_by:
            status = "no Answer Key: Claims about it are unscored"
        elif not labelled and not claimed:
            status = "missing: no Chip has it and no Caption claims it"
        elif not labelled:
            status = "claimed, but no Chip in the set has it"
        else:
            status = "covered"
        classes.append({"class": c.id, "name": c.name, "keyed": bool(c.keyed_by),
                        "labelled": labelled, "claimed": claimed,
                        "status": status})  # fmt: skip
    return {
        "classes": classes,
        "missing": [c["class"] for c in classes if c["status"].startswith("missing")],
        "regions": {
            k: {"captions": v, "chips": len(chips_by_region[k])} for k, v in sorted(regions.items())
        },
        "terrain": None,
    }


def _names(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _unchecked_limit(card: dict) -> str:
    """The limit on error patterns. The classes no Answer Key covers are named from the Object
    Ontology, so the sentence follows it when a class gains or loses a key."""
    text = "Error patterns cover only Object Classes an Answer Key can check."
    unchecked = [c["name"].lower() for c in card["coverage"]["classes"] if not c["keyed"]]
    if not unchecked:
        return text
    claims = card["claims"]
    text += (
        f" Mistakes about {_names(unchecked)}, and look-alike confusions involving them, "
        "can't be seen here."
    )
    if claims["unscored"]:
        return text + (
            f" In this set, {claims['unscored']} of {claims['claims']} Claims name a class "
            "no Answer Key covers."
        )
    return text + " No Claim in this set names a class without an Answer Key."


def _limits(card: dict, source: dict) -> list[str]:
    n = card["size"]["captions"]
    out = [
        (
            "It can't show whether these Captions would improve Clay v2: only training it can, and "
            "that's out of scope. Retrieval with an off-the-shelf text model is a proxy for that."
        ),
        (
            f"Rates are point estimates over {n} Captions, without confidence intervals yet; the "
            "dataset-level verdict (CAP-21) adds Wilson 95% intervals per rate and per stratum."
        ),
        _unchecked_limit(card),
        "Terrain coverage isn't shown: Cases don't record terrain yet.",
        (
            "Coverage is shown against the Object Ontology's claimable classes, because Clay hasn't "
            "said what it will caption."
        ),
        (
            "Duplication is counted across Chips only: Repeats of one Case describe the same Chip, "
            "so similar wording between them is expected."
        ),
    ]
    if not card["duplication"]["near_checked"]:
        out.append(
            f"Near-duplicates weren't searched: the set has more than {NEAR_DUPLICATE_LIMIT} "
            "Captions."
        )
    thin = [c for c, e in card["errors"].items() if e["thin"] and e["chips"]]
    if thin:
        out.append(
            f"Fewer than {THIN} labelled Chips for {', '.join(thin)}: those rates can swing on a "
            "single Caption."
        )
    if source.get("kind") == "batch":
        out.append(
            "This Caption Set is a Batch's own Captions. Imported Caption Sets from other "
            "sources get the same card once the importer (CAP-20) is built."
        )
    return out


def build(records: list[dict], source: dict, ontology=None) -> dict:
    """The card for a Caption Set. `source` says where the records came from, e.g.
    {"kind": "batch", "id": <batch id>, "generator": <caption model>}."""
    ontology = ontology or onto.load()
    errors, confusions, claims = _errors(records, ontology)
    card = {
        "source": source,
        "ontology_version": ontology.version,
        "size": {
            "captions": len(records),
            "chips": len({r["chip_id"] for r in records}),
            "claims": claims["claims"],
            "claims_per_caption": claims["claims"] / len(records) if records else None,
        },
        "duplication": _duplication(records),
        "coverage": _coverage(records, ontology, errors),
        "vocabulary": _vocabulary(records, ontology),
        "errors": errors,
        "confusions": confusions,
        "claims": claims,
    }
    card["limits"] = _limits(card, source)
    return card


# ── Rendering ───────────────────────────────────────────────────────────────────────────


def _p(x) -> str:
    return "—" if x is None else f"{x * 100:.0f}%"


def _n(x, digits: int = 1) -> str:
    return "—" if x is None else f"{x:.{digits}f}"


def to_markdown(card: dict) -> str:
    s, d, v, cov = card["size"], card["duplication"], card["vocabulary"], card["coverage"]
    lines = [
        "## Caption dataset card",
        "",
        (
            f"{s['captions']} Captions of {s['chips']} Chips · {s['claims']} Claims "
            f"({_n(s['claims_per_caption'])} per Caption) · Object Ontology {card['ontology_version']}"
        ),
        "",
        f"- **Duplication across Chips:** {d['exact_across_chips']} exact ({_p(d['exact_rate'])}), "
        + (
            f"{d['near_across_chips']} near ({_p(d['near_rate'])})"
            if d["near_checked"]
            else "near-duplicates not searched"
        )
        + f"; {_n(d['distinct_texts_per_chip'])} distinct texts per Chip",
        (
            f"- **Vocabulary:** {v['distinct_words']} distinct words of {v['words']} "
            f"(type-token ratio {_n(v['type_token_ratio'], 2)}), {_n(v['words_per_caption'])} words "
            f"per Caption, {v['distinct_openings']} distinct openings"
        ),
        "- **Regions:** "
        + (", ".join(f"{k} ({r['chips']} Chips)" for k, r in cov["regions"].items()) or "none"),
        "- **Missing classes:** " + (", ".join(cov["missing"]) or "none"),
        "",
        (
            "| Object Class | Chips with it | Captions of them | Captions claiming it | Missed "
            "| False positive | Miscounted | Misplaced |"
        ),
        "|---|---|---|---|---|---|---|---|",
    ]
    for e in card["errors"].values():
        if not e["keyed"]:
            continue
        lines.append(
            f"| {e['name']}{' (thin)' if e['thin'] else ''} | {e['chips']} | {e['labelled']} | {e['claimed']} | "
            f"{_p(e['miss_rate'])} | {_p(e['false_positive_rate'])} | {_p(e['miscount_rate'])} | "
            f"{_p(e['misplaced_rate'])} |"
        )
    lines += ["", "**Look-alike confusions:** "]
    lines[-1] += (
        "; ".join(
            f"{c['labelled']} called {c['claimed']} in {c['captions']} Captions "
            f"(e.g. {c['example']})"
            for c in card["confusions"]
        )
        or "none found"
    )
    lines += ["", "**What this card can't show:**", ""] + [f"- {x}" for x in card["limits"]]
    return "\n".join(lines) + "\n"


def to_html(card: dict) -> str:
    """The card as an HTML section, for the Batch report."""
    s, d, v, cov = card["size"], card["duplication"], card["vocabulary"], card["coverage"]
    near = (
        f"{d['near_across_chips']} near ({_p(d['near_rate'])})"
        if d["near_checked"]
        else "near-duplicates not searched"
    )
    facts = [
        ("Size", (f"{s['captions']} Captions of {s['chips']} Chips, {s['claims']} Claims "
                 f"({_n(s['claims_per_caption'])} per Caption)")),
        ("Duplication across Chips", (f"{d['exact_across_chips']} exact ({_p(d['exact_rate'])}), "
                                     f"{near}; {_n(d['distinct_texts_per_chip'])} distinct texts "
                                     "per Chip")),
        ("Vocabulary", (f"{v['distinct_words']} distinct words of {v['words']} (type-token ratio "
                       f"{_n(v['type_token_ratio'], 2)}); {_n(v['words_per_caption'])} words per "
                       f"Caption; {v['distinct_openings']} distinct openings")),
        ("Most used words", ", ".join(f"{w} ({n})" for w, n in v["top_words"]) or "—"),
        ("Regions", ", ".join(f"{k}: {r['captions']} Captions, {r['chips']} Chips"
                              for k, r in cov["regions"].items()) or "—"),
        ("Terrain", "not recorded"),
    ]  # fmt: skip
    html = [
        "<section class='dataset-card' id='dataset-card'><h2>Caption dataset card</h2>",
        (
            f"<p class='sub'>This Batch's Captions as one Caption Set · Object Ontology "
            f"{escape(card['ontology_version'])} · no model calls</p>"
        ),
        "<table>"
        + "".join(f"<tr><th>{escape(k)}</th><td>{escape(val)}</td></tr>" for k, val in facts)
        + "</table>",
        (
            "<h3>Coverage by Object Class</h3><table><tr><th>Object Class</th>"
            "<th class='num'>Chips with it</th><th class='num'>Captions claiming it</th>"
            "<th class='num'>Named in text</th><th>Status</th></tr>"
        ),
    ]
    for c in cov["classes"]:
        html.append(
            f"<tr><td>{escape(c['name'])}</td><td class='num'>{c['labelled']}</td>"
            f"<td class='num'>{c['claimed']}</td>"
            f"<td class='num'>{v['classes_in_text'].get(c['class'], 0)}</td>"
            f"<td>{escape(c['status'])}</td></tr>"
        )
    html += [
        "</table><h3>Error patterns by Object Class</h3>",
        (
            "<p class='sub'>Missed is out of the Captions of Chips that have the class; false "
            "positive, out of the Captions claiming it; miscounted, out of the Captions whose "
            "count the Answer Key can check; misplaced, out of the Claims that matched."
            "</p><table><tr><th>Object Class</th><th class='num'>Chips with it</th>"
            "<th class='num'>Captions of them</th><th class='num'>Captions claiming it</th>"
            "<th class='num'>Missed</th><th class='num'>False positive"
            "</th><th class='num'>Miscounted</th><th class='num'>Mean count error</th>"
            "<th class='num'>Misplaced</th></tr>"
        ),
    ]
    for e in card["errors"].values():
        if not e["keyed"]:
            continue
        thin = " <small>(thin)</small>" if e["thin"] else ""
        html.append(
            f"<tr><td>{escape(e['name'])}{thin}</td><td class='num'>{e['chips']}</td>"
            f"<td class='num'>{e['labelled']}</td>"
            f"<td class='num'>{e['claimed']}</td><td class='num'>{_p(e['miss_rate'])}</td>"
            f"<td class='num'>{_p(e['false_positive_rate'])}</td>"
            f"<td class='num'>{_p(e['miscount_rate'])}</td>"
            f"<td class='num'>{_n(e['mean_count_error'])}</td>"
            f"<td class='num'>{_p(e['misplaced_rate'])}</td></tr>"
        )
    html.append("</table><h3>Look-alike confusions</h3>")
    if card["confusions"]:
        html.append(
            "<table><tr><th>Really there</th><th>Caption said</th><th class='num'>Captions</th>"
            "<th class='num'>Of Captions where it's there</th><th>Example</th></tr>"
            + "".join(
                f"<tr><td>{escape(c['labelled'])}</td><td>{escape(c['claimed'])}</td>"
                f"<td class='num'>{c['captions']}</td><td class='num'>{_p(c['of_labelled'])}</td>"
                f"<td class='mono'>{escape(c['example'])}</td></tr>"
                for c in card["confusions"]
            )
            + "</table>"
        )
    else:
        html.append("<p>None found among the classes an Answer Key can check.</p>")
    html += [
        "<h3>What this card can't show</h3><ul>",
        *(f"<li>{escape(x)}</li>" for x in card["limits"]),
        "</ul></section>",
    ]
    return "\n".join(html)
