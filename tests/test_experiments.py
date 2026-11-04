"""The manual prompt loop with fake Bedrock: record, reject, keep, and preserve history."""

import json
from dataclasses import replace

import pytest
from test_loop import env, run, throttled  # noqa: F401

from clayzer import batch as batches
from clayzer.cli import main
from clayzer.config import REPO
from clayzer.experiments import record_experiment
from clayzer.gate import accept_baseline, load_baseline


def setup(env):  # noqa: F811
    store, settings, _ = env
    base = run(env, "baseline")
    accept_baseline(base, settings.baselines_dir)
    return store, settings, base


def test_passing_attempt_records_evidence_without_promoting_by_default(env):  # noqa: F811
    store, settings, base = setup(env)
    candidate = run(env, "coverage-prompt")
    candidate["config"] = replace(
        candidate["config"], prompt_sha="new-prompt", prompt_source="p.txt"
    )
    result, key = record_experiment(candidate, store, settings.baselines_dir, "Improve coverage")
    record = json.loads(store.get(key + ".json"))
    assert result.verdict == "pass" and record["decision"] == "eligible"
    assert record["baseline"]["batch_id"] == base["config"].batch_id
    assert record["candidate"]["prompt_sha"] == "new-prompt"
    assert record["gate"]["exit_code"] == 0
    assert "Improve coverage" in store.get(key + ".md").decode()
    assert "Compare" in store.get(key + ".md").decode()
    assert load_baseline(settings.baselines_dir)["config"] == base["config"]


def test_keep_promotes_and_preserves_workflow_scores_without_claim_rows(env):  # noqa: F811
    store, settings, base = setup(env)
    candidate = run(env, "keep")
    _, key = record_experiment(candidate, store, settings.baselines_dir, "Control", accept=True)
    saved = load_baseline(settings.baselines_dir)
    assert saved["config"] == candidate["config"]
    assert saved["results"][0]["workflow"]["score"] is not None
    assert "rows" not in saved["results"][0]["grounding"]
    original = store.get(key + ".json")
    assert json.loads(original)["decision"] == "kept"
    assert json.loads(original)["baseline"]["batch_id"] == base["config"].batch_id
    # A later decision on the same Batch gets a new record instead of overwriting history.
    _, later = record_experiment(candidate, store, settings.baselines_dir, "Control again")
    assert later != key and store.get(key + ".json") == original


@pytest.mark.parametrize(
    "fake, verdict", [({"wrong": True}, "fail"), ({"fail": {1: throttled()}}, "inconclusive")]
)
def test_failed_and_inconclusive_attempts_are_logged_without_promotion(env, fake, verdict):  # noqa: F811
    store, settings, base = setup(env)
    result, key = record_experiment(
        run(env, "candidate", **fake),
        store,
        settings.baselines_dir,
        "Try a change",
        accept=True,
    )
    assert result.verdict == verdict
    assert json.loads(store.get(key + ".json"))["decision"] != "kept"
    assert load_baseline(settings.baselines_dir)["config"] == base["config"]


@pytest.mark.parametrize(
    "change",
    [
        {"judge_model": "different"},
        {"cases_sha": "different"},
        {"judge_prompt_sha": None},
        {"repeats": 4},
    ],
)
def test_changed_measurements_cannot_promote_a_passing_score_comparison(env, change):  # noqa: F811
    store, settings, base = setup(env)
    candidate = run(env, "candidate")
    candidate["config"] = replace(candidate["config"], **change)
    result, _ = record_experiment(candidate, store, settings.baselines_dir, "Change", accept=True)
    assert result.exit_code == 2
    assert load_baseline(settings.baselines_dir)["config"] == base["config"]


def test_experiments_refuse_test_cases_multiple_changes_and_empty_notes(env):  # noqa: F811
    store, settings, _ = setup(env)
    candidate = run(env, "candidate")
    cfg = candidate["config"]
    for change, hypothesis, error in [
        ({"region": "test"}, "Tune", "development Cases"),
        ({"prompt_sha": "new", "caption_model": "new"}, "Tune", "only one"),
        ({"label": " "}, "Tune", "labelled Batch"),
        ({}, " ", "hypothesis"),
    ]:
        candidate["config"] = replace(cfg, **change)
        with pytest.raises(ValueError, match=error):
            record_experiment(candidate, store, settings.baselines_dir, hypothesis)


def test_baseline_refuses_missing_or_duplicate_runs_and_keeps_previous_baseline(env):  # noqa: F811
    _, settings, base = setup(env)
    candidate = run(env, "candidate")
    rows = candidate["results"]
    for bad in (rows[:-1], rows + [rows[0]], rows[:-1] + [rows[0]]):
        with pytest.raises(ValueError, match="incomplete"):
            accept_baseline({**candidate, "results": bad}, settings.baselines_dir)
        assert load_baseline(settings.baselines_dir)["config"] == base["config"]


@pytest.mark.parametrize("wrong, exit_code", [(False, 0), (True, 1)])
def test_experiment_cli_exit_codes(env, monkeypatch, capsys, wrong, exit_code):  # noqa: F811
    store, settings, _ = setup(env)
    candidate = run(env, "cli-attempt", wrong=wrong)
    monkeypatch.setattr("clayzer.cli.load_env", lambda: None)
    monkeypatch.setattr("clayzer.cli.Settings.from_env", lambda: settings)
    assert (
        main(["experiment", candidate["config"].batch_id, "--hypothesis", "Test prompt"])
        == exit_code
    )
    assert "PR log:" in capsys.readouterr().out
    assert store.list_dirs(f"batches/{candidate['config'].batch_id}/")


def test_cli_handles_a_batch_that_has_not_been_run(env, monkeypatch):  # noqa: F811
    store, settings, _ = setup(env)
    from test_loop import SOLAR, WIND

    bid = batches.create([SOLAR, WIND], settings, store, 3, "not-started", "dev")
    monkeypatch.setattr("clayzer.cli.load_env", lambda: None)
    monkeypatch.setattr("clayzer.cli.Settings.from_env", lambda: settings)
    assert main(["experiment", bid, "--hypothesis", "Control", "--accept"]) == 2


def test_candidate_prompt_runs_through_the_whole_loop(env):  # noqa: F811
    from test_loop import SOLAR, WIND

    from clayzer.harness import PROMPT

    store, settings, _ = setup(env)
    path = REPO / "prompts" / "coverage-v1.txt"
    prompt = path.read_text()
    assert prompt.startswith(PROMPT)  # the only change is the added coverage instruction
    bid = batches.start(
        [SOLAR, WIND],
        settings,
        store,
        3,
        "coverage-v1",
        "dev",
        prompt=prompt,
        prompt_source=str(path),
        progress=lambda _: None,
        narrate=False,
    )
    result, key = record_experiment(
        batches.load(store, bid),
        store,
        settings.baselines_dir,
        "Scan every grid cell",
        accept=True,
    )
    assert result.exit_code == 0
    assert store.get(f"batches/{bid}/prompt.txt").decode() == prompt
    record = json.loads(store.get(key + ".json"))
    assert record["decision"] == "kept"
    assert record["baseline"]["prompt_sha"] != record["candidate"]["prompt_sha"]
