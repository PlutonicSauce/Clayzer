"""Compare two Batches, and the regression gate: keep or reject a change (caption-plan.md §6).

The regression gate compares a candidate Batch with the accepted Baseline. Exit codes are for
scripts and CI:
    0  pass          no Case regressed
    1  fail          a Case or the Batch's retrieval regressed, or a Baseline Case is missing
    2  inconclusive  the candidate has Sandbox Failures, so missing Runs could hide a regression

Each Case is checked on grounding correctness, grounding coverage, and fidelity. A score
regresses when its mean drops by more than max(tolerance, the Baseline's Spread). Only the
Baseline's Spread counts (decided 2026-11-04): with the larger of the two, a candidate that made
scores erratic loosened its own threshold, and drops of 0.31 and 0.32 passed. A Case whose
Spread rose sharply is warned about separately, since an unstable captioner is a problem in its
own right. The tolerance does the work when there are too few Repeats to measure Spread.

Baselines live in the repo under baselines/<name>/ so they can be committed: the configuration
and scores only, no Captions or Claim rows (so no OSM-derived data, caption-plan.md §3).
"""

import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

from clayzer import baseline_files
from clayzer.batch import SANDBOX_FAILURE, BatchConfig, config_from
from clayzer.gate_evidence import METRIC_PATHS, number, validate_rows, validate_summary
from clayzer.provenance import RECORDED_SINCE  # None there means "not recorded", not "off"

Verdict = Literal["pass", "fail", "inconclusive"]
EXIT_CODES: dict[Verdict, int] = {"pass": 0, "fail": 1, "inconclusive": 2}
DEFAULT_TOLERANCE = 0.05
TOKEN_WARNING = 0.25  # warn when mean tokens per Caption rise more than this
SPREAD_WARNING = 3.0  # warn when a Case's Spread grows this many times (and by over 0.1)
METRICS = tuple(METRIC_PATHS)

# Settings that change the measuring stick itself: a difference makes scores less comparable.
MEASUREMENT = ("judge_model", "judge_prompt_sha", "embed_model", "cases_sha", "chips_sha",
               "ontology_version", "ontology_sha", "scorer_version", "region", "extra",
               "repeats", "retrieval_queries_sha")  # fmt: skip
# Settings a change to the captioner is expected to vary.
CAPTIONER = ("caption_model", "prompt_sha", "change_prompt_sha", "prompt_source", "tools",
             "max_turns", "verify", "verifiers_sha")  # fmt: skip
# The code itself: a change can move either, so it's shown but not warned about.
CODE = ("code_commit", "code_dirty")


# ── Baselines ───────────────────────────────────────────────────────────────────────────


def _scores_only(r: dict) -> dict:
    g = r.get("grounding") or {}
    return {
        "run_id": r["run_id"], "case_id": r["case_id"], "repeat": r["repeat"],
        "status": r["status"],
        "grounding": {k: g.get(k) for k in
                      ("correctness", "coverage", "precision", "recall", "count", "position",
                       "attributes", "relations", "change", "unscored_share")} if g else None,
        "fidelity": {"score": (r.get("fidelity") or {}).get("score")} if r.get("fidelity") else None,
        "workflow": {"score": (r.get("workflow") or {}).get("score")},
        "seconds_to_caption": r.get("seconds_to_caption"),
        "caption_tokens": r.get("caption_tokens"),
    }  # fmt: skip


