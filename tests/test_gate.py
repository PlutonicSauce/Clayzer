"""Regression decisions at boundaries, incomplete data, cost, and Baseline preservation."""

from copy import deepcopy

import pytest
from test_loop import _cfg, _summary

from clayzer.gate import gate


def pair(metric="correctness", base=0.8, candidate=0.8, spread=0.0):
    b = {"config": _cfg(), "summary": _summary({"x": {metric: (base, spread)}})}
    c = {"config": _cfg(), "summary": _summary({"x": {metric: (candidate, 0.0)}})}
    return b, c


@pytest.mark.parametrize("metric", ["correctness", "coverage", "fidelity", "workflow"])
def test_exact_allowed_drop_passes_but_larger_drop_fails(metric):
    b, c = pair(metric, base=0.8, candidate=0.75)
    assert gate(b, c).exit_code == 0
    c["summary"]["cases"]["x"][metric]["mean"] = 0.749
    assert gate(b, c).exit_code == 1


def test_retrieval_uses_only_baseline_spread():
    b, c = pair()
    b["summary"]["batch"]["retrieval_mrr"] = {"mean": 0.8, "spread": 0.1}
    c["summary"]["batch"]["retrieval_mrr"] = {"mean": 0.7, "spread": 0.5}
    assert gate(b, c).verdict == "pass"
    c["summary"]["batch"]["retrieval_mrr"]["mean"] = 0.69
    assert gate(b, c).verdict == "fail"


@pytest.mark.parametrize("value", [-0.01, float("nan"), float("inf"), -float("inf")])
@pytest.mark.parametrize("option", ["tolerance", "max_token_increase"])
def test_invalid_gate_options_are_refused(option, value):
    with pytest.raises(ValueError, match="finite, non-negative"):
        gate(*pair(), **{option: value})


def test_missing_case_fails_even_when_baseline_scores_are_not_applicable():
    b, c = pair(base=None, candidate=None)
    c["summary"]["cases"].clear()
    assert gate(b, c).verdict == "fail"


def test_missing_summary_is_inconclusive():
    b, c = pair()
    c["summary"] = None
    assert gate(b, c).exit_code == 2


def test_unfinished_run_counts_are_inconclusive_without_a_stop_marker():
    b, c = pair()
    c["summary"]["batch"]["runs"].update(planned=6, ok=5, harness_faults=0)
    assert gate(b, c).verdict == "inconclusive"


def test_missing_repeats_in_one_case_are_inconclusive_even_if_totals_match():
    b, c = pair()
    c["summary"]["cases"]["x"]["runs"] = 2
    assert gate(b, c).verdict == "inconclusive"


def test_known_regression_still_fails_with_sandbox_failures():
    b, c = pair(candidate=0.6)
    c["summary"]["batch"]["runs"]["sandbox_failures"] = 1
    assert gate(b, c).verdict == "fail"


def test_tokens_warn_by_default_and_can_fail_with_an_explicit_cap():
    b, c = pair()
    c["summary"]["batch"]["tokens_per_caption"] = 150
    assert any("tokens" in w for w in gate(b, c).warnings)
    assert gate(b, c, max_token_increase=0.5).verdict == "pass"
    assert gate(b, c, max_token_increase=0.49).verdict == "fail"


def test_gate_does_not_modify_either_batch():
    b, c = pair()
    before = deepcopy((b, c))
    gate(b, c)
    assert (b, c) == before


@pytest.mark.parametrize("value", [float("nan"), float("inf")])
def test_non_finite_scores_cannot_pass_the_gate(value):
    with pytest.raises(ValueError, match="scores must be finite"):
        gate(*pair(candidate=value))
