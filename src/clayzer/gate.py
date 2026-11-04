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
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

from clayzer.batch import SANDBOX_FAILURE, BatchConfig

Verdict = Literal["pass", "fail", "inconclusive"]
EXIT_CODES: dict[Verdict, int] = {"pass": 0, "fail": 1, "inconclusive": 2}
DEFAULT_TOLERANCE = 0.05
TOKEN_WARNING = 0.25  # warn when mean tokens per Caption rise more than this
SPREAD_WARNING = 3.0  # warn when a Case's Spread grows this many times (and by over 0.1)
METRICS = ("correctness", "coverage", "fidelity")

# Settings that change the measuring stick itself: a difference makes scores less comparable.
MEASUREMENT = ("judge_model", "embed_model", "cases_sha", "scorer_version")
# Settings a change to the captioner is expected to vary.
CAPTIONER = ("caption_model", "prompt_sha", "prompt_source")


# ── Baselines ───────────────────────────────────────────────────────────────────────────


def _scores_only(r: dict) -> dict:
    g = r.get("grounding") or {}
    return {
        "run_id": r["run_id"], "case_id": r["case_id"], "repeat": r["repeat"],
        "status": r["status"],
        "grounding": {k: g.get(k) for k in
                      ("correctness", "coverage", "precision", "recall", "count", "position",
                       "attributes", "relations", "unscored_share")} if g else None,
        "fidelity": {"score": (r.get("fidelity") or {}).get("score")} if r.get("fidelity") else None,
        "seconds_to_caption": r.get("seconds_to_caption"),
        "caption_tokens": r.get("caption_tokens"),
    }  # fmt: skip


