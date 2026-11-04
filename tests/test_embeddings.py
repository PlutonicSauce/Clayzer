"""Per-Chip embeddings: the two sources, and attaching them to Cases (ADR-0010)."""

import base64
import io
import json

from clayzer import embeddings as emb


class FakeTitan:
    """Bedrock Titan multimodal: echoes the input image's length so tests can tell calls apart."""

    def __init__(self):
        self.seen = []

    def invoke_model(self, modelId, body):
        payload = json.loads(body)
        self.seen.append(payload)
        img = base64.b64decode(payload["inputImage"])
        return {"body": io.BytesIO(json.dumps({"embedding": [float(len(img)), 1.0]}).encode())}


def _case(cid, obj, embedding=None):
    chip = {"id": cid, "uri": f"chips/{cid}.png"}
    if embedding is not None:
        chip["embedding"] = embedding
    return {"id": f"fixed-{cid}", "chips": [chip],
            "reference_labels": [{"object": obj, "count": 1, "position": "centre"}]}  # fmt: skip


def test_precomputed_looks_up_by_chip_id():
    source = emb.PrecomputedEmbedding({"c-1": [0.1, 0.2]})
    assert source.embed_chip({"id": "c-1"}, None) == [0.1, 0.2]
    assert source.embed_chip({"id": "missing"}, None) is None


def test_titan_embeds_the_png_and_calls_once_per_chip():
    source = emb.TitanImageEmbedding(FakeTitan())
    vec = source.embed_chip({"id": "c-1"}, b"PNGDATA")
    assert vec == [7.0, 1.0]  # len(b"PNGDATA") == 7
    assert source.embed_chip({"id": "c-2"}, None) is None  # no image → no call


def test_attach_to_cases_sets_embedding_and_counts():
    cases = [_case("c-1", "solar_array"), _case("c-2", "water")]
    source = emb.PrecomputedEmbedding({"c-1": [1.0, 0.0], "c-2": [0.0, 1.0]})
    n = emb.attach_to_cases(cases, source)
    assert n == 2
    assert cases[0]["chips"][0]["embedding"] == [1.0, 0.0]


def test_pairs_from_cases_uses_reference_labels_as_class_membership():
    cases = [_case("c-1", "solar_array", [1.0, 0.0]), _case("c-2", "water", [0.0, 1.0])]
    pairs = emb.pairs_from_cases(cases)
    assert ("solar_array", [1.0, 0.0]) in pairs
    assert ("water", [0.0, 1.0]) in pairs
    # A Case with no embedding contributes nothing.
    assert emb.pairs_from_cases([_case("c-3", "field")]) == []


def test_load_precomputed_reads_jsonl(tmp_path):
    p = tmp_path / "e.jsonl"
    p.write_text('{"chip_id": "c-1", "embedding": [0.5, 0.5]}\n')
    source = emb.load_precomputed(p)
    assert source.embed_chip({"id": "c-1"}, None) == [0.5, 0.5]
