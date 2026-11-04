"""Replay (REQ-09): a recorded Batch rescored against updated Cases with no model or network."""

import copy

import boto3
import pytest
from test_loop import SOLAR, WIND, FakeBedrock

from clayzer import batch as batches
from clayzer.config import Settings
from clayzer.gate import accept_baseline, gate, load_baseline
from clayzer.store import LocalStore
from clayzer.trace import trace_key


@pytest.fixture
def recorded(tmp_path, monkeypatch):
    store = LocalStore(tmp_path / "data", tmp_path / "batches")
    for case in (SOLAR, WIND):
        store.put(case["chips"][0]["uri"], case["chips"][0]["id"].encode())
    settings = Settings(
        caption_model="cap", judge_model="judge", embed_model="embed",
        bedrock_endpoint_url=None, data_dir=tmp_path / "data",
        batches_dir=tmp_path / "batches", baselines_dir=tmp_path / "baselines",
        store_url=None, naip_source="pc",
    )  # fmt: skip
    monkeypatch.setattr(batches, "bedrock", lambda s: FakeBedrock())
    bid = batches.start([SOLAR, WIND], settings, store, 2, "rec", "dev", narrate=False,
                        progress=lambda _: None)  # fmt: skip
    return store, settings, bid


def offline(monkeypatch):
    """No model, no AWS client, no credentials: anything that reaches for them fails."""

    def refuse(*a, **k):
        raise AssertionError("replay must not call a model or AWS")

    monkeypatch.setattr(batches, "bedrock", refuse)
    monkeypatch.setattr(boto3, "client", refuse)
    for var in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "AWS_PROFILE"):
        monkeypatch.delenv(var, raising=False)


def relabelled():
    wind = copy.deepcopy(WIND)
    wind["reference_labels"][0]["count"] = 3  # a corrected turbine count
    return [SOLAR, wind]


def test_replay_rescores_offline_and_reuses_the_rest(recorded, monkeypatch):
    store, _, bid = recorded
    offline(monkeypatch)
    rid = batches.replay(bid, store, relabelled(), "fix")
    a, b = batches.load(store, bid), batches.load(store, rid)
    assert b["config"].replayed_from == bid and b["config"].cases_sha != a["config"].cases_sha
    assert b["summary"]["replayed_from"] == bid and rid.endswith("-fix")
    wind_a = {r["repeat"]: r for r in a["results"] if r["case_id"] == WIND["id"]}
    for r in (r for r in b["results"] if r["case_id"] == WIND["id"]):
        assert (
            r["grounding"]["count"] != wind_a[r["repeat"]]["grounding"]["count"]
        )  # 2 claimed vs 3 now
        assert r["fidelity"] == wind_a[r["repeat"]]["fidelity"]  # the Judge's verdict, reused
    assert b["captions"] == a["captions"]
    assert [row["mrr"] for row in b["retrieval"]] == [row["mrr"] for row in a["retrieval"]]
    assert store.exists(trace_key(rid, WIND["id"], 1)) and store.exists(
        f"batches/{rid}/report.html"
    )


def test_a_replayed_baseline_gates_live_batches_on_the_new_cases(recorded, monkeypatch, tmp_path):
    store, settings, bid = recorded
    offline(monkeypatch)
    rid = batches.replay(bid, store, relabelled(), "fix", reports=False)
    accept_baseline(batches.load(store, rid), settings.baselines_dir)
    monkeypatch.setattr(batches, "bedrock", lambda s: FakeBedrock())
    live = batches.start(relabelled(), settings, store, 2, "live", "dev", narrate=False,
                         progress=lambda _: None)  # fmt: skip
    result = gate(load_baseline(settings.baselines_dir), batches.load(store, live))
    assert not any("not comparable" in r for r in result.reasons), result.reasons


def test_replay_refuses_what_it_cant_rescore(recorded, monkeypatch):
    store, _, bid = recorded
    offline(monkeypatch)
    with pytest.raises(ValueError, match="same Cases"):
        batches.replay(bid, store, [SOLAR], "x")
    moved = copy.deepcopy(SOLAR)
    moved["chips"][0]["uri"] = "chips/elsewhere.png"
    with pytest.raises(ValueError, match="Chips differ"):
        batches.replay(bid, store, [moved, WIND], "x")
    rail = copy.deepcopy(SOLAR)
    rail["reference_labels"].append({**rail["reference_labels"][0], "object": "railroad"})
    with pytest.raises(ValueError, match="can't replay retrieval"):
        batches.replay(bid, store, [rail, WIND], "x")  # nothing was ever ranked for railroads