def accept_baseline(batch: dict, root: Path, name: str = "default") -> Path:
    """Copy a Batch's configuration and scores into baselines/<name>/, replacing any old one."""
    cfg, summary = batch["config"], batch["summary"]
    if not batch["results"] or summary is None:
        raise ValueError(f"{cfg.batch_id} has no results to accept")
    failures = sum(r["status"] == SANDBOX_FAILURE for r in batch["results"])
    if failures or summary.get("stopped"):
        raise ValueError(
            f"{cfg.batch_id} is incomplete ({failures} Sandbox Failures); "
            "resume it first so the Baseline is complete"
        )
    target = root / name
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    (target / "batch.json").write_text(json.dumps(asdict(cfg), indent=2) + "\n")
    (target / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    rows = "".join(json.dumps(_scores_only(r)) + "\n" for r in batch["results"])
    (target / "results.jsonl").write_text(rows)
    (target / "ACCEPTED_FROM").write_text(cfg.batch_id + "\n")
    return target


def load_baseline(root: Path, name: str = "default") -> dict:
    d = root / name
    if not (d / "summary.json").exists():
        raise FileNotFoundError(f"no Baseline named {name!r} in {root}")
    return {
        "config": BatchConfig(**json.loads((d / "batch.json").read_text())),
        "summary": json.loads((d / "summary.json").read_text()),
        "results": [json.loads(x) for x in (d / "results.jsonl").read_text().splitlines() if x],
    }


# ── Comparing ───────────────────────────────────────────────────────────────────────────


def setting_changes(a: BatchConfig, b: BatchConfig) -> list[dict]:
    out = []
    for key in CAPTIONER + MEASUREMENT + ("repeats",):
        va, vb = getattr(a, key), getattr(b, key)
        if va != vb:
            kind = "measurement" if key in MEASUREMENT else "captioner"
            out.append({"setting": key, "a": va, "b": vb, "kind": kind})
    return out


def _delta(a, b):
    return None if a is None or b is None else b - a


def compare(a: dict, b: dict) -> dict:
    """What changed from Batch a to Batch b: settings, Batch-level scores, and per Case."""
    sa, sb = a["summary"]["batch"], b["summary"]["batch"]
    batch_rows = []
    for key, label in (
        ("correctness", "Grounding correctness"), ("coverage", "Grounding coverage"),
        ("fidelity", "Fidelity"),
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
    if delta < -allowed:
        return "regressed"
    return "improved" if delta > allowed else "ok"


def _check(case_id, metric, b: dict | None, c: dict | None, tolerance) -> Check:
    bm, cm = (b or {}).get("mean"), (c or {}).get("mean")
    allowed = max(tolerance, (b or {}).get("spread") or 0.0)  # the Baseline's Spread only
    if c is None and bm is not None:
        status = "missing"
    else:
        status = _status(bm, cm, allowed)
    return Check(case_id, metric, bm, cm, allowed, status)


def gate(
    baseline: dict,
    candidate: dict,
    tolerance: float = DEFAULT_TOLERANCE,
    max_token_increase: float | None = None,
) -> GateResult:
    """`max_token_increase` (0.5 = +50%) makes a rise in tokens per Caption fail the gate;
    without it, a rise over 25% only warns."""
    bs, cs = baseline["summary"], candidate["summary"]
    checks = []
    for case_id, b in bs["cases"].items():
        c = cs["cases"].get(case_id)
        for metric in METRICS:
            checks.append(
                _check(case_id, metric, b.get(metric), c.get(metric) if c else None, tolerance)
            )
    checks.append(
        _check("(batch)", "retrieval", bs["batch"]["retrieval_mrr"],
               cs["batch"]["retrieval_mrr"], tolerance)
    )  # fmt: skip

    reasons = []
    regressed = [c for c in checks if c.status == "regressed"]
    missing = sorted({c.case_id for c in checks if c.status == "missing"})
    if regressed:
        reasons.append(
            f"{len(regressed)} regression(s): "
            + ", ".join(f"{c.case_id} {c.metric}" for c in regressed)
        )
    if missing:
        reasons.append("Baseline Cases or scores missing from the candidate: " + ", ".join(missing))

    tb, tc = bs["batch"]["tokens_per_caption"], cs["batch"]["tokens_per_caption"]
    token_change = (tc - tb) / tb if tb and tc is not None else None
    cost_regressed = (
        max_token_increase is not None
        and token_change is not None
        and token_change > max_token_increase
    )
    if cost_regressed:
        reasons.append(
            f"tokens per Caption rose {token_change:+.0%}, over the allowed "
            f"{max_token_increase:+.0%}"
        )

    failures = cs["batch"]["runs"]["sandbox_failures"]
    incomplete = failures or cs.get("stopped")
    if regressed or missing or cost_regressed:
        verdict: Verdict = "fail"
    elif incomplete:
        verdict = "inconclusive"
        reasons.append(
            f"candidate is incomplete ({failures} Sandbox Failures); "
            "run `clayzer batch --resume`, then gate again"
        )
    else:
        verdict = "pass"

    warnings = [
        f"{s['setting']} differs ({s['a']!r} → {s['b']!r}): scores may not be comparable"
        for s in setting_changes(baseline["config"], candidate["config"])
        if s["kind"] == "measurement"
    ]
    rb, rc = baseline["config"].repeats, candidate["config"].repeats
    if rb < 3 or rc < 3:
        warnings.append(
            f"repeats {rb} vs {rc}: under 3, Spread is barely measured, so the fixed "
            "tolerance does most of the work"
        )
    for case_id, b in bs["cases"].items():
        c = cs["cases"].get(case_id) or {}
        for metric in METRICS:
            sb = (b.get(metric) or {}).get("spread")
            sc = (c.get(metric) or {}).get("spread")
            if sb is not None and sc is not None and sc > sb + 0.1 and sc > SPREAD_WARNING * sb:
                warnings.append(f"{case_id} {metric} became erratic: Spread {sb:.2f} → {sc:.2f}")
    if token_change is not None and token_change > TOKEN_WARNING and not cost_regressed:
        warnings.append(f"tokens per Caption rose {token_change:+.0%}; is the gain worth it?")
    return GateResult(
        verdict, baseline["config"].batch_id, candidate["config"].batch_id, checks, reasons,
        warnings,
    )  # fmt: skip


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
