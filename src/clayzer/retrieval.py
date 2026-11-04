"""Text-only retrieval, frozen relevance and queries, reusable offline ranking recordings.

Recall@K is the fraction of relevant documents retrieved, NOT hit rate. MRR uses the first
relevant rank. Missing reference records never define known negative documents.
"""

import hashlib
import json
import math

from clayzer.ontology import load

QUERIES = load().queries()
VERSION = "text-retrieval-2"


def _sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def freeze_queries(docs: list[dict], queries: dict | None = None) -> list[dict]:
    """Freeze query text and positive relevance; official sets may supply explicit negatives."""
    return [
        {
            "id": str(i),
            "query": q,
            "target": target,
            "relevant": sorted(d["case_id"] for d in docs if target in d.get("objects", [])),
            "relevance_complete": False,
        }
        for i, (q, target) in enumerate((QUERIES if queries is None else queries).items())
    ]


def synonym_queries(specs: list[dict]) -> list[dict]:
    ontology = load()
    return [
        {**q, "query": q["query"] + "; " + "; ".join(ontology.classes[q["target"]].synonyms)}
        if q.get("target") in ontology.classes
        else dict(q)
        for q in specs
    ]


def embed(client, model: str, text: str) -> list[float]:
    body = json.dumps({"inputText": text, "normalize": True})
    return json.loads(client.invoke_model(modelId=model, body=body)["body"].read())["embedding"]


def _vector(v):
    if (
        not isinstance(v, list)
        or not v
        or any(
            isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x)
            for x in v
        )
        or not any(v)
    ):
        raise ValueError("Embedding must be a finite, nonzero numeric vector")
    return v


def _cos(a, b) -> float:
    _vector(a)
    _vector(b)
    if len(a) != len(b):
        raise ValueError("Embedding dimensions differ")
    return sum(x * y for x, y in zip(a, b, strict=True)) / (
        math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    )


def rank_recording(recording: dict, k: int = 1) -> dict:
    """Recalculate metrics from saved text embeddings without a client or network."""
    if isinstance(k, bool) or not isinstance(k, int) or k < 1:
        raise ValueError("K must be a positive integer")
    docs, specs = recording["documents"], recording["queries"]
    ids = [d["case_id"] for d in docs]
    if len(ids) != len(set(ids)) or len({q["id"] for q in specs}) != len(specs):
        raise ValueError("Duplicate document or query id")
    warnings, rows, skipped = [], [], []
    if len(ids) < 10:
        warnings.append("tiny corpus (<10 documents); ranking is not evidence of generalization")
    if k >= len(ids):
        warnings.append("K covers the entire corpus; Recall@K is trivial")
    for q in specs:
        relevant = set(q["relevant"])
        absent = relevant - set(ids)
        if absent:
            skipped.append(
                {"id": q["id"], "reason": "relevant documents missing", "missing": sorted(absent)}
            )
            continue
        if not relevant:
            skipped.append({"id": q["id"], "reason": "no established relevant documents"})
            continue
        if not q.get("relevance_complete", False):
            warnings.append("incomplete relevance evidence; unlabelled documents are unjudged")
        qv = recording["query_vectors"][q["id"]]
        ranked = sorted(ids, key=lambda cid: (-_cos(qv, recording["document_vectors"][cid]), cid))
        first = next(i for i, cid in enumerate(ranked, 1) if cid in relevant)
        rows.append(
            {
                **q,
                "ranked": ranked,
                "reciprocal_rank": 1 / first,
                f"recall@{k}": len(relevant & set(ranked[:k])) / len(relevant),
                f"hit@{k}": float(bool(relevant & set(ranked[:k]))),
                "relevant_count": len(relevant),
            }
        )
    n = len(rows)
    return {
        "version": VERSION,
        "mrr": sum(q["reciprocal_rank"] for q in rows) / n if n else None,
        f"recall@{k}": sum(q[f"recall@{k}"] for q in rows) / n if n else None,
        f"hit@{k}": sum(q[f"hit@{k}"] for q in rows) / n if n else None,
        "queries": rows,
        "skipped_queries": skipped,
        "query_count": n,
        "corpus_size": len(ids),
        "warnings": sorted(set(warnings)),
        "queries_sha256": _sha(specs),
        "corpus_sha256": _sha(docs),
    }


def retrieval(
    client,
    model: str,
    docs: list[dict],
    k: int = 1,
    queries: list[dict] | None = None,
    compare_synonyms: bool = False,
) -> dict:
    specs = freeze_queries(docs) if queries is None else queries
    # Canonical serializable text corpus: no imagery or labels are passed to the embedder.
    documents = [{"case_id": d["case_id"], "text": d["text"]} for d in docs]
    vectors = {d["case_id"]: embed(client, model, d["text"]) for d in documents}

    def evaluate(qs):
        recording = {
            "version": VERSION,
            "model": model,
            "documents": documents,
            "queries": qs,
            "document_vectors": vectors,
            "query_vectors": {
                q["id"]: embed(client, model, q["query"]) for q in qs if q["relevant"]
            },
        }
        try:
            ranked = rank_recording(recording, k)
        except ValueError as exc:
            ranked = {
                "version": VERSION,
                "mrr": None,
                f"recall@{k}": None,
                f"hit@{k}": None,
                "queries": [],
                "query_count": 0,
                "warnings": [f"Retrieval unavailable: {exc}"],
            }
        return {**ranked, "recording": recording}

    result = evaluate(specs)
    if compare_synonyms:
        result["synonym_expanded"] = evaluate(synonym_queries(specs))
    return result
