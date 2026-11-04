"""Inbound OAuth on the Runtime endpoint (the JWT authorizer): minting the Cognito token, and
RemoteHarness invoking over HTTPS with it instead of the SigV4 boto3 call. No network or AWS."""

import io
import json
import urllib.error

import pytest
from test_loop import FakeBedrock

from clayzer.agentcore import runtime
from clayzer.agentcore.inbound import InboundAuth, InboundTokens, claims
from clayzer.agentcore.remote import RemoteHarness, _invocation_url
from clayzer.agentcore.runtime import ToolboxCache
from clayzer.trace import RunInfo, Tracer

ARN = "arn:aws:bedrock-agentcore:us-west-2:123456789012:runtime/clayzer-test"
CHIP = {"id": "c-solar", "uri": "chips/c-solar.png", "date": "2022-07-02", "bbox": [0, 0, 1, 1]}
AUTH = InboundAuth(
    token_url="https://pool.auth.us-west-2.amazoncognito.com/oauth2/token",
    client_id="client-abc",
    client_secret="shh",
    scope="clayzer-runtime/invoke",
)


def tracer():
    run = RunInfo(run_id="r#1", task="caption", case_id="c", repeat=1, batch_id="b",
                  model_id="m", prompt_sha="p")  # fmt: skip
    return Tracer(run, [])


def cfg():
    return type("Cfg", (), {"caption_model": "cap", "max_turns": 8, "tools": [], "verify": None})()


class FakeOpener:
    """Stands in for urllib: records requests and plays back queued token responses. Invoke
    requests (not to /oauth2/token) are handed to `on_invoke` if set."""

    def __init__(self, *token_responses, on_invoke=None):
        self.responses, self.requests, self.on_invoke = list(token_responses), [], on_invoke

    def open(self, request, timeout=None):
        self.requests.append(request)
        if not request.full_url.endswith("/oauth2/token") and self.on_invoke is not None:
            return self.on_invoke(request, timeout)
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return io.BytesIO(r if isinstance(r, bytes) else json.dumps(r).encode())


def token_response(value="tok-1", ttl=3600):
    return {"access_token": value, "token_type": "Bearer", "expires_in": ttl}


def http_error(code, body=b"denied"):
    return urllib.error.HTTPError("https://x", code, "no", {}, io.BytesIO(body))


# ── Minting the token ───────────────────────────────────────────────────────────────────


def test_a_client_credentials_token_is_minted_with_basic_auth_and_scope():
    opener = FakeOpener(token_response("tok-1"))
    assert InboundTokens(AUTH, opener).token() == "tok-1"
    req = opener.requests[0]
    assert req.full_url == AUTH.token_url and req.method == "POST"
    assert req.headers["Authorization"].startswith("Basic ")  # client id:secret, not in the body
    body = req.data.decode()
    assert "grant_type=client_credentials" in body and "scope=clayzer-runtime" in body
    assert b"shh" not in req.data  # the secret rides in the header, not the form body


def test_the_token_is_cached_until_it_nears_expiry_then_re_minted():
    opener = FakeOpener(token_response("tok-1", ttl=3600), token_response("tok-2", ttl=3600))
    tokens = InboundTokens(AUTH, opener)
    assert tokens.token() == "tok-1" and tokens.token() == "tok-1"  # second call is cached
    assert len(opener.requests) == 1
    assert tokens.token(force=True) == "tok-2"  # forced refresh mints again


def test_a_token_that_expires_immediately_is_re_minted_each_call():
    opener = FakeOpener(token_response("a", ttl=0), token_response("b", ttl=0))
    tokens = InboundTokens(AUTH, opener)
    assert tokens.token() == "a" and tokens.token() == "b"


def test_claims_reads_the_payload_without_verifying():
    # header.payload.signature; the middle is base64url JSON.
    import base64

    payload = base64.urlsafe_b64encode(
        json.dumps({"client_id": "c", "scope": "s"}).encode()
    ).decode()
    assert claims(f"h.{payload}.sig") == {"client_id": "c", "scope": "s"}


