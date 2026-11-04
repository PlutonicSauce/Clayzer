"""A Bedrock error on the caption call: the captioner's fault scores 0, the service's is retried."""

from botocore.exceptions import ClientError
from test_loop import SOLAR, FakeBedrock

from clayzer import batch as batches
from clayzer.config import Settings
from clayzer.gate import accept_baseline
from clayzer.store import LocalStore


def error(code: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": "x"},
                        "ResponseMetadata": {"HTTPStatusCode": 400}}, "Converse")  # fmt: skip


def run(tmp_path, monkeypatch, code):
    store = LocalStore(tmp_path / "data", tmp_path / "batches")
    store.put(SOLAR["chips"][0]["uri"], SOLAR["chips"][0]["id"].encode())
    settings = Settings(
        caption_model="cap", judge_model="judge", embed_model="embed",
        bedrock_endpoint_url=None, data_dir=tmp_path / "data",
        batches_dir=tmp_path / "batches", baselines_dir=tmp_path / "baselines",
        store_url=None, naip_source="pc",
    )  # fmt: skip
    monkeypatch.setattr(batches, "bedrock", lambda s: FakeBedrock(fail={1: error(code)}))
    bid = batches.start(
        [SOLAR], settings, store, 1, "", "dev", narrate=False, progress=lambda _: None
    )
    return batches.load(store, bid), settings


def test_a_malformed_model_answer_is_a_harness_fault(tmp_path, monkeypatch):
    b, settings = run(tmp_path, monkeypatch, "ModelErrorException")
    (r,) = b["results"]
    assert r["status"] == "harness_fault" and "ModelErrorException" in r["error"]
    assert r["grounding"]["correctness"] == 0.0 and r["fidelity"]["score"] == 0.0
    assert b["summary"]["batch"]["runs"]["harness_faults"] == 1
    accept_baseline(b, settings.baselines_dir)  # complete: no Sandbox Failure to resume


def test_a_throttled_call_is_still_a_sandbox_failure(tmp_path, monkeypatch):
    b, _ = run(tmp_path, monkeypatch, "ThrottlingException")
    (r,) = b["results"]
    assert r["status"] == "sandbox_failure"
