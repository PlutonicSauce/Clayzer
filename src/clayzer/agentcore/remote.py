"""The Batch's side of the AgentCore Harness: invoke the Runtime once per Run.

`RemoteHarness.caption` has the same shape as `harness.caption` and returns the same things, so a
Run is scored by exactly the same code whichever Harness produced the Caption. What differs:

- The Batch still reads the Chip, checks its SHA-256 against chips.json, and scores the result.
  The Runtime is sent the Chip's pixels and settings, never the Case (contract.py, ADR-0006).
- The Runtime's Steps are added to the Run's own Trace, so one Trace holds the Run and nothing
  needs AgentCore to replay or score it (ADR-0001). Each is marked as having run remotely.
- Faults keep their meaning (ADR-0003): the model not submitting a Caption is a HarnessFault;
  Bedrock failing inside the Runtime is raised as the ClientError it was, which the Batch already
  treats as a Sandbox Failure; a missing sign-in stops the Batch, as it does locally.
"""

from __future__ import annotations

import urllib.error
import urllib.parse
import urllib.request
import uuid
from http.client import HTTPException

from botocore.exceptions import ClientError

from clayzer import harness
from clayzer.agentcore import contract
from clayzer.agentcore.contract import ContractError, RunRequest, RunResponse
from clayzer.agentcore.inbound import InboundAuth, InboundTokens
from clayzer.mcp_auth import NotSignedIn
from clayzer.trace import Step

# A Run can take minutes: eight model turns, each with tool calls, then verification. The default
# 60 s read timeout would cut it off.
READ_TIMEOUT = 900
SESSION_HEADER = "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id"


def runtime_client(region: str | None = None):
    import boto3
    from botocore.config import Config

    # Retrying an invocation can duplicate model calls and remotely created work.
    config = Config(read_timeout=READ_TIMEOUT, connect_timeout=10,
                    retries={"total_max_attempts": 1, "mode": "standard"})  # fmt: skip
    return boto3.client("bedrock-agentcore", region_name=region, config=config)


def region_of(arn: str) -> str:
    """arn:aws:bedrock-agentcore:<region>:<account>:runtime/<id>"""
    return arn.split(":")[3]


def _invocation_url(runtime_arn: str, qualifier: str = "DEFAULT") -> str:
    region = region_of(runtime_arn)
    encoded = urllib.parse.quote(runtime_arn, safe="")
    return (f"https://bedrock-agentcore.{region}.amazonaws.com/runtimes/{encoded}"
            f"/invocations?qualifier={qualifier}")  # fmt: skip