def accept_baseline(
    batch: dict,
    root: Path,
    name: str = "default",
    *,
    expected_snapshot: str | None = None,
    experiment_record: dict | None = None,
) -> Path:
    """Copy a Batch's configuration and scores into baselines/<name>/, replacing any old one."""
    cfg, summary = batch["config"], batch["summary"]
    baseline_files.baseline_name(name)
    validate_summary(batch)
    if not batch["results"] or summary is None:
        raise ValueError(f"{cfg.batch_id} has no results to accept")
    failures = sum(r["status"] == SANDBOX_FAILURE for r in batch["results"])
    expected = {(cid, repeat) for cid in cfg.case_ids for repeat in range(1, cfg.repeats + 1)}
    actual = [(r["case_id"], r["repeat"]) for r in batch["results"]]
    if (
        failures
        or summary.get("stopped")
        or not expected
        or set(actual) != expected
        or len(actual) != len(expected)
        or summary["batch"]["runs"]["planned"] != len(expected)
    ):
        raise ValueError(
            f"{cfg.batch_id} is incomplete ({failures} Sandbox Failures); "
            "resume it first so the Baseline is complete"
        )
    counts = validate_rows(batch)
    for cid, case in summary["cases"].items():
        for metric in METRICS:
            measured = (case.get(metric) or {}).get("mean") is not None
            if measured and counts[cid][metric] != cfg.repeats:
                raise ValueError(f"{cid} {metric}: incomplete score samples")
    files = {
        "batch.json": json.dumps(asdict(cfg), indent=2, allow_nan=False) + "\n",
        "summary.json": json.dumps(summary, indent=2, allow_nan=False) + "\n",
        "results.jsonl": "".join(
            json.dumps(_scores_only(r), allow_nan=False) + "\n" for r in batch["results"]
        ),
        "ACCEPTED_FROM": cfg.batch_id + "\n",
    }
    if experiment_record is not None:
        files["experiment.json"] = json.dumps(experiment_record, indent=2, allow_nan=False) + "\n"
    return baseline_files.publish(root, name, files, expected_snapshot)


def load_baseline(root: Path, name: str = "default") -> dict:
    baseline_files.baseline_name(name)
    if not root.exists():
        raise FileNotFoundError(f"no Baseline named {name!r} in {root}")
    with baseline_files.directory(root, name) as d:
        return _read_baseline(d, root, name)


def _read_baseline(d: Path, root: Path, name: str) -> dict:
    if not (d / "summary.json").exists():
        raise FileNotFoundError(f"no Baseline named {name!r} in {root}")
    return {
        "config": config_from(json.loads((d / "batch.json").read_text())),
        "summary": json.loads((d / "summary.json").read_text()),
        "results": [json.loads(x) for x in (d / "results.jsonl").read_text().splitlines() if x],
        "snapshot": baseline_files.snapshot(d),
        "baseline_scores_only": True,
    }


# ── Comparing ───────────────────────────────────────────────────────────────────────────


def setting_changes(a: BatchConfig, b: BatchConfig) -> list[dict]:
    out = []
    for key in CAPTIONER + MEASUREMENT + CODE:
        va, vb = getattr(a, key), getattr(b, key)
        if va == vb:
            continue
        if key in RECORDED_SINCE and (va is None or vb is None):
            kind = "not recorded"
        else:
            kind = ("measurement" if key in MEASUREMENT else "code" if key in CODE
                    else "captioner")  # fmt: skip
        out.append({"setting": key, "a": va, "b": vb, "kind": kind})
    return out


def comparability_issues(a: BatchConfig, b: BatchConfig) -> list[str]:
    issues = [
        s["setting"]
        for s in setting_changes(a, b)
        if s["kind"] in {"measurement", "not recorded"} and s["setting"] not in CODE
    ]
    for label, cfg in (("Baseline", a), ("candidate", b)):
        required = (
            "chips_sha",
            "ontology_version",
            "ontology_sha",
            "cases_sha",
            "scorer_version",
            "embed_model",
        )
        if cfg.judge_model:
            required += ("judge_prompt_sha",)
        issues.extend(f"{label} {key} not recorded" for key in required if not getattr(cfg, key))
    return issues


def _delta(a, b):
    return None if a is None or b is None else b - a


def compare(a: dict, b: dict) -> dict:
    """What changed from Batch a to Batch b: settings, Batch-level scores, and per Case."""
    sa, sb = a["summary"]["batch"], b["summary"]["batch"]
    batch_rows = []
    for key, label in (
        ("correctness", "Grounding correctness"), ("coverage", "Grounding coverage"),
        ("fidelity", "Fidelity"),
        ("workflow", "Workflow Score"),
        ("unscored_share", "Unscored share of Claims"),
        ("seconds_per_caption", "Seconds per Caption"),
        ("tokens_per_caption", "Tokens per Caption"),
    ):  # fmt: skip
        batch_rows.append({"metric": label, "a": sa[key], "b": sb[key],
                           "delta": _delta(sa[key], sb[key])})  # fmt: skip
    ra, rb = sa["retrieval_mrr"], sb["retrieval_mrr"]
    batch_rows.insert(3, {
        "metric": "Retrieval (MRR)", "a": ra["mean"], "b": rb["mean"],
        "delta": _delta(ra["mean"], rb["mean"]),
        "spread": max(ra["spread"] or 0, rb["spread"] or 0) or None,
    })  # fmt: skip

    case_rows = []
    ca, cb = a["summary"]["cases"], b["summary"]["cases"]
    for case_id in sorted(set(ca) | set(cb)):
        for metric in METRICS:
            x, y = (ca.get(case_id) or {}).get(metric), (cb.get(case_id) or {}).get(metric)
            ma, mb = (x or {}).get("mean"), (y or {}).get("mean")
            spread = max((x or {}).get("spread") or 0, (y or {}).get("spread") or 0) or None
            case_rows.append({"case_id": case_id, "metric": metric, "a": ma, "b": mb,
                              "delta": _delta(ma, mb), "spread": spread})  # fmt: skip
    return {
        "a": a["config"].batch_id,
        "b": b["config"].batch_id,
        "settings": setting_changes(a["config"], b["config"]),
        "batch": batch_rows,
        "cases": case_rows,
    }


