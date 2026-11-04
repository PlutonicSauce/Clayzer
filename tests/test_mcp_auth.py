"""Remote MCP servers: the saved sign-in, the browser callback, TLS, and the HTTP transport."""

import asyncio
import importlib.util
import socket
import ssl
import stat
import threading
import time
import urllib.request

import pytest

from clayzer.mcp_auth import FileTokenStorage, NotSignedIn, tls_context, wait_for_callback

needs = pytest.mark.skipif(
    not all(importlib.util.find_spec(m) for m in ("mcp", "uvicorn")),
    reason="needs the tools and ui extras: uv sync --extra tools --extra ui",
)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def get(url: str) -> int:
    # Straight to localhost, never through a proxy from the environment.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for _ in range(50):
        try:
            return opener.open(url, timeout=5).status
        except (ConnectionError, urllib.error.URLError):
            time.sleep(0.05)
    raise AssertionError(f"nothing answered at {url}")


@needs
def test_the_sign_in_is_saved_privately_and_read_back(tmp_path):
    from mcp.shared.auth import OAuthToken

    store = FileTokenStorage("lgnd", tmp_path / "auth")
    assert asyncio.run(store.get_tokens()) is None
    token = OAuthToken(access_token="a", token_type="Bearer", expires_in=60, refresh_token="r")
    asyncio.run(store.set_tokens(token))
    again = asyncio.run(store.get_tokens())
    assert (again.access_token, again.refresh_token) == ("a", "r")
    assert stat.S_IMODE(store.path.stat().st_mode) == 0o600
    assert stat.S_IMODE(store.path.parent.stat().st_mode) == 0o700


def test_the_callback_returns_the_code():
    port, got = free_port(), {}
    t = threading.Thread(target=lambda: got.update(wait_for_callback(port, timeout=10)))
    t.start()
    assert get(f"http://127.0.0.1:{port}/callback?code=abc&state=xyz") == 200
    t.join(5)
    assert got == {"code": "abc", "state": "xyz"}


def test_a_refused_or_missing_sign_in_raises():
    port, errors = free_port(), []

    def wait():
        try:
            wait_for_callback(port, timeout=10)
        except NotSignedIn as e:
            errors.append(str(e))

    t = threading.Thread(target=wait)
    t.start()
    get(f"http://127.0.0.1:{port}/callback?error=access_denied")
    t.join(5)
    assert errors and "access_denied" in errors[0]
    with pytest.raises(NotSignedIn, match="within"):
        wait_for_callback(free_port(), timeout=0.2)


def test_tls_follows_the_settings(monkeypatch, tmp_path):
    import certifi

    monkeypatch.delenv("CLAYZER_MCP_SYSTEM_TRUST", raising=False)
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    assert tls_context() is True
    monkeypatch.setenv("SSL_CERT_FILE", certifi.where())
    assert isinstance(tls_context(), ssl.SSLContext)
    monkeypatch.setenv("CLAYZER_MCP_SYSTEM_TRUST", "1")
    assert isinstance(tls_context(), ssl.SSLContext)


@needs
def test_the_toolbox_reaches_a_server_over_http(monkeypatch):
    import uvicorn
    from fake_mcp_server import server

    from clayzer.tools import McpServer, Toolbox

    for var in ("NO_PROXY", "no_proxy"):
        monkeypatch.setenv(var, "127.0.0.1,localhost")
    port = free_port()
    http = uvicorn.Server(
        uvicorn.Config(server.streamable_http_app(), port=port, log_level="error")
    )
    t = threading.Thread(target=http.run, daemon=True)
    t.start()
    try:
        while not http.started:
            time.sleep(0.05)
        remote = McpServer("fake-http", url=f"http://127.0.0.1:{port}/mcp")
        with Toolbox([remote]) as box:
            assert sorted(s.name for s in box.specs) == ["broken", "lookup"]
            assert box.call("lookup", {"place": "Mojave"}).text == "NAIP 2022 covers Mojave"
            assert box.versions["fake-http"].startswith("fake")
    finally:
        http.should_exit = True
        t.join(5)


def _expired_store(tmp_path):
    import json

    store = FileTokenStorage("lgnd", tmp_path / "auth", url="https://mcp.example/mcp")
    store.path.parent.mkdir(parents=True)
    store.path.write_text(json.dumps({
        "tokens": {"access_token": "old", "token_type": "Bearer", "expires_in": 300,
                   "refresh_token": "r1", "scope": "openid offline_access"},
        "client_info": {"client_id": "client-1", "redirect_uris": ["http://127.0.0.1:1/callback"]},
        "expires_at": time.time() - 1,
    }))  # fmt: skip
    return store


