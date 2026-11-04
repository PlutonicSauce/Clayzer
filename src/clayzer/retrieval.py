"""Retrieval: can a text query alone find the right Caption? (CAP-09)

Captions and queries are embedded with an off-the-shelf text model. A Caption is relevant to a
query when its Case's Reference Labels contain the query's object, so the Answer Key defines
the right answers. Only queries with at least one relevant Caption are scored.

Each query is scored twice: as written, and expanded with its class's synonyms from the
ontology ("find solar farms" also as "PV plant", "solar park", ...), a Caption ranked by its
best match among them (decided 2026-11-04). The gap shows whether Captions are findable only
by the words the fixed queries use, or however people phrase things.
"""

import json
import math

from clayzer import ontology

# Each query and the class whose Chips are its right answers, from the ontology's `queries`.
QUERIES = ontology.load().queries()


def expansions(query: str) -> list[str]:
    """The query, then its class's synonyms: every phrasing the expanded query matches."""
    return [query, *ontology.load().classes[QUERIES[query]].synonyms]


def embed(client, model: str, text: str) -> list[float]:
    body = json.dumps({"inputText": text, "normalize": True})
    return json.loads(client.invoke_model(modelId=model, body=body)["body"].read())["embedding"]


def _cos(a, b) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    return dot / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)) or 1)


def retrieval(client, model: str, docs: list[dict], k: int = 1) -> dict:
    """docs: [{"case_id", "text", "objects": set of labelled object types}]. The scores for the
    queries as written, with the same scores under `expanded` for the synonym-expanded ones."""
    vectors = {d["case_id"]: embed(client, model, d["text"]) for d in docs}
    cache: dict[str, list[float]] = {}

    def vec(text: str) -> list[float]:
        if text not in cache:
            cache[text] = embed(client, model, text)
        return cache[text]

    plain = _score(docs, vectors, {q: [q] for q in QUERIES}, vec, k)
    expanded = _score(docs, vectors, {q: expansions(q) for q in QUERIES}, vec, k)
    return {**plain, "expanded": expanded}


def _score(docs, vectors, phrasings: dict[str, list[str]], vec, k: int) -> dict:
    """Rank the Captions for each query by their best match among its phrasings."""
    per_query = []
    for query, texts in phrasings.items():
        relevant = {d["case_id"] for d in docs if QUERIES[query] in d["objects"]}
        if not relevant:
            continue
        qvs = [vec(t) for t in texts]

        def best(d, qvs=qvs):
            return max(_cos(qv, vectors[d["case_id"]]) for qv in qvs)

        ranked = sorted(docs, key=best, reverse=True)
        ids = [d["case_id"] for d in ranked]
        first = next(i for i, cid in enumerate(ids) if cid in relevant)
        per_query.append({
            "query": query,
            "relevant": sorted(relevant),
            "ranked": ids,
            "reciprocal_rank": 1 / (first + 1),
            f"recall@{k}": len(relevant & set(ids[:k])) / len(relevant),
        })  # fmt: skip
    n = len(per_query)
    return {
        "mrr": sum(q["reciprocal_rank"] for q in per_query) / n if n else None,
        f"recall@{k}": sum(q[f"recall@{k}"] for q in per_query) / n if n else None,
        "queries": per_query,
    }
