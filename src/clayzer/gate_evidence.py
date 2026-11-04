"""Validate the evidence used by the gate, independently of trusting saved means."""

import math
import re
import statistics

from clayzer.batch import HARNESS_FAULT, OK, SANDBOX_FAILURE

METRIC_PATHS = {
    "correctness": ("grounding", "correctness"),
    "coverage": ("grounding", "coverage"),
    "fidelity": ("fidelity", "score"),
    "workflow": ("workflow", "score"),
}
COUNTERS = ("planned", "ok", "harness_faults", "sandbox_failures")


def number(value, label, *, upper=None, optional=True):
    if value is None and optional:
        return
    if (
        type(value) not in (int, float)
        or not math.isfinite(value)
        or value < 0
        or (upper is not None and value > upper)
    ):
        raise ValueError(
            f"{label}: scores must be finite, non-negative numbers"
            + (f" in [0, {upper}]" if upper is not None else "")
        )


def counter(value, label):
    if type(value) is not int or value < 0:
        raise ValueError(f"{label} must be a non-negative integer")


def stats(value, label):
    if not isinstance(value, dict) or not {"mean", "spread"} <= value.keys():
        raise ValueError(f"{label}: missing mean or Spread")
    number(value["mean"], label, upper=1)
    number(value["spread"], label + " Spread", upper=1)


def validate_summary(batch):
    cfg, summary = batch["config"], batch["summary"]
    if (
        not isinstance(cfg.batch_id, str)
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,120}", cfg.batch_id)
        or ".." in cfg.batch_id
    ):
        raise ValueError("invalid Batch id")
    if type(cfg.repeats) is not int or cfg.repeats < 1:
        raise ValueError("Repeats must be a positive integer")
    if (
        not cfg.case_ids
        or any(not isinstance(cid, str) or not cid for cid in cfg.case_ids)
        or len(set(cfg.case_ids)) != len(cfg.case_ids)
    ):
        raise ValueError("configuration needs distinct, non-empty Case ids")
    if summary is None:
        return
    if not isinstance(summary, dict) or not {"batch", "cases"} <= summary.keys():
        raise ValueError("summary needs batch and cases")
    if summary.get("batch_id", cfg.batch_id) != cfg.batch_id:
        raise ValueError("summary Batch id differs from its configuration")
    if not isinstance(summary["cases"], dict) or not isinstance(summary["batch"], dict):
        raise ValueError("summary batch and cases must be objects")  # noqa: TRY004 -- invalid saved data
    runs = summary["batch"].get("runs")
    if not isinstance(runs, dict) or not set(COUNTERS) <= runs.keys():
        raise ValueError("summary is missing required Run counters")
    for key in COUNTERS:
        counter(runs[key], key)
    for cid, case in summary["cases"].items():
        if not isinstance(case, dict):
            raise ValueError(f"{cid}: invalid Case summary")  # noqa: TRY004 -- invalid saved data
        for key in ("runs", "harness_faults", "sandbox_failures"):
            counter(case.get(key), f"{cid} {key}")
        for metric in METRIC_PATHS:
            if metric in case:
                stats(case[metric], f"{cid} {metric}")
    stats(summary["batch"].get("retrieval_mrr"), "retrieval")
    number(summary["batch"].get("tokens_per_caption"), "tokens per Caption")


def _equal(actual, expected, label):
    same = (actual is None and expected is None) or (
        type(actual) in (int, float)
        and type(expected) in (int, float)
        and math.isclose(actual, expected, rel_tol=0, abs_tol=1e-12)
    )
    if not same:
        raise ValueError(f"{label}: stored summary disagrees with Run results; rebuild it")


def check_stats(saved, values, label):
    scored = [x for x in values if x is not None]
    for value in scored:
        number(value, label, upper=1)
    _equal((saved or {}).get("mean"), statistics.mean(scored) if scored else None, label)
    _equal(
        (saved or {}).get("spread"),
        statistics.stdev(scored) if len(scored) > 1 else None,
        label + " Spread",
    )


