"""Evaluate normalized JSONL captions without running a Harness or fetching labels/imagery.

The Case importer is team-owned: independent references may be supplied inline or by case id.
Missing references, images or extraction are explicitly unavailable. Providers are opt-in API
arguments; the CLI runs fully offline, using optional saved embedding recordings.
"""

import hashlib
import json
from html import escape
from pathlib import Path

from botocore.exceptions import BotoCoreError, ClientError

from clayzer import extraction
from clayzer.dataset_score import dataset_report
from clayzer.grid import GRID, RELATIONS
from clayzer.grounding import COMPARABILITY_NOTE, SCORE_SCOPE_NOTE, specificity_note
from clayzer.ontology import load
from clayzer.output_score import VERSION, score_caption
from clayzer.provenance import ontology_version
from clayzer.retrieval import freeze_queries, rank_recording, retrieval


def normalize(row: dict) -> dict:
    cid = row.get("id") or row.get("caption_id") or row.get("case_id")
    text = row.get("text", row.get("caption"))
    if not isinstance(cid, str) or not cid or not isinstance(text, str) or not text.strip():
        raise ValueError("Each imported caption requires an id and nonempty text/caption")
    claims = row.get("claims")
    if claims is None and "objects" in row:
        claims = {k: row.get(k, []) for k in ("objects", "relations", "uncertain")}
    cap = {
        "text": text,
        "objects": [],
        "relations": [],
        "uncertain": [],
        "claims_status": "unavailable",
    }
    if claims is not None:
        if not isinstance(claims, dict) or any(
            not isinstance(claims.get(k, []), list) for k in ("objects", "relations", "uncertain")
        ):
            raise ValueError("Claims require objects, relations and uncertain arrays")
        if any(not isinstance(o, dict) for o in claims.get("objects", [])):
            raise ValueError("Malformed structured Claim")
        cap.update({k: claims.get(k, []) for k in ("objects", "relations", "uncertain")})
        cap["text"] = text
        ids = [o.get("id") for o in cap["objects"]]
        if any(not isinstance(i, str) or not i for i in ids) or len(ids) != len(set(ids)):
            raise ValueError("Claim ids must be unique strings")
        for o in cap["objects"]:
            count = o.get("count")
            if (
                o.get("object") not in load().claimable()
                or (
                    count is not None
                    and (isinstance(count, bool) or not isinstance(count, int) or count < 1)
                )
                or (o.get("position") is not None and o["position"] not in GRID)
            ):
                raise ValueError("Invalid structured Claim")
        if any(not isinstance(s, str) for s in cap["uncertain"]):
            raise ValueError("Uncertain must contain strings")
        for o in cap["objects"]:
            cls = load().classes[o["object"]]
            if not isinstance(o.get("attributes", {}), dict) or any(
                v not in cls.attributes.get(k, []) for k, v in o.get("attributes", {}).items()
            ):
                raise ValueError("Invalid structured Claim attributes")
        for r in cap["relations"]:
            if not isinstance(r, dict):
                raise ValueError("Malformed structured relation")  # noqa: TRY004 -- validation contract
            if (
                r.get("subject") not in ids
                or r.get("object") not in ids
                or r.get("relation") not in RELATIONS
            ):
                raise ValueError("Invalid structured relation")
        cap["claims_status"] = "supplied; text alignment not independently validated"
    return {
        **row,
        "id": cid,
        "text": text,
        **{k: cap[k] for k in ("objects", "relations", "uncertain", "claims_status")},
    }


