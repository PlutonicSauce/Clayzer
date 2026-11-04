"""AgentCore Identity holds the LGND sign-in (task agentcore-identity-token): fetching the token,
the one-time approval, and registering the OAuth client. Fakes stand in for AWS and for LGND's
sign-in server, so none of this needs a network."""

import asyncio
import importlib.util

import pytest
from botocore.exceptions import ClientError

from clayzer import cli, mcp_auth
from clayzer.agentcore import identity
from clayzer.agentcore.identity import (
    IdentitySettings,
    IdentityTokens,
    SignIn,
    ensure_oauth_client,
    ensure_workload_identity,
    login,
    session_from_callback,
)
from clayzer.mcp_auth import NotSignedIn

SESSION = "urn:ietf:params:oauth:request_uri:abc123"
CALLBACK = (
    "http://localhost:8765/callback?session_id=urn%3Aietf%3Aparams%3Aoauth%3Arequest_uri%3Aabc123"
)
SETTINGS = IdentitySettings(
    region="us-west-2", workload="clayzer", user_id="clayzer-team", provider="clayzer-lgnd",
    return_url="http://localhost:8765/callback",
)  # fmt: skip
needs_httpx2 = pytest.mark.skipif(
    importlib.util.find_spec("httpx2") is None, reason="needs the tools extra"
)


def aws_error(code):
    return ClientError({"Error": {"Code": code, "Message": code}}, "Op")


class FakeData:
    """The bedrock-agentcore client: a token once someone has approved, a link until then."""

    def __init__(self, signed_in=False, tokens=("tok-1",)):
        self.signed_in, self.tokens, self.calls = signed_in, list(tokens), []

    def get_workload_access_token_for_user_id(self, **kw):
        self.calls.append(("workload", kw))
        return {"workloadAccessToken": "workload-token"}

    def get_resource_oauth2_token(self, **kw):
        self.calls.append(("token", kw))
        if self.signed_in:
            return {"accessToken": self.tokens[0] if len(self.tokens) == 1 else self.tokens.pop(0)}
        return {
            "authorizationUrl": "https://agentcore.example/authorize?x=1",
            "sessionUri": SESSION,
        }

    def complete_resource_token_auth(self, **kw):
        self.calls.append(("complete", kw))
        self.signed_in = True


class FakeControl:
    """The bedrock-agentcore-control client, for the one-time setup."""

    def __init__(self, provider_client_id=None, workload_urls=None):
        self.provider = None
        if provider_client_id:
            self.provider = self._record(provider_client_id)
        self.workload_urls, self.calls = workload_urls, []

    @staticmethod
    def _record(client_id):
        return {
            "credentialProviderArn": "arn:aws:bedrock-agentcore:us-west-2:1:token-vault/default/p",
            "callbackUrl": "https://agentcore.example/callback/uuid-1",
            "oauth2ProviderConfigOutput": {"customOauth2ProviderConfig": {"clientId": client_id}},
        }

    def get_oauth2_credential_provider(self, name):
        if self.provider is None:
            raise aws_error("ResourceNotFoundException")
        return self.provider

    def create_oauth2_credential_provider(self, **kw):
        self.calls.append(("create_provider", kw))
        self.provider = self._record("placeholder")
        return self.provider

    def update_oauth2_credential_provider(self, **kw):
        self.calls.append(("update_provider", kw))
        config = kw["oauth2ProviderConfigInput"]["customOauth2ProviderConfig"]
        self.provider = self._record(config["clientId"])

    def get_workload_identity(self, name):
        if self.workload_urls is None:
            raise aws_error("ResourceNotFoundException")
        return {"allowedResourceOauth2ReturnUrls": self.workload_urls}

    def create_workload_identity(self, **kw):
        self.calls.append(("create_workload", kw))
        self.workload_urls = kw["allowedResourceOauth2ReturnUrls"]

    def update_workload_identity(self, **kw):
        self.calls.append(("update_workload", kw))
        self.workload_urls = kw["allowedResourceOauth2ReturnUrls"]


METADATA = {
    "issuer": "https://auth.example",
    "registration_endpoint": "https://auth.example/register",
}


def find(_url):
    return METADATA


# ── Fetching the token ──────────────────────────────────────────────────────────────────


def test_the_token_comes_from_identity_for_the_shared_team_identity():
    data = FakeData(signed_in=True)
    assert IdentityTokens(SETTINGS, "lgnd", data).token() == "tok-1"
    _, who = data.calls[0]
    assert (who["workloadName"], who["userId"]) == ("clayzer", "clayzer-team")
    _, ask = data.calls[1]
    assert ask["resourceCredentialProviderName"] == "clayzer-lgnd"
    assert ask["oauth2Flow"] == "USER_FEDERATION" and "offline_access" in ask["scopes"]
    assert ask["workloadIdentityToken"] == "workload-token"


