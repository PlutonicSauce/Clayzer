"""Shared native/imported Output Score engine; the five criteria have no combined score."""

import math

from clayzer.grounding import grounding
from clayzer.judge import fidelity, self_judging, validate_verdict
from clayzer.provenance import judge_prompt, sha

VERSION = "output-1+grounding-5+retrieval-2"


def _number(value, name):
    if value is not None and (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < 0
    ):
        raise ValueError(f"{name} must be a finite nonnegative measurement")
    return value


def cost_observation(
    provider="bedrock",
    *,
    gpu_seconds=None,
    gpu_count=None,
    gpu_type=None,
    seconds=None,
    tokens=None,
    method=None,
):
    """Self-hosted providers supply observed metrics and their measurement method explicitly."""
    for key, value in (
        ("gpu_seconds", gpu_seconds),
        ("gpu_count", gpu_count),
        ("seconds", seconds),
        ("tokens", tokens),
    ):
        _number(value, key)
    if gpu_count is not None and (
        not isinstance(gpu_count, int) or isinstance(gpu_count, bool) or gpu_count < 1
    ):
        raise ValueError("GPU count must be a positive observed integer")
    if tokens is not None and (not isinstance(tokens, int) or isinstance(tokens, bool)):
        raise ValueError("Token usage must be an observed integer")
    if gpu_type is not None and (not isinstance(gpu_type, str) or not gpu_type.strip()):
        raise ValueError("GPU type must be an observed hardware identifier")
    if provider == "bedrock" and any(x is not None for x in (gpu_seconds, gpu_count, gpu_type)):
        raise ValueError("Bedrock does not expose GPU metrics")
    if any(x is not None for x in (gpu_seconds, gpu_count, gpu_type)) and not method:
        raise ValueError("Observed GPU metrics require a measurement method")
    return {
        "provider": provider,
        "gpu_seconds": gpu_seconds,
        "gpu_count": gpu_count,
        "gpu_type": gpu_type,
        "gpu_status": "unavailable" if gpu_seconds is None else "observed",
        "method": method,
        "latency_seconds": seconds,
        "tokens": tokens,
        "note": "Latency and tokens are operational measurements, not GPU cost",
    }


def preparation(case: dict, seconds_to_caption=None) -> dict:
    observed = case.get("preparation")
    if observed is None:
        observed = {
            "value": case.get("prep_seconds"),
            "scope": "case_build",
            "method": "legacy prep_seconds: Case builder monotonic wall clock; includes imagery and references",
            "units": "seconds",
            "reference_only": False,
        }
    observed = dict(observed)
    if observed.get("units") != "seconds" or observed.get("scope") not in {
        "case_build",
        "reference_labels",
    }:
        raise ValueError("Preparation requires scope case_build/reference_labels and units seconds")
    if observed.get("value") is not None and not observed.get("method"):
        raise ValueError("Measured preparation time requires a method")
    _number(observed.get("value"), "preparation time")
    _number(seconds_to_caption, "caption generation time")
    return {
        "reference_preparation": {
            **observed,
            "status": "unmeasured" if observed.get("value") is None else "observed",
        },
        "caption_generation": {
            "value": seconds_to_caption,
            "units": "seconds",
            "scope": "caption_generation",
            "method": "observed caption pipeline wall time; native includes tools, verification and rewrite",
            "status": "unmeasured" if seconds_to_caption is None else "observed",
        },
    }


def grounding_by_class(cap, labels) -> dict:
    """Grounding sliced to each class the Caption claims or the Reference Labels name."""
    classes = {o["object"] for o in cap["objects"]} | {lb["object"] for lb in labels}
    return {obj: grounding(cap, labels, class_id=obj) for obj in sorted(classes)}


def score_caption(
    cap,
    case,
    *,
    client=None,
    judge_model=None,
    generator=None,
    png=None,
    tracer=None,
    image_key=None,
    seconds=None,
    tokens=None,
    judge_fn=None,
    provider="bedrock",
    observed_cost=None,
) -> dict:
    """No provider is constructed here. An absent client/image means explicitly unavailable."""
    claims_available = cap.get("claims_status") != "unavailable"
    labels = case.get("reference_labels")
    g = grounding(cap, labels) if labels is not None and claims_available else None
    fid, reason = None, None
    if not judge_model:
        reason = "Judge disabled"
    elif png is None:
        reason = "No image available"
    elif client is None:
        reason = "No judge provider supplied"
    else:
        fid, _ = (judge_fn or fidelity)(client, judge_model, cap, png, tracer, image_key)
        fid = {
            **validate_verdict(fid),
            "kind": "model_opinion",
            "self_judged": self_judging(generator, judge_model),
            "judge_model": judge_model,
            "rubric_sha": sha(judge_prompt().encode()),
        }
    per_class = grounding_by_class(cap, labels) if g is not None else {}
    return {
        "version": VERSION,
        "grounding_by_class": per_class,
        "grounding": g,
        "fidelity": fid,
        "grounding_unavailable": None
        if g is not None
        else "Missing reference evidence or unextracted Claims",
        "fidelity_unavailable": reason,
        "cost": cost_observation(**observed_cost)
        if observed_cost is not None
        else cost_observation(provider=provider, seconds=seconds, tokens=tokens),
        "label_preparation": preparation(case, seconds),
    }
