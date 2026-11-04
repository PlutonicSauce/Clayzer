"""Recorded-Trace replay (REQ-09): a Batch is rescored and its reports rebuilt with no model, no
MCP server, no credentials, and no network.

The fake Bedrock client from test_loop records a call count, so these tests can show that replay
asked it nothing, and the offline fixture makes any attempt to reach AWS or a socket fail.
"""

import json
import socket

import pytest
from test_loop import SOLAR, env, run  # noqa: F401

from clayzer import batch as batches
from clayzer.narrate import narrative_key
from clayzer.run_report import run_keys
from clayzer.summarize import summary_key
from clayzer.trace import dumps, loads, trace_key


def _no_network(*args, **kwargs):
    raise AssertionError("replay tried to use the network")


@pytest.fixture
def offline(monkeypatch, tmp_path):
    """A switch: call it to cut off the network and AWS credentials, and to make building an AWS
    client fail. A test records its Batch first, with the fake model, then goes offline."""

    def go_offline():
        for name in ("connect", "connect_ex"):
            monkeypatch.setattr(socket.socket, name, _no_network)
        monkeypatch.setattr(socket, "create_connection", _no_network)
        monkeypatch.setattr(socket, "getaddrinfo", _no_network)

        import boto3

        monkeypatch.setattr(boto3, "client", _no_network)
        monkeypatch.setattr(boto3, "Session", _no_network)
        monkeypatch.setattr(batches, "bedrock", _no_network)
        for var in (
            "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "AWS_PROFILE",
            "AWS_BEARER_TOKEN_BEDROCK", "AWS_REGION", "AWS_DEFAULT_REGION", "CLAYZER_STORE",
        ):  # fmt: skip
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(tmp_path / "no-credentials"))
        monkeypatch.setenv("AWS_CONFIG_FILE", str(tmp_path / "no-config"))
        monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")

    return go_offline


def test_the_offline_switch_really_blocks_the_network(offline):
    offline()
    with pytest.raises(AssertionError, match="network"):
        socket.create_connection(("example.com", 443))
    with pytest.raises(AssertionError, match="network"):
        socket.socket().connect(("127.0.0.1", 9))


def _damage(store, bid, b):
    """What a Batch looks like when only its recorded files survive: no summaries, no reports,
    and one Run whose Judge verdict is gone from the results."""
    for r in b["results"]:
        store.delete(summary_key(bid, r["case_id"], r["repeat"]))
        for key in run_keys(bid, r["case_id"], r["repeat"]):
            store.delete(key)
    for name in ("report.md", "report.html", "summary.json"):
        store.delete(f"batches/{bid}/{name}")
    lost = b["results"][0]
    lost["fidelity"] = None
    store.put(
        f"batches/{bid}/results.jsonl",
        "".join(json.dumps(r) + "\n" for r in b["results"]).encode(),
    )
    return lost


def test_a_batch_is_rescored_and_reported_with_the_network_off(env, offline):  # noqa: F811
    store, _, fake = env
    # Recording the Batch is the live part, so it uses the fake model before it's cut off.
    b = run(env, "recorded", repeats=2)
    bid = b["config"].batch_id
    before = b["summary"]["batch"]
    asked = (fake["client"].calls, fake["client"].narrations)
    lost = _damage(store, bid, b)
    offline()

    summary = batches.rescore(bid, store)

    # Nothing was asked of any model: Judge verdicts were reused, not requested again.
    assert (fake["client"].calls, fake["client"].narrations) == asked
    verdicts = summary["replay"]["judge_verdicts"]
    assert verdicts == {"reused": 3, "recovered": 1, "missing": 0}
    # The scores are the ones recorded, including the verdict recovered from the Trace.
    for metric in ("correctness", "coverage", "fidelity", "workflow"):
        assert summary["batch"][metric] == pytest.approx(before[metric]), metric
    assert summary["batch"]["retrieval_mrr"] == before["retrieval_mrr"]
    recovered = next(
        r for r in batches.load(store, bid)["results"]
        if (r["case_id"], r["repeat"]) == (lost["case_id"], lost["repeat"])
    )  # fmt: skip
    assert recovered["fidelity"]["score"] == pytest.approx(0.8)
    # Every report is back: the Batch's, and each Run's with its summary.
    assert summary["replay"]["summaries_rebuilt"] == 4
    assert store.exists(f"batches/{bid}/report.html") and store.exists(f"batches/{bid}/report.md")
    for r in b["results"]:
        assert store.exists(summary_key(bid, r["case_id"], r["repeat"]))
        html_key, json_key = run_keys(bid, r["case_id"], r["repeat"])
        assert store.exists(html_key) and store.exists(json_key)
    assert "Captioned the Chip" in store.get(run_keys(bid, SOLAR["id"], 1)[0]).decode()


def test_a_verdict_in_neither_the_results_nor_the_trace_is_counted_as_missing(env, offline):  # noqa: F811
    store, _, _ = env
    b = run(env, "no-verdict", repeats=1)
    bid = b["config"].batch_id
    lost = _damage(store, bid, b)
    # Cut the Judge Step out of that Run's Trace as well.
    key = trace_key(bid, lost["case_id"], lost["repeat"])
    info, steps = loads(store.get(key))
    store.put(key, dumps(info, [s for s in steps if s.kind != "judge"]))
    offline()

    summary = batches.rescore(bid, store)

    assert summary["replay"]["judge_verdicts"] == {"reused": 1, "recovered": 0, "missing": 1}
    scored = batches.load(store, bid)["results"]
    assert [r["fidelity"] is None for r in scored].count(True) == 1  # not invented, not zero


def test_saved_narratives_are_shown_and_none_are_written(env, offline):  # noqa: F811
    store, _, fake = env
    b = run(env, "narrated", repeats=1)
    bid = b["config"].batch_id
    key = narrative_key(bid, SOLAR["id"], 1)
    before, asked = store.get(key), fake["client"].narrations
    _damage(store, bid, b)
    offline()

    batches.rescore(bid, store)

    assert store.get(key) == before  # replayed as written, not asked for again
    assert fake["client"].narrations == asked
    assert "Run ended ok" in store.get(run_keys(bid, SOLAR["id"], 1)[0]).decode()


def test_the_command_line_replays_a_batch_with_no_credentials(env, offline, monkeypatch, capsys):  # noqa: F811
    from clayzer import cli

    store, settings, _ = env
    bid = run(env, "cli", repeats=1)["config"].batch_id
    # The command reads its store from the environment and must not need a .env for it.
    monkeypatch.setattr(cli, "load_env", lambda: None)
    monkeypatch.setenv("CLAYZER_DATA_DIR", str(settings.data_dir))
    monkeypatch.setenv("CLAYZER_BATCHES_DIR", str(settings.batches_dir))
    offline()

    assert cli.main(["rescore", bid]) == 0

    out = capsys.readouterr().out
    assert f"rescored {bid}" in out
    assert "replayed offline: Judge verdicts 2 reused, 0 recovered from Traces, 0 missing" in out
    assert "2 Run summaries rebuilt" in out
    assert store.exists(f"batches/{bid}/report.html")
