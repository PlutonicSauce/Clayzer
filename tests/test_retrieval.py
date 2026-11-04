"""Retrieval with and without synonym expansion (CAP-09, CAP-06): a Caption that says "PV plant"
is missed by "find solar farms" as written and found once the query is expanded."""

import io
import json

from test_loop import env, run  # noqa: F401

from clayzer.retrieval import QUERIES, expansions, retrieval

WORDS = ("solar", "pv", "plant", "wind", "turbine", "farm")


class BagOfWords:
    """Embeddings that count which of WORDS a text contains; `calls` records every text."""

    def __init__(self):
        self.calls = []

    def invoke_model(self, modelId, body):
        text = json.loads(body)["inputText"].lower()
        self.calls.append(text)
        vec = [float(w in text) for w in WORDS]
        return {"body": io.BytesIO(json.dumps({"embedding": vec}).encode())}


DOCS = [
    {"case_id": "solar", "text": "A PV plant in the desert.", "objects": {"solar_array"}},
    {"case_id": "wind", "text": "A wind farm: three turbines.", "objects": {"wind_turbine"}},
]


def test_expansions_come_from_the_ontology_synonyms():
    assert expansions("find solar farms")[0] == "find solar farms"
    assert "PV plant" in expansions("find solar farms")
    assert all(expansions(q)[0] == q for q in QUERIES)


def test_a_synonym_finds_the_caption_the_fixed_query_misses():
    client = BagOfWords()
    r = retrieval(client, "embed", DOCS)
    plain = {q["query"]: q for q in r["queries"]}
    expanded = {q["query"]: q for q in r["expanded"]["queries"]}
    # "find solar farms" shares only "farm" with the wind Caption, nothing with "PV plant".
    assert plain["find solar farms"]["ranked"][0] == "wind"
    assert plain["find solar farms"]["recall@1"] == 0.0
    assert expanded["find solar farms"]["ranked"][0] == "solar"
    assert expanded["find solar farms"]["recall@1"] == 1.0
    assert r["expanded"]["recall@1"] > r["recall@1"]
    # Only queries with a relevant Caption are embedded, and each phrasing once.
    assert len(client.calls) == len(set(client.calls))
    assert "find railroads" not in client.calls


def test_batches_report_recall_with_and_without_expansion(env):  # noqa: F811
    b = run(env, repeats=1)
    s = b["summary"]["batch"]
    assert s["retrieval_recall_at_1_expanded"]["mean"] is not None
    assert "expanded" in b["retrieval"][0]
    store = env[0]
    bid = b["config"].batch_id
    assert "With synonyms" in store.get(f"batches/{bid}/report.html").decode()
    assert "expanded by synonyms" in store.get(f"batches/{bid}/report.md").decode()
