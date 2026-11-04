"""Try to manufacture false passes and damage a Baseline, using only temporary stores."""

import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest
from test_experiments import setup
from test_gate import pair
from test_loop import env, run  # noqa: F401

from clayzer.experiments import record_experiment
from clayzer.gate import accept_baseline, gate, load_baseline


@pytest.mark.parametrize("value", [-0.1, 1.01, True, "0.8"])
def test_invalid_scores_are_refused(value):
    with pytest.raises(ValueError):
        gate(*pair(candidate=value))


@pytest.mark.parametrize("value", [-0.1, float("nan"), float("inf"), "0.2", True])
def test_invalid_candidate_spread_is_refused(value):
    b, c = pair()
    c["summary"]["cases"]["x"]["correctness"]["spread"] = value
    with pytest.raises(ValueError):
        gate(b, c)


@pytest.mark.parametrize("value", [-1, float("nan"), float("inf"), True, "100"])
def test_invalid_cost_cannot_bypass_a_token_cap(value):
    b, c = pair()
    c["summary"]["batch"]["tokens_per_caption"] = value
    with pytest.raises(ValueError):
        gate(b, c, max_token_increase=0.5)


def test_missing_cost_is_inconclusive_when_a_cap_is_requested():
    b, c = pair()
    c["summary"]["batch"]["tokens_per_caption"] = None
    assert gate(b, c, max_token_increase=0.5).exit_code == 2


def test_zero_baseline_tokens_cannot_hide_a_positive_cost_increase():
    b, c = pair()
    b["summary"]["batch"]["tokens_per_caption"] = 0
    assert gate(b, c, max_token_increase=0.5).exit_code == 1


def test_no_comparable_scores_is_inconclusive():
    assert gate(*pair(base=None, candidate=None)).exit_code == 2


@pytest.mark.parametrize("field", ["planned", "ok", "harness_faults", "sandbox_failures"])
def test_missing_run_counters_cannot_imply_completion(env, field):  # noqa: F811
    b = run(env, "complete")
    c = deepcopy(b)
    del c["summary"]["batch"]["runs"][field]
    with pytest.raises(ValueError):
        gate(b, c)


def test_partial_metric_samples_do_not_pass_as_complete(env):  # noqa: F811
    b = run(env, "complete")
    c = deepcopy(b)
    # The mean still looks healthy, but only one of the three Runs was judged.
    for row in c["results"][1:]:
        row["fidelity"] = None
    with pytest.raises(ValueError, match="summary disagrees"):
        gate(b, c)


@pytest.mark.parametrize("mutation", ["missing_run", "duplicate_run", "stale_mean", "wrong_case"])
def test_experiment_cannot_promote_stale_or_inconsistent_results(env, mutation):  # noqa: F811
    store, settings, base = setup(env)
    c = run(env, "candidate")
    if mutation == "missing_run":
        c["results"].pop()
    elif mutation == "duplicate_run":
        c["results"][-1] = c["results"][0]
    elif mutation == "stale_mean":
        c["results"][0]["grounding"]["correctness"] = 0
    else:
        c["config"] = replace(c["config"], case_ids=["unrelated-case"])
    try:
        result, _ = record_experiment(c, store, settings.baselines_dir, "Attempt", accept=True)
        assert result.verdict != "pass"
    except ValueError:
        pass
    assert load_baseline(settings.baselines_dir)["config"] == base["config"]


@pytest.mark.parametrize("name", ["..", "../outside", "/tmp/escape", "", "a/b"])
def test_baseline_names_cannot_leave_the_baseline_directory(env, name):  # noqa: F811
    _, settings, base = setup(env)
    # Never actually write to an escaped path, even on the unfixed implementation.
    from unittest.mock import patch

    with (
        patch("pathlib.Path.mkdir") as mkdir,
        patch("shutil.rmtree"),
        patch("pathlib.Path.write_text"),
    ):
        with pytest.raises(ValueError, match="Baseline name"):
            accept_baseline(base, settings.baselines_dir, name)
        mkdir.assert_not_called()


def test_serialization_failure_preserves_the_previous_baseline(env):  # noqa: F811
    _, settings, base = setup(env)
    c = run(env, "candidate")
    c["summary"]["unserializable"] = object()
    with pytest.raises((ValueError, TypeError)):
        accept_baseline(c, settings.baselines_dir)
    assert load_baseline(settings.baselines_dir)["config"] == base["config"]