def test_without_an_approval_the_token_is_a_clear_error_that_says_what_to_run():
    tokens = IdentityTokens(SETTINGS, "lgnd", FakeData(signed_in=False))
    with pytest.raises(NotSignedIn, match="clayzer agentcore login lgnd"):
        tokens.token()
    assert tokens.signed_in() is False


def test_begin_gives_the_link_and_session_or_none_when_already_signed_in():
    pending = IdentityTokens(SETTINGS, "lgnd", FakeData()).begin()
    assert pending == SignIn("https://agentcore.example/authorize?x=1", SESSION)
    assert IdentityTokens(SETTINGS, "lgnd", FakeData(signed_in=True)).begin() is None


def test_the_session_is_read_from_the_redirect_under_either_name():
    assert session_from_callback(CALLBACK) == SESSION
    assert session_from_callback("http://localhost/cb?sessionUri=abc") == "abc"
    assert session_from_callback("http://localhost/cb?code=1") is None


def test_finish_binds_the_approval_to_the_session_it_started():
    data = FakeData()
    tokens = IdentityTokens(SETTINGS, "lgnd", data)
    pending = tokens.begin()
    with pytest.raises(ValueError, match="no session id"):
        tokens.finish("http://localhost:8765/callback", pending)
    with pytest.raises(ValueError, match="different sign-in"):
        tokens.finish("http://localhost:8765/callback?session_id=urn%3Aother", pending)
    assert not any(kind == "complete" for kind, _ in data.calls)  # nothing was bound
    tokens.finish(CALLBACK, pending)
    done = next(kw for kind, kw in data.calls if kind == "complete")
    assert done == {"userIdentifier": {"userId": "clayzer-team"}, "sessionUri": SESSION}
    assert tokens.signed_in()


# ── The httpx2 auth the Toolbox uses ────────────────────────────────────────────────────


@needs_httpx2
def test_requests_carry_the_token_and_a_401_asks_identity_again_once():
    import httpx2

    seen = []

    def handler(request):
        seen.append(request.headers["Authorization"])
        return httpx2.Response(401 if len(seen) == 1 else 200)

    auth = identity.identity_token_auth("lgnd", IdentityTokens(
        SETTINGS, "lgnd", FakeData(signed_in=True, tokens=["old", "new"])))  # fmt: skip

    async def call():
        async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler), auth=auth) as c:
            return await c.get("https://lgnd.example/mcp")

    assert asyncio.run(call()).status_code == 200
    assert seen == ["Bearer old", "Bearer new"]


@needs_httpx2
def test_a_401_with_the_same_token_is_not_retried():
    import httpx2

    seen = []

    def handler(request):
        seen.append(1)
        return httpx2.Response(401)

    auth = identity.identity_token_auth(
        "lgnd", IdentityTokens(SETTINGS, "lgnd", FakeData(signed_in=True))
    )

    async def call():
        async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler), auth=auth) as c:
            return await c.get("https://lgnd.example/mcp")

    assert asyncio.run(call()).status_code == 401 and len(seen) == 1


# ── Choosing the token source ───────────────────────────────────────────────────────────


def test_the_token_source_defaults_to_the_local_file(monkeypatch):
    monkeypatch.delenv("CLAYZER_TOKEN_SOURCE", raising=False)
    assert mcp_auth.token_source() == "file"
    monkeypatch.setenv("CLAYZER_TOKEN_SOURCE", "agentcore")
    assert mcp_auth.token_source() == "agentcore"
    monkeypatch.setenv("CLAYZER_TOKEN_SOURCE", "somewhere")
    with pytest.raises(ValueError, match="CLAYZER_TOKEN_SOURCE"):
        mcp_auth.token_source()


