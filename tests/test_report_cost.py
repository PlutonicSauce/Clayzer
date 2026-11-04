from test_grounding import caption, claim, label

from clayzer.grounding import grounding
from clayzer.report_cost import evidence_yield


def test_no_observations_never_become_zero_cost_or_inferred_gpu():
    g = grounding(caption([claim("x", "building", "east")]), [label("building", "east")])
    result = evidence_yield(
        g, observed_cost={"provider": "bedrock", "gpu_seconds": 2, "tokens": 100}
    )
    assert result["supported_claim_credit_per_dollar"] is None
    assert result["supported_claim_credit_per_gpu_second"] is None


def test_duplicate_claims_and_partial_parent_credit():
    cap = caption(
        [claim("x", "building", None, count=None), claim("y", "building", None, count=None)]
    )
    result = evidence_yield(grounding(cap, [label("greenhouse", "east")]))
    assert result["unique_object_claims"] == 1
    assert result["supported_object_claim_credit"] == 0.5
    assert result["supported_field_units"] == 0.5


def test_detailed_caption_verifies_more_fields_without_changing_quality_definitions():
    refs = [label("building", "east")]
    detailed = grounding(caption([claim("x", "building", "east")]), refs)
    vague = grounding(caption([claim("x", "building", None, count=None)]), refs)
    assert detailed["correctness"] == vague["correctness"] == 1
    assert evidence_yield(detailed)["supported_field_units"] == 3
    assert evidence_yield(vague)["supported_field_units"] == 1


def test_only_explicit_verified_cost_provenance_enables_ratios():
    g = grounding(caption([claim("x", "building", "east")]), [label("building", "east")])
    dollars = {
        "value": 0.02,
        "currency": "USD",
        "verified": True,
        "method": "fixture observation",
        "model_id": "fixture",
        "region": "synthetic",
        "source": "synthetic test only",
        "observed_at": "2026-11-04",
    }
    result = evidence_yield(
        g,
        dollar_measurement=dollars,
        observed_cost={
            "provider": "self-hosted",
            "gpu_seconds": 2,
            "gpu_status": "observed",
            "method": "fixture device timer",
        },
    )
    assert result["supported_claim_credit_per_dollar"] == 50
    assert result["supported_claim_credit_per_gpu_second"] == 0.5
    assert (
        evidence_yield(g, dollar_measurement={**dollars, "verified": False})[
            "supported_claim_credit_per_dollar"
        ]
        is None
    )
