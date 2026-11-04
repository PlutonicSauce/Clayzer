"""Standalone Gateway-backed AgentCore HTTP adapter for the caption Harness (AWS-11).

Deployment fixes the store, model and MCP gateway. Requests contain only a Chip id;
neither a Case nor an Answer Key is accepted. AgentCore authenticates inbound calls
with IAM. Outbound Gateway calls use a confidential Cognito client: Gateway requires
JWT inbound authentication for LGND's authorization-code OAuth.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
import uuid
from contextlib import contextmanager, nullcontext
from pathlib import Path

from clayzer import harness
from clayzer.agentcore_trace import BoundedTools, RunFailure, RuntimeSink, RuntimeTracer
from clayzer.tools import McpServer, Toolbox, ToolView
from clayzer.trace import RunInfo, watch_retries

_CHIP_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}")
ALLOWED_TOOLS = frozenset(
    "lgnd___" + name
    for name in (
        "discover_area_shift_find",
        "discover_area_view",
        "discover_node_compare",
        "discover_space_zoom",
        "discover_time_zoom",
        "reasoning_change_view",
        "reasoning_chip_view",
        "reasoning_imagery_check",
        "search_change_find",
        "search_chip_lat_lon",
        "search_place_find",
        "search_similar_change_find",
        "toolbox_classifier_apply",
        "toolbox_classifier_get",
        "toolbox_classifier_list",
    )
)


def chip_id_from(payload: dict) -> str:
    """Reject arbitrary store paths and caller-supplied prompts, labels or settings."""
    if not isinstance(payload, dict) or set(payload) != {"chip_id"}:
        raise ValueError("provide only chip_id")
    chip_id = payload["chip_id"]
    if not isinstance(chip_id, str) or not _CHIP_ID.fullmatch(chip_id):
        raise ValueError("chip_id must contain only letters, digits, underscores and dashes")
    return chip_id


def gateway_auth(session, secret_arn: str):
    """Get Gateway JWTs using the execution role's Secrets Manager credential.

    The secret contains token_endpoint, client_id, client_secret and scope.
    LGND's sign-in is separate: AgentCore Identity owns those OAuth tokens.
    """
    import asyncio

    import httpx2
    from botocore.config import Config

    from clayzer.mcp_auth import http_client

    credential = json.loads(
        session.client(
            "secretsmanager",
            config=Config(connect_timeout=5, read_timeout=10, retries={"total_max_attempts": 2}),
        ).get_secret_value(SecretId=secret_arn)["SecretString"]
    )
    if not credential["token_endpoint"].startswith("https://"):
        raise ValueError("Gateway token endpoint must use HTTPS")

    class GatewayAuth(httpx2.Auth):
        requires_request_body = True

        def __init__(self):
            self.token = None
            self.expires_at = 0.0
            self.lock = asyncio.Lock()

        async def access_token(self, force=False):
            async with self.lock:
                if force or time.monotonic() >= self.expires_at:
                    async with http_client() as client:
                        response = await client.post(
                            credential["token_endpoint"],
                            auth=(credential["client_id"], credential["client_secret"]),
                            data={"grant_type": "client_credentials", "scope": credential["scope"]},
                        )
                        token = response.raise_for_status().json()
                    self.token = token["access_token"]
                    self.expires_at = time.monotonic() + max(0, token.get("expires_in", 300) - 30)
                return self.token

        async def async_auth_flow(self, request):
            request.headers["Authorization"] = f"Bearer {await self.access_token()}"
            response = yield request
            if response.status_code == 401:
                request.headers["Authorization"] = f"Bearer {await self.access_token(force=True)}"
                yield request

    return GatewayAuth()


@contextmanager
def gateway_tools(url: str, session, secret_arn: str, elicitation_callback=None, http_auth=None):
    """Connect only to the deployment's gateway, never a URL supplied by a caller."""
    from urllib.parse import urlparse

    parsed = urlparse(url)
    expected = f".gateway.bedrock-agentcore.{session.region_name}.amazonaws.com"
    if parsed.scheme != "https" or not (parsed.hostname or "").endswith(expected):
        raise ValueError("CLAYZER_AGENTCORE_GATEWAY must be an AgentCore Gateway HTTPS URL")

    async def decline_consent(_context, _params):
        from mcp.types import ElicitResult

        # Hosted caption Runs never authorize interactively. Use authorize-caller first.
        return ElicitResult(action="decline")

    with Toolbox(
        [McpServer("gateway", url=url)],
        http_auth=http_auth if http_auth is not None else gateway_auth(session, secret_arn),
        elicitation_callback=elicitation_callback or decline_consent,
        allowed_tools=ALLOWED_TOOLS,
        connect_timeout=45,
    ) as box:
        # LGND also exposes account-management tools such as user_alias_set.
        # The captioner gets only the geospatial tool groups from the named LGND target.
        specs = [tool for tool in box.specs if tool.name in ALLOWED_TOOLS]
        if not specs:
            raise RuntimeError("AgentCore Gateway exposed no tools")
        yield ToolView(box, specs)


