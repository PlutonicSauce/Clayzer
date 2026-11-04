"""Scoring an imported Caption Set (CAP-20): the same criteria as our Captions, with no Harness
run. Rows without a location aren't grounded and rows without an image aren't judged, and the
Batch says so."""

import pytest
from test_importer import BOX, keys, row  # noqa: F401
from test_loop import FakeBedrock, env  # noqa: F401

from clayzer import batch as batches
from clayzer import cli
from clayzer.cases import save_case
from clayzer.importer import import_key, import_rows
from clayzer.trace import loads, trace_key

CLAIMS = {"objects": [{"id": "o1", "object": "solar_array", "count": 1, "position": "centre"}],
          "relations": [], "uncertain": []}  # fmt: skip


class ExtractingBedrock(FakeBedrock):
    """Also answers the Claim extractor (text only, no image) with one solar Claim."""

    def converse(self, modelId, messages, toolConfig=None, inferenceConfig=None, system=None):
        if toolConfig and toolConfig["tools"][0]["toolSpec"]["name"] == "submit_claims":
            self.calls += 1
            block = {"toolUse": {"toolUseId": "t", "name": "submit_claims", "input": CLAIMS}}
            return {"output": {"message": {"content": [block]}}, "usage": {"totalTokens": 40},
                    "stopReason": "tool_use", "ResponseMetadata": {"HTTPStatusCode": 200}}  # fmt: skip
        return super().converse(modelId, messages, toolConfig, inferenceConfig, system)


@pytest.fixture
def imported(env, keys):  # noqa: F811
    """Three imported captions: located with Claims and an image; located, text only, no image;
    and unlocated with no image, like RSICD."""
    store, settings, fake = env
    fake["client"] = ExtractingBedrock()
    rows = [
        row("given", "k1", claims=CLAIMS, image_uri="chips/c-solar.png", generator="pipe v1"),
        row("text-only", "k1"),
        row("rsicd-like", "r1", geometry=None, datetime=None, gsd_m=None, sensor="rsicd"),
    ]
    cases = import_rows(rows, "demo", progress=lambda *_: None).cases
    for c in cases:
        save_case(store, import_key("demo"), c)
    return store, settings, fake, cases


def by_case(b):
    return {r["case_id"].removeprefix("import-demo-"): r for r in b["results"]}


def test_an_imported_set_is_scored_on_every_criterion_that_applies(imported):
    store, settings, fake, cases = imported
    bid = batches.create(cases, settings, store, 1, "demo", "import-demo", source="imported")
    batches.resume(bid, settings, store, progress=lambda *_: None)
    b = batches.load(store, bid)
    r = by_case(b)

    assert b["config"].source == "imported" and b["config"].extract_model == settings.judge_model
    assert r["given"]["grounding"]["correctness"] == 1.0
    assert r["given"]["fidelity"]["score"] == pytest.approx(0.8)
    assert r["given"]["imported"] == {"claims": "source", "located": True, "image": True}
    # Text only: Claims extracted, grounded, but no image for the Judge.
    assert r["text-only"]["imported"] == {"claims": "extracted", "located": True, "image": False}
    assert r["text-only"]["grounding"]["correctness"] == 1.0
    assert r["text-only"]["fidelity"] is None
    # No location: not grounded (not scored 0), and no image either.
    assert r["rsicd-like"]["grounding"]["correctness"] is None
    assert r["rsicd-like"]["grounding"]["not_grounded"] == "no location"
    assert r["rsicd-like"]["fidelity"] is None
    assert all(x["workflow"] is None for x in b["results"])
    assert fake["client"].narrations == 0  # no Harness, nothing to narrate

    s = b["summary"]["batch"]
    assert s["imported"] == {"captions": 3, "not_located": 1, "no_image": 2,
                             "claims_extracted": 2}  # fmt: skip
    assert s["correctness"] == 1.0 and s["fidelity"] == pytest.approx(0.8)
    assert s["retrieval_mrr"]["mean"] is not None

    # The extraction is recorded as the evaluation's work, not a Harness's.
    _, steps = loads(store.get(trace_key(bid, "import-demo-text-only", 1)))
    assert [(s.name, s.attributes.get("role")) for s in steps] == [("extract_claims", "scoring")]

    report = store.get(f"batches/{bid}/report.md").decode()
    assert "1 have no location, so aren't grounded; 2 have no image" in report
    assert "Both until Clay says which it means" in report  # label-prep: both readings
    assert "judged for fidelity" in store.get(f"batches/{bid}/report.html").decode()

    # Rescoring keeps the unlocated caption ungrounded.
    summary = batches.rescore(bid, store)
    assert summary["cases"]["import-demo-rsicd-like"]["correctness"]["mean"] is None
    assert summary["batch"]["correctness"] == 1.0


def test_score_import_from_the_cli(imported, monkeypatch, capsys):
    _, settings, _, _ = imported
    monkeypatch.setattr(cli, "load_env", lambda: None)
    monkeypatch.setenv("CLAYZER_DATA_DIR", str(settings.data_dir))
    monkeypatch.setenv("CLAYZER_BATCHES_DIR", str(settings.batches_dir))
    monkeypatch.setenv("CLAYZER_JUDGE_MODEL", "judge")
    monkeypatch.delenv("CLAYZER_STORE", raising=False)
    assert cli.main(["score-import", "demo", "--only", "import-demo-given"]) == 0
    out = capsys.readouterr().out
    assert "scoring 1 imported captions" in out and "0 have no location" in out
    assert cli.main(["score-import", "missing"]) == 2
