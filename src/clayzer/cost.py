"""Cost and quality together: verified Claims per dollar and per GPU-second (CAP-12, CAP-10).

Grounding correctness rewards a vaguer Caption (fewer Claims, fewer mistakes), but a vague
Caption earns few verified Claims, so this number falls when Captions say less.

A Claim is verified when its type is in the Answer Key and every part scored on it is right:
its position, its type's total count, its attributes, and on Change Cases its change. Claims
about types no Answer Key covers are neither verified nor counted against it.

Cost is the Harness's model calls only, from the Trace: Judge Steps (`role: scoring`) are the
evaluation's cost, not the Caption's. Dollars use on-demand list prices per million tokens;
a model not in PRICES gets no dollar cost rather than a guess. GPU-seconds exist only for a
self-hosted model; Bedrock doesn't expose them, so on Bedrock that ratio is left empty.
"""

# (input, output) US dollars per million tokens, on-demand, checked 2026-11-04. Keyed by a
# substring of the Bedrock model id, so the cross-region `us.` prefix matches too. Claude rows
# are Anthropic's list prices; Bedrock bills Claude at its own rates, so confirm them in the
# account's Bedrock pricing page before quoting a dollar figure outside the team.
PRICES = {
    "amazon.nova-pro": (0.80, 3.20),
    "amazon.nova-lite": (0.06, 0.24),
    "anthropic.claude-opus-5-5": (4.00, 20.00),
    "anthropic.claude-sonnet-5-5": (2.00, 10.00),
    "anthropic.claude-haiku-5-5": (0.10, 0.50),
}
PRICES_AS_OF = "2026-11-04"


def price(model_id: str | None) -> tuple[float, float] | None:
    for key, p in PRICES.items():
        if model_id and key in model_id:
            return p
    return None


def run_cost(steps) -> dict:
    """The Harness's tokens, dollars, and GPU-seconds for one Run, from its Trace's Steps."""
    tokens_in = tokens_out = 0
    usd, gpu = 0.0, None
    for s in steps:
        a = s.attributes
        if a.get("role") == "scoring" or "cost" not in a:
            continue
        c = a["cost"]
        n_in, n_out = c.get("input_tokens") or 0, c.get("output_tokens") or 0
        tokens_in, tokens_out = tokens_in + n_in, tokens_out + n_out
        p = price(a.get("model_id"))
        usd = None if usd is None or p is None else usd + (n_in * p[0] + n_out * p[1]) / 1e6
        if c.get("gpu_seconds") is not None:
            gpu = (gpu or 0.0) + c["gpu_seconds"]
    return {"input_tokens": tokens_in, "output_tokens": tokens_out, "usd": usd,
            "gpu_seconds": gpu}  # fmt: skip


def verified_claims(g: dict) -> int:
    """How many of a Caption's Claims are right on every part scored on them."""
    exact = {obj for obj, c in g.get("counts", {}).items() if c["claimed"] == c["reference"]}
    counted = set(g.get("counts", {}))
    n = 0
    for row in g.get("rows", []):
        if row["verdict"] != "matched":
            continue
        obj = row["claim"]["object"]
        parts = [row.get("position"), row.get("change"), *(row.get("attributes") or {}).values()]
        if all(p in (None, 1.0) for p in parts) and (obj not in counted or obj in exact):
            n += 1
    return n


def per(numerator: float, denominator: float | None) -> float | None:
    return numerator / denominator if denominator else None