def run_caption(
    payload, store, client, model: str, toolbox, *, seconds: float = 600, access_check=None
) -> dict:
    """Run the bounded agentic loop and persist its full Trace, including failures."""
    chip_id = chip_id_from(payload)
    batch_id = f"agentcore-{uuid.uuid4().hex}"
    prefix = f"runs/agentcore/{batch_id}"
    key = f"{prefix}/trace.jsonl"
    image_key = f"chips/{chip_id}.png"
    run = RunInfo(
        run_id=f"{batch_id}/{chip_id}#1",
        task="caption",
        case_id=chip_id,
        repeat=1,
        batch_id=batch_id,
        model_id=model,
        prompt_sha=hashlib.sha256((harness.PROMPT + harness.TOOLS_NOTE).encode()).hexdigest(),
        started_at=time.time(),
        metadata={"hosting": "agentcore", "standalone": True},
    )
    build = Path(__file__).with_name("agentcore_build.json")
    if build.exists():
        run.metadata["build"] = json.loads(build.read_text())
    tracer = RuntimeTracer(run, RuntimeSink(store, key), seconds)
    watch_retries(client)
    try:
        tracer.checkpoint()
        tracer.check_deadline()
        if access_check is not None:
            run.metadata["case_read_denied"] = access_check()
            tracer.checkpoint()
        png = store.get(image_key)
        # Opening the gateway is part of the Run, so an OAuth/connect failure leaves a Trace.
        with toolbox() if callable(toolbox) else nullcontext(toolbox) as box:
            if box is None or not box.specs:
                raise RuntimeError("AgentCore Gateway exposed no tools")
            tracer.run.metadata["gateway_versions"] = getattr(
                getattr(box, "box", box), "versions", {}
            )
            bounded = BoundedTools(box, tracer)
            _check_lgnd(bounded, tracer)
            cap, summary = harness.caption(
                client, model, chip_id, png, tracer=tracer, image_key=image_key, toolbox=bounded
            )
        result = {
            "status": "ok",
            "caption": cap,
            "summary": summary,
            "trace_key": key,
            "run_id": run.run_id,
            "batch_id": batch_id,
        }
        # The Trace's run_end is the completion authority: S3 has no atomic multi-object write.
        artifact = {k: v for k, v in result.items() if k != "status"}
        store.put(f"{prefix}/caption.json", json.dumps(artifact).encode(), "application/json")
        tracer.finish("ok", final_answer=cap["text"])
    except Exception as exc:
        status = "harness_fault" if isinstance(exc, harness.HarnessFault) else "stopped"
        saved = True
        try:
            tracer.finish(status, error=f"{type(exc).__name__}: {exc}")
        except Exception:  # noqa: BLE001 - preserve the Run locator when storage is unavailable
            saved = False
        raise RunFailure(run, key, saved) from exc
    return result


def _check_lgnd(box: BoundedTools, tracer: RuntimeTracer) -> None:
    """Fail before paying for inference if the runtime's LGND consent is not usable.

    This read-only readiness call is marked as setup, not as a model-selected action.
    Its Trace proves the complete hosted path, including Gateway's LGND OAuth token.
    """
    name = "lgnd___toolbox_classifier_list"
    started = time.time()
    result = box.call(name, {})
    tracer.tool(
        name,
        {},
        started,
        time.time(),
        result.text,
        result.text if result.is_error else None,
        {
            "role": "setup",
            "server": "gateway",
            "is_error": result.is_error,
            "error_code": result.error_code,
        },
    )
    if result.is_error:
        raise RuntimeError("LGND readiness check failed")


