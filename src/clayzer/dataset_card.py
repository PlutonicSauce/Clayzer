"""A descriptive card over existing Output Score evidence, without a new quality rubric."""

import json
import re
import statistics
from collections import Counter
from html import escape
from pathlib import Path

from clayzer.ontology import load
from clayzer.report_html import STYLE
from clayzer.report_safety import redact

VERSION = "dataset-card-1"


def build(report: dict) -> dict:
    rows, results = report["captions"], report["results"]
    references = report.get("references", {})
    vocabulary, lengths, classes, regions, terrains = Counter(), [], Counter(), Counter(), Counter()
    images, case_ids, missing_images = set(), set(), 0
    outcomes, confusions, fields = {}, Counter(), Counter()

    def observed(value):
        return str(value) if value not in (None, "") else "unknown"

    for row in rows:
        words = re.findall(r"\b\w+\b", row["text"].casefold())
        vocabulary.update(words)
        lengths.append(len(words))
        case = references.get(row["id"], {})
        regions[observed(row.get("region", case.get("region")))] += 1
        terrains[observed(row.get("terrain", case.get("terrain")))] += 1
        case_id = row.get("case_id")
        if case_id:
            case_ids.add(case_id)
        image = row.get("chip_id") or row.get("image_uri")
        if not image and case.get("chips"):
            image = case["chips"][0].get("id")
        if image:
            images.add(image)
        else:
            missing_images += 1
        for obj in {o["object"] for o in row.get("objects", [])}:
            classes[obj] += 1

    def means(key):
        xs = [
            r["grounding"][key]
            for r in results
            if r.get("grounding") and r["grounding"].get(key) is not None
        ]
        return {"mean": statistics.mean(xs) if xs else None, "n": len(xs)}

    for result in results:
        g = result.get("grounding") or {}
        for row in g.get("rows", []):
            obj = row["claim"]["object"]
            stats = outcomes.setdefault(obj, Counter())
            stats["claims"] += 1
            stats[row["outcome"]] += 1
            stats["class_credit_sum"] += row.get("class_credit") or 0
            for f in row.get("unknown_fields", []):
                fields[f"unknown_{f}"] += 1
            for f in row.get("omitted_fields", []):
                fields[f"omitted_{f}"] += 1
            ref = row.get("reference_object")
            if ref and ref != obj:
                confusions[(obj, ref)] += 1
    ont = load()
    metadata = report.get("dataset_metadata", {})
    field_coverage = {
        field: {
            key: sum(
                (r.get("grounding") or {}).get("specificity", {}).get(field, {}).get(key, 0)
                for r in results
            )
            for key in ("available", "stated", "evaluated")
        }
        for field in ("count", "position")
    }
    return {
        "schema_version": VERSION,
        "evaluation_notice": report.get("demo_notice"),
        "dataset": {k: metadata.get(k) for k in ("name", "source", "date", "split", "provenance")},
        "scorer_version": report.get("scorer_version"),
        "source_sha256": report.get("source_sha256"),
        "references_sha256": report.get("references_sha256"),
        "ontology": report.get("ontology"),
        "counts": {
            "captions": len(rows),
            "unique_cases_observed": len(case_ids),
            "unique_images_observed": len(images),
            "captions_missing_image_identity": missing_images,
        },
        "duplication": {
            "exact_duplicate_captions": report["dataset"]["duplicate_captions"],
            "rate": report["dataset"]["duplicate_captions"] / len(rows) if rows else None,
            "definition": "Additional captions after strip + casefold text equality; no semantic or image deduplication",
        },
        "vocabulary": {
            "tokens": sum(lengths),
            "unique_tokens": len(vocabulary),
            "type_token_ratio": len(vocabulary) / sum(lengths) if sum(lengths) else None,
            "definition": "Unicode word tokens, casefolded; descriptive, not a quality score",
        },
        "length_words": {
            "min": min(lengths) if lengths else None,
            "median": statistics.median(lengths) if lengths else None,
            "mean": statistics.mean(lengths) if lengths else None,
            "max": max(lengths) if lengths else None,
        },
        "class_caption_counts": dict(sorted(classes.items())),
        "regions": dict(sorted(regions.items())),
        "terrain": dict(sorted(terrains.items())),
        "grounding": {
            "correctness": means("correctness"),
            "coverage": means("coverage"),
            "binary_caption_evidence": report["dataset"]["overall"],
            "field_gaps": dict(fields),
            "field_coverage": field_coverage,
            "specificity": [
                r["grounding"].get("specificity") for r in results if r.get("grounding")
            ],
        },
        "per_class_claim_outcomes": {k: dict(v) for k, v in sorted(outcomes.items())},
        "observed_class_mappings": [
            {
                "claimed": a,
                "reference": b,
                "claims": n,
                "interpretation": "Parent mapping may earn partial credit; not evidence of a visual confusion",
            }
            for (a, b), n in sorted(confusions.items())
        ],
        "ontology_confusers": {
            obj: ont.classes[obj].confusers if obj in ont.classes else [] for obj in classes
        },
        "strata": report["dataset"]["strata"],
        "sampling": report["dataset"]["sample"],
        "fidelity": {
            "kind": "model_opinion",
            "measured_captions": sum(r.get("fidelity") is not None for r in results),
            "mean": statistics.mean([r["fidelity"]["score"] for r in results if r.get("fidelity")])
            if any(r.get("fidelity") for r in results)
            else None,
        },
        "cost": {
            "gpu_measured_captions": sum(
                (r.get("cost") or {}).get("gpu_status") == "observed" for r in results
            ),
            "note": "GPU use cannot be inferred from hosted-model latency or tokens",
        },
        "label_preparation": {
            "measured_captions": sum(
                (r.get("label_preparation") or {}).get("reference_preparation", {}).get("value")
                is not None
                for r in results
            ),
            "note": "Legacy preparation includes imagery and reference queries; not reference-only labour",
        },
        "retrieval": report.get("retrieval"),
        "retrieval_unavailable": report.get("retrieval_unavailable"),
        "limitations": report.get("limitations", [])
        + report["dataset"]["limitations"]
        + [
            "Caption-level object classes, regions and strata overlap; do not sum them as independent samples",
            "Missing metadata is unknown. Observed unique counts exclude missing identities",
            "Ontology confusers are review candidates, not measured confusions or verified absence",
            "Correctness is conditional on checkable assertions; coverage is reference type recall",
            "No evidence of downstream training improvement or caption-generation accuracy without evaluated model outputs",
        ],
    }


