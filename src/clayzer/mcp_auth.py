"""OAuth sign-in for MCP servers that need it (LGND Geo), and the HTTP client they're reached by.

LGND Geo signs in each person through OAuth (WorkOS AuthKit). Clayzer registers itself as a
client the first time (dynamic client registration, no secret), and `clayzer login lgnd` opens
the browser once; the redirect comes back to a one-shot server on 127.0.0.1. The tokens and the
client registration are saved outside the repo (CLAYZER_AUTH_DIR, default ~/.clayzer/auth),
readable only by you, and the SDK refreshes the access token from them.

Batches never sign in: without a saved sign-in they stop with a message saying to run
`clayzer login <server>` first.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import ssl
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

# The SDK logs a traceback when a sign-in is needed; NotSignedIn already says what to do, so
# don't let Python print it when no logging is configured.
logging.getLogger("mcp.client.auth").addHandler(logging.NullHandler())

CALLBACK_PATH = "/callback"
SCOPE = "openid profile email offline_access"  # offline_access: a refresh token
SIGN_IN_TIMEOUT = 300  # seconds to finish signing in in the browser
EXPIRY_MARGIN = 30  # treat an access token as expired this many seconds early


class NotSignedIn(RuntimeError):
    """The server needs a sign-in that only `clayzer login` can do."""


def auth_dir() -> Path:
    return Path(os.environ.get("CLAYZER_AUTH_DIR") or Path.home() / ".clayzer" / "auth")


def callback_port() -> int:
    # Fixed, because the redirect URI is part of the client registration.
    return int(os.environ.get("CLAYZER_OAUTH_PORT", "33418"))


class FileTokenStorage:
    """The SDK's TokenStorage: one JSON file per server, readable only by its owner.

    It also refreshes an expired access token itself. The SDK only refreshes a token it knows
    has expired, which it learns when it receives the token, and in a new process it doesn't yet
    know the sign-in service's token endpoint. So without this, every new `clayzer` process would
    send an expired token, get a 401, and need a full sign-in. If the refresh fails, the expired
    token is returned and the server's 401 leads to the usual sign-in (NotSignedIn in a Batch).
    """

    def __init__(self, server: str, directory: Path | None = None, url: str | None = None):
        self.path = (directory or auth_dir()) / f"{server}.json"
        self.url = url  # the MCP endpoint, for finding the sign-in service when refreshing

    def _read(self) -> dict:
        return json.loads(self.path.read_text()) if self.path.exists() else {}

    def _write(self, key: str, value, **extra) -> None:
        data = self._read()
        data[key] = value.model_dump(mode="json", exclude_none=True)
        data.update(extra)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2))
        tmp.chmod(0o600)
        tmp.replace(self.path)

    def signed_in(self) -> bool:
        return bool(self._read().get("tokens"))

    async def get_tokens(self, force_refresh: bool = False):
        from mcp.shared.auth import OAuthToken

        data = self._read()
        t = data.get("tokens")
        if not t:
            return None
        token = OAuthToken.model_validate(t)
        expires_at = data.get("expires_at")
        if expires_at is None and token.expires_in is not None:
            # Saved before expiry was recorded: the file was written when the token arrived.
            expires_at = self.path.stat().st_mtime + token.expires_in - EXPIRY_MARGIN
        expired = expires_at is not None and time.time() >= expires_at
        if (expired or force_refresh) and token.refresh_token and self.url:
            return await self._refresh(token, data.get("client_info", {}).get("client_id")) or token
        return token

    async def _refresh(self, token, client_id: str | None):
        """Refresh through the sign-in service the server names (RFC 9728, RFC 8414). Returns
        the new token, saved, or None if the refresh didn't work."""
        import httpx2
        from mcp.shared.auth import OAuthToken

        if not client_id:
            return None
        u = urlparse(self.url)
        resource_doc = f"{u.scheme}://{u.netloc}/.well-known/oauth-protected-resource{u.path}"
        try:
            async with http_client() as http:
                prm = (await http.get(resource_doc)).raise_for_status().json()
                issuer = prm["authorization_servers"][0].rstrip("/")
                meta = await http.get(f"{issuer}/.well-known/oauth-authorization-server")
                endpoint = meta.raise_for_status().json()["token_endpoint"]
                r = await http.post(endpoint, data={
                    "grant_type": "refresh_token", "refresh_token": token.refresh_token,
                    "client_id": client_id, "resource": prm.get("resource") or self.url,
                })  # fmt: skip
            if r.status_code != 200:
                return None
            new = OAuthToken.model_validate_json(r.content)
        except (httpx2.HTTPError, KeyError, IndexError, ValueError):
            return None
        # A refresh response may leave out the refresh token (not rotated) and the scope.
        new.refresh_token = new.refresh_token or token.refresh_token
        new.scope = new.scope or token.scope
        await self.set_tokens(new)
        return new

    async def set_tokens(self, tokens) -> None:
        expires_at = time.time() + tokens.expires_in - EXPIRY_MARGIN if tokens.expires_in else None
        self._write("tokens", tokens, expires_at=expires_at)

    async def get_client_info(self):
        from mcp.shared.auth import OAuthClientInformationFull

        c = self._read().get("client_info")
        return OAuthClientInformationFull.model_validate(c) if c else None

    async def set_client_info(self, client_info) -> None:
        self._write("client_info", client_info)