def render_compare(c: dict) -> str:
    def f(x, signed=False):
        return "—" if x is None else (f"{x:+.2f}" if signed else f"{x:.2f}")

    lines = [f"# Compare {c['a']} → {c['b']}", "", "## What changed", ""]
    if c["settings"]:
        lines += ["| Setting | A | B | Kind |", "|---|---|---|---|"]
        lines += [
            f"| {s['setting']} | `{s['a']}` | `{s['b']}` | {s['kind']} |" for s in c["settings"]
        ]
        if any(s["kind"] == "measurement" for s in c["settings"]):
            lines += ["", "A measurement setting changed, so the scores may not be comparable."]
    else:
        lines.append("No settings changed: the difference is run-to-run variation.")
    lines += ["", "## Batch", "", "| Metric | A | B | Change | Spread |", "|---|---|---|---|---|"]
    for r in c["batch"]:
        lines.append(
            f"| {r['metric']} | {f(r['a'])} | {f(r['b'])} | {f(r['delta'], True)} "
            f"| {f(r.get('spread'))} |"
        )
    lines += ["", "## Cases", "", "| Case | Metric | A | B | Change | Spread |",
              "|---|---|---|---|---|---|"]  # fmt: skip
    for r in c["cases"]:
        lines.append(
            f"| {r['case_id']} | {r['metric']} | {f(r['a'])} | {f(r['b'])} "
            f"| {f(r['delta'], True)} | {f(r['spread'])} |"
        )
    return "\n".join(lines) + "\n"


# ── Regression gate ─────────────────────────────────────────────────────────────────────


@dataclass
class Check:
    case_id: str
    metric: str
    baseline: float | None
    candidate: float | None
    allowed_drop: float
    status: Literal["ok", "regressed", "improved", "missing", "n/a"]


@dataclass
class GateResult:
    verdict: Verdict
    baseline_id: str
    candidate_id: str
    checks: list[Check]
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def exit_code(self) -> int:
        return EXIT_CODES[self.verdict]


def _status(baseline, candidate, allowed) -> str:
    if baseline is None and candidate is None:
        return "n/a"
    if baseline is None:
        return "ok"
    if candidate is None:
        # The Baseline had a score and the candidate has none (e.g. the Judge was off): it
        # can't be shown not to have regressed.
        return "missing"
    delta = candidate - baseline
    # Decimal scores exactly on the boundary can subtract to e.g. -0.050000000000000044.
    if math.isclose(abs(delta), allowed, rel_tol=0, abs_tol=1e-12):
        return "ok"
    if delta < -allowed:
        return "regressed"
    return "improved" if delta > allowed else "ok"


def _check(case_id, metric, b: dict | None, c: dict | None, tolerance) -> Check:
    bm, cm = (b or {}).get("mean"), (c or {}).get("mean")
    spread = (b or {}).get("spread")
    for label, value in (("Baseline", bm), ("candidate", cm), ("Spread", spread)):
        number(value, f"{case_id} {metric} {label}", upper=1)
    allowed = max(tolerance, spread or 0.0)  # the Baseline's Spread only
    if c is None and bm is not None:
        status = "missing"
    else:
        status = _status(bm, cm, allowed)
    return Check(case_id, metric, bm, cm, allowed, status)


