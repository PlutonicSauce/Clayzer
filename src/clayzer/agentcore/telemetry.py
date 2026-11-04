"""OpenTelemetry spans for the Runtime, for AgentCore Observability.

AgentCore Observability reads OpenTelemetry traces from CloudWatch (once Transaction Search is on).
The ADOT auto-instrumentation (`opentelemetry-instrument`, set up in the Runtime Dockerfile) already
traces the raw Bedrock and HTTP calls. This adds the named, GenAI-convention spans that make a Run
readable as one trace: a parent `caption` span, a child span per model turn, and a child span per
tool call, following the `gen_ai.*` semantic conventions so the GenAI Observability dashboard groups
them.

It is a thin layer over our own Trace (trace.py, ADR-0001), which stays the record of truth: these
spans are an export, lossy by design (no full prompts or tool outputs), for the dashboard. When
OpenTelemetry isn't installed (a local Batch, the tests), every span here is a no-op, so nothing
else changes.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator

try:
    from opentelemetry import trace as _otel

    _tracer = _otel.get_tracer("clayzer.agentcore")
except ImportError:  # OpenTelemetry absent: spans become no-ops
    _tracer = None


@contextlib.contextmanager
def span(name: str, **attributes) -> Iterator[object]:
    """A span with the given name and attributes, or a no-op when OTEL is absent. Exceptions are
    recorded on the span and re-raised."""
    if _tracer is None:
        yield None
        return
    with _tracer.start_as_current_span(name) as s:
        for key, value in attributes.items():
            if value is not None:
                s.set_attribute(key, value)
        try:
            yield s
        except Exception as e:
            s.record_exception(e)
            s.set_status(_status_error(str(e)))
            raise


def set_session(session_id: str) -> object:
    """Attach a session id to every span of this Run, so the dashboard correlates them. Returns a
    context token to detach, or None when OTEL is absent."""
    if _tracer is None:
        return None
    from opentelemetry import baggage, context

    return context.attach(baggage.set_baggage("session.id", session_id))


def detach(token: object) -> None:
    if token is not None:
        from opentelemetry import context

        context.detach(token)


def add_event(name: str, **attributes) -> None:
    if _tracer is None:
        return
    current = _otel.get_current_span()
    current.add_event(name, {k: v for k, v in attributes.items() if v is not None})


def _status_error(message: str):
    from opentelemetry.trace import Status, StatusCode

    return Status(StatusCode.ERROR, message)
