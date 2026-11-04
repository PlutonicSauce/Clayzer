"""Inbound OAuth for the AgentCore Runtime endpoint.

The Runtime can require a JWT bearer token on every request, validated by AgentCore Identity against
an OIDC provider before the agent code runs (a `customJWTAuthorizer`). A caller with no token, or a
bad one, is rejected at the edge.

The provider is an Amazon Cognito user pool with a client-credentials (machine-to-machine) app
client: a Batch is an automated caller, not a person, so it mints a token with its client id and
secret and sends it as `Authorization: Bearer`. LGND's own sign-in server can't do this (it is a
user-login provider and refuses the client-credentials grant), which is why the inbound edge uses
its own provider, separate from the LGND sign-in the Harness uses outbound.

A token is cached until shortly before it expires, so a Batch of many Runs mints only a few.
"""

from __future__ import annotations

import base64
import json
import os
import threading
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass

from clayzer.mcp_auth import tls_context

EXPIRY_MARGIN = 60  # refresh this many seconds before the token's own expiry


@dataclass(frozen=True)
class InboundAuth:
    """A Cognito client-credentials client that mints tokens for the Runtime endpoint."""

    token_url: str
    client_id: str
    client_secret: str
    scope: str

    @classmethod
    def from_env(cls) -> InboundAuth | None:
        """The inbound auth from the environment, or None when the endpoint takes SigV4.

        Set CLAYZER_AGENTCORE_INBOUND_TOKEN_URL, _CLIENT_ID, _CLIENT_SECRET and (optionally)
        _SCOPE. The CDK stack writes these for the Batch; without them a Batch uses SigV4."""
        env = os.environ.get
        url = env("CLAYZER_AGENTCORE_INBOUND_TOKEN_URL")
        cid = env("CLAYZER_AGENTCORE_INBOUND_CLIENT_ID")
        secret = env("CLAYZER_AGENTCORE_INBOUND_CLIENT_SECRET")
        if not (url and cid and secret):
            return None
        return cls(url, cid, secret, env("CLAYZER_AGENTCORE_INBOUND_SCOPE", ""))


class InboundTokens:
    """Mints and caches a client-credentials token. Safe to call from any thread."""

    def __init__(self, auth: InboundAuth, opener=None):
        self.auth = auth
        self._opener = opener or _https_opener()
        self._lock = threading.Lock()
        self._token: str | None = None
        self._expires_at = 0.0

    def token(self, force: bool = False) -> str:
        with self._lock:
            if not force and self._token and time.time() < self._expires_at:
                return self._token
            body = {"grant_type": "client_credentials"}
            if self.auth.scope:
                body["scope"] = self.auth.scope
            basic = base64.b64encode(
                f"{self.auth.client_id}:{self.auth.client_secret}".encode()
            ).decode()
            request = urllib.request.Request(
                self.auth.token_url, data=urllib.parse.urlencode(body).encode(), method="POST",
                headers={"Content-Type": "application/x-www-form-urlencoded",
                         "Authorization": f"Basic {basic}"},
            )  # fmt: skip
            reply = json.loads(self._opener.open(request, timeout=30).read())
            self._token = reply["access_token"]
            self._expires_at = time.time() + reply.get("expires_in", 3600) - EXPIRY_MARGIN
            return self._token


def _https_opener():
    import ssl

    ctx = tls_context()
    handler = urllib.request.HTTPSHandler(context=ctx if isinstance(ctx, ssl.SSLContext) else None)
    return urllib.request.build_opener(handler, urllib.request.ProxyHandler())


def claims(token: str) -> dict:
    """The JWT payload, for logging the client id and scope (never the signature)."""
    payload = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