def _sign_in_service(seen, token_status=200, rotated=True):
    import httpx2

    def handle(request):
        seen.append(request)
        if request.url.path == "/.well-known/oauth-protected-resource/mcp":
            return httpx2.Response(200, json={"resource": "https://mcp.example/mcp",
                                              "authorization_servers": ["https://auth.example"]})  # fmt: skip
        if request.url.path == "/.well-known/oauth-authorization-server":
            return httpx2.Response(
                200, json={"token_endpoint": "https://auth.example/oauth2/token"}
            )
        if request.url.path == "/oauth2/token":
            body = {"access_token": "new", "token_type": "Bearer", "expires_in": 300}
            return httpx2.Response(
                token_status, json=body | ({"refresh_token": "r2"} if rotated else {})
            )
        return httpx2.Response(404)

    return lambda auth=None: httpx2.AsyncClient(transport=httpx2.MockTransport(handle))


@needs
def test_an_expired_token_is_refreshed_through_the_sign_in_service(tmp_path, monkeypatch):
    from urllib.parse import parse_qs

    from clayzer import mcp_auth

    seen = []
    monkeypatch.setattr(mcp_auth, "http_client", _sign_in_service(seen))
    store = _expired_store(tmp_path)
    token = asyncio.run(store.get_tokens())
    assert (token.access_token, token.refresh_token) == ("new", "r2")
    sent = parse_qs(seen[-1].content.decode())
    assert str(seen[-1].url) == "https://auth.example/oauth2/token"
    assert sent["grant_type"] == ["refresh_token"] and sent["refresh_token"] == ["r1"]
    assert sent["client_id"] == ["client-1"] and sent["resource"] == ["https://mcp.example/mcp"]
    # Saved, still private, and good for a while.
    again = asyncio.run(store.get_tokens())
    assert again.access_token == "new" and len(seen) == 3
    assert stat.S_IMODE(store.path.stat().st_mode) == 0o600


@needs
def test_a_refresh_that_keeps_the_refresh_token_carries_it_forward(tmp_path, monkeypatch):
    from clayzer import mcp_auth

    monkeypatch.setattr(mcp_auth, "http_client", _sign_in_service([], rotated=False))
    token = asyncio.run(_expired_store(tmp_path).get_tokens())
    assert (token.access_token, token.refresh_token, token.scope) == (
        "new",
        "r1",
        "openid offline_access",
    )


@needs
def test_a_failed_refresh_returns_the_old_token(tmp_path, monkeypatch):
    from clayzer import mcp_auth

    monkeypatch.setattr(mcp_auth, "http_client", _sign_in_service([], token_status=400))
    store = _expired_store(tmp_path)
    assert asyncio.run(store.get_tokens()).access_token == "old"


@needs
def test_a_401_mid_batch_refreshes_once_and_retries(tmp_path, monkeypatch):
    import json

    import httpx2

    from clayzer import mcp_auth

    seen = []
    monkeypatch.setattr(mcp_auth, "http_client", _sign_in_service(seen))
    store = _expired_store(tmp_path)
    data = json.loads(store.path.read_text())
    data["expires_at"] = time.time() + 600  # looks valid, but the server has revoked it
    store.path.write_text(json.dumps(data))

    def mcp(request):
        seen.append(request)
        ok = request.headers.get("Authorization") == "Bearer new"
        return httpx2.Response(200 if ok else 401)

    auth = mcp_auth.stored_token_auth("lgnd", "https://mcp.example/mcp", tmp_path / "auth")

    async def go():
        async with httpx2.AsyncClient(auth=auth, transport=httpx2.MockTransport(mcp)) as c:
            return await c.post("https://mcp.example/mcp")

    assert asyncio.run(go()).status_code == 200
    hits = [str(r.url) for r in seen]
    assert hits.count("https://mcp.example/mcp") == 2  # the 401, then the retry
    assert hits.count("https://auth.example/oauth2/token") == 1


@needs
def test_an_expired_token_is_refreshed_before_the_request(tmp_path, monkeypatch):
    import httpx2

    from clayzer import mcp_auth

    seen = []
    monkeypatch.setattr(mcp_auth, "http_client", _sign_in_service(seen))
    _expired_store(tmp_path)
    auth = mcp_auth.stored_token_auth("lgnd", "https://mcp.example/mcp", tmp_path / "auth")
    sent = []

    def mcp(request):
        sent.append(request.headers.get("Authorization"))
        return httpx2.Response(200)

    async def go():
        async with httpx2.AsyncClient(auth=auth, transport=httpx2.MockTransport(mcp)) as c:
            return await c.post("https://mcp.example/mcp")

    assert asyncio.run(go()).status_code == 200 and sent == ["Bearer new"]


@needs
def test_without_a_sign_in_the_toolbox_refuses_up_front(tmp_path, monkeypatch):
    from clayzer.tools import McpServer, Toolbox

    monkeypatch.setenv("CLAYZER_AUTH_DIR", str(tmp_path / "empty"))
    remote = McpServer("lgnd", url="https://mcp.example/mcp", oauth=True)
    with pytest.raises(NotSignedIn, match="clayzer login lgnd"), Toolbox([remote]):
        pass