def create_app(execute=None):
    """AgentCore HTTP contract: GET /ping and POST /invocations on port 8080."""
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import JSONResponse

    app = FastAPI()

    @app.get("/ping")
    def ping():
        return {"status": "Healthy"}

    @app.post("/invocations")
    def invocations(payload: dict):
        try:
            chip_id_from(payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        try:
            return (execute or execute_remote)(payload)
        except RunFailure as exc:
            # AgentCore replaces non-2xx application bodies with RuntimeClientError.
            # A failed Run is a domain outcome: keep its locator in the successful envelope.
            return JSONResponse(content={"detail": str(exc), **exc.details})
        except Exception as exc:
            # Trace contains the diagnostic; never echo credentials or SDK wire data.
            raise HTTPException(status_code=500, detail="caption run failed") from exc

    return app


def execute_remote(payload: dict) -> dict:
    import boto3
    from botocore.config import Config

    from clayzer.config import Settings
    from clayzer.store import S3Store

    # Deliberately do not load .env on the service: use its execution role.
    # boto3 reads AWS_DEFAULT_REGION; AgentCore documents AWS_REGION.
    if os.environ.get("AWS_REGION"):
        os.environ.setdefault("AWS_DEFAULT_REGION", os.environ["AWS_REGION"])
    settings = Settings.from_env()
    if not settings.store_url or not settings.store_url.startswith("s3://"):
        raise ValueError("AgentCore requires CLAYZER_STORE=s3://bucket/prefix")
    session = boto3.Session()
    store = S3Store(
        settings.store_url,
        session.client(
            "s3",
            config=Config(connect_timeout=5, read_timeout=10, retries={"total_max_attempts": 2}),
        ),
    )
    return run_caption(
        payload,
        store,
        session.client(
            "bedrock-runtime",
            config=Config(
                connect_timeout=5,
                read_timeout=35,
                retries={"mode": "standard", "total_max_attempts": 2},
            ),
        ),
        settings.caption_model,
        lambda: gateway_tools(
            os.environ["CLAYZER_AGENTCORE_GATEWAY"],
            session,
            os.environ["CLAYZER_AGENTCORE_GATEWAY_SECRET"],
        ),
        access_check=(lambda: _check_case_boundary(store))
        if os.environ.get("CLAYZER_AGENTCORE_VALIDATE_IAM") == "1"
        else None,
    )


def _check_case_boundary(store) -> bool:
    """HEAD a provisioned, harmless canary using the actual runtime role; never read labels."""
    from botocore.exceptions import ClientError

    try:
        store.s3.head_object(
            Bucket=store.bucket, Key=store._key("cases/agentcore-access-canary.json")
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] in ("403", "AccessDenied"):
            return True
        raise
    raise RuntimeError("Runtime role can read the Cases prefix; refusing to caption")


def authorize_target(gateway_id: str, target_id: str) -> None:
    """Complete the target-discovery consent from the same browser that started it.

    The target's defaultReturnUrl must be http://localhost:33418/callback.
    The random start URL and HttpOnly cookie bind this single local flow to its browser.
    """
    import boto3

    control = boto3.client("bedrock-agentcore-control")
    target = control.get_gateway_target(gatewayIdentifier=gateway_id, targetId=target_id)
    authorization = target.get("authorizationData", {}).get("oauth2")
    if not authorization:
        raise ValueError("target has no pending authorization; synchronize it first")

    def status():
        return control.get_gateway_target(gatewayIdentifier=gateway_id, targetId=target_id)[
            "status"
        ]

    _authorize_browser(
        authorization["authorizationUrl"], {"userId": authorization["userId"]}, status
    )


def authorize_caller(gateway_id: str, secret_arn: str, force: bool = False) -> None:
    """Authorize LGND for the runtime's stable Cognito subject, through Gateway elicitation."""
    from urllib.parse import urlparse

    import boto3
    from mcp.types import ElicitResult

    session = boto3.Session()
    gateway = session.client("bedrock-agentcore-control").get_gateway(gatewayIdentifier=gateway_id)
    urls = []

    async def requested(_context, params):
        url = getattr(params, "url", None)
        parsed = urlparse(url or "")
        if parsed.scheme != "https" or parsed.hostname != (
            f"bedrock-agentcore.{session.region_name}.amazonaws.com"
        ):
            return ElicitResult(action="decline")
        urls.append(url)
        # Acknowledge the URL request. OAuth remains blocked on actual browser consent.
        return ElicitResult(action="accept")

    auth = gateway_auth(session, secret_arn)
    meta = {
        "aws.bedrock-agentcore.gateway/credentialProviderConfiguration": {
            "oauthCredentialProvider": {
                "returnUrl": "http://localhost:33418/callback",
                "forceAuthentication": force,
            }
        }
    }
    with gateway_tools(gateway["gatewayUrl"], session, secret_arn, requested, auth) as box:
        result = box.call("lgnd___toolbox_classifier_list", {}, meta=meta)
    urls.extend(result.authorization_urls)
    urls = [
        url
        for url in urls
        if urlparse(url).scheme == "https"
        and urlparse(url).hostname == f"bedrock-agentcore.{session.region_name}.amazonaws.com"
        and urlparse(url).path == "/identities/oauth2/authorize"
    ]
    if not urls:
        if result.is_error:
            raise RuntimeError(result.text)
        print("The runtime's LGND caller is already authorized.", flush=True)
        return
    # Keep the exact JWT used by the tool request. Admin discovery uses userId;
    # Gateway invocation session binding requires the caller's userToken.
    _authorize_browser(urls[0], {"userToken": auth.token})


def _authorize_browser(
    authorization_url: str,
    user_identifier: dict,
    status=None,
    nonce: str | None = None,
    port: int = 33418,
) -> None:
    """Single consent flow with a browser cookie; OAuth session URIs are never logged."""
    import secrets
    from http.cookies import SimpleCookie
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from urllib.parse import parse_qs, urlparse

    import boto3
    from botocore.exceptions import BotoCoreError, ClientError

    identity = boto3.client("bedrock-agentcore")
    nonce = nonce or secrets.token_urlsafe(32)
    completed = False

    class Callback(BaseHTTPRequestHandler):
        def do_GET(self):
            nonlocal completed
            parsed = urlparse(self.path)
            if parsed.path == f"/start/{nonce}":
                self.send_response(302)
                self.send_header("Location", authorization_url)
                self.send_header(
                    "Set-Cookie",
                    f"clayzer_agentcore_oauth={nonce}; HttpOnly; SameSite=Lax; Path=/callback",
                )
                self.end_headers()
                return
            cookies = SimpleCookie(self.headers.get("Cookie", ""))
            cookie = cookies.get("clayzer_agentcore_oauth")
            if (
                parsed.path != "/callback"
                or cookie is None
                or not secrets.compare_digest(cookie.value, nonce)
            ):
                self.send_error(403)
                return
            session_uri = parse_qs(parsed.query).get("session_id", [None])[0]
            if not session_uri:
                self.send_error(400, "Missing authorization session")
                return
            try:
                identity.complete_resource_token_auth(
                    sessionUri=session_uri, userIdentifier=user_identifier
                )
            except (BotoCoreError, ClientError) as exc:
                detail = type(exc).__name__
                if isinstance(exc, ClientError):
                    detail += ": " + exc.response["Error"].get("Message", "")
                    for value in [session_uri, *user_identifier.values()]:
                        if value:
                            detail = detail.replace(value, "[redacted]")
                print(f"OAuth completion failed: {detail}", flush=True)
                self.send_error(502, "Authorization could not be completed")
                return
            completed = True
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(b"LGND authorization completed. You can close this tab.")

        def log_message(self, *_args):
            pass  # OAuth session URIs must not enter logs.

    with HTTPServer(("127.0.0.1", port), Callback) as server:
        server.timeout = 1
        print(
            f"Open http://localhost:{server.server_port}/start/{nonce} to authorize LGND.",
            flush=True,
        )
        deadline = time.monotonic() + 600
        check_at = time.monotonic() + 5
        while not completed and time.monotonic() < deadline:
            server.handle_request()
            if not completed and status is not None and time.monotonic() >= check_at:
                current = status()
                completed = current == "READY"
                if current == "FAILED":
                    raise RuntimeError("LGND target synchronization failed; inspect statusReasons")
                check_at = time.monotonic() + 5
    if not completed:
        raise TimeoutError("LGND authorization was not completed within ten minutes")
    print("LGND authorization completed.", flush=True)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="serve AgentCore's HTTP contract")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8080)
    invoke = sub.add_parser("invoke", help="invoke a deployed runtime using local AWS credentials")
    invoke.add_argument("runtime_arn")
    invoke.add_argument("chip_id")
    authorize = sub.add_parser("authorize", help="complete pending LGND target-discovery consent")
    authorize.add_argument("gateway_id")
    authorize.add_argument("target_id")
    caller = sub.add_parser("authorize-caller", help="authorize LGND for the caption runtime")
    caller.add_argument("gateway_id")
    caller.add_argument("gateway_secret_arn")
    caller.add_argument("--force", action="store_true", help="replace an expired consent session")
    args = parser.parse_args()
    if args.command == "serve":
        import uvicorn

        uvicorn.run(create_app(), host=args.host, port=args.port)
        return

    import boto3
    from botocore.config import Config

    from clayzer.config import load_env

    load_env()
    if args.command == "authorize":
        authorize_target(args.gateway_id, args.target_id)
        return
    if args.command == "authorize-caller":
        authorize_caller(args.gateway_id, args.gateway_secret_arn, args.force)
        return
    payload = {"chip_id": args.chip_id}
    chip_id_from(payload)
    # Invocation retries could duplicate expensive model calls and traces.
    client = boto3.client(
        "bedrock-agentcore",
        config=Config(read_timeout=900, retries={"total_max_attempts": 1}),
    )
    response = client.invoke_agent_runtime(
        agentRuntimeArn=args.runtime_arn,
        runtimeSessionId=str(uuid.uuid4()),
        contentType="application/json",
        payload=json.dumps(payload).encode(),
    )
    with response["response"] as body:
        result = json.loads(body.read())
    print(json.dumps(result, indent=2))
    if result.get("status", "ok") != "ok":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