def test_failed_baseline_file_write_preserves_the_previous_baseline(env, monkeypatch):  # noqa: F811
    _, settings, base = setup(env)
    c = run(env, "candidate")
    original = Path.write_text

    def fail_summary(path, *args, **kwargs):
        if path.name == "summary.json":
            raise OSError("simulated disk full")
        return original(path, *args, **kwargs)

    with monkeypatch.context() as m:
        m.setattr(Path, "write_text", fail_summary)
        with pytest.raises(OSError, match="disk full"):
            accept_baseline(c, settings.baselines_dir)
    assert load_baseline(settings.baselines_dir)["config"] == base["config"]


def test_store_failure_before_promotion_preserves_baseline(env, monkeypatch):  # noqa: F811
    store, settings, base = setup(env)
    c = run(env, "candidate")
    monkeypatch.setattr(store, "put", lambda *a, **kw: (_ for _ in ()).throw(OSError("offline")))
    with pytest.raises(OSError, match="offline"):
        record_experiment(c, store, settings.baselines_dir, "Attempt", accept=True)
    assert load_baseline(settings.baselines_dir)["config"] == base["config"]


def test_a_concurrent_baseline_change_cannot_be_silently_overwritten(env, monkeypatch):  # noqa: F811
    store, settings, _ = setup(env)
    candidate, other = run(env, "candidate"), run(env, "other")
    original = store.put
    changed = False

    def change_baseline(key, *args, **kwargs):
        nonlocal changed
        if not changed and "/experiments/" in key:
            changed = True
            accept_baseline(other, settings.baselines_dir)
        return original(key, *args, **kwargs)

    monkeypatch.setattr(store, "put", change_baseline)
    with pytest.raises(ValueError, match="Baseline changed"):
        record_experiment(candidate, store, settings.baselines_dir, "Attempt", accept=True)
    assert load_baseline(settings.baselines_dir)["config"] == other["config"]


def test_unknown_pipeline_settings_cannot_be_ignored(env):  # noqa: F811
    store, settings, _ = setup(env)
    c = run(env, "candidate")
    c["config"] = replace(c["config"], extra={"new_preprocessor": "v2"})
    result, _ = record_experiment(c, store, settings.baselines_dir, "Attempt", accept=True)
    assert result.exit_code == 2


def test_missing_provenance_on_both_sides_is_not_evidence_of_equality(env):  # noqa: F811
    store, settings, _ = env
    b = run(env, "baseline")
    b["config"] = replace(b["config"], chips_sha=None, ontology_sha=None)
    accept_baseline(b, settings.baselines_dir)
    c = run(env, "candidate")
    c["config"] = replace(c["config"], chips_sha=None, ontology_sha=None)
    result, _ = record_experiment(c, store, settings.baselines_dir, "Attempt", accept=True)
    assert result.exit_code == 2


def test_test_cases_mislabeled_as_a_dev_batch_are_refused(env):  # noqa: F811
    store, settings, _ = setup(env)
    c = run(env, "candidate")
    c["cases"][0]["region"] = "test"
    with pytest.raises(ValueError, match="development"):
        record_experiment(c, store, settings.baselines_dir, "Attempt", accept=True)


def test_metric_improvements_elsewhere_cannot_hide_one_cases_regression():
    b, c = pair(candidate=0.6)
    for i in range(10):
        b["summary"]["cases"][f"better-{i}"] = deepcopy(b["summary"]["cases"]["x"])
        c["summary"]["cases"][f"better-{i}"] = deepcopy(c["summary"]["cases"]["x"])
        c["summary"]["cases"][f"better-{i}"]["correctness"]["mean"] = 1
    assert gate(b, c).exit_code == 1


def test_experiment_logs_survive_later_mutation_of_input(env):  # noqa: F811
    store, settings, _ = setup(env)
    c = run(env, "candidate")
    _, key = record_experiment(c, store, settings.baselines_dir, "Attempt")
    before = store.get(key + ".json")
    c["summary"]["cases"].clear()
    assert store.get(key + ".json") == before
    assert json.loads(before)["comparison"]["cases"]


