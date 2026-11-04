"""AgentCore Identity as the home of the LGND Geo sign-in (task agentcore-identity-token).

LGND Geo signs people in with OAuth. Until now the sign-in lived in a file on one person's
machine (`clayzer login lgnd`, mcp_auth.py), so only that machine could run a Batch that uses
LGND. AgentCore Identity can hold it instead: a person approves once in a browser, and anything
with the right AWS permissions, a laptop or an AgentCore Runtime, then fetches the token with no
browser. Verified 2026-11-04: a Runtime fetched it with its own IAM role and made a real LGND call.

How it fits together:
- an OAuth client for LGND, registered at LGND's sign-in server (dynamic client registration,
  the same standard `clayzer login` uses) and stored in Identity as a credential provider
- a workload identity, which names who is asking and which return URLs are allowed
- one shared user id for the team, so one approval serves every caller. All of them draw on
  one LGND account's quota (the free tier is 150 calls a day, per docs/mcp.md).

Setup is `clayzer agentcore login lgnd`, once per AWS account. CDK can't do it: it needs a person
in a browser. The token never leaves memory: it is not logged, stored, or returned in a Trace.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

from botocore.exceptions import ClientError

from clayzer.mcp_auth import NotSignedIn, tls_context

DEFAULT_REGION = "us-west-2"
SCOPES = ["openid", "profile", "email", "offline_access"]
# The browser is sent here after approving; nothing needs to answer. The address, which carries
# the session, is what matters. It must also be allowed on the workload identity.
DEFAULT_RETURN_URL = "http://localhost:8765/callback"
_PLACEHOLDER = "placeholder"  # the client id of a provider whose real client isn't registered yet


@dataclass(frozen=True)
class IdentitySettings:
    region: str
    workload: str  # the workload identity the sign-in is stored under
    user_id: str  # the shared team identity
    provider: str  # the OAuth client (credential provider) for this server
    return_url: str
    scopes: tuple[str, ...] = tuple(SCOPES)

    @classmethod
    def from_env(cls, server: str = "lgnd") -> IdentitySettings:
        env = os.environ.get
        return cls(
            region=env("CLAYZER_AGENTCORE_REGION")
            or env("AWS_REGION")
            or env("AWS_DEFAULT_REGION")
            or DEFAULT_REGION,
            workload=env("CLAYZER_AGENTCORE_WORKLOAD", "clayzer"),
            user_id=env("CLAYZER_AGENTCORE_USER_ID", "clayzer-team"),
            provider=env("CLAYZER_AGENTCORE_PROVIDER", f"clayzer-{server}"),
            return_url=env("CLAYZER_AGENTCORE_RETURN_URL", DEFAULT_RETURN_URL),
        )


@dataclass(frozen=True)
class SignIn:
    """A sign-in waiting for a person: where to send them, and the session it belongs to."""

    url: str
    session_uri: str


def session_from_callback(address: str) -> str | None:
    """The session id in the address the browser was sent to after approving. Identity calls the
    same value `sessionUri` in its API and `session_id` in the redirect."""
    query = parse_qs(urlparse(address).query)
    for key in ("session_id", "session_uri", "sessionUri"):
        if query.get(key):
            return query[key][0]
    return None


class IdentityTokens:
    """Fetch the LGND access token from AgentCore Identity. Safe to call from any thread."""

    def __init__(self, settings: IdentitySettings, server: str = "lgnd", data=None):
        self.settings, self.server = settings, server
        self._data = data

    @property
    def data(self):
        if self._data is None:
            import boto3

            self._data = boto3.client("bedrock-agentcore", region_name=self.settings.region)
        return self._data

    def _ask(self, session_uri: str | None = None) -> dict:
        s = self.settings
        workload = self.data.get_workload_access_token_for_user_id(
            workloadName=s.workload, userId=s.user_id
        )["workloadAccessToken"]
        request = {
            "workloadIdentityToken": workload,
            "resourceCredentialProviderName": s.provider,
            "scopes": list(s.scopes),
            "oauth2Flow": "USER_FEDERATION",
            "resourceOauth2ReturnUrl": s.return_url,
        }
        if session_uri:
            request["sessionUri"] = session_uri
        return self.data.get_resource_oauth2_token(**request)

    def token(self) -> str:
        """The access token. Raises NotSignedIn when nobody has approved yet."""
        reply = self._ask()
        if reply.get("accessToken"):
            return reply["accessToken"]
        raise NotSignedIn(
            f"{self.server} needs a one-time sign-in held by AgentCore Identity: "
            f"run `clayzer agentcore login {self.server}` first"
        )

    def signed_in(self) -> bool:
        try:
            return bool(self.token())
        except NotSignedIn:
            return False

    def begin(self) -> SignIn | None:
        """Start a sign-in. None if a token is already stored."""
        reply = self._ask()
        if reply.get("accessToken"):
            return None
        return SignIn(reply["authorizationUrl"], reply["sessionUri"])

    def finish(self, address: str, expected: SignIn) -> None:
        """Complete the sign-in from the address the browser was sent to. Refuses an address
        for some other session, so a stale or foreign link can't bind a sign-in."""
        session = session_from_callback(address)
        if not session:
            raise ValueError("that address has no session id; copy the whole address bar")
        if session != expected.session_uri:
            raise ValueError("that address is for a different sign-in; start again")
        self.data.complete_resource_token_auth(
            userIdentifier={"userId": self.settings.user_id}, sessionUri=session
        )


