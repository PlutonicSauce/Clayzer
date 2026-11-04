"""Replay must be local, deterministic, non-destructive, and honest about missing evidence."""

import hashlib
import json
import socket
from pathlib import Path

import pytest
from test_loop import env, run  # noqa: F401

from clayzer import batch, replay
from clayzer.cases import to_jsonl


def snapshot(root):
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in root.rglob("*")
        if p.is_file()
    }


def recording(env):  # noqa: F811
    b = run(env, repeats=1)
    store = env[0]
    return b, Path(store.url(f"batches/{b['config'].batch_id}")), store.data_dir


def test_replay_without_credentials_network_or_providers(env, tmp_path, monkeypatch):  # noqa: F811
    b, source, data = recording(env)
    before = snapshot(source)

    def forbidden(*a, **k):
        raise AssertionError("Replay attempted network/provider access")

    for key in list(__import__("os").environ):
        if key.startswith(("AWS_", "CLAYZER_")):
            monkeypatch.delenv(key)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(batch, "bedrock", forbidden)
    monkeypatch.setattr("boto3.client", forbidden)
    monkeypatch.setattr("clayzer.retrieval.embed", forbidden)
    monkeypatch.setattr("clayzer.tools.Toolbox.__enter__", forbidden)
    output = replay.replay(source, data=data, output=tmp_path / "replayed")
    bid = b["config"].batch_id
    result = json.loads((output / "batches" / bid / "summary.json").read_text())
    assert result["batch"]["fidelity"] == b["summary"]["batch"]["fidelity"] == 0.8
    assert result["batch"]["retrieval_mrr"] == b["summary"]["batch"]["retrieval_mrr"]
    assert result["replay"]["network"] == "disabled by design: local files only"
    assert result["replay"]["metrics"]["fidelity"] == "retained recorded model opinion"
    report = output / "batches" / bid / "report.html"
    assert "OFFLINE REPLAY" in report.read_text()
    for r in b["results"]:
        name = f"{r['case_id']}--r{r['repeat']}"
        page = report.parent / "runs" / (name + ".html")
        assert page.exists() and "href='../report.html'" in page.read_text()
        assert (report.parent / "traces" / (name + ".jsonl")).exists()
    assert snapshot(source) == before
    second = replay.replay(source, data=data, output=tmp_path / "again")
    assert snapshot(second) == snapshot(output)


@pytest.mark.parametrize("missing", ["trace", "caption", "judge", "retrieval"])
def test_missing_evidence_is_explicit_and_status_is_preserved(env, tmp_path, missing):  # noqa: F811
    b, source, data = recording(env)
    if missing == "trace":
        for p in (source / "traces").glob("*"):
            p.unlink()
    elif missing == "caption":
        (source / "captions.jsonl").unlink()
    elif missing == "retrieval":
        (source / "retrieval.jsonl").unlink()
    else:
        rows = b["results"]
        for r in rows:
            r["fidelity"] = None
        (source / "results.jsonl").write_bytes(to_jsonl(rows))
    output = replay.replay(source, data=data, output=tmp_path / "replay")
    target = output / "batches" / b["config"].batch_id
    summary = json.loads((target / "summary.json").read_text())
    assert any(missing in w.lower() for w in summary["replay"]["warnings"])
    rows = [json.loads(s) for s in (target / "results.jsonl").read_text().splitlines()]
    assert [r["status"] for r in rows] == [r["status"] for r in b["results"]]
    if missing == "caption":
        assert summary["batch"]["correctness"] is None
    if missing == "trace":
        assert summary["batch"]["workflow"] is None


def test_partial_failed_and_historical_recordings(env, tmp_path):  # noqa: F811
    b = run(env, repeats=1, no_caption={"c-wind"})
    store = env[0]
    source = Path(store.url(f"batches/{b['config'].batch_id}"))
    config = json.loads((source / "batch.json").read_text())
    config["scorer_version"] = "grounding-3"
    (source / "batch.json").write_text(json.dumps(config))
    # A planned Run has not happened yet; don't invent a result or successful Caption.
    (source / "results.jsonl").write_bytes(to_jsonl([b["results"][1]]))
    (source / "captions.jsonl").write_text("")
    output = replay.replay(source, data=store.data_dir, output=tmp_path / "replay")
    summary = json.loads((output / "batches" / config["batch_id"] / "summary.json").read_text())
    assert summary["batch"]["runs"]["harness_faults"] == 1
    assert summary["batch"]["correctness"] == 0
    assert summary["replay"]["pending_runs"] == 1
    assert summary["replay"]["original_scorer"] == "grounding-3"
    assert summary["replay"]["historical_scores_comparable"] is False