def _validate_options(tolerance, max_token_increase):
    for name, value in (("tolerance", tolerance), ("max_token_increase", max_token_increase)):
        if value is not None and (
            type(value) not in (int, float) or not math.isfinite(value) or value < 0
        ):
            raise ValueError(f"{name} must be a finite, non-negative number")
    if tolerance is None:
        raise ValueError("tolerance must be a finite, non-negative number")


def _score_checks(bs, cs, tolerance):
    checks = []
    for case_id, b in bs["cases"].items():
        c = cs["cases"].get(case_id) or {}
        checks.extend(
            _check(case_id, metric, b.get(metric), c.get(metric), tolerance) for metric in METRICS
        )
    checks.append(
        _check(
            "(batch)",
            "retrieval",
            bs["batch"]["retrieval_mrr"],
            cs["batch"]["retrieval_mrr"],
            tolerance,
        )
    )
    return checks


def _regression_reasons(checks, bs, cs):
    reasons = []
    regressed = [c for c in checks if c.status == "regressed"]
    missing = sorted(
        {c.case_id for c in checks if c.status == "missing"} | (set(bs["cases"]) - set(cs["cases"]))
    )
    if regressed:
        reasons.append(
            f"{len(regressed)} regression(s): "
            + ", ".join(f"{c.case_id} {c.metric}" for c in regressed)
        )
    if missing:
        reasons.append("Baseline Cases or scores missing from the candidate: " + ", ".join(missing))
    return reasons


def _token_assessment(baseline, candidate, limit):
    tb = baseline["summary"]["batch"]["tokens_per_caption"]
    tc = candidate["summary"]["batch"]["tokens_per_caption"]
    change = (tc - tb) / tb if tb and tc is not None else None
    zero_increase = tb == 0 and tc is not None and tc > 0
    missing_rows = any(
        row.get("caption_tokens") is None
        for batch in (baseline, candidate)
        for row in batch.get("results", [])
        if row["status"] != SANDBOX_FAILURE
    )
    unknown = limit is not None and (tb is None or tc is None or missing_rows)
    reason = None
    if limit is not None and (zero_increase or (change is not None and change > limit)):
        rise = "from zero" if zero_increase else f"{change:+.0%}"
        reason = f"tokens per Caption rose {rise}, over the allowed {limit:+.0%}"
    return change, unknown, reason


def _partial_samples(summary, samples, checks):
    return any(
        check.baseline is not None
        and check.case_id in samples
        and samples[check.case_id][check.metric] < summary["cases"][check.case_id]["runs"]
        for check in checks
        if check.metric in METRICS
    )


def _incomplete_candidate(baseline, candidate, samples, checks):
    cs, cfg = candidate["summary"], candidate["config"]
    runs = cs["batch"]["runs"]
    completed = runs["ok"] + runs["harness_faults"]
    planned = len(cfg.case_ids) * cfg.repeats
    retrieval_short = (
        "retrieval" in candidate
        and baseline["summary"]["batch"]["retrieval_mrr"]["mean"] is not None
        and sum(r.get("mrr") is not None for r in candidate["retrieval"]) < cfg.repeats
    )
    return (
        runs["sandbox_failures"]
        or cs.get("stopped")
        or completed != runs["planned"]
        or runs["planned"] != planned
        or any(c["runs"] != cfg.repeats for c in cs["cases"].values())
        or set(cs["cases"]) != set(cfg.case_ids)
        or _partial_samples(cs, samples, checks)
        or retrieval_short
    )


def _uncertainty_reasons(baseline, candidate, checks, baseline_samples, samples, unknown_cost):
    reasons = []
    incomparable = comparability_issues(baseline["config"], candidate["config"])
    if incomparable:
        reasons.append("scores are not comparable: " + ", ".join(incomparable))
    if unknown_cost:
        reasons.append("token cap cannot be checked: token usage is missing")
    if not any(c.baseline is not None and c.candidate is not None for c in checks):
        reasons.append("no comparable Baseline and candidate scores")
    if _partial_samples(baseline["summary"], baseline_samples, checks):
        reasons.append("Baseline has incomplete metric samples; rebuild and re-accept it")
    if _incomplete_candidate(baseline, candidate, samples, checks):
        runs = candidate["summary"]["batch"]["runs"]
        completed = runs["ok"] + runs["harness_faults"]
        reasons.append(
            f"candidate is incomplete ({runs['sandbox_failures']} Sandbox Failures, "
            f"{completed} completed Runs); run `clayzer batch --resume`, then gate again"
        )
    return reasons