def _display(value):
    if value is None:
        return "Unavailable"
    if isinstance(value, float):
        return f"{value:.3f}"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def render(card: dict) -> str:
    def table(data):
        return (
            "<table><tbody>"
            + "".join(
                f'<tr><th scope="row">{escape(k.replace("_", " "))}</th>'
                f"<td>{table(v) if isinstance(v, dict) else escape(_display(v))}</td></tr>"
                for k, v in data.items()
            )
            + "</tbody></table>"
        )

    title = card["dataset"].get("name") or "Imported caption set"
    html = [
        "<!doctype html><html lang='en'><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width, initial-scale=1'>",
        f"<title>Dataset card — {escape(title)}</title><style>{STYLE}</style><body>",
        (
            f"<header><h1>Dataset card: {escape(title)}</h1><p>Descriptive evidence, five separate criteria. "
            'Unknown evidence stays unavailable.</p><a href="output-score.html">Output Score report</a> · '
            '<a href="dataset-card.json">Card JSON</a></header><main>'
        ),
    ]
    if card.get("evaluation_notice"):
        html.append(f"<p role='note'><strong>{escape(card['evaluation_notice'])}</strong></p>")
    for heading, data in [
        ("Dataset provenance", card["dataset"]),
        ("Counts", card["counts"]),
        ("Duplication", card["duplication"]),
        ("Vocabulary", card["vocabulary"]),
        ("Caption length (words)", card["length_words"]),
        ("Claimed classes (overlapping)", card["class_caption_counts"]),
        ("Regions", card["regions"]),
        ("Terrain", card["terrain"]),
        (
            "Grounding — correctness and coverage separately",
            {
                k: card["grounding"][k]
                for k in (
                    "correctness",
                    "coverage",
                    "binary_caption_evidence",
                    "field_gaps",
                    "field_coverage",
                )
            },
        ),
        ("Per-class claim outcomes (claim denominators)", card["per_class_claim_outcomes"]),
        ("Ontology confusers — candidates for review", card["ontology_confusers"]),
        ("Fidelity (model opinion)", card["fidelity"]),
        ("GPU cost", card["cost"]),
        ("Label preparation", card["label_preparation"]),
    ]:
        html.append(f"<section><h2>{escape(heading)}</h2>{table(data)}</section>")
    html.append(
        "<h2>Retrieval</h2><p>"
        + escape(
            "Recorded measurement available; see evidence below"
            if card["retrieval"]
            else card["retrieval_unavailable"] or "Unavailable"
        )
        + "</p>"
    )
    html.append(
        "<h2>Limits and interpretation</h2><ul>"
        + "".join(f"<li>{escape(s)}</li>" for s in card["limitations"])
        + "</ul>"
    )
    html.append(
        "<details><summary>Strata, specificity, sampling and complete evidence</summary><pre>"
        + escape(json.dumps(card, indent=2, ensure_ascii=False))
        + "</pre></details></main></body></html>"
    )
    return "\n".join(html)


def write(report: dict, target: Path):
    card = redact(build(report))
    (target / "dataset-card.json").write_text(json.dumps(card, indent=2, allow_nan=False) + "\n")
    (target / "dataset-card.html").write_text(render(card))
    return card