def stored_token_auth(name: str, url: str, directory: Path | None = None):
    """httpx2 auth for a saved sign-in, used by everything except `clayzer login`.

    It adds the saved access token to each request, refreshing it first when it has expired,
    and on a 401 refreshes once and retries. The SDK's own provider does neither within a
    running process: it doesn't know a loaded token's expiry, and on a 401 it starts a full
    sign-in, which a Batch can't do (a Batch lost every LGND call after its first 5-minute
    token expired). Check `.storage.signed_in()` before connecting.
    """
    import httpx2

    class StoredTokenAuth(httpx2.Auth):
        def __init__(self):
            self.storage = FileTokenStorage(name, directory, url)
            self._lock = asyncio.Lock()

        def signed_in(self) -> bool:
            return self.storage.signed_in()

        async def _token(self, force: bool = False) -> str | None:
            async with self._lock:
                token = await self.storage.get_tokens(force_refresh=force)
            return token.access_token if token else None

        async def async_auth_flow(self, request):
            access = await self._token()
            if not access:
                raise NotSignedIn(f"{name} needs a sign-in: run `clayzer login {name}` first")
            request.headers["Authorization"] = f"Bearer {access}"
            response = yield request
            if response.status_code == 401:
                fresh = await self._token(force=True)
                if fresh and fresh != access:
                    request.headers["Authorization"] = f"Bearer {fresh}"
                    yield request

    return StoredTokenAuth()


TOKEN_SOURCES = ("file", "agentcore")


def token_source() -> str:
    """Where non-interactive connections get a sign-in: `file` (the default: what `clayzer login`
    saved on this machine) or `agentcore` (held by AgentCore Identity, set up once with
    `clayzer agentcore login`). Chosen by CLAYZER_TOKEN_SOURCE, so the same code runs on a laptop
    and inside an AgentCore Runtime."""
    source = os.environ.get("CLAYZER_TOKEN_SOURCE", "file")
    if source not in TOKEN_SOURCES:
        raise ValueError(f"CLAYZER_TOKEN_SOURCE must be one of {TOKEN_SOURCES}, not {source!r}")
    return source


def sign_in_auth(name: str, url: str):
    """httpx2 auth for a saved sign-in from the configured source. Check `.signed_in()`."""
    if token_source() == "agentcore":
        from clayzer.agentcore.identity import IdentitySettings, IdentityTokens, identity_token_auth

        tokens = IdentityTokens(IdentitySettings.from_env(name), name)
        return identity_token_auth(name, tokens)
    return stored_token_auth(name, url)


def wait_for_callback(port: int, timeout: float = SIGN_IN_TIMEOUT) -> dict[str, str]:
    """Serve one request on 127.0.0.1:<port>/callback and return its query parameters."""
    got: dict[str, str] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            url = urlparse(self.path)
            if url.path != CALLBACK_PATH:
                self.send_error(404)
                return
            got.update({k: v[0] for k, v in parse_qs(url.query).items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            ok = "code" in got
            self.wfile.write(
                b"<p>Signed in to Clayzer. You can close this tab.</p>"
                if ok
                else b"<p>Sign-in failed; see the terminal.</p>"
            )

        def log_message(self, *args):  # keep the terminal quiet
            pass

    server = HTTPServer(("127.0.0.1", port), Handler)
    server.timeout = timeout
    try:
        server.handle_request()
    finally:
        server.server_close()
    if not got:
        raise NotSignedIn(f"no sign-in came back within {timeout:.0f} s")
    if "error" in got:
        raise NotSignedIn(f"sign-in refused: {got['error']} {got.get('error_description', '')}")
    return got


def oauth_provider(name: str, url: str, interactive: bool, blocked: list[str] | None = None):
    """The SDK's OAuth provider for one server. Non-interactive providers use the saved
    sign-in and its refresh token, and raise NotSignedIn instead of opening a browser.

    The SDK runs the flow inside a task group, which turns that error into a cancellation;
    the reason is also appended to `blocked`, so the caller can raise it again."""
    from mcp.client.auth import OAuthClientProvider
    from mcp.shared.auth import AuthorizationCodeResult, OAuthClientMetadata

    port = callback_port()
    metadata = OAuthClientMetadata(
        client_name="Clayzer",
        redirect_uris=[f"http://127.0.0.1:{port}{CALLBACK_PATH}"],
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        token_endpoint_auth_method="none",
        scope=SCOPE,
    )

    async def redirect(authorization_url: str) -> None:
        if not interactive:
            reason = f"{name} needs a sign-in: run `clayzer login {name}` first"
            if blocked is not None:
                blocked.append(reason)
            raise NotSignedIn(reason)
        print(
            f"Opening the browser to sign in to {name}. If it doesn't open, go to:\n  {authorization_url}"
        )
        webbrowser.open(authorization_url)

    async def callback() -> AuthorizationCodeResult:
        got = await asyncio.to_thread(wait_for_callback, port)
        return AuthorizationCodeResult(code=got["code"], state=got.get("state"), iss=got.get("iss"))

    return OAuthClientProvider(url, metadata, FileTokenStorage(name, url=url), redirect, callback)


def tls_context() -> ssl.SSLContext | bool:
    """TLS verification for HTTP MCP servers: the OS trust store with
    CLAYZER_MCP_SYSTEM_TRUST=1, else SSL_CERT_FILE if set, else httpx2's default."""
    if os.environ.get("CLAYZER_MCP_SYSTEM_TRUST") == "1":
        import truststore

        return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    if cafile := os.environ.get("SSL_CERT_FILE"):
        return ssl.create_default_context(cafile=cafile)
    return True


def http_client(auth=None):
    """An httpx2 client with the MCP transports' default timeouts; proxies come from the
    environment."""
    import httpx2

    timeout = httpx2.Timeout(30.0, read=300.0)
    return httpx2.AsyncClient(auth=auth, timeout=timeout, verify=tls_context())