def test_partially_judged_scores_with_a_rebuilt_summary_are_inconclusive(env):  # noqa: F811
    from clayzer.batch import summarize

    b = run(env, "complete")
    c = deepcopy(b)
    for row in c["results"][2:]:
        row["fidelity"] = None
    c["summary"] = summarize(c["config"], c["cases"], c["results"], c["retrieval"])
    assert gate(b, c).exit_code == 2


def test_partial_cost_samples_cannot_pass_an_explicit_cap(env):  # noqa: F811
    from clayzer.batch import summarize

    b = run(env, "complete")
    c = deepcopy(b)
    c["results"][0]["caption_tokens"] = None
    c["summary"] = summarize(c["config"], c["cases"], c["results"], c["retrieval"])
    assert gate(b, c, max_token_increase=0.5).exit_code == 2


@pytest.mark.parametrize(
    "field", ["chips_sha", "judge_prompt_sha", "ontology_sha", "embed_model", "extra"]
)
def test_plain_gate_cannot_pass_changed_measurement_settings(env, field):  # noqa: F811
    b = run(env, "complete")
    c = deepcopy(b)
    c["config"] = replace(c["config"], **{field: {"new": True} if field == "extra" else "changed"})
    assert gate(b, c).exit_code == 2


@pytest.mark.parametrize(
    "field, value", [("repeats", 0), ("repeats", True), ("case_ids", []), ("case_ids", ["x", "x"])]
)
def test_invalid_configurations_are_refused(field, value):
    b, c = pair()
    c["config"] = replace(c["config"], **{field: value})
    with pytest.raises(ValueError):
        gate(b, c)


def test_one_failed_case_is_not_hidden_by_successes_in_ninety_nine_cases():
    b, c = pair(candidate=0.2)
    for i in range(99):
        cid = f"other-{i}"
        b["config"].case_ids.append(cid)
        c["config"].case_ids.append(cid)
        b["summary"]["cases"][cid] = deepcopy(b["summary"]["cases"]["x"])
        c["summary"]["cases"][cid] = deepcopy(b["summary"]["cases"]["x"])
    for data in (b, c):
        data["summary"]["batch"]["runs"].update(planned=300, ok=300)
    assert gate(b, c).exit_code == 1


def test_policy_limitation_a_noisy_baseline_can_allow_a_large_drop():
    # Deliberately documents the current policy, not evidence that this drop is acceptable.
    b, c = pair(base=0.8, candidate=0.6, spread=0.3)
    assert gate(b, c).exit_code == 0


def test_policy_limitation_repeated_small_drops_can_accumulate():
    b, _ = pair()
    original = b["summary"]["cases"]["x"]["correctness"]["mean"]
    for _ in range(5):
        c = deepcopy(b)
        c["summary"]["cases"]["x"]["correctness"]["mean"] -= 0.04
        assert gate(b, c).exit_code == 0
        b = c
    assert original - b["summary"]["cases"]["x"]["correctness"]["mean"] == pytest.approx(0.2)


def test_two_attempts_with_the_same_label_at_the_same_time_do_not_overwrite(env, monkeypatch):  # noqa: F811
    from datetime import UTC, datetime

    from clayzer import batch as batches

    class FrozenTime:
        @staticmethod
        def now(*args):
            return datetime(2026, 11, 4, tzinfo=UTC)

    monkeypatch.setattr(batches, "datetime", FrozenTime)
    first = run(env, "same-label")
    second = run(env, "same-label", wrong=True)
    assert first["config"].batch_id != second["config"].batch_id
    reloaded = batches.load(env[0], first["config"].batch_id)
    assert reloaded["results"] == first["results"]


def test_monotonicity_across_deterministic_random_scores():
    import random

    rng = random.Random(20261104)
    for _ in range(100):
        base = rng.uniform(0.2, 0.9)
        spread = rng.uniform(0, 0.15)
        b, c = pair(base=base, candidate=base, spread=spread)
        assert gate(b, c).exit_code == 0
        c["summary"]["cases"]["x"]["correctness"]["mean"] = base - max(0.05, spread) - 0.001
        assert gate(b, c).exit_code == 1
        c["summary"]["cases"]["x"]["correctness"]["mean"] = base + 0.01
        assert gate(b, c).exit_code == 0
