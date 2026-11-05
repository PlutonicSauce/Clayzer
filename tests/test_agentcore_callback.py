"""Actual loopback callback requests exercise cookie binding and safe error handling."""

import threading
from http.server import HTTPServer

import boto3
import httpx
from botocore.exceptions import ClientError

from clayzer.agentcore.gateway_runtime import _authorize_browser


def test_callback_requires_cookie_redacts_errors_and_completes(monkeypatch, capsys):
    import http.server

    bound = threading.Event()
    servers = []
    calls = []
    errors = []

    class Server(HTTPServer):
        def __init__(self, *args):
            super().__init__(*args)
            servers.append(self)
            bound.set()

    class Identity:
        def complete_resource_token_auth(self, **kwargs):
            calls.append(kwargs)
            if kwargs["sessionUri"] == "private-session":
                raise ClientError(
                    {
                        "Error": {
                            "Code": "AccessDeniedException",
                            "Message": "private-session token-secret rejected",
                        }
                    },
                    "Complete",
                )

    monkeypatch.setattr(http.server, "HTTPServer", Server)
    monkeypatch.setattr(boto3, "client", lambda _: Identity())

    def serve():
        try:
            _authorize_browser(
                "https://issuer.example/authorize",
                {"userToken": "token-secret"},
                nonce="nonce",
                port=0,
            )
        except Exception as exc:  # noqa: BLE001 - propagate worker-thread failures to the assertion
            errors.append(exc)

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    assert bound.wait(5)
    with httpx.Client(
        base_url=f"http://127.0.0.1:{servers[0].server_port}", trust_env=False
    ) as client:
        assert client.get("/callback?session_id=ok").status_code == 403
        assert not calls
        start = client.get("/start/nonce")
        assert start.status_code == 302 and "HttpOnly" in start.headers["set-cookie"]
        assert client.get("/callback?session_id=private-session").status_code == 502
        response = client.get("/callback?session_id=ok")
        assert response.status_code == 200
        assert "completed" in response.text
    thread.join(5)
    assert not thread.is_alive() and not errors
    assert calls[-1] == {"sessionUri": "ok", "userIdentifier": {"userToken": "token-secret"}}
    output = capsys.readouterr().out
    assert "private-session" not in output and "token-secret" not in output
