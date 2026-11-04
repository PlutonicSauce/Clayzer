"""Fault injection at persistence boundaries, concurrency, and recovery after promotion."""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from botocore.exceptions import ClientError
from test_experiments import setup
from test_loop import env, run  # noqa: F401

from clayzer import baseline_files
from clayzer.experiments import record_experiment, recover_experiment
from clayzer.gate import accept_baseline, load_baseline


def test_failed_directory_replacement_rolls_back(env, monkeypatch):  # noqa: F811
    _, settings, base = setup(env)
    c = run(env, "candidate")
    original = os.replace

    def fail_publish(src, dst):
        if Path(src).name.startswith(".default-") and Path(dst).name == "default":
            raise OSError("simulated rename failure")
        return original(src, dst)

    with monkeypatch.context() as m:
        m.setattr(baseline_files.os, "replace", fail_publish)
        with pytest.raises(OSError, match="rename failure"):
            accept_baseline(c, settings.baselines_dir)
    assert load_baseline(settings.baselines_dir)["config"] == base["config"]


def test_reader_recovers_a_process_interrupted_between_directory_renames(env):  # noqa: F811
    _, settings, base = setup(env)
    root = settings.baselines_dir
    os.replace(root / "default", root / ".default.backup")
    assert load_baseline(root)["config"] == base["config"]
    assert not (root / ".default.backup").exists()


def test_symlink_baselines_cannot_redirect_writes_or_reads(env, tmp_path):  # noqa: F811
    _, settings, base = setup(env)
    outside = tmp_path / "outside"
    outside.mkdir()
    marker = outside / "keep.txt"
    marker.write_text("untouched")
    (settings.baselines_dir / "redirect").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="symbolic links"):
        accept_baseline(base, settings.baselines_dir, "redirect")
    with pytest.raises(ValueError, match="symbolic links"):
        load_baseline(settings.baselines_dir, "redirect")
    assert marker.read_text() == "untouched"


@pytest.mark.parametrize("fail_call", [1, 2])
def test_log_failure_before_acceptance_does_not_promote(env, monkeypatch, fail_call):  # noqa: F811
    store, settings, base = setup(env)
    c = run(env, "candidate")
    original, calls = store.put, 0

    def fail(key, *args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == fail_call:
            raise OSError("store unavailable")
        return original(key, *args, **kwargs)

    monkeypatch.setattr(store, "put", fail)
    with pytest.raises(OSError, match="unavailable"):
        record_experiment(c, store, settings.baselines_dir, "Attempt", accept=True)
    assert load_baseline(settings.baselines_dir)["config"] == base["config"]


@pytest.mark.parametrize("fail_call", [3, 4])
@pytest.mark.parametrize("s3_error", [False, True])
def test_log_outage_after_promotion(env, monkeypatch, fail_call, s3_error):  # noqa: F811
    store, settings, _ = setup(env)
    c = run(env, "candidate")
    original, calls = store.put, 0

    def fail(key, *args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == fail_call:
            if s3_error:
                raise ClientError(
                    {"Error": {"Code": "AccessDenied", "Message": "unavailable"}}, "PutObject"
                )
            raise OSError("store unavailable")
        return original(key, *args, **kwargs)

    with monkeypatch.context() as m:
        m.setattr(store, "put", fail)
        with pytest.raises(OSError, match="WAS PROMOTED"):
            record_experiment(c, store, settings.baselines_dir, "Attempt", accept=True)
    assert load_baseline(settings.baselines_dir)["config"] == c["config"]
    key = recover_experiment(store, settings.baselines_dir)
    assert json.loads(store.get(key + ".json"))["decision"] == "kept"
    assert "Decision: **kept**" in store.get(key + ".md").decode()
    assert recover_experiment(store, settings.baselines_dir) == key  # retry is idempotent


def test_recovery_requires_an_acceptance_receipt(env):  # noqa: F811
    store, settings, _ = setup(env)
    with pytest.raises(ValueError, match="no experiment receipt"):
        recover_experiment(store, settings.baselines_dir)


def test_concurrent_readers_never_observe_half_a_baseline(env):  # noqa: F811
    _, settings, base = setup(env)
    candidate = run(env, "candidate")

    def reader():
        saved = load_baseline(settings.baselines_dir)
        assert saved["summary"]["batch_id"] == saved["config"].batch_id
        assert saved["config"].batch_id in {base["config"].batch_id, candidate["config"].batch_id}
        assert len(saved["results"]) == 6

    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = []
        for i in range(15):
            futures.append(
                pool.submit(accept_baseline, candidate if i % 2 else base, settings.baselines_dir)
            )
            futures.append(pool.submit(reader))
        for future in futures:
            future.result(timeout=10)


def test_failure_to_remove_an_old_backup_does_not_hide_a_completed_promotion(env, monkeypatch):  # noqa: F811
    _, settings, _ = setup(env)
    candidate = run(env, "candidate")
    original = baseline_files.shutil.rmtree

    def fail_backup(path, *args, **kwargs):
        if Path(path).name == ".default.backup":
            raise PermissionError("backup cleanup unavailable")
        return original(path, *args, **kwargs)

    with monkeypatch.context() as m:
        m.setattr(baseline_files.shutil, "rmtree", fail_backup)
        accept_baseline(candidate, settings.baselines_dir)
        assert load_baseline(settings.baselines_dir)["config"] == candidate["config"]
    assert load_baseline(settings.baselines_dir)["config"] == candidate["config"]
    assert not (settings.baselines_dir / ".default.backup").exists()


def test_recovery_command_recreates_both_files(env, monkeypatch, capsys):  # noqa: F811
    from clayzer.cli import main

    store, settings, _ = setup(env)
    c = run(env, "candidate")
    _, key = record_experiment(c, store, settings.baselines_dir, "Attempt", accept=True)
    expected = store.get(key + ".json")
    store.delete(key + ".json")
    store.delete(key + ".md")
    monkeypatch.setattr("clayzer.cli.load_env", lambda: None)
    monkeypatch.setattr("clayzer.cli.Settings.from_env", lambda: settings)
    assert main(["experiment-recover"]) == 0
    assert "Recovered experiment:" in capsys.readouterr().out
    assert store.get(key + ".json") == expected
    assert "Decision: **kept**" in store.get(key + ".md").decode()