def test_inbound_auth_from_env_is_none_until_all_three_are_set(monkeypatch):
    for v in ("TOKEN_URL", "CLIENT_ID", "CLIENT_SECRET", "SCOPE"):
        monkeypatch.delenv(f"CLAYZER_AGENTCORE_INBOUND_{v}", raising=False)
    assert InboundAuth.from_env() is None
    monkeypatch.setenv("CLAYZER_AGENTCORE_INBOUND_TOKEN_URL", AUTH.token_url)
    monkeypatch.setenv("CLAYZER_AGENTCORE_INBOUND_CLIENT_ID", "client-abc")
    assert InboundAuth.from_env() is None  # still missing the secret
    monkeypatch.setenv("CLAYZER_AGENTCORE_INBOUND_CLIENT_SECRET", "shh")
    got = InboundAuth.from_env()
    assert got.client_id == "client-abc" and got.scope == ""  # scope optional


# ── RemoteHarness over HTTPS ──────────────────────────────────────────────────────────────


def test_the_invocation_url_encodes_the_arn():
    url = _invocation_url(ARN)
    assert url.startswith("https://bedrock-agentcore.us-west-2.amazonaws.com/runtimes/")
    assert "arn%3Aaws%3Abedrock-agentcore" in url and url.endswith("?qualifier=DEFAULT")


def test_with_inbound_auth_the_runtime_is_called_over_https_with_a_bearer_token():
    # The agent code runs in-process so the response is real; only the transport is faked.
    def answer(request, timeout=None):
        body = runtime.answer(request.data, FakeBedrock(), ToolboxCache())
        return io.BytesIO(body.to_json())

    opener = FakeOpener(token_response("tok-1"), on_invoke=answer)
    h = RemoteHarness(ARN, inbound=AUTH, opener=opener)
    cap, step = h.caption(cfg(), CHIP, b"c-solar", "p {grid} {objects} {relations}", tracer(), None)
    assert cap["objects"][0]["object"] == "solar_array" and step["ok"]
    invokes = [r for r in opener.requests if "/invocations" in r.full_url]
    assert len(invokes) == 1
    invoke = invokes[0]
    assert invoke.headers["Authorization"] == "Bearer tok-1"
    assert invoke.full_url.startswith("https://bedrock-agentcore.us-west-2.amazonaws.com/runtimes/")
    assert "x-amzn-bedrock-agentcore-runtime-session-id" in {k.lower() for k in invoke.headers}


def test_without_inbound_auth_the_sigv4_boto3_path_is_used(monkeypatch):
    monkeypatch.delenv("CLAYZER_AGENTCORE_INBOUND_TOKEN_URL", raising=False)

    class FakeBoto:
        def __init__(self):
            self.called = False

        def invoke_agent_runtime(self, **kw):
            self.called = True
            body = runtime.answer(kw["payload"], FakeBedrock(), ToolboxCache())
            return {"response": io.BytesIO(body.to_json())}

    boto = FakeBoto()
    h = RemoteHarness(ARN, client=boto)
    cap, _ = h.caption(cfg(), CHIP, b"c-solar", "p", tracer(), None)
    assert boto.called and cap["objects"][0]["object"] == "solar_array"


def test_a_401_mints_a_fresh_token_and_retries_once():
    calls = {"n": 0}

    def answer(request, timeout=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise http_error(401, b"expired")
        body = runtime.answer(request.data, FakeBedrock(), ToolboxCache())
        return io.BytesIO(body.to_json())

    opener = FakeOpener(token_response("stale"), token_response("fresh"), on_invoke=answer)
    h = RemoteHarness(ARN, inbound=AUTH, opener=opener)
    cap, _ = h.caption(cfg(), CHIP, b"c-solar", "p", tracer(), None)
    assert cap["objects"][0]["object"] == "solar_array"
    bearers = [r.headers["Authorization"] for r in opener.requests if "/invocations" in r.full_url]
    assert bearers == ["Bearer stale", "Bearer fresh"]  # retried with a new token


def test_a_persistent_403_becomes_an_environment_fault():
    from botocore.exceptions import ClientError

    def answer(request, timeout=None):
        raise http_error(403, b"forbidden")

    opener = FakeOpener(token_response("a"), token_response("b"), on_invoke=answer)
    h = RemoteHarness(ARN, inbound=AUTH, opener=opener)
    with pytest.raises(ClientError) as e:
        h.caption(cfg(), CHIP, b"c-solar", "p", tracer(), None)
    # A ClientError is what the Batch already treats as a Sandbox Failure (excluded, retried).
    assert "AgentCoreInbound403" in e.value.response["Error"]["Code"]