@needs_httpx2
def test_sign_in_auth_follows_the_source(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAYZER_AUTH_DIR", str(tmp_path))
    monkeypatch.delenv("CLAYZER_TOKEN_SOURCE", raising=False)
    local = mcp_auth.sign_in_auth("lgnd", "https://geo.lgnd.ai/mcp")
    assert hasattr(local, "storage") and local.signed_in() is False  # nothing saved here
    monkeypatch.setenv("CLAYZER_TOKEN_SOURCE", "agentcore")
    remote = mcp_auth.sign_in_auth("lgnd", "https://geo.lgnd.ai/mcp")
    assert not hasattr(remote, "storage") and callable(remote.signed_in)


# ── One-time setup ──────────────────────────────────────────────────────────────────────


def test_a_new_oauth_client_is_created_registered_with_the_callback_then_saved():
    ctl, registered, said = FakeControl(), [], []

    def register(endpoint, redirect, scopes):
        registered.append((endpoint, redirect))
        return "client-1", "secret-1"

    arn = ensure_oauth_client(ctl, SETTINGS, "https://geo.lgnd.ai/mcp", said.append, find, register)
    assert arn.endswith("/p")
    # The callback only exists once the provider does, so it is registered after creating it.
    assert registered == [
        ("https://auth.example/register", "https://agentcore.example/callback/uuid-1")
    ]
    assert [c[0] for c in ctl.calls] == ["create_provider", "update_provider"]
    saved = ctl.calls[1][1]["oauth2ProviderConfigInput"]["customOauth2ProviderConfig"]
    assert (saved["clientId"], saved["clientSecret"]) == ("client-1", "secret-1")
    assert (
        saved["oauthDiscovery"]["discoveryUrl"]
        == "https://auth.example/.well-known/oauth-authorization-server"
    )
    assert not any("secret-1" in line for line in said)  # the secret is never printed


def test_setup_is_safe_to_run_again_and_finishes_an_interrupted_run():
    def never(*_):
        raise AssertionError("must not register again")

    done = FakeControl(provider_client_id="client-1")
    ensure_oauth_client(done, SETTINGS, "https://geo.lgnd.ai/mcp", lambda _: None, find, never)
    assert done.calls == []

    interrupted = FakeControl(provider_client_id="placeholder")
    ensure_oauth_client(interrupted, SETTINGS, "https://geo.lgnd.ai/mcp", lambda _: None, find,
                        lambda *_: ("client-2", "secret-2"))  # fmt: skip
    assert [c[0] for c in interrupted.calls] == ["update_provider"]  # no second provider


def test_a_client_without_a_secret_is_refused():
    with pytest.raises(RuntimeError, match="no secret"):
        ensure_oauth_client(FakeControl(), SETTINGS, "https://geo.lgnd.ai/mcp", lambda _: None, find,
                            lambda *_: ("client-1", None))  # fmt: skip


def test_the_workload_identity_is_created_or_given_the_return_address():
    new = FakeControl()
    ensure_workload_identity(new, SETTINGS, lambda _: None)
    assert new.workload_urls == ["http://localhost:8765/callback"]

    old = FakeControl(workload_urls=["https://elsewhere.example/cb"])
    ensure_workload_identity(old, SETTINGS, lambda _: None)
    assert old.workload_urls == ["https://elsewhere.example/cb", "http://localhost:8765/callback"]

    same = FakeControl(workload_urls=["http://localhost:8765/callback"])
    ensure_workload_identity(same, SETTINGS, lambda _: None)
    assert same.calls == []  # already right: no write


def test_login_walks_a_person_through_the_approval_and_reports_success(monkeypatch):
    for key in (
        "CLAYZER_AGENTCORE_WORKLOAD",
        "CLAYZER_AGENTCORE_USER_ID",
        "CLAYZER_AGENTCORE_PROVIDER",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(identity, "discover", find)
    monkeypatch.setattr(identity, "register_client", lambda *_: ("client-1", "secret-1"))
    ctl, data, said = FakeControl(), FakeData(), []
    tokens = IdentityTokens(SETTINGS, "lgnd", data)
    assert login("lgnd", "https://geo.lgnd.ai/mcp", lambda: CALLBACK, said.append, ctl, tokens)
    text = "\n".join(said)
    assert (
        "https://agentcore.example/authorize?x=1" in text and "stored in AgentCore Identity" in text
    )
    assert tokens.signed_in()


def test_login_when_already_signed_in_asks_for_nothing():
    def no_paste():
        raise AssertionError("nothing to approve")

    ctl = FakeControl(
        provider_client_id="client-1", workload_urls=["http://localhost:8765/callback"]
    )
    tokens = IdentityTokens(SETTINGS, "lgnd", FakeData(signed_in=True))
    assert login("lgnd", "https://geo.lgnd.ai/mcp", no_paste, lambda _: None, ctl, tokens)


def test_the_command_refuses_a_server_with_no_sign_in_to_keep(capsys):
    assert cli.main(["agentcore", "login", "roda"]) == 2
    assert "no sign-in to keep" in capsys.readouterr().err
