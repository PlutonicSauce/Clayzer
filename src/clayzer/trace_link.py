"""Report-side X-Ray navigation. The capture/export owner must supply actual export evidence.

RunInfo.metadata['otel'] = {trace_id, aws_region, exported_to: 'xray'}.
Accept an OTel 32-hex trace id or an AWS 1-8hex-24hex id; zero IDs are invalid.
No ID is generated here and no AWS calls are made.
"""

import re


def xray_link(metadata: dict) -> dict:
    context = metadata.get("otel") or {}
    unavailable = lambda reason: {"url": None, "reason": reason, "trace_id": None}
    if not isinstance(context, dict) or context.get("exported_to") != "xray":
        return unavailable("no recorded X-Ray export context")
    tid, region = context.get("trace_id"), context.get("aws_region")
    if not isinstance(tid, str):
        return unavailable("trace id not recorded")
    tid = tid.lower()
    if re.fullmatch(r"[0-9a-f]{32}", tid):
        tid = f"1-{tid[:8]}-{tid[8:]}"
    if (
        not re.fullmatch(r"1-[0-9a-f]{8}-[0-9a-f]{24}", tid)
        or int(tid.replace("-", "")[1:], 16) == 0
    ):
        return unavailable("malformed trace id")
    if not isinstance(region, str) or not re.fullmatch(
        r"(?:us|eu|ap|sa|ca|me|af|il|mx)-(?:gov-)?[a-z]+-\d", region
    ):
        return unavailable("AWS region missing or malformed")
    domain = "console.amazonaws.cn" if region.startswith("cn-") else "console.aws.amazon.com"
    return {
        "trace_id": tid,
        "reason": None,
        "url": f"https://{region}.{domain}/xray/home?region={region}#/traces/{tid}",
    }