def _rows_by_case(rows, cfg):
    by_case = {cid: [] for cid in cfg.case_ids}
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Run result must be an object")  # noqa: TRY004 -- invalid saved data
        cid, repeat = row.get("case_id"), row.get("repeat")
        if (
            not isinstance(cid, str)
            or cid not in by_case
            or type(repeat) is not int
            or not 1 <= repeat <= cfg.repeats
            or (cid, repeat) in seen
            or row.get("status") not in {OK, HARNESS_FAULT, SANDBOX_FAILURE}
        ):
            raise ValueError("invalid or duplicate Run identity/status in Batch results")
        for section, _ in METRIC_PATHS.values():
            if row.get(section) is not None and not isinstance(row[section], dict):
                raise ValueError(f"invalid {section} score object in Run results")
        seen.add((cid, repeat))
        by_case[cid].append(row)
    return by_case


def _metric_samples(saved, scored, label, *, legacy_scores_only=False):
    counts = {}
    for metric, (section, key) in METRIC_PATHS.items():
        values = [(r.get(section) or {}).get(key) for r in scored]
        # Earlier Baseline exports stripped the Workflow Score from every result row.
        # Preserve the recorded summary for display, but zero samples make the gate
        # inconclusive. An explicit null in a current row must still be validated.
        stripped_workflow = (
            legacy_scores_only
            and metric == "workflow"
            and all(section not in row for row in scored)
        )
        if not stripped_workflow:
            check_stats(saved.get(metric), values, label + " " + metric)
        counts[metric] = sum(
            v is not None or (metric == "correctness" and _nothing_to_grade(r))
            for v, r in zip(values, scored, strict=True)
        )
    return counts


def _nothing_to_grade(row):
    """A graded Run whose Caption made no gradable Claims: correctness is undefined, not missing.

    Grounding leaves precision (and so correctness) None only then; coverage still carries the
    miss. A Run that was never graded has no grounding and still counts as a missing sample.
    """
    g = row.get("grounding")
    return (
        row["status"] == OK and isinstance(g, dict) and "precision" in g and g["precision"] is None
    )


def validate_rows(batch):
    """Check identities, counts and scores if raw results are available.

    Light web views contain summaries only. Full CLI Batches and accepted Baselines also have
    result rows, so they can be checked for stale summaries and partial metric samples.
    Returns sample counts per Case and metric. Does not re-judge captions or re-read imagery.
    """
    if "results" not in batch or batch["summary"] is None:
        return {}
    cfg, summary, rows = batch["config"], batch["summary"], batch["results"]
    by_case = _rows_by_case(rows, cfg)
    if set(summary["cases"]) != set(by_case):
        raise ValueError("summary Case ids differ from configuration/results")
    for status, field in (
        (OK, "ok"),
        (HARNESS_FAULT, "harness_faults"),
        (SANDBOX_FAILURE, "sandbox_failures"),
    ):
        _equal(summary["batch"]["runs"][field], sum(r["status"] == status for r in rows), field)
    counts = {}
    for cid, case_rows in by_case.items():
        saved = summary["cases"][cid]
        scored = [r for r in case_rows if r["status"] != SANDBOX_FAILURE]
        _equal(saved["runs"], len(scored), cid + " runs")
        for status, field in (
            (HARNESS_FAULT, "harness_faults"),
            (SANDBOX_FAILURE, "sandbox_failures"),
        ):
            _equal(saved[field], sum(r["status"] == status for r in case_rows), cid + " " + field)
        counts[cid] = _metric_samples(
            saved, scored, cid, legacy_scores_only=batch.get("baseline_scores_only", False)
        )
    tokens = [r.get("caption_tokens") for r in rows if r["status"] != SANDBOX_FAILURE]
    for value in tokens:
        number(value, "Run tokens")
    tokens = [v for v in tokens if v is not None]
    _equal(
        summary["batch"].get("tokens_per_caption"),
        statistics.mean(tokens) if tokens else None,
        "tokens per Caption",
    )
    if "retrieval" in batch:
        if not isinstance(batch["retrieval"], list) or any(
            not isinstance(r, dict) for r in batch["retrieval"]
        ):
            raise ValueError("retrieval results must be a list of objects")
        repeats = [r.get("repeat") for r in batch["retrieval"]]
        if any(type(r) is not int or not 1 <= r <= cfg.repeats for r in repeats) or len(
            set(repeats)
        ) != len(repeats):
            raise ValueError("invalid or duplicate retrieval Repeat")
        check_stats(
            summary["batch"]["retrieval_mrr"],
            [r.get("mrr") for r in batch["retrieval"]],
            "retrieval",
        )
    return counts