@pytest.mark.parametrize("bad", ["duplicate", "case_mismatch", "malformed"])
def test_invalid_recording_is_rejected_before_output_is_written(env, tmp_path, bad):  # noqa: F811
    b, source, data = recording(env)
    rows = b["results"]
    if bad == "duplicate":
        rows.append(rows[0])
    elif bad == "case_mismatch":
        rows[0]["case_id"] = "unrecorded-case"
    if bad == "malformed":
        (source / "results.jsonl").write_text("{invalid")
    else:
        (source / "results.jsonl").write_bytes(to_jsonl(rows))
    with pytest.raises(ValueError):
        replay.replay(source, data=data, output=tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_malformed_and_incomplete_traces_are_unavailable(env, tmp_path):  # noqa: F811
    b, source, data = recording(env)
    traces = sorted((source / "traces").glob("*.jsonl"))
    traces[0].write_text("{bad")
    lines = traces[1].read_text().splitlines()
    traces[1].write_text("\n".join(lines[:-1]) + "\n")
    out = replay.replay(source, data=data, output=tmp_path / "out")
    summary = json.loads((out / "batches" / b["config"].batch_id / "summary.json").read_text())
    assert summary["batch"]["workflow"] is None
    assert sum("trace unavailable" in w.lower() for w in summary["replay"]["warnings"]) == 2


def test_replay_refuses_existing_output_and_overlapping_paths(env, tmp_path):  # noqa: F811
    _, source, data = recording(env)
    for output in (source, source / "replay", data, tmp_path):
        with pytest.raises(ValueError):
            replay.replay(source, data=data, output=output)


def test_missing_image_hash_mismatch_and_missing_references_are_disclosed(env, tmp_path):  # noqa: F811
    b, source, data = recording(env)
    first, second = b["cases"]
    (data / first["chips"][0]["uri"]).write_bytes(b"replaced-image")
    (data / second["chips"][0]["uri"]).unlink()
    first.pop("reference_labels")
    (source / "cases.jsonl").write_bytes(to_jsonl([first, second]))
    output = replay.replay(source, data=data, output=tmp_path / "out")
    target = output / "batches" / b["config"].batch_id
    summary = json.loads((target / "summary.json").read_text())
    assert any("hash mismatch" in w for w in summary["replay"]["warnings"])
    assert any("image unavailable" in w for w in summary["replay"]["warnings"])
    assert "Image unavailable" in (target / "report.html").read_text()
    rows = [json.loads(s) for s in (target / "results.jsonl").read_text().splitlines()]
    assert rows[0]["grounding"]["correctness"] is None


def test_replay_cli_ignores_dotenv_s3_and_credentials(env, tmp_path, monkeypatch, capsys):  # noqa: F811
    from clayzer.cli import main

    b, source, data = recording(env)

    def forbidden(*args, **kwargs):
        raise AssertionError("Local replay loaded credentials/cloud")

    monkeypatch.setattr("clayzer.cli.load_env", forbidden)
    monkeypatch.setattr("boto3.client", forbidden)
    monkeypatch.setenv("CLAYZER_STORE", "s3://must-not-be-contacted")
    assert (
        main(["replay", str(source), "--data", str(data), "--output", str(tmp_path / "out")]) == 0
    )
    assert b["config"].batch_id in capsys.readouterr().out


def test_replay_retains_new_reference_provenance_and_polygon_cells(tmp_path):
    from dataclasses import asdict

    from clayzer.config import REPO

    cases = [
        json.loads(line)
        for line in (REPO / "fixtures/caption/cases/caption-dev.jsonl").read_text().splitlines()
    ]
    source = tmp_path / "recording"
    source.mkdir()
    cfg = batch.BatchConfig(
        "preview",
        "No Captions evaluated",
        "fixture",
        "dev",
        1,
        [c["id"] for c in cases],
        "frozen",
        "not run",
        None,
        "not run",
        "empty",
        "not run",
    )
    (source / "batch.json").write_text(json.dumps(asdict(cfg)))
    (source / "cases.jsonl").write_bytes(to_jsonl(cases))
    output = replay.replay(source, data=REPO / "fixtures/caption", output=tmp_path / "out")
    target = output / "batches/preview"
    saved = [json.loads(s) for s in (target / "cases.jsonl").read_text().splitlines()]
    assert saved == cases
    assert any(c["kind"] == "change" and len(c["chips"]) == 2 for c in saved)
    assert any(c.get("answer_keys") for c in saved)
    assert any(
        len(lb.get("cells", [])) > 1
        for c in saved
        for lb in c["reference_labels"]
        if lb["object"] == "solar_array"
    )
    summary = json.loads((target / "summary.json").read_text())
    assert summary["batch"]["correctness"] is None
    assert summary["batch"]["fidelity"] is None
    assert summary["batch"]["runs"]["ok"] == 0
    assert summary["replay"]["pending_runs"] == len(cases)
    expected_chips = {Path(chip["uri"]).name for c in cases for chip in c["chips"]}
    assert {p.name for p in (output / "data/chips").glob("*.png")} == expected_chips


def test_change_pair_replay_preserves_upstream_scoring(env, tmp_path, monkeypatch):  # noqa: F811
    from test_change import PairBedrock
    from test_loop import SOLAR

    from clayzer import harness

    store, settings = env[:2]
    before = {
        **SOLAR["chips"][0],
        "id": "c-before",
        "uri": "chips/c-before.png",
        "date": "2016-06-01",
    }
    case = {
        **SOLAR,
        "id": "change-dev-solar",
        "kind": "change",
        "chips": [before, SOLAR["chips"][0]],
        "reference_labels": [{**SOLAR["reference_labels"][0], "change": "appeared"}],
    }
    store.put(before["uri"], b"c-before")
    monkeypatch.setattr(batch, "bedrock", lambda _: PairBedrock())
    bid = batch.start(
        [case], settings, store, 1, "change", "dev", progress=lambda _: None, narrate=False
    )

    def forbidden(*args, **kwargs):
        raise AssertionError("Replay invoked a model")

    monkeypatch.setattr(batch, "bedrock", forbidden)
    output = replay.replay(
        Path(store.url(f"batches/{bid}")), data=store.data_dir, output=tmp_path / "change-replay"
    )
    record = json.loads((output / "batches" / bid / "runs/change-dev-solar--r1.json").read_text())
    assert (
        record["scores"]["grounding"]["change"] == 0.0
    )  # scripted caption omitted the known change
    assert record["config"]["prompt_sha"] == batch._sha(harness.CHANGE_PROMPT.encode())
    assert (
        record["config"]["scorer_version"] == batch.SCORER_VERSION
        and "grounding-5" in batch.SCORER_VERSION
    )
    assert record["chip"]["id"] == SOLAR["chips"][0]["id"]  # labels use the later image
    assert all((output / "data" / c["uri"]).is_file() for c in case["chips"])