def _spread_warnings(baseline, candidate):
    warnings = []
    for case_id, b in baseline["summary"]["cases"].items():
        c = candidate["summary"]["cases"].get(case_id) or {}
        for metric in METRICS:
            sb = (b.get(metric) or {}).get("spread")
            sc = (c.get(metric) or {}).get("spread")
            if sb is not None and sc is not None and sc > sb + 0.1 and sc > SPREAD_WARNING * sb:
                warnings.append(f"{case_id} {metric} became erratic: Spread {sb:.2f} → {sc:.2f}")
    return warnings


def _gate_warnings(baseline, candidate, token_change, cost_regressed):
    changes = setting_changes(baseline["config"], candidate["config"])
    warnings = [
        f"{s['setting']} differs ({s['a']!r} → {s['b']!r}): scores may not be comparable"
        for s in changes
        if s["kind"] == "measurement"
    ]
    unrecorded = [s["setting"] for s in changes if s["kind"] == "not recorded"]
    if unrecorded:
        warnings.append(
            f"{', '.join(unrecorded)} not recorded for one side, so a change there "
            "can't be detected; re-run the Baseline to record them"
        )
    rb, rc = baseline["config"].repeats, candidate["config"].repeats
    if rb < 3 or rc < 3:
        warnings.append(
            f"repeats {rb} vs {rc}: under 3, Spread is barely measured, so the fixed "
            "tolerance does most of the work"
        )
    warnings.extend(_spread_warnings(baseline, candidate))
    if token_change is not None and token_change > TOKEN_WARNING and not cost_regressed:
        warnings.append(f"tokens per Caption rose {token_change:+.0%}; is the gain worth it?")
    return warnings


def gate(
    baseline: dict,
    candidate: dict,
    tolerance: float = DEFAULT_TOLERANCE,
    max_token_increase: float | None = None,
) -> GateResult:
    """Compare stored evidence; a token cap (0.5 = +50%) makes excess usage fail."""
    _validate_options(tolerance, max_token_increase)
    validate_summary(baseline)
    validate_summary(candidate)
    baseline_samples = validate_rows(baseline)
    samples = validate_rows(candidate)
    bs, cs = baseline["summary"], candidate["summary"]
    if not bs or not bs["cases"]:
        raise ValueError("Baseline has no scored Cases; accept a complete Batch first")
    if cs is None:
        return GateResult(
            "inconclusive",
            baseline["config"].batch_id,
            candidate["config"].batch_id,
            [],
            ["candidate has no summary; finish or resume its Batch, then gate again"],
        )
    checks = _score_checks(bs, cs, tolerance)
    reasons = _regression_reasons(checks, bs, cs)
    token_change, unknown_cost, cost_reason = _token_assessment(
        baseline, candidate, max_token_increase
    )
    if cost_reason:
        reasons.append(cost_reason)
    if reasons:
        verdict: Verdict = "fail"
    else:
        reasons = _uncertainty_reasons(
            baseline, candidate, checks, baseline_samples, samples, unknown_cost
        )
        verdict = "inconclusive" if reasons else "pass"
    return GateResult(
        verdict,
        baseline["config"].batch_id,
        candidate["config"].batch_id,
        checks,
        reasons,
        _gate_warnings(baseline, candidate, token_change, cost_reason is not None),
    )


def render_gate(result: GateResult) -> str:
    def f(x):
        return "  n/a" if x is None else f"{x:5.2f}"

    mark = {"ok": "ok", "regressed": "REGRESSED", "improved": "improved", "missing": "MISSING",
            "n/a": "n/a"}  # fmt: skip
    lines = [
        f"Regression gate: {result.verdict.upper()}",
        f"  Baseline  {result.baseline_id}",
        f"  candidate {result.candidate_id}",
        "",
        f"  {'Case':<34} {'metric':<10} {'base':>5} {'cand':>5} {'allowed':>7}  status",
    ]
    for c in result.checks:
        lines.append(
            f"  {c.case_id:<34} {c.metric:<10} {f(c.baseline)} {f(c.candidate)} "
            f"{-c.allowed_drop:7.2f}  {mark[c.status]}"
        )
    lines += [""] + [f"  reason: {r}" for r in result.reasons]
    lines += [f"  warning: {w}" for w in result.warnings]
    return "\n".join(lines).rstrip() + "\n"