def identity_token_auth(name: str, tokens: IdentityTokens):
    """httpx2 auth that adds the token from AgentCore Identity to each request.

    Like mcp_auth.stored_token_auth, it asks again after a 401 (Identity refreshes expired
    tokens itself) and retries once. Check `.signed_in()` before connecting."""
    import asyncio

    import httpx2

    class IdentityAuth(httpx2.Auth):
        def signed_in(self) -> bool:
            return tokens.signed_in()

        async def async_auth_flow(self, request):
            access = await asyncio.to_thread(tokens.token)
            request.headers["Authorization"] = f"Bearer {access}"
            response = yield request
            if response.status_code == 401:
                fresh = await asyncio.to_thread(tokens.token)
                if fresh != access:
                    request.headers["Authorization"] = f"Bearer {fresh}"
                    yield request

    return IdentityAuth()


# ── One-time setup: the OAuth client and the workload identity ───────────────────────────


def _missing(e: ClientError) -> bool:
    return e.response.get("Error", {}).get("Code") == "ResourceNotFoundException"


def _json(request: urllib.request.Request) -> dict:
    ctx = tls_context()
    context = ctx if not isinstance(ctx, bool) else None
    with urllib.request.urlopen(request, timeout=30, context=context) as reply:
        return json.loads(reply.read())


def discover(mcp_url: str) -> dict:
    """The sign-in server's metadata for an MCP server (RFC 9728, then RFC 8414)."""
    u = urlparse(mcp_url)
    resource = _json(urllib.request.Request(
        f"{u.scheme}://{u.netloc}/.well-known/oauth-protected-resource{u.path}"))  # fmt: skip
    issuer = resource["authorization_servers"][0].rstrip("/")
    return _json(urllib.request.Request(f"{issuer}/.well-known/oauth-authorization-server"))


