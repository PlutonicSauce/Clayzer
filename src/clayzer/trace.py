"""Traces: the complete, ordered record of one Run (ADR-0001).

One JSONL file per Run, one event per line: `run_start`, then a `step` per model turn or tool
call, then `run_end`. The shapes follow the Sandbox's (breaking-barriers tracing/base.py), so
its summarizer and Workflow Score can read these Traces.

A Step keeps everything needed to judge the Run later without running it again: the full
request (prompt text, settings, tool names; the image as its store key and hash, not its
bytes), the full response, wall time and the provider's own latency, tokens, retries (with the
error code of each failed attempt), and, for a failed call, its error code and HTTP status.
Attributing a failure to the Harness or the environment (ADR-0003) is done from these fields
afterwards, not here.

Judge calls are recorded too, with `role: scoring`, so a Workflow Score can leave them out:
they're the evaluation's work, not the Harness's.

Sinks receive the Trace: the store sink writes it next to the Batch, and other backends (an
OpenTelemetry export, REQ-11) can be added without touching scoring.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Protocol

StepKind = Literal["llm", "tool", "judge"]
RunStatus = Literal["running", "ok", "harness_fault", "sandbox_failure", "stopped"]


@dataclass
class RunInfo:
    run_id: str
    task: str
    case_id: str
    repeat: int
    batch_id: str
    model_id: str
    prompt_sha: str
    tools: list[str] = field(default_factory=list)
    started_at: float = 0.0
    ended_at: float | None = None
    final_answer: str | None = None
    status: RunStatus = "running"
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Step:
    run_id: str
    index: int
    kind: StepKind
    name: str
    started_at: float
    ended_at: float
    input: Any = None
    output: Any = None
    error: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)

    @property
    def latency_ms(self) -> float:
        return (self.ended_at - self.started_at) * 1000


class TraceSink(Protocol):
    def write(self, run: RunInfo, steps: list[Step]) -> None: ...


class StoreSink:
    """Writes each Run's Trace to `batches/<batch-id>/traces/<case-id>--r<repeat>.jsonl`."""

    def __init__(self, store):
        self.store = store

    def write(self, run: RunInfo, steps: list[Step]) -> None:
        self.store.put(trace_key(run.batch_id, run.case_id, run.repeat), dumps(run, steps),
                       "application/x-ndjson")  # fmt: skip


def trace_key(batch_id: str, case_id: str, repeat: int) -> str:
    # `#` would need escaping in URLs, so the file name spells the Repeat out.
    return f"batches/{batch_id}/traces/{case_id}--r{repeat}.jsonl"


def dumps(run: RunInfo, steps: list[Step], *, final: bool = True) -> bytes:
    def line(event: str, data: Any) -> str:
        return json.dumps({"event": event, "data": data}, default=str) + "\n"

    start = {**asdict(run), "status": "running", "ended_at": None, "final_answer": None}
    body = [line("run_start", start)] + [line("step", asdict(s)) for s in steps]
    if final:
        body.append(line("run_end", asdict(run)))
    return "".join(body).encode()


def loads(body: bytes) -> tuple[RunInfo, list[Step]]:
    """Read a Trace. A Run that stopped mid-way still loads, with status `running`."""
    run, steps = None, []
    for raw in body.decode().splitlines():
        if not raw.strip():
            continue
        record = json.loads(raw)
        if record["event"] in ("run_start", "run_end"):
            run = RunInfo(**record["data"])
        elif record["event"] == "step":
            steps.append(Step(**record["data"]))
    if run is None:
        raise ValueError("Trace has no run_start event")
    return run, steps


def image_ref(key: str, data: bytes) -> dict:
    """How a Step records an image: where it lives and what it was, not its bytes."""
    return {"key": key, "sha256": hashlib.sha256(data).hexdigest()[:16], "bytes": len(data)}


# ── Recording ───────────────────────────────────────────────────────────────────────────

# botocore retries failed attempts itself; this collects each failed attempt's error code for
# the Step being recorded on this thread.
_attempts = threading.local()


def _on_needs_retry(response=None, attempts=None, caught_exception=None, **kwargs):
    log = getattr(_attempts, "log", None)
    if log is None:
        return
    if caught_exception is not None:
        log.append({"attempt": attempts, "error": type(caught_exception).__name__})
    elif response is not None:
        http, parsed = response
        status = getattr(http, "status_code", None)
        if status and status >= 400:
            code = (parsed or {}).get("Error", {}).get("Code")
            log.append({"attempt": attempts, "http_status": status, "error": code})
    return  # never decide the retry; botocore's own handler does


