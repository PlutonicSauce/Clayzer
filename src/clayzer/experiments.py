"""Record a manual, single-change experiment and optionally keep a passing candidate.

Evaluation uses stored scores only. Each attempt saves JSON and Markdown in the candidate's
Batch folder, including the Baseline used at that moment, so later promotions don't rewrite
history. The automatic Proposer remains a separate, deferred task.
"""

import json
from copy import deepcopy
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from clayzer import baseline_files
from clayzer.gate import (
    DEFAULT_TOLERANCE,
    Check,
    GateResult,
    accept_baseline,
    compare,
    gate,
    load_baseline,
    policy_anchor,
    render_compare,
    render_gate,
    setting_changes,
)
from clayzer.gate_policy import GatePolicy


def _save_record(store, record):
    key = record["record_key"]
    result = GateResult(
        **{k: v for k, v in record["gate"].items() if k not in {"exit_code", "checks"}},
        checks=[Check(**row) for row in record["gate"]["checks"]],
    )
    text = (
        f"# Experiment: {record['label']}\n\n{record['hypothesis']}\n\n"
        f"Decision: **{record['decision']}**\n\n"
        f"```text\n{render_gate(result)}```\n\n"
    )
    if record["comparison"]:
        text += render_compare(record["comparison"])
    store.put(
        key + ".json",
        (json.dumps(record, indent=2, allow_nan=False) + "\n").encode(),
        "application/json",
    )
    store.put(key + ".md", text.encode(), "text/markdown")


def recover_experiment(store, baselines_dir: Path, baseline_name: str = "default") -> str:
    """Recreate the kept log from the receipt committed with the current Baseline."""
    with baseline_files.directory(baselines_dir, baseline_name) as target:
        path = target / "experiment.json"
        if not path.exists():
            raise ValueError("this Baseline has no experiment receipt to recover")
        record = json.loads(path.read_text())
        cfg = json.loads((target / "batch.json").read_text())
        if record["candidate"]["batch_id"] != cfg["batch_id"] or record["decision"] != "kept":
            raise ValueError("experiment receipt does not match the accepted Baseline")
    _save_record(store, record)
    return record["record_key"]


def record_experiment(
    candidate: dict,
    store,
    baselines_dir: Path,
    hypothesis: str,
    *,
    baseline_name: str = "default",
    accept: bool = False,
    tolerance: float = DEFAULT_TOLERANCE,
    max_token_increase: float | None = None,
    policy: GatePolicy | None = None,
) -> tuple[GateResult, str]:
    """Save an attempt; `accept` promotes only a passing, comparable development Batch.

    A rejected or inconclusive attempt is recorded too. Control reruns (zero changes) are
    allowed. Prompt source and prompt hash describe the same change, so count as one.
    """
    cfg = candidate["config"]
    if not cfg.label.strip() or not hypothesis.strip():
        raise ValueError("experiments need a labelled Batch and a non-empty hypothesis")
    baseline = load_baseline(baselines_dir, baseline_name)
    anchor = policy_anchor(policy, baselines_dir)
    if accept and policy is not None and policy.anchor == baseline_name:
        raise ValueError("an experiment cannot promote over its frozen anchor")
    if cfg.region != "dev" or baseline["config"].region != "dev":
        raise ValueError("prompt experiments use development Cases only; keep test Cases held out")
    if any(case.get("region", "dev") != "dev" for case in candidate.get("cases", [])):
        raise ValueError("experiments must contain development Cases only")
    changes = setting_changes(baseline["config"], cfg)
    changed = {s["setting"] for s in changes if s["kind"] == "captioner"}
    changed.discard("prompt_source")
    changed.discard("repeats")
    if len(changed) > 1:
        raise ValueError(
            "change only one of prompt, caption model, tools, turn budget, or verifier"
        )

    result = gate(baseline, candidate, tolerance, max_token_increase, policy=policy, anchor=anchor)
    decision = {"pass": "eligible", "fail": "rejected", "inconclusive": "inconclusive"}[
        result.verdict
    ]
    created = datetime.now(UTC)
    key = (
        f"batches/{cfg.batch_id}/experiments/"
        f"{created.strftime('%Y%m%dT%H%M%S%fZ')}-{uuid4().hex[:8]}"
    )
    record = {
        "record_key": key,
        "created": created.isoformat(),
        "label": cfg.label,
        "hypothesis": hypothesis.strip(),
        "baseline_name": baseline_name,
        "baseline": asdict(baseline["config"]),
        "candidate": asdict(cfg),
        "tolerance": tolerance,
        "max_token_increase": max_token_increase,
        "policy": policy.to_dict() if policy is not None else None,
        "anchor": {"config": asdict(anchor["config"]), "snapshot": anchor["snapshot"]}
        if anchor is not None
        else None,
        "decision": decision,
        "accept_requested": accept,
        "gate": {**asdict(result), "exit_code": result.exit_code},
        "comparison": compare(baseline, candidate) if candidate["summary"] else None,
    }

    # Persist the attempt before changing the Baseline; a failed promotion stays 'eligible'.
    _save_record(store, record)
    if accept and result.verdict == "pass":
        kept = deepcopy(record)
        kept["decision"] = "kept"
        accept_baseline(
            candidate,
            baselines_dir,
            baseline_name,
            expected_snapshot=baseline["snapshot"],
            experiment_record=kept,
        )
        try:
            _save_record(store, kept)
        except Exception as e:
            raise OSError(
                f"Baseline {baseline_name!r} WAS PROMOTED, but its experiment log could not be "
                "completed. The acceptance receipt is in baselines/<name>/experiment.json; "
                f"restore the store and run `clayzer experiment-recover --baseline {baseline_name}`"
            ) from e
    return result, key
