"""Provenance: every Batch keeps what it was run and judged with, and the app shows where it is."""

import hashlib
import json
from dataclasses import replace

import pytest
from test_loop import SOLAR, WIND, env, run  # noqa: F401
from test_ui import client  # noqa: F401

from clayzer import batch as batches
from clayzer import judge, provenance
from clayzer.gate import gate, load_baseline, setting_changes


def test_a_batch_records_its_rubric_chips_ontology_and_commit(env):  # noqa: F811
    store = env[0]
    b = run(env, repeats=1)
    cfg, bid = b["config"], b["config"].batch_id
    rubric = store.get(f"batches/{bid}/judge-prompt.txt")
    assert judge.PROMPT in rubric.decode() and "submit_verdict" in rubric.decode()
    assert cfg.judge_prompt_sha == provenance.sha(rubric)
    chips = json.loads(store.get(f"batches/{bid}/chips.json"))
    assert chips == {
        c["chips"][0]["uri"]: hashlib.sha256(store.get(c["chips"][0]["uri"])).hexdigest()
        for c in (SOLAR, WIND)
    }
    assert cfg.chips_sha == provenance.sha(store.get(f"batches/{bid}/chips.json"))
    assert cfg.ontology_version == "0.1" and len(cfg.ontology_sha) == 12
    assert cfg.code_commit is None or len(cfg.code_commit) == 40
    assert cfg.summary_model


def test_a_chip_replaced_after_the_batch_started_is_not_scored(env):  # noqa: F811
    store, settings, _ = env
    bid = batches.create([SOLAR, WIND], settings, store, 1, "", "dev")
    store.put("chips/c-solar.png", b"a different image")
    batches.resume(bid, settings, store, progress=lambda _: None)
    results = {r["case_id"]: r for r in batches.load(store, bid)["results"]}
    assert results["fixed-dev-solar"]["status"] == batches.SANDBOX_FAILURE
    assert "changed since the Batch started" in results["fixed-dev-solar"]["error"]
    assert results["fixed-dev-wind"]["status"] == batches.OK


def test_resume_refuses_a_changed_judge_rubric(env, monkeypatch):  # noqa: F811
    store, settings, _ = env
    bid = batches.create([SOLAR], settings, store, 1, "", "dev")
    monkeypatch.setattr(judge, "PROMPT", judge.PROMPT + "\nBe lenient.")
    with pytest.raises(ValueError, match="rubric changed"):
        batches.resume(bid, settings, store, progress=lambda _: None)


def test_a_changed_rubric_is_a_measurement_change_and_unrecorded_items_are_flagged(env):  # noqa: F811
    cfg = run(env, repeats=1)["config"]
    changes = {
        s["setting"]: s["kind"] for s in setting_changes(cfg, replace(cfg, judge_prompt_sha="x"))
    }
    assert changes == {"judge_prompt_sha": "measurement"}
    old = replace(cfg, judge_prompt_sha=None, chips_sha=None, code_commit=None)
    kinds = {s["setting"]: s["kind"] for s in setting_changes(old, cfg)}
    assert kinds["judge_prompt_sha"] == kinds["chips_sha"] == "not recorded"
    assert kinds.get("code_commit") in (None, "not recorded")


def test_the_gate_warns_when_the_baseline_predates_provenance(env):  # noqa: F811
    from clayzer.gate import accept_baseline

    store, settings, _ = env
    b = run(env, repeats=1)
    b["config"] = replace(b["config"], judge_prompt_sha=None, chips_sha=None)
    accept_baseline(b, settings.baselines_dir)
    result = gate(load_baseline(settings.baselines_dir), batches.load(store, b["config"].batch_id))
    assert any("not recorded" in w and "re-run the Baseline" in w for w in result.warnings)


def test_the_app_shows_provenance_beside_the_baseline(client):  # noqa: F811
    app, bid = client
    p = app.get(f"/api/batches/{bid}/provenance").json()
    assert p["baseline_id"] == bid
    rows = {s["key"]: s for s in p["settings"]}
    assert rows["judge_prompt_sha"]["recorded"] and not rows["judge_prompt_sha"]["differs"]
    assert rows["caption_model"]["value"] == "cap"
    files = {f["name"]: f for f in p["files"]}
    assert files["judge-prompt.txt"]["exists"] and files["chips.json"]["exists"]
    assert files["batch.json"]["store_url"].endswith(f"batches/{bid}/batch.json")
    assert files["batch.json"]["console_url"] is None  # a local store has no console


def test_the_app_shows_a_runs_provenance(client):  # noqa: F811
    app, bid = client
    p = app.get(f"/api/batches/{bid}/runs/fixed-dev-solar--r1/provenance").json()
    assert p["case"]["chip_uri"] == "chips/c-solar.png"
    assert p["case"]["chip_sha256"] == hashlib.sha256(b"c-solar").hexdigest()
    assert [c["uri"] for c in p["case"]["chips"]] == ["chips/c-solar.png"]
    assert p["case"]["chips"][0]["sha256"] == p["case"]["chip_sha256"]
    assert p["case"]["reference_labels"] == 1
    files = {f["name"]: f for f in p["files"]}
    assert files["traces/fixed-dev-solar--r1.jsonl"]["exists"]


def test_only_a_batchs_own_files_are_served(client):  # noqa: F811
    app, bid = client
    ok = app.get(f"/api/batches/{bid}/files/batch.json")
    assert ok.status_code == 200 and ok.json()["batch_id"] == bid
    assert app.get(f"/api/batches/{bid}/files/traces/fixed-dev-solar--r1.jsonl").status_code == 200
    for name in ("../../cases/caption-dev.jsonl", "secret.txt", "traces/..--r1.jsonl",
                 "runs/x--r1.py"):  # fmt: skip
        assert app.get(f"/api/batches/{bid}/files/{name}").status_code == 404, name


def test_s3_objects_link_to_the_aws_console():
    class S3:
        bucket = "b"

        def _key(self, key):
            return f"caption/{key}"

    assert provenance.console_url(S3(), "batches/x/batch.json") == (
        "https://s3.console.aws.amazon.com/s3/object/b?prefix=caption/batches/x/batch.json"
    )


def test_a_batch_written_by_another_branch_still_loads(env):  # noqa: F811
    store = env[0]
    bid = run(env, repeats=1)["config"].batch_id
    key = f"batches/{bid}/batch.json"
    # A setting this branch doesn't know (`verify` was the first, before it merged).
    store.put(key, json.dumps({**json.loads(store.get(key)), "relocate": True}).encode())
    cfg = batches.load_config(store, bid)
    assert cfg.extra == {"relocate": True}
    # And it round-trips through a rewrite, as rescore does.
    store.put(key, json.dumps(batches.asdict(cfg)).encode())
    assert batches.load_config(store, bid).extra == {"relocate": True}
