"""Fault attribution: who is to blame for each failed Step (ADR-0003).

Every failed Step is attributed to one of:
- harness      the system under test: a request it built badly, a forced tool call it never
               made, wrong arguments to a tool. Lowers the Workflow Score.
- environment  outside the Harness's control: throttling, an overloaded or unavailable
               service, timeouts, network and TLS failures, expired or missing access. Doesn't
               lower the Workflow Score, so the same Harness scores the same on any network.
- sandbox      the evaluation machinery itself (a Judge call): the Run gets no valid score.

Unrecognized failures default to harness, so attribution errs toward penalizing rather than
excusing. A Soft Failure is a tool call that reports success but whose response says it failed;
it's caught from the response text, then attributed like any other failure.

The rules read only fields the Trace records (error code, HTTP status, output), so they work on
recorded Traces too.
"""

import re

# Bedrock and botocore error codes that are the environment's fault.
ENVIRONMENT_CODES = {
    "ThrottlingException", "TooManyRequestsException", "ServiceUnavailableException",
    "InternalServerException", "ModelNotReadyException", "ModelTimeoutException",
    "ServiceQuotaExceededException",
    "ExpiredToken", "ExpiredTokenException", "UnrecognizedClientException", "InvalidClientTokenId",
    "InvalidSignatureException", "AccessDeniedException",
    "EndpointConnectionError", "ConnectTimeoutError", "ReadTimeoutError", "ConnectionClosedError",
    "SSLError", "ProxyConnectionError", "TimeoutError", "ConnectionError",
}  # fmt: skip
# Codes that mean the Harness's own request was wrong.
HARNESS_CODES = {"ValidationException", "ResourceNotFoundException", "ModelErrorException"}

# Text in a "successful" tool response that means it actually failed.
SOFT_FAILURE = re.compile(
    r"\b(error|exception|failed|failure|not found|no such|denied|forbidden|unauthori[sz]ed|"
    r"invalid|traceback|requester ?pays|status(?: code)? (?:4|5)\d\d)\b",
    re.IGNORECASE,
)


def _env_or_harness(code: str | None, http_status: int | None) -> tuple[str, str]:
    if code in ENVIRONMENT_CODES:
        return "environment", f"{code} is outside the Harness's control"
    if http_status == 429 or (http_status is not None and http_status >= 500):
        return "environment", f"HTTP {http_status} from the service"
    if code in HARNESS_CODES:
        return "harness", f"{code}: the request the Harness built was rejected"
    return "harness", f"unrecognized failure ({code or 'no code'}); ADR-0003 defaults to harness"


def _soft_failure(output) -> str | None:
    """The phrase in a 'successful' tool response that shows it failed, if any."""
    if output is None:
        return None
    text = output if isinstance(output, str) else str(output)
    m = SOFT_FAILURE.search(text[:4000])
    return m.group(0) if m else None


def classify(step) -> dict | None:
    """The fault for one Step, or None if it didn't fail.

    Returns {"attribution": harness | environment | sandbox, "reason": str, "soft": bool}.
    """
    a = step.attributes or {}
    expects = a.get("expects_tool")
    out = step.output if isinstance(step.output, dict) else {}
    made_call = any("toolUse" in b for b in out.get("content", []))
    if step.kind == "judge":
        if step.error:
            return {"attribution": "sandbox", "soft": False,
                    "reason": "the Judge failed: evaluation machinery, not the Harness"}  # fmt: skip
        if expects and not made_call:
            return {"attribution": "sandbox", "soft": False,
                    "reason": f"the Judge didn't call {expects}"}  # fmt: skip
        return None
    if step.error:
        who, why = _env_or_harness(a.get("error_code"), a.get("http_status"))
        return {"attribution": who, "reason": why, "soft": False}
    if step.kind == "llm" and expects and not made_call:
        return {"attribution": "harness", "soft": False,
                "reason": f"the model didn't call {expects}"}  # fmt: skip
    if step.kind == "tool" and not a.get("is_error"):
        phrase = _soft_failure(step.output)
        if phrase:
            return {"attribution": "harness", "soft": True,
                    "reason": f"reported success but the response says {phrase!r}"}  # fmt: skip
    if step.kind == "tool" and a.get("is_error"):
        who, why = _env_or_harness(a.get("error_code"), a.get("http_status"))
        return {"attribution": who, "reason": why, "soft": False}
    return None


def attribute(steps) -> dict:
    """Classify every Step in place (`attributes["fault"]`) and return the Run's counts."""
    counts = {"harness": 0, "environment": 0, "sandbox": 0, "soft": 0}
    for step in steps:
        fault = classify(step)
        if fault is None:
            step.attributes.pop("fault", None)
            continue
        step.attributes["fault"] = fault
        counts[fault["attribution"]] += 1
        counts["soft"] += fault["soft"]
    return counts
