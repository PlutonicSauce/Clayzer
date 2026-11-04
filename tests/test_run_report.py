"""The per-Run evaluation report (REQ-08): HTML for people, JSON for machines, rebuilt offline."""

import json

from test_loop import SOLAR, WIND, env, run, throttled  # noqa: F401

from clayzer import batch as batches
from clayzer.run_report import run_keys


def test_every_run_gets_an_html_and_a_json_report(env):  # noqa: F811
    store = env[0]
    b = run(env, repeats=2, no_caption={"c-wind"})
    bid = b["config"].batch_id
    for case in (SOLAR, WIND):
        for repeat in (1, 2):
            hkey, jkey = run_keys(bid, case["id"], repeat)
            assert store.exists(hkey) and store.exists(jkey)

    rec = json.loads(store.get(run_keys(bid, SOLAR["id"], 1)[1]))
    assert rec["status"] == "ok" and rec["scores"]["grounding"]["correctness"] == 1.0
    assert rec["scores"]["fidelity"]["score"] == 0.8
    assert rec["summary"]["verdict"].startswith("Captioned")
    assert rec["caption"]["text"] == "A solar farm." and rec["trace"].endswith("--r1.jsonl")
    assert rec["config"]["scorer_version"] and rec["faults"]["harness"] == 0

    html = store.get(run_keys(bid, SOLAR["id"], 1)[0]).decode()
    for expected in ("Run fixed-dev-solar#1", "Captioned", "A solar farm.", "Steps",
                     "llm · caption", "judge · fidelity", "evaluation, not the Harness",
                     "Prompt", "aerial image", "Grounding: Claims against the Reference Labels"):  # fmt: skip
        assert expected in html, expected

    faulted = json.loads(store.get(run_keys(bid, WIND["id"], 1)[1]))
    assert faulted["status"] == "harness_fault" and faulted["faults"]["harness"] == 1
    assert "Harness Fault" in store.get(run_keys(bid, WIND["id"], 1)[0]).decode()


def test_run_reports_rebuild_without_a_model(env, monkeypatch):  # noqa: F811
    store = env[0]
    b = run(env, repeats=1, fail={1: throttled()})
    bid = b["config"].batch_id
    hkey, _ = run_keys(bid, SOLAR["id"], 1)
    store.delete(hkey)

    def no_model(*_):
        raise AssertionError("reports must not call a model")

    monkeypatch.setattr(batches, "bedrock", no_model)
    batches.write_reports(store, bid)
    assert "Environment Fault" in store.get(hkey).decode()


def test_the_batch_report_links_each_run(env):  # noqa: F811
    store = env[0]
    b = run(env, repeats=1)
    html = store.get(f"batches/{b['config'].batch_id}/report.html").decode()
    assert f"runs/{SOLAR['id']}--r1.html" in html
