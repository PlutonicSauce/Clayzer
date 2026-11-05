"""Bounded losses, pinned anchors and explicit floors: no network or paid models."""

import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest
from test_gate import pair
from test_loop import env, run  # noqa: F401

from clayzer import batch as batches
from clayzer.cli import main
from clayzer.experiments import record_experiment
from clayzer.gate import accept_baseline, gate, load_baseline, policy_anchor, render_gate
from clayzer.gate_policy import GatePolicy, load_policy


def test_noisy_baseline_cannot_allow_a_large_drop_with_policy():
    base, candidate = pair(base=0.8, candidate=0.6, spread=0.3)
    assert gate(base, candidate).verdict == "pass"  # Existing API remains compatible.
    result = gate(base, candidate, policy=GatePolicy(max_allowed_drop=0.05))
    assert result.verdict == "fail"
    assert next(c for c in result.checks if c.metric == "correctness").allowed_drop == 0.05


def test_bounded_retrieval_drop_and_exact_boundary():
    base, candidate = pair()
    base["summary"]["batch"]["retrieval_mrr"] = {"mean": 0.8, "spread": 0.3}
    candidate["summary"]["batch"]["retrieval_mrr"] = {"mean": 0.75, "spread": 0.0}
    policy = GatePolicy(max_allowed_drop=0.05)
    assert gate(base, candidate, policy=policy).verdict == "pass"
    candidate["summary"]["batch"]["retrieval_mrr"]["mean"] = 0.749
    assert gate(base, candidate, policy=policy).verdict == "fail"


@pytest.mark.parametrize("metric", ["correctness", "coverage", "fidelity", "workflow"])
def test_an_unchanged_low_score_fails_its_quality_floor(metric):
    base, candidate = pair(metric, base=0.3, candidate=0.3)
    result = gate(base, candidate, policy=GatePolicy(minimum_scores={metric: 0.7}))
    assert result.verdict == "fail"
    assert any("quality floor" in reason for reason in result.reasons)


def test_quality_floor_is_per_case_and_does_not_treat_na_as_zero():
    base, candidate = pair(base=0.8, candidate=0.8)
    for batch in (base, candidate):
        batch["summary"]["cases"]["na"] = deepcopy(batch["summary"]["cases"]["x"])
        batch["summary"]["cases"]["na"]["correctness"] = {"mean": None, "spread": None}
        batch["config"] = replace(batch["config"], case_ids=["x", "na"])
        batch["summary"]["batch"]["runs"].update(planned=6, ok=6)
    policy = GatePolicy(minimum_scores={"correctness": 0.8})
    assert gate(base, candidate, policy=policy).verdict == "pass"
    candidate["summary"]["cases"]["x"]["correctness"]["mean"] = 0.79
    assert gate(base, candidate, policy=policy).verdict == "fail"


def test_unmeasured_floor_is_inconclusive_and_missing_required_score_fails():
    base, candidate = pair()
    policy = GatePolicy(minimum_scores={"fidelity": 0.7})
    assert gate(base, candidate, policy=policy).verdict == "inconclusive"
    candidate["summary"]["cases"]["x"]["correctness"]["mean"] = None
    assert (
        gate(base, candidate, policy=GatePolicy(minimum_scores={"correctness": 0.7})).verdict
        == "fail"
    )


def test_improvement_requirement_does_not_accept_an_unchanged_control():
    base, candidate = pair()
    policy = GatePolicy(require_improvement=True)
    assert gate(base, candidate, policy=policy).verdict == "fail"
    candidate["summary"]["cases"]["x"]["correctness"]["mean"] = 0.86
    assert gate(base, candidate, policy=policy).verdict == "pass"


@pytest.mark.parametrize(
    "change",
    [
        {"version": 2},
        {"version": True},
        {"max_allowed_drop": -1},
        {"max_allowed_drop": float("nan")},
        {"max_allowed_drop": True},
        {"max_allowed_drop": 1.1},
        {"minimum_scores": []},
        {"minimum_scores": {"typo": 0.5}},
        {"minimum_scores": {"correctness": None}},
        {"minimum_scores": {"coverage": float("inf")}},
        {"require_improvement": "yes"},
        {"anchor": "../outside", "anchor_snapshot": "a" * 64},
        {"anchor": "frozen"},
        {"anchor_snapshot": "a" * 64},
    ],
)
def test_invalid_policies_cannot_pass(change):
    with pytest.raises(ValueError):
        gate(*pair(), policy=GatePolicy(**change))


@pytest.mark.parametrize("data", [{}, [], {"version": 1, "max_drop_typo": 0.05}])
def test_policy_file_rejects_unknown_or_missing_fields(tmp_path, data):
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        load_policy(path)


@pytest.mark.parametrize(
    "content",
    [
        '{"version":1,"max_allowed_drop":0,"max_allowed_drop":1}',
        '{"version":1,"minimum_scores":{"correctness":0.9,"correctness":0}}',
    ],
)
def test_policy_file_rejects_duplicate_fields(tmp_path, content):
    path = tmp_path / "policy.json"
    path.write_text(content)
    with pytest.raises(ValueError, match="duplicate"):
        load_policy(path)


def test_retrieval_floor_and_zero_loss_policy():
    base, candidate = pair()
    for batch in (base, candidate):
        batch["summary"]["batch"]["retrieval_mrr"] = {"mean": 0.6, "spread": 0}
    assert (
        gate(base, candidate, policy=GatePolicy(minimum_scores={"retrieval": 0.7})).verdict
        == "fail"
    )
    candidate["summary"]["cases"]["x"]["correctness"]["mean"] = 0.799
    assert gate(base, candidate, policy=GatePolicy(max_allowed_drop=0)).verdict == "fail"


