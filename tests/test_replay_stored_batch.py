"""Recorded-Trace replay (REQ-09): a Batch rescored and reported from its stored files alone, with
no model, MCP server, AWS credentials, or network, and the Judge's saved verdicts reused."""

import json
import socket

import pytest
from test_loop import SOLAR, env, run  # noqa: F401

from clayzer import batch as batches
from clayzer import cli
from clayzer.run_report import run_keys

AWS_ENV = ("AWS_PROFILE", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN",
           "AWS_BEARER_TOKEN_BEDROCK", "AWS_REGION", "AWS_DEFAULT_REGION")  # fmt: skip


@pytest.fixture
def offline(monkeypatch, tmp_path):
    """No network, no AWS credentials, and no Bedrock client: any attempt fails the test."""

    def refuse(*a, **k):
        raise AssertionError("replay tried to reach the network")

    for name in ("connect", "connect_ex"):
        monkeypatch.setattr(socket.socket, name, refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    for key in AWS_ENV:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("AWS_CONFIG_FILE", str(tmp_path / "no-aws-config"))
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(tmp_path / "no-aws-credentials"))
    monkeypatch.setattr(batches, "bedrock", refuse)


def test_a_batch_rescores_and_reports_with_the_network_off(env, monkeypatch, offline_later):  # noqa: F811
    store, settings, _ = env
    b = run(env, repeats=2)
    bid = b["config"].batch_id
    judged = {(r["case_id"], r["repeat"]): r["fidelity"] for r in b["results"]}
    retrieval = b["retrieval"]

    # Break the stored grounding and drop the reports, so replay has to rebuild both.
    for r in b["results"]:
        r["grounding"] = {**r["grounding"], "correctness": 0.0}
    store.put(f"batches/{bid}/results.jsonl",
              "".join(json.dumps(r) + "\n" for r in b["results"]).encode())  # fmt: skip
    html, rec = run_keys(bid, SOLAR["id"], 1)
    for key in (f"batches/{bid}/report.html", f"batches/{bid}/report.md", html, rec):
        store.delete(key)

    offline_later()
    monkeypatch.setattr(cli, "load_env", lambda: None)  # keep a developer's .env out of it
    monkeypatch.setenv("CLAYZER_DATA_DIR", str(settings.data_dir))
    monkeypatch.setenv("CLAYZER_BATCHES_DIR", str(settings.batches_dir))
    monkeypatch.delenv("CLAYZER_STORE", raising=False)
    assert cli.main(["rescore", bid]) == 0

    after = batches.load(store, bid)
    assert after["summary"]["batch"]["correctness"] == 1.0  # grounding recomputed
    assert {(r["case_id"], r["repeat"]): r["fidelity"] for r in after["results"]} == judged
    assert after["retrieval"] == retrieval
    for key in (f"batches/{bid}/report.html", f"batches/{bid}/report.md", html, rec):
        assert store.exists(key)
    fid = judged[(SOLAR["id"], 1)]
    assert {k: json.loads(store.get(rec))["scores"]["fidelity"][k] for k in ("score", "issues")} == {
        "score": fid["score"], "issues": fid.get("issues", [])}  # fmt: skip


@pytest.fixture
def offline_later(request):
    """Turn `offline` on partway through a test, after the Batch has been run."""
    return lambda: request.getfixturevalue("offline")


def test_replay_cli_retains_updated_case_batch_form(env, monkeypatch, offline_later):  # noqa: F811
    store, settings, _ = env
    original = run(env, repeats=1)
    bid = original["config"].batch_id
    before = store.get(f"batches/{bid}/results.jsonl")
    offline_later()
    monkeypatch.setattr(cli, "load_env", lambda: None)
    monkeypatch.setenv("CLAYZER_DATA_DIR", str(settings.data_dir))
    monkeypatch.setenv("CLAYZER_BATCHES_DIR", str(settings.batches_dir))
    monkeypatch.delenv("CLAYZER_STORE", raising=False)
    assert (
        cli.main(
            [
                "replay",
                bid,
                "--cases",
                "cases/caption-dev.jsonl",
                "--label",
                "cli-fixed",
                "--no-reports",
            ]
        )
        == 0
    )
    ids = [x for x in batches.list_batches(store) if x.endswith("-cli-fixed")]
    assert len(ids) == 1
    assert batches.load(store, ids[0])["config"].replayed_from == bid
    assert store.get(f"batches/{bid}/results.jsonl") == before