class RemoteHarness:
    """Runs the Harness in an AgentCore Runtime."""

    def __init__(self, runtime_arn: str, client=None, session_id: str | None = None,
                 inbound: InboundAuth | None = None, opener=None):  # fmt: skip
        self.runtime_arn = runtime_arn
        self._client = client
        # One session for the Batch: the Runtime keeps its tool connections between Runs. The
        # id must be at least 33 characters.
        self.session_id = session_id or f"clayzer-{uuid.uuid4().hex}"
        self.versions: dict = {}  # what the Runtime's MCP servers reported
        self.build: str | None = None  # which build of the Runtime image answered
        # When the endpoint has inbound OAuth, invoke it over HTTPS with a bearer token minted by
        # Cognito (inbound.py). Without it, the SigV4 boto3 call (the client property) is used.
        if inbound is None:
            inbound = InboundAuth.from_env()
        self._opener = opener or urllib.request.build_opener(urllib.request.ProxyHandler())
        # Token minting and the invoke share one opener, so a proxy or custom TLS applies to both.
        self._inbound = InboundTokens(inbound, self._opener) if inbound else None

    @property
    def client(self):
        if self._client is None:
            self._client = runtime_client(region_of(self.runtime_arn))
        return self._client

    def _invoke(self, request: RunRequest) -> RunResponse:
        if self._inbound is not None:
            return self._invoke_https(request)
        reply = self.client.invoke_agent_runtime(
            agentRuntimeArn=self.runtime_arn, runtimeSessionId=self.session_id,
            contentType="application/json", accept="application/json",
            payload=request.to_json(),
        )  # fmt: skip
        with reply["response"] as body:
            return RunResponse.from_json(body.read())

    def _invoke_https(self, request: RunRequest, retry: bool = True) -> RunResponse:
        """Invoke the JWT-protected endpoint with a bearer token. On a 401/403 (an expired
        token), mint a fresh one and retry once; any other HTTP error is an environment fault."""
        try:
            token = self._inbound.token(force=not retry)
            http = urllib.request.Request(
                _invocation_url(self.runtime_arn), data=request.to_json(), method="POST",
                headers={"Content-Type": "application/json", "Accept": "application/json",
                         "Authorization": f"Bearer {token}", SESSION_HEADER: self.session_id},
            )  # fmt: skip
            with self._opener.open(http, timeout=READ_TIMEOUT) as reply:
                return RunResponse.from_json(reply.read())
        except urllib.error.HTTPError as e:
            if e.code in (401, 403) and retry:
                return self._invoke_https(request, retry=False)
            body = e.read().decode(errors="replace")[:300]
            raise ClientError(
                {"Error": {"Code": f"AgentCoreInbound{e.code}", "Message": body}},
                "InvokeAgentRuntime",
            ) from e
        except (OSError, HTTPException) as e:
            raise ClientError(
                {"Error": {"Code": "AgentCoreInboundConnection", "Message": type(e).__name__}},
                "InvokeAgentRuntime",
            ) from e

    def caption(self, cfg, chip: dict, png: bytes, prompt: str, tracer, footprint: dict | None):
        """Caption one Chip in the Runtime. Returns (Caption, step) like harness.caption."""
        request = RunRequest.build(
            chip=chip, png=png, prompt=prompt, model=cfg.caption_model, max_turns=cfg.max_turns,
            tools=cfg.tools, verify=None if isinstance(png, list) else cfg.verify, footprint=footprint,
        )  # fmt: skip
        response = self._invoke(request)
        self.versions = response.tool_versions or self.versions
        self.build = response.build or self.build
        self._merge(tracer, response)
        error = response.error
        if error is None:
            if request.verify:
                actual = response.metadata.get("verification_files", {})
                for key in ("ontology_sha", "verifiers_sha"):
                    expected = getattr(cfg, key, None)
                    # BatchConfig uses the first 12 hex digits; retain the full runtime hash
                    # in the Trace while comparing the same representation.
                    if expected is not None and actual.get(key, "")[:12] != expected:
                        raise ContractError(
                            f"Runtime {key} differs from the Batch; redeploy matching verification data"
                        )
            return response.caption, response.step
        kind, code, message = error["kind"], error["code"], error["message"]
        if kind == contract.HARNESS_FAULT:
            raise harness.HarnessFault(message, response.step or _empty_step(cfg, chip))
        if kind == contract.NOT_SIGNED_IN:
            raise NotSignedIn(message)
        if kind == contract.CONTRACT:
            raise ContractError(f"the Runtime refused the request: {message}")
        # Bedrock failed in the Runtime, or the Runtime itself did: no valid score for the Run.
        # Raised as the ClientError the Batch already sorts into a Sandbox Failure, or a stop if
        # the code says credentials expired.
        raise ClientError({"Error": {"Code": code, "Message": message}}, "RunInAgentCore")

    @staticmethod
    def _merge(tracer, response: RunResponse) -> None:
        """Add the Runtime's Steps to the Run's Trace, as the Batch's own."""
        for raw in response.steps:
            step = Step(**raw)
            step.run_id = tracer.run.run_id
            step.index = len(tracer.steps)
            step.attributes = {**step.attributes, "harness": "agentcore"}
            tracer.steps.append(step)
        if response.tools:
            tracer.run.tools = list(response.tools)
        tracer.run.metadata.update(response.metadata)


def _empty_step(cfg, chip: dict) -> dict:
    return {"step": "caption", "chip_id": chip["id"], "model": cfg.caption_model, "seconds": 0.0,
            "usage": {}, "stop_reason": None, "ok": False}  # fmt: skip