def test_anchor_cannot_make_an_incomplete_or_incomparable_candidate_pass():
    base, candidate = pair()
    anchor = {**deepcopy(base), "snapshot": "a" * 64}
    policy = GatePolicy(anchor="frozen", anchor_snapshot="a" * 64)
    candidate["summary"] = None
    assert gate(base, candidate, policy=policy, anchor=anchor).verdict == "inconclusive"
    base, candidate = pair()
    candidate["config"] = replace(candidate["config"], judge_model="different")
    assert gate(base, candidate, policy=policy, anchor=anchor).verdict == "inconclusive"


def scored(batch, correctness):
    batch = deepcopy(batch)
    for row in batch["results"]:
        row["grounding"]["correctness"] = correctness
    batch["summary"] = batches.summarize(
        batch["config"], batch["cases"], batch["results"], batch["retrieval"]
    )
    return batch


def setup_anchor(fixture_env):
    store, settings, _ = fixture_env
    base = run(fixture_env, "control")
    accept_baseline(base, settings.baselines_dir)
    accept_baseline(base, settings.baselines_dir, "frozen")
    anchor = load_baseline(settings.baselines_dir, "frozen")
    policy = GatePolicy(max_allowed_drop=0.05, anchor="frozen", anchor_snapshot=anchor["snapshot"])
    return store, settings, base, policy


def test_fixed_anchor_prevents_successive_small_promotions_and_is_logged(env):  # noqa: F811
    store, settings, _, policy = setup_anchor(env)
    first = scored(run(env, "first"), 0.96)
    result, key = record_experiment(
        first, store, settings.baselines_dir, "First change", accept=True, policy=policy
    )
    assert result.verdict == "pass"
    kept = load_baseline(settings.baselines_dir)
    second = scored(run(env, "second"), 0.92)
    assert gate(kept, second).verdict == "pass"
    result, rejected = record_experiment(
        second, store, settings.baselines_dir, "Second change", accept=True, policy=policy
    )
    assert result.verdict == "fail" and any(r.startswith("anchor:") for r in result.reasons)
    assert load_baseline(settings.baselines_dir)["snapshot"] == kept["snapshot"]
    assert load_baseline(settings.baselines_dir, "frozen")["snapshot"] == policy.anchor_snapshot
    record = json.loads(store.get(rejected + ".json"))
    assert record["decision"] == "rejected" and record["policy"] == policy.to_dict()
    assert record["anchor"]["snapshot"] == policy.anchor_snapshot
    assert json.loads(store.get(key + ".json"))["decision"] == "kept"
    assert "anchor/" in store.get(rejected + ".md").decode()


def test_anchor_change_missing_anchor_and_promoting_over_anchor_are_refused(env):  # noqa: F811
    store, settings, base, policy = setup_anchor(env)
    candidate = run(env, "candidate")
    with pytest.raises(ValueError, match="missing or changed"):
        gate(base, candidate, policy=policy)
    with pytest.raises(ValueError, match="frozen anchor"):
        record_experiment(
            candidate,
            store,
            settings.baselines_dir,
            "Try",
            accept=True,
            baseline_name="frozen",
            policy=policy,
        )
    accept_baseline(candidate, settings.baselines_dir, "frozen")
    with pytest.raises(ValueError, match="missing or changed"):
        policy_anchor(policy, settings.baselines_dir)


def test_gate_and_experiment_cli_apply_the_same_policy(env, monkeypatch, tmp_path):  # noqa: F811
    store, settings, _, policy = setup_anchor(env)
    candidate = scored(run(env, "candidate"), 0.9)
    bid = candidate["config"].batch_id
    store.put(f"batches/{bid}/results.jsonl", batches.to_jsonl(candidate["results"]))
    store.put(f"batches/{bid}/summary.json", json.dumps(candidate["summary"]).encode())
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(policy.to_dict()))
    monkeypatch.setattr("clayzer.cli.load_env", lambda: None)
    monkeypatch.setattr("clayzer.cli.Settings.from_env", lambda: settings)
    assert main(["gate", bid, "--policy", str(path)]) == 1
    assert main(["experiment", bid, "--policy", str(path), "--hypothesis", "Try", "--accept"]) == 1
    assert load_baseline(settings.baselines_dir)["config"].batch_id != bid


def test_committed_74_case_anchor_is_complete_pinned_and_unchanged_passes():
    root = Path(__file__).resolve().parents[1]
    policy = load_policy(root / "policies/regression-gate.json")
    anchor = policy_anchor(policy, root / "baselines")
    result = gate(anchor, anchor, policy=policy, anchor=anchor)
    assert result.verdict == "pass" and len(anchor["config"].case_ids) == 74
    assert result.anchor_id == anchor["config"].batch_id
    assert "Policy" in render_gate(result)


def test_new_measurement_baseline_does_not_silently_replace_the_pinned_reference():
    root = Path(__file__).resolve().parents[1]
    policy = load_policy(root / "policies/regression-gate.json")
    anchor = policy_anchor(policy, root / "baselines")
    current = load_baseline(root / "baselines")
    assert current["config"].scorer_version != anchor["config"].scorer_version
    assert gate(current, current).verdict == "pass"
    result = gate(current, current, policy=policy, anchor=anchor)
    assert result.verdict != "pass"
    assert policy_anchor(policy, root / "baselines")["snapshot"] == policy.anchor_snapshot
