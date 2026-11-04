"""Retrieval: can a text query alone find the right Caption? (CAP-09)

Captions and queries are embedded with an off-the-shelf text model. A Caption is relevant to a
query when its Case's Reference Labels contain the query's object, so the Answer Key defines
the right answers. Only queries with at least one relevant Caption are scored.
"""

import json
import math

QUERIES = {
    "find solar farms": "solar_array",
    "find wind turbines": "wind_turbine",
    "find railroads": "railroad",
    "find buildings": "building",
    "find greenhouses": "greenhouse",
    "find parking lots": "parking_lot",
    "find farmland": "field",
    "find water": "water",
}


def embed(client, model: str, text: str) -> list[float]:
    body = json.dumps({"inputText": text, "normalize": True})
    return json.loads(client.invoke_model(modelId=model, body=body)["body"].read())["embedding"]


def _cos(a, b) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    return dot / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)) or 1)


def retrieval(client, model: str, docs: list[dict], k: int = 1) -> dict:
    """docs: [{"case_id", "text", "objects": set of labelled object types}]."""
    vectors = {d["case_id"]: embed(client, model, d["text"]) for d in docs}
    per_query = []
    for query, target in QUERIES.items():
        relevant = {d["case_id"] for d in docs if target in d["objects"]}
        if not relevant:
            continue
        qv = embed(client, model, query)
        ranked = sorted(docs, key=lambda d: _cos(qv, vectors[d["case_id"]]), reverse=True)
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
