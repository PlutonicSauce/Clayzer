"""Demo Stories: the pack holds only what each Story needs, redacted, and replays offline."""

import json
import socket
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from test_loop import SOLAR, WIND, env, run  # noqa: F401

from clayzer import stories
from clayzer.config import Settings
from clayzer.trace import trace_key
from clayzer.ui.app import create_app


def story(b, case, repeat=1, **extra):
    return {"id": f"{case}-{repeat}", "title": "t", "batch": b["config"].batch_id, "case": case,
            "repeat": repeat, "shows": "s", "note": "n", **extra}  # fmt: skip


def local_app(root):
    """The app over a local root, as `clayzer ui --local-root` starts it: no S3 store."""
    s = replace(
        Settings.from_env(),
        store_url=None,
        data_dir=root / "data",
        batches_dir=root / "batches",
        baselines_dir=root / "baselines",
    )
    return TestClient(create_app(s))


def offline(monkeypatch):
    def forbidden(*a, **k):
        raise AssertionError("the demo pack must not reach the network")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)


def test_the_pack_copies_only_the_story_runs_redacted(env, tmp_path):  # noqa: F811
    store, _, _ = env
    b = run(env, "base")
    key = trace_key(b["config"].batch_id, SOLAR["id"], 1)
    body = store.get(key)
    assert b'"error": null' in body
    store.put(key, body.replace(b'"error": null', b'"error": "denied with Bearer abc.def"', 1))
    out = stories.pack(store, [story(b, SOLAR["id"])], tmp_path / "pack")
    bdir = out / "batches" / b["config"].batch_id
    traces = sorted(p.name for p in (bdir / "traces").iterdir())
    # The Story Run's Trace, summary and narrative; not WIND's, nor the other Repeats.
    assert traces and all(name.startswith(f"{SOLAR['id']}--r1.") for name in traces)
    trace = (bdir / "traces" / f"{SOLAR['id']}--r1.jsonl").read_text()
    assert "Bearer [REDACTED]" in trace and "abc.def" not in trace
    assert sorted(p.name for p in (out / "data" / "chips").iterdir()) == [
        f"{SOLAR['chips'][0]['id']}.png"
    ]
    assert (
        json.loads((out / "data" / stories.INDEX).read_text())[0]["chip"] == SOLAR["chips"][0]["id"]
    )


def test_the_pack_carries_the_baseline_redacted(env, tmp_path):  # noqa: F811
    store, _, _ = env
    b = run(env, "base")
    accepted = tmp_path / "baselines" / "default"
    accepted.mkdir(parents=True)
    (accepted / "ACCEPTED_FROM").write_text(b["config"].batch_id + "\n")
    (accepted / "summary.json").write_text(json.dumps({"note": "denied with Bearer abc.def"}))
    out = stories.pack(store, [story(b, SOLAR["id"])], tmp_path / "pack", accepted)
    packed = out / "baselines" / "default"
    assert (packed / "ACCEPTED_FROM").read_text().strip() == b["config"].batch_id
    summary = (packed / "summary.json").read_text()
    assert "Bearer [REDACTED]" in summary and "abc.def" not in summary


def test_the_pack_refuses_a_missing_run_and_a_folder_that_isnt_a_pack(env, tmp_path):  # noqa: F811
    store, _, _ = env
    b = run(env, "base")
    with pytest.raises(ValueError, match="isn't in it"):
        stories.pack(store, [story(b, SOLAR["id"], repeat=9)], tmp_path / "pack")
    other = tmp_path / "notes"
    other.mkdir()
    with pytest.raises(ValueError, match="isn't a demo pack"):
        stories.pack(store, [story(b, SOLAR["id"])], other)
    assert other.exists()


def test_a_gate_story_is_gated_offline(env, tmp_path, monkeypatch):  # noqa: F811
    store, _, _ = env
    base, cand = run(env, "base"), run(env, "candidate")
    out = stories.pack(
        store, [story(cand, WIND["id"], baseline=base["config"].batch_id)], tmp_path / "p"
    )
    offline(monkeypatch)
    app = local_app(out)
    [s] = app.get("/api/stories").json()
    assert s["gate"]["verdict"] in {"pass", "fail", "inconclusive"}


def test_the_committed_pack_replays_every_story_offline(monkeypatch):
    committed = stories.load_stories()
    assert len(committed) >= 5 and all(s["note"] for s in committed)
    offline(monkeypatch)
    pack = stories.PACK
    app = local_app(pack)
    listed = app.get("/api/stories").json()
    assert [s["id"] for s in listed] == [s["id"] for s in committed], (
        "rebuild: clayzer stories pack"
    )
    for s in listed:
        src = f"/api/batches/{s['batch']}/runs/{s['case']}--r{s['repeat']}"
        for url in (
            f"{src}.json",
            f"{src}.html",
            f"{src}/provenance",
            f"/api/chips/{s['chip']}.png",
        ):
            assert app.get(url).status_code == 200, (s["id"], url)
    gated = {s["id"]: s["gate"]["verdict"] for s in listed if s.get("gate")}
    assert gated == {"gate-rejects-vague-prompt": "fail"}
    # Results shows the accepted Baseline's scores, and the Baseline's Batch is in the pack.
    o = app.get("/api/overview").json()
    baseline = o["baseline"]
    # Its featured Captions are only ones the pack can draw: each Chip is served.
    for sc in o["showcase"]:
        assert app.get(f"/api/chips/{sc['chip']['id']}.png").status_code == 200, sc["case_id"]
    assert baseline and baseline["batch_id"] in [
        b["batch_id"] for b in app.get("/api/batches").json()
    ]
