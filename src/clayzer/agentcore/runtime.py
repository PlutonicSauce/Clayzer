"""The app inside an AgentCore Runtime container: one Harness Run per request.

AgentCore starts the container and sends it HTTP: `GET /ping` for health and `POST /invocations`
for work. This answers a `/invocations` request by running exactly the code a local Batch runs,
`harness.caption`, then returns the Caption and every Step (contract.py). It does not score, write
to the store, or hold the Case's Reference Labels: it is sent a Chip and nothing else, and its role
can't reach the store (ADR-0006).

Tool servers are connected on first use and kept for later requests, because starting them is
slow (LGND Geo is an HTTPS handshake, RODA a package launch) and a Batch sends many Runs to one
session. The LGND sign-in comes from AgentCore Identity (CLAYZER_TOKEN_SOURCE=agentcore), fetched
with this Runtime's own IAM role.

    python -m clayzer.agentcore.runtime
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from botocore.exceptions import BotoCoreError, ClientError

from clayzer import harness
from clayzer.agentcore import contract, telemetry
from clayzer.agentcore.contract import ContractError, RunRequest, RunResponse
from clayzer.mcp_auth import NotSignedIn
from clayzer.trace import RunInfo, Tracer, watch_retries

PORT = 8080


class ToolboxCache:
    """MCP connections kept between requests, one Toolbox per combination of servers."""

    def __init__(self, factory=None):
        if factory is None:
            from clayzer.tools import Toolbox

            factory = Toolbox.named
        self.factory = factory
        self._boxes: dict[tuple, object] = {}
        self._lock = threading.Lock()

    def get(self, tools: list[str], verify: str | None):
        """(the model's tools, the verifier, what the servers reported); None for no tools."""
        servers = tuple(dict.fromkeys([*tools, *([verify] if verify else [])]))
        if not servers:
            return None, None, {}
        with self._lock:
            box = self._boxes.get(servers)
            if box is None:
                box = self.factory(list(servers))
                box.__enter__()  # may raise NotSignedIn; nothing is cached then
                self._boxes[servers] = box
        return (
            box.view(tools) if tools else None,
            box.view([verify]) if verify else None,
            dict(box.versions),
        )

    def reset(self) -> None:
        """Drop every connection, so the next request makes fresh ones."""
        with self._lock:
            boxes, self._boxes = list(self._boxes.values()), {}
        for box in boxes:
            try:
                box.__exit__(None, None, None)
            except Exception as e:  # noqa: BLE001 - closing a dead connection may fail
                print(f"note: closing a tool connection failed: {type(e).__name__}", flush=True)


def build() -> str:
    return os.environ.get("CLAYZER_BUILD", "unknown")


def _response(tracer: Tracer, versions: dict, **rest) -> RunResponse:
    """A response carrying the Steps recorded so far, success or not."""
    return RunResponse(
        steps=[asdict(s) for s in tracer.steps],
        tools=list(tracer.run.tools),
        metadata=json.loads(json.dumps(tracer.run.metadata, default=str)),
        tool_versions=versions,
        build=build(),
        **rest,
    )


def run_request(request: RunRequest, client, cache: ToolboxCache) -> RunResponse:
    """One Run: the Harness, exactly as a local Batch runs it."""
    png = request.png()
    tracer = Tracer(
        RunInfo(run_id=f"agentcore#{request.chip_id}", task="caption", case_id=request.chip_id,
                repeat=0, batch_id="agentcore", model_id=request.model, prompt_sha="", tools=[]),
        [],
    )  # fmt: skip
    versions: dict = {}
    # One parent span per Run for AgentCore Observability (telemetry.py). The ADOT
    # auto-instrumentation traces the Bedrock and tool-server HTTP calls underneath it; after the
    # Run, each Trace Step becomes a child span so the tool call and each model turn are visible.
    with telemetry.span(
        "caption", **{"gen_ai.operation.name": "caption", "gen_ai.request.model": request.model,
                      "clayzer.chip_id": request.chip_id, "clayzer.tools": ",".join(request.tools),
                      "clayzer.verify": request.verify or ""},
    ):  # fmt: skip
        try:
            model_tools, verifier, versions = cache.get(request.tools, request.verify)
            cap, step = harness.caption(
                client, request.model, request.chip_id, png, request.prompt, tracer,
                request.image_key, model_tools, request.max_turns, verifier, request.footprint,
            )  # fmt: skip
            _spans_from_trace(tracer)
            telemetry.add_event(
                "caption.submitted", **{"gen_ai.response.finish_reason": "submit_caption"}
            )
            return _response(tracer, versions, caption=cap, step=step)
        except harness.HarnessFault as e:
            _spans_from_trace(tracer)
            telemetry.add_event("caption.harness_fault", **{"error.message": str(e)[:200]})
            return _response(
                tracer, versions, step=e.step,
                error={"kind": contract.HARNESS_FAULT, "code": "HarnessFault", "message": str(e)[:1000]},
            )  # fmt: skip
        except NotSignedIn as e:
            return RunResponse.failure(contract.NOT_SIGNED_IN, "NotSignedIn", str(e), build=build())
        except (ClientError, BotoCoreError) as e:
            _spans_from_trace(tracer)
            code = e.response["Error"]["Code"] if isinstance(e, ClientError) else type(e).__name__
            return _response(
                tracer, versions,
                error={"kind": contract.BEDROCK, "code": code, "message": str(e)[:1000]},
            )  # fmt: skip


def _spans_from_trace(tracer) -> None:
    """Emit one child span per recorded Step, so the OTEL trace shows each model turn and tool
    call. The Trace itself (trace.py) is the full record; these are the readable export."""
    for s in tracer.steps:
        a = s.attributes or {}
        if s.kind == "tool":
            attrs = {"gen_ai.operation.name": "execute_tool", "gen_ai.tool.name": s.name,
                     "clayzer.tool.server": a.get("server"), "clayzer.tool.is_error": a.get("is_error"),
                     "clayzer.tool.error_code": a.get("error_code")}  # fmt: skip
        elif s.kind == "llm":
            usage = a.get("usage") or {}
            attrs = {"gen_ai.operation.name": "chat", "gen_ai.request.model": a.get("model_id"),
                     "gen_ai.usage.input_tokens": usage.get("inputTokens"),
                     "gen_ai.usage.output_tokens": usage.get("outputTokens")}  # fmt: skip
        else:
            attrs = {"gen_ai.operation.name": s.kind}
        attrs["clayzer.latency_ms"] = a.get("latency_ms")
        with telemetry.span(f"{s.kind}.{s.name}", **attrs):
            pass


def answer(body: bytes, client, cache: ToolboxCache) -> RunResponse:
    """The response to one request body. Always a structured response, never an exception, so the
    caller can tell a Harness Fault from a mismatch from an outage by what the body says rather
    than by guessing at HTTP codes."""
    try:
        return run_request(RunRequest.from_json(body), client, cache)
    except ContractError as e:
        return RunResponse.failure(contract.CONTRACT, "ContractError", str(e), build=build())
    except Exception as e:  # noqa: BLE001 - report it; one bad Run must not kill the server
        cache.reset()  # a broken connection would fail every later Run
        return RunResponse.failure(contract.INTERNAL, type(e).__name__, str(e), build=build())


class Handler(BaseHTTPRequestHandler):
    server_version = "clayzer-agentcore"
    client = None  # set by serve()
    cache: ToolboxCache | None = None
    busy = 0
    _count = threading.Lock()

    def _send(self, code: int, body: bytes) -> None:
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/ping":
            # AgentCore asks while a long Run is going; say so rather than look unhealthy.
            status = "HealthyBusy" if type(self).busy else "Healthy"
            return self._send(200, json.dumps({"status": status}).encode())
        self._send(404, b'{"error": "not found"}')

    def do_POST(self) -> None:
        if self.path != "/invocations":
            return self._send(404, b'{"error": "not found"}')
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        # Tie every span of this Run to the caller's session, so the dashboard groups a Batch's
        # Runs together (the header AgentCore forwards, or OTEL's own trace otherwise).
        session = self.headers.get("X-Amzn-Bedrock-AgentCore-Runtime-Session-Id")
        token = telemetry.set_session(session) if session else None
        with type(self)._count:
            type(self).busy += 1
        try:
            response = answer(body, type(self).client, type(self).cache)
        finally:
            with type(self)._count:
                type(self).busy -= 1
            telemetry.detach(token)
        self._send(200, response.to_json())

    def log_message(self, fmt, *args) -> None:  # one line per request, to the container log
        print(f"{self.address_string()} {fmt % args}", flush=True)


def serve(port: int = PORT, client=None, cache: ToolboxCache | None = None) -> None:
    if client is None:
        from clayzer.config import Settings, bedrock

        client = bedrock(Settings.from_env())
        watch_retries(client)
    Handler.client, Handler.cache = client, cache or ToolboxCache()
    print(f"clayzer runtime (build {build()}) listening on :{port}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()


if __name__ == "__main__":
    serve()