def watch_retries(client) -> None:
    """Hook a boto3 client so Steps can record each failed attempt that botocore retried."""
    events = getattr(getattr(client, "meta", None), "events", None)
    if events is not None and not getattr(client, "_clayzer_watched", False):
        events.register("needs-retry.bedrock-runtime", _on_needs_retry)
        client._clayzer_watched = True


class Tracer:
    """Collects one Run's Steps, then hands the finished Trace to the sinks."""

    def __init__(self, run: RunInfo, sinks: list[TraceSink]):
        self.run, self.sinks, self.steps = run, sinks, []
        self.run.started_at = time.time()

    def converse(
        self,
        client,
        kind: StepKind,
        name: str,
        request: dict,
        recorded_input: dict,
        attributes: dict | None = None,
    ):
        """Call Bedrock Converse and record it as a Step. Re-raises the call's error after
        recording it. `attributes` are added to the Step's (e.g. `expects_tool`)."""
        extra = attributes or {}
        _attempts.log = []
        started = time.time()
        try:
            resp = client.converse(**request)
        except Exception as e:
            ended = time.time()
            meta = (
                getattr(e, "response", {}).get("ResponseMetadata", {})
                if hasattr(e, "response")
                else {}
            )
            err = getattr(e, "response", {}).get("Error", {}) if hasattr(e, "response") else {}
            self._add(kind, name, started, ended, recorded_input, None,
                      f"{type(e).__name__}: {e}"[:1000], {
                          "error_code": err.get("Code") or type(e).__name__,
                          "http_status": meta.get("HTTPStatusCode"),
                          "request_id": meta.get("RequestId"),
                          "retries": meta.get("RetryAttempts", len(_attempts.log)),
                          "failed_attempts": _attempts.log,
                          **extra,
                      })  # fmt: skip
            _attempts.log = None
            raise
        ended = time.time()
        meta = resp.get("ResponseMetadata", {})
        usage = resp.get("usage", {})
        self._add(kind, name, started, ended, recorded_input, {
            "content": resp.get("output", {}).get("message", {}).get("content", []),
            "stop_reason": resp.get("stopReason"),
        }, None, {
            "model_id": request.get("modelId"),
            "usage": usage,
            "provider_latency_ms": resp.get("metrics", {}).get("latencyMs"),
            "http_status": meta.get("HTTPStatusCode"),
            "request_id": meta.get("RequestId"),
            "retries": meta.get("RetryAttempts", len(_attempts.log)),
            "failed_attempts": _attempts.log,
            # Cost is tokens and time on Bedrock; GPU time only when self-hosted (CAP-12).
            "cost": {"input_tokens": usage.get("inputTokens"),
                     "output_tokens": usage.get("outputTokens"), "gpu_seconds": None},
            **extra,
        })  # fmt: skip
        _attempts.log = None
        return resp

    def tool(
        self,
        name: str,
        arguments: dict,
        started: float,
        ended: float,
        output=None,
        error: str | None = None,
        attributes: dict | None = None,
    ) -> None:
        """Record an MCP tool call made by the Harness."""
        self._add("tool", name, started, ended, arguments, output, error, attributes or {})

    def _add(self, kind, name, started, ended, input_, output, error, attributes) -> None:
        if kind == "judge":
            attributes = {**attributes, "role": "scoring"}
        attributes["latency_ms"] = round((ended - started) * 1000, 1)
        self.steps.append(Step(self.run.run_id, len(self.steps), kind, name, started, ended,
                               input_, output, error, attributes))  # fmt: skip

    def finish(
        self, status: RunStatus, final_answer: str | None = None, error: str | None = None
    ) -> dict:
        """Attribute faults (ADR-0003), write the Trace to every sink, and return the counts."""
        from clayzer.faults import attribute

        self.run.ended_at = time.time()
        self.run.status, self.run.final_answer, self.run.error = status, final_answer, error
        counts = attribute(self.steps)
        self.run.metadata["faults"] = counts
        for sink in self.sinks:
            sink.write(self.run, self.steps)
        return counts
