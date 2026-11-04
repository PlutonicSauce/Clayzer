"""Redaction at report/export boundaries; never rewrite original internal recordings."""

import re

_SECRET = re.compile(
    r"(?i)(authorization|api[_-]?key|access[_-]?key|secret|password|credential|session[_-]?token|^token$|cookie)"
)
_URL = re.compile(r'https?://[^\s<>"\']+')


def redact(value):
    if isinstance(value, dict):
        return {k: "[REDACTED]" if _SECRET.search(k) else redact(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    if isinstance(value, str):
        value = _URL.sub(
            lambda m: (
                "[REDACTED URL]"
                if (
                    (
                        "?" in m[0]
                        and not re.fullmatch(
                            r"https://[a-z0-9-]+\.console\.aws\.amazon\.com/xray/home\?region=[a-z0-9-]+#/traces/1-[a-f0-9]{8}-[a-f0-9]{24}",
                            m[0],
                        )
                    )
                    or "@" in m[0]
                    or re.search(r"localhost|127\.0\.0\.1|\.internal\b", m[0])
                )
                else m[0]
            ),
            value,
        )
        value = re.sub(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b", "[REDACTED AWS KEY]", value)
        value = re.sub(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+", "Bearer [REDACTED]", value)
        value = re.sub(
            r'(?i)(["\']?(?:authorization|api[_-]?key|secret[_-]?access[_-]?key|session[_-]?token)["\']?\s*[:=]\s*)["\']?[^\s,"\'<>]+["\']?',
            r"\1[REDACTED]",
            value,
        )
        return value
    return value