def evaluate(
    rows: list[dict],
    *,
    cases: dict | None = None,
    client=None,
    judge_model=None,
    extraction_model=None,
    embed_model=None,
    queries=None,
    recording=None,
    image_loader=None,
    extraction_tracer=None,
) -> dict:
    normalized = [normalize(r) for r in rows]
    if len({r["id"] for r in normalized}) != len(normalized):
        raise ValueError("Duplicate caption ids")
    results, docs, references = [], [], {}
    for row in normalized:
        case = (cases or {}).get(row.get("case_id", row["id"]), row)
        references[row["id"]] = case
        cap = row
        row.setdefault("reference_labels", case.get("reference_labels"))
        row.setdefault("region", case.get("region", "unknown"))
        row.setdefault("terrain", case.get("terrain", "unknown"))
        if row["claims_status"] == "unavailable" and extraction_model:
            if client is None:
                raise ValueError("Extraction requires an explicit provider")
            cap = extraction.extract(client, extraction_model, row["text"], extraction_tracer)
            row.update({k: cap[k] for k in ("objects", "relations", "uncertain", "claims_status")})
        png = image_loader(row["image_uri"]) if image_loader and row.get("image_uri") else None
        try:
            result = score_caption(
                cap,
                case,
                client=client,
                judge_model=judge_model,
                generator=row.get("generator"),
                png=png,
                provider=row.get("provider", "unknown"),
                seconds=row.get("seconds_to_caption"),
                tokens=row.get("caption_tokens"),
                observed_cost=row.get("cost"),
            )
        except (RuntimeError, OSError, BotoCoreError, ClientError) as exc:
            # A failed judge never becomes a zero score; retain deterministic criteria.
            result = score_caption(
                cap,
                case,
                provider=row.get("provider", "unknown"),
                seconds=row.get("seconds_to_caption"),
                tokens=row.get("caption_tokens"),
                observed_cost=row.get("cost"),
            )
            result["fidelity_unavailable"] = f"Judge failed: {type(exc).__name__}"
        if cap.get("extraction"):
            result["extraction"] = cap["extraction"]
        gsd = row.get("gsd_m")
        result["resolution_warnings"] = [
            o["object"]
            for o in cap["objects"]
            if isinstance(gsd, (int, float))
            and load().classes[o["object"]].min_visible_m is not None
            and load().classes[o["object"]].min_visible_m < 2 * gsd
        ]
        results.append({"id": row["id"], **result})
        docs.append(
            {
                "case_id": row["id"],
                "text": row["text"],
                "objects": [
                    lb["object"]
                    for lb in (case.get("reference_labels") or [])
                    if lb.get("count") != 0
                ],
            }
        )
    specs = freeze_queries(docs) if queries is None else queries
    retr = None
    if recording is not None:
        expected = [{"case_id": d["case_id"], "text": d["text"]} for d in docs]
        if recording["documents"] != expected or recording["queries"] != specs:
            raise ValueError("Recording does not match this frozen corpus and query set")
        retr = rank_recording(recording)
    elif client is not None and embed_model:
        retr = retrieval(client, embed_model, docs, queries=specs, compare_synonyms=True)
    return {
        "scorer_version": VERSION,
        "ontology": dict(zip(("version", "sha"), ontology_version(), strict=True)),
        "references": references,
        "references_sha256": hashlib.sha256(
            json.dumps(references, sort_keys=True).encode()
        ).hexdigest(),
        "mode": "imported_no_harness",
        "captions": normalized,
        "results": results,
        "retrieval": retr,
        "retrieval_unavailable": None
        if retr
        else "No embedding provider or matching recording supplied",
        "queries": specs,
        "dataset": dataset_report(normalized, results),
        "source_sha256": hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest(),
        "criteria": ["grounding", "fidelity", "retrieval", "cost", "label_preparation"],
        "limitations": [
            "Supplied structured Claims need text-alignment review; extracted Claims are model opinion",
            "Image/reference acquisition is the separate Case importer's responsibility",
            "No Workflow Score: no Harness was executed",
        ],
    }


def write_evaluation(report: dict, target: Path):
    """Escape all imported text; do not render untrusted Markdown or execute embedded HTML."""
    target.mkdir(parents=True, exist_ok=True)
    from clayzer.dataset_card import write as write_card
    from clayzer.report_safety import redact

    report = redact(report)
    write_card(report, target)
    content = json.dumps(report, indent=2, allow_nan=False)
    (target / "output-score.json").write_text(content + "\n")
    summaries = []
    for result in report["results"]:
        g = result.get("grounding")
        if g is None:
            continue
        summaries.append(
            f"<section><h2>Caption {escape(result['id'])}</h2>"
            f"<p>Claim correctness (conditional): {escape(str(g['correctness']))}; "
            f"reference type coverage: {escape(str(g['coverage']))}.</p>"
            f"<p role='note'><strong>{escape(specificity_note(g))}</strong></p></section>"
        )
    (target / "output-score.html").write_text(
        '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
        "<title>Imported caption Output Score</title><h1>Output Score — imported captions</h1>"
        '<p><a href="dataset-card.html">Open dataset card: duplication, vocabulary, class evidence and limits</a></p>'
        "<p>Five separate criteria. Fidelity is model opinion. Missing evidence is unavailable.</p>"
        f"<p role='note'><strong>{escape(SCORE_SCOPE_NOTE)}</strong></p>"
        f"<p role='note'>{escape(COMPARABILITY_NOTE)}</p>"
        + "".join(summaries)
        + '<pre style="white-space:pre-wrap;overflow-wrap:anywhere">'
        + escape(content)
        + "</pre></html>"
    )