def register_client(endpoint: str, redirect_uri: str, scopes) -> tuple[str, str | None]:
    """Dynamic client registration (RFC 7591). Returns the client id and secret."""
    body = {
        "client_name": "Clayzer (AgentCore Identity)",
        "redirect_uris": [redirect_uri],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "client_secret_post",
        "scope": " ".join(scopes),
    }
    request = urllib.request.Request(endpoint, data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json"})  # fmt: skip
    registered = _json(request)
    return registered["client_id"], registered.get("client_secret")


def _config(metadata_url: str, client_id: str, secret: str) -> dict:
    return {"customOauth2ProviderConfig": {
        "oauthDiscovery": {"discoveryUrl": metadata_url},
        "clientId": client_id, "clientSecret": secret}}  # fmt: skip


def ensure_oauth_client(
    ctl, s: IdentitySettings, mcp_url: str, say: Callable[[str], None] = print,
    find: Callable[[str], dict] = discover, register=register_client,
) -> str:  # fmt: skip
    """Make sure Identity has a registered OAuth client for the server. Returns its ARN.

    The redirect address belongs to the provider and exists only once the provider does, while
    registration needs it, so a new provider is created with a placeholder client, registered,
    then updated with the real one. Safe to run again: a provider already holding a real client
    is left alone, and one left with the placeholder (an interrupted run) is finished."""
    try:
        found = ctl.get_oauth2_credential_provider(name=s.provider)
    except ClientError as e:
        if not _missing(e):
            raise
        found = None
    metadata = find(mcp_url)
    discovery = metadata["issuer"].rstrip("/") + "/.well-known/oauth-authorization-server"
    if found is None:
        found = ctl.create_oauth2_credential_provider(
            name=s.provider, credentialProviderVendor="CustomOauth2",
            oauth2ProviderConfigInput=_config(discovery, _PLACEHOLDER, _PLACEHOLDER),
        )  # fmt: skip
        say(f"created the OAuth client record {s.provider}")
    current = (found.get("oauth2ProviderConfigOutput", {}).get("customOauth2ProviderConfig", {})
               .get("clientId"))  # fmt: skip
    if current and current != _PLACEHOLDER:
        say(f"OAuth client already registered ({s.provider})")
        return found["credentialProviderArn"]
    client_id, secret = register(metadata["registration_endpoint"], found["callbackUrl"], s.scopes)
    if not secret:
        raise RuntimeError("the sign-in server issued a client with no secret; Identity needs one")
    ctl.update_oauth2_credential_provider(
        name=s.provider, credentialProviderVendor="CustomOauth2",
        oauth2ProviderConfigInput=_config(discovery, client_id, secret),
    )  # fmt: skip
    say(f"registered an OAuth client at {metadata['issuer']}")
    return found["credentialProviderArn"]


def ensure_workload_identity(ctl, s: IdentitySettings, say: Callable[[str], None] = print) -> None:
    """Create the workload identity, or make sure it allows our return address."""
    try:
        existing = ctl.get_workload_identity(name=s.workload)
    except ClientError as e:
        if not _missing(e):
            raise
        ctl.create_workload_identity(
            name=s.workload, allowedResourceOauth2ReturnUrls=[s.return_url]
        )
        say(f"created the workload identity {s.workload}")
        return
    urls = list(dict.fromkeys([*existing.get("allowedResourceOauth2ReturnUrls", []), s.return_url]))
    if urls != existing.get("allowedResourceOauth2ReturnUrls"):
        ctl.update_workload_identity(name=s.workload, allowedResourceOauth2ReturnUrls=urls)
    say(f"workload identity {s.workload} exists")


def login(
    server: str, mcp_url: str, paste_callback: Callable[[], str],
    say: Callable[[str], None] = print, ctl=None, tokens: IdentityTokens | None = None,
) -> bool:  # fmt: skip
    """`clayzer agentcore login <server>`: set up the OAuth client and workload identity, then
    walk a person through the browser approval. Returns True once a token is stored.

    `paste_callback` returns the address the browser ended up at. It is a parameter so the CLI
    can read it from the terminal and tests can supply it."""
    s = IdentitySettings.from_env(server)
    if ctl is None:
        import boto3

        ctl = boto3.client("bedrock-agentcore-control", region_name=s.region)
    ensure_workload_identity(ctl, s, say)
    ensure_oauth_client(ctl, s, mcp_url, say)
    tokens = tokens or IdentityTokens(s, server)
    pending = tokens.begin()
    if pending is None:
        say(f"{server} is already signed in; nothing to approve")
        return True
    say(f"\nOpen this link in your browser and sign in to {server}:\n\n  {pending.url}\n")
    say("Afterwards the browser goes to a localhost address that won't load. That is expected.")
    say("Copy the whole address from the address bar.")
    tokens.finish(paste_callback(), pending)
    ok = tokens.signed_in()
    say(f"{server} sign-in {'stored in AgentCore Identity' if ok else 'did not complete'}")
    return ok
