"""Runs INSIDE an AgentCore Runtime. Proves the runtime can use the LGND sign-in held by AgentCore Identity.

POST /invocations {"lat": 35.55, "lon": -115.47}
  1. asks Identity for the LGND access token, using this runtime's own IAM role (no browser, no laptop)
  2. makes one real LGND call: search_chip_lat_lon on the NAIP index, the first call verify.py makes
  3. returns what LGND said, never the token

Settings come from environment variables so the same image works in any account.
"""

import json
import os
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

import boto3

REGION = os.environ.get("AWS_REGION", "us-west-2")
WORKLOAD = os.environ["LGND_WORKLOAD"]          # the workload identity the sign-in was stored under
USER_ID = os.environ["LGND_USER_ID"]            # the shared team identity
PROVIDER = os.environ["LGND_PROVIDER"]          # the Identity OAuth client for LGND
RETURN_URL = os.environ["LGND_RETURN_URL"]
SCOPES = os.environ.get("LGND_SCOPES", "openid profile email offline_access").split()
LGND_MCP = os.environ.get("LGND_MCP", "https://geo.lgnd.ai/mcp")

data_plane = boto3.client("bedrock-agentcore", region_name=REGION)


def lgnd_token() -> str:
    """The sign-in is stored once; any process with the right IAM permissions can fetch the token."""
    workload = data_plane.get_workload_access_token_for_user_id(
        workloadName=WORKLOAD, userId=USER_ID)["workloadAccessToken"]
    resp = data_plane.get_resource_oauth2_token(
        workloadIdentityToken=workload, resourceCredentialProviderName=PROVIDER,
        scopes=SCOPES, oauth2Flow="USER_FEDERATION", resourceOauth2ReturnUrl=RETURN_URL)
    if "accessToken" not in resp:
        raise RuntimeError("no stored LGND sign-in for this identity; a person must sign in once")
    return resp["accessToken"]


def mcp(token: str, payload: dict, session: str | None = None) -> tuple[dict | None, str | None]:
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json",
               "Accept": "application/json, text/event-stream", "MCP-Protocol-Version": "2025-06-18"}
    if session:
        headers["Mcp-Session-Id"] = session
    req = urllib.request.Request(LGND_MCP, data=json.dumps(payload).encode(), headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        sid = r.headers.get("Mcp-Session-Id") or session
        raw = r.read().decode()
        if not raw.strip():
            return None, sid
        if "text/event-stream" in r.headers.get("Content-Type", ""):
            for line in raw.splitlines():       # the answer arrives as a server-sent event
                if line.startswith("data:"):
                    return json.loads(line[5:].strip()), sid
            return None, sid
        return json.loads(raw), sid


def search_chip(lat: float, lon: float) -> dict:
    started = time.time()
    token = lgnd_token()
    token_seconds = round(time.time() - started, 2)
    init, sid = mcp(token, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2025-06-18", "capabilities": {},
        "clientInfo": {"name": "clayzer-runtime-probe", "version": "0"}}})
    mcp(token, {"jsonrpc": "2.0", "method": "notifications/initialized"}, sid)
    reply, _ = mcp(token, {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
        "name": "search_chip_lat_lon", "arguments": {"index": "naip", "lat": lat, "lon": lon}}}, sid)
    result = (reply or {}).get("result", {})
    text = " ".join(c.get("text", "") for c in result.get("content", []) if c.get("type") == "text")
    return {
        "token_fetch_seconds": token_seconds,
        "lgnd_server": (init or {}).get("result", {}).get("serverInfo"),
        "tool_error": bool(result.get("isError")) or "error" in (reply or {}),
        "lgnd_reply_chars": len(text),
        "lgnd_reply_start": text[:500],
        "total_seconds": round(time.time() - started, 2),
    }


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: dict) -> None:
        raw = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:
        self._send(200, {"status": "Healthy"}) if self.path == "/ping" else self._send(404, {"error": "not found"})

    def do_POST(self) -> None:
        if self.path != "/invocations":
            return self._send(404, {"error": "not found"})
        length = int(self.headers.get("Content-Length", 0))
        req = json.loads(self.rfile.read(length) or b"{}")
        try:
            self._send(200, {"status": "success",
                             **search_chip(float(req.get("lat", 35.55)), float(req.get("lon", -115.47)))})
        except urllib.error.HTTPError as exc:
            self._send(502, {"status": "error", "where": "lgnd", "http": exc.code, "body": exc.read().decode()[:300]})
        except Exception as exc:  # report the real failure to the caller, never the token
            self._send(500, {"status": "error", "type": type(exc).__name__, "message": str(exc)[:400]})


if __name__ == "__main__":
    HTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
