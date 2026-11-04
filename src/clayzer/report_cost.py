"""Descriptive evidence yield, separate from correctness/coverage and from the regression gate.

Object Claims are deduplicated ignoring local IDs. Supported field units count presence
(including ontology credit), correct stated positions/attributes, and one correct aggregate
count per class. Unknown, omitted and contradicted fields earn no supported units. These
units are an accounting convention, not an independently calibrated quality metric.
"""

import json
import math


def evidence_yield(
    grounding: dict | None,
    *,
    observed_cost: dict | None = None,
    dollar_measurement: dict | None = None,
) -> dict:
    g = grounding or {}
    unique, supported, checkable, fields, count_classes = set(), 0.0, 0, 0.0, set()
    for row in g.get("rows", []):
        claim = row["claim"]
        key = json.dumps({k: v for k, v in claim.items() if k != "id"}, sort_keys=True)
        if key in unique:
            continue
        unique.add(key)
        if row.get("outcome") != "not_verifiable":
            checkable += 1
        if row.get("outcome") == "supported" and not row.get("unknown_fields"):
            supported += row.get("class_credit", 1.0)
        fields += row.get("presence") or 0
        if row.get("position") == 1:
            fields += 1
        fields += sum(v == 1 for v in row.get("attributes", {}).values())
        obj = claim["object"]
        if obj not in count_classes and claim.get("count") is not None:
            values = g.get("counts", {}).get(obj)
            if (
                values
                and values["claimed"] == values["reference"]
                and "count" not in row.get("unknown_fields", [])
            ):
                fields += 1
                count_classes.add(obj)

    def positive(x):
        return type(x) in (int, float) and math.isfinite(x) and x > 0

    dollars = None
    if dollar_measurement:
        # Do not calculate a bill from tokens or a guessed price table. This is an explicit
        # observation boundary for a teammate's verified billing/pricing implementation.
        required = ("method", "model_id", "region", "source", "observed_at")
        if (
            dollar_measurement.get("verified") is True
            and dollar_measurement.get("currency") == "USD"
            and all(
                isinstance(dollar_measurement.get(k), str) and dollar_measurement[k].strip()
                for k in required
            )
            and positive(dollar_measurement.get("value"))
        ):
            dollars = dollar_measurement["value"]
    cost = observed_cost or {}
    gpu = cost.get("gpu_seconds")
    if (
        cost.get("provider") == "bedrock"
        or cost.get("gpu_status") != "observed"
        or not cost.get("method")
        or not positive(gpu)
    ):
        gpu = None
    return {
        "unique_object_claims": len(unique),
        "checkable_object_claims": checkable,
        "supported_object_claim_credit": supported,
        "supported_field_units": fields,
        "supported_claim_credit_per_dollar": supported / dollars if dollars else None,
        "supported_claim_credit_per_gpu_second": supported / gpu if gpu else None,
        "dollar_measurement": dollar_measurement if dollars else None,
        "cost_unavailable_reason": None
        if dollars
        else "No verified USD observation with model, region, source, method and date",
        "definition": "Object Claims deduplicated ignoring IDs; fully supported as stated, partial parent class credit retained. Field units count presence, exact position, attributes and one exact aggregate count/class. Relations excluded. Not a quality score.",
    }
