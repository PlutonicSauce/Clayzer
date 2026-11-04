"""AgentCore contract, input isolation, and durable model/tool traces."""

import json

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("mcp")

from fastapi.testclient import TestClient
from test_agentic import CAPTION, Scripted, turn, use
from test_agentic import FakeToolbox as BaseToolbox

from clayzer.agentcore import gateway_runtime as agentcore
from clayzer.agentcore_trace import RunFailure
from clayzer.store import LocalStore
from clayzer.tools import ToolResult
from clayzer.trace import loads


class FakeToolbox(BaseToolbox):
    def call(self, name, arguments, timeout=None):
        if name == "lgnd___toolbox_classifier_list":
            return ToolResult('{"data":[]}', False)
        return super().call(name, arguments)


@pytest.fixture
def store(tmp_path):
    store = LocalStore(tmp_path / "data", tmp_path / "batches")
    store.put("chips/solar.png", b"png")
    return store


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"chip_id": "../cases/solar"},
        {"chip_id": "/etc/passwd"},
        {"chip_id": "solar", "labels": ["solar_array"]},
        {"chip_id": "solar", "model": "different"},
        {"chip_id": 4},
    ],
)
def test_request_cannot_select_paths_labels_or_configuration(payload):
    with pytest.raises(ValueError):
        agentcore.chip_id_from(payload)


def test_runtime_records_tool_and_model_steps_in_store(store):
    model = Scripted(
        turn(use("lookup", {"catalog": "naip"})),
        turn(use("submit_caption", CAPTION, "t2")),
    )
    result = agentcore.run_caption({"chip_id": "solar"}, store, model, "nova", FakeToolbox())
    run, steps = loads(store.get(result["trace_key"]))
    assert run.status == "ok"
    assert run.metadata["hosting"] == "agentcore"
    assert [s.kind for s in steps] == ["tool", "llm", "tool", "llm"]
    assert steps[0].attributes["role"] == "setup"
    assert result["caption"] == CAPTION
    assert json.loads(store.get(f"runs/agentcore/{result['batch_id']}/caption.json")) == {
        k: v for k, v in result.items() if k != "status"
    }
    assert not store.list_dirs("batches/")
    assert "cases/" not in json.dumps(model.requests)


def test_failed_caption_still_has_a_trace(store):
    with pytest.raises(RunFailure) as failed:
        agentcore.run_caption(
            {"chip_id": "solar"}, store, Scripted(turn(text="no caption")), "nova", FakeToolbox()
        )
    run, steps = loads(store.get(failed.value.details["trace_key"]))
    assert run.status == "harness_fault"
    assert len(steps) == 2


def test_http_contract_and_errors():
    calls = []

    def execute(payload):
        calls.append(payload)
        return {"caption": CAPTION}

    client = TestClient(agentcore.create_app(execute))
    assert client.get("/ping").json() == {"status": "Healthy"}
    assert client.post("/invocations", json={"chip_id": "solar"}).json() == {"caption": CAPTION}
    assert client.post("/invocations", json={"chip_id": "../secret"}).status_code == 400
    assert calls == [{"chip_id": "solar"}]

    def fail(_):
        raise RuntimeError("secret token must not reach the response")

    failed = TestClient(agentcore.create_app(fail)).post("/invocations", json={"chip_id": "solar"})
    assert failed.status_code == 500
    assert failed.json() == {"detail": "caption run failed"}


def test_gateway_tokens_are_cached_and_refreshed_on_401(monkeypatch):
    import asyncio
    from types import SimpleNamespace

    import httpx2

    from clayzer import mcp_auth

    calls = []

    def token(request):
        calls.append(request)
        assert b"grant_type=client_credentials" in request.content
        return httpx2.Response(
            200, json={"access_token": f"token-{len(calls)}", "expires_in": 3600}
        )

    monkeypatch.setattr(
        mcp_auth,
        "http_client",
        lambda: httpx2.AsyncClient(transport=httpx2.MockTransport(token)),
    )
    secret = json.dumps(
        {
            "token_endpoint": "https://issuer.example/oauth2/token",
            "client_id": "client",
            "client_secret": "secret",
            "scope": "caption/invoke",
        }
    )
    session = SimpleNamespace(
        client=lambda *_, **__: SimpleNamespace(
            get_secret_value=lambda **_: {"SecretString": secret}
        )
    )
    auth = agentcore.gateway_auth(session, "arn:secret")

    async def check():
        assert await auth.access_token() == await auth.access_token() == "token-1"
        request = httpx2.Request("POST", "https://gateway.example/mcp", content=b"{}")
        flow = auth.async_auth_flow(request)
        assert (await anext(flow)).headers["Authorization"] == "Bearer token-1"
        retry = await flow.asend(httpx2.Response(401))
        assert retry.headers["Authorization"] == "Bearer token-2"
        await flow.aclose()

    asyncio.run(check())
    assert len(calls) == 2


def test_gateway_connection_failure_leaves_trace(store):
    def unavailable():
        raise RuntimeError("OAuth consent is required")

    with pytest.raises(RunFailure) as failed:
        agentcore.run_caption({"chip_id": "solar"}, store, None, "nova", unavailable)
    run, steps = loads(store.get(failed.value.details["trace_key"]))
    assert run.status == "stopped"
    assert "consent" in run.error
    assert steps == []


def test_mcp_consent_urls_stay_out_of_model_input_and_trace_text():
    from types import SimpleNamespace

    from mcp.shared.exceptions import MCPError

    from clayzer.tools import Toolbox, ToolSpec

    url = "https://issuer.example/authorize?request_uri=private"

    async def needs_consent(*_):
        raise MCPError(
            code=-32042,
            message="This request requires more information.",
            data={"elicitations": [{"mode": "url", "url": url}]},
        )

    with Toolbox([]) as box:
        box.specs = [ToolSpec("lookup", "gateway", "", {})]
        box._sessions["gateway"] = SimpleNamespace(call_tool=needs_consent)
        result = box.call("lookup", {})
    assert result.error_code == "AuthorizationRequired"
    assert result.authorization_urls == [url]
    assert url not in result.text


def test_gateway_does_not_expose_account_management_tools(monkeypatch):
    from types import SimpleNamespace

    from clayzer.tools import ToolSpec

    class Box:
        def __init__(self, *_args, **_kwargs):
            self.specs = [
                ToolSpec("lgnd___search_chip_lat_lon", "gateway", "", {}),
                ToolSpec("lgnd___user_alias_set", "gateway", "", {}),
                ToolSpec("lgnd___toolbox_classifier_build", "gateway", "", {}),
                ToolSpec("lgnd___search_future_write_tool", "gateway", "", {}),
                ToolSpec("other___lookup", "gateway", "", {}),
            ]

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

    monkeypatch.setattr(agentcore, "Toolbox", Box)
    monkeypatch.setattr(agentcore, "gateway_auth", lambda *_: None)
    url = "https://caption.gateway.bedrock-agentcore.us-west-2.amazonaws.com/mcp"
    with agentcore.gateway_tools(url, SimpleNamespace(region_name="us-west-2"), "secret") as tools:
        assert [tool.name for tool in tools.specs] == ["lgnd___search_chip_lat_lon"]
        assert tools.call("lgnd___user_alias_set", {"alias": "changed"}).is_error


def test_caller_consent_completes_with_the_initiating_jwt(monkeypatch):
    from contextlib import contextmanager
    from types import SimpleNamespace

    import boto3

    from clayzer.tools import ToolResult

    url = "https://bedrock-agentcore.us-west-2.amazonaws.com/identities/oauth2/authorize?request_uri=x"
    auth = SimpleNamespace(token=None)
    session = SimpleNamespace(
        region_name="us-west-2",
        client=lambda _: SimpleNamespace(
            get_gateway=lambda **_: {"gatewayUrl": "https://gateway.example/mcp"}
        ),
    )
    monkeypatch.setattr(boto3, "Session", lambda: session)
    monkeypatch.setattr(agentcore, "gateway_auth", lambda *_: auth)
    completed = []
    monkeypatch.setattr(
        agentcore, "_authorize_browser", lambda url, who: completed.append((url, who))
    )

    @contextmanager
    def gateway(*args):
        assert args[-1] is auth

        def call(_name, _arguments, *, meta):
            assert meta["aws.bedrock-agentcore.gateway/credentialProviderConfiguration"][
                "oauthCredentialProvider"
            ]["forceAuthentication"]
            auth.token = "the-jwt-sent-to-gateway"
            return ToolResult("authorize", True, "AuthorizationRequired", [url])

        yield SimpleNamespace(call=call)

    monkeypatch.setattr(agentcore, "gateway_tools", gateway)
    agentcore.authorize_caller("gateway", "secret", force=True)
    assert completed == [(url, {"userToken": "the-jwt-sent-to-gateway"})]


def test_agentcore_runs_and_legacy_runs_do_not_break_batch_listing(store):
    from dataclasses import replace

    from clayzer.config import Settings
    from clayzer.ui.app import create_app

    agentcore.run_caption(
        {"chip_id": "solar"},
        store,
        Scripted(turn(use("submit_caption", CAPTION))),
        "nova",
        FakeToolbox(),
    )
    store.put("batches/agentcore-legacy/caption.json", b"{}")
    settings = replace(
        Settings.from_env(), store_url=None, data_dir=store.data_dir, batches_dir=store.batches_dir
    )
    client = TestClient(create_app(settings))
    assert client.get("/api/batches").json() == []


def test_failure_response_identifies_the_saved_trace(store):
    def execute(payload):
        return agentcore.run_caption(payload, store, None, "nova", FakeToolbox())

    response = TestClient(agentcore.create_app(execute)).post(
        "/invocations", json={"chip_id": "missing"}
    )
    assert response.status_code == 200  # AgentCore preserves the domain outcome and trace locator.
    info = response.json()
    assert info["status"] == "stopped" and info["trace_saved"]
    run, _ = loads(store.get(info["trace_key"]))
    assert run.run_id == info["run_id"]
    assert "FileNotFoundError" not in json.dumps(info)


def test_deadline_stops_new_calls_and_saves_trace(store):
    model = Scripted(turn(use("submit_caption", CAPTION)))
    with pytest.raises(RunFailure) as failed:
        agentcore.run_caption({"chip_id": "solar"}, store, model, "nova", FakeToolbox(), seconds=0)
    run, steps = loads(store.get(failed.value.details["trace_key"]))
    assert run.status == "stopped" and "deadline" in run.error
    assert not model.requests and not steps


def test_abrupt_termination_preserves_running_checkpoint(store):
    class Killed:
        def converse(self, **request):
            raise SystemExit("simulate process termination")

    with pytest.raises(SystemExit):
        agentcore.run_caption({"chip_id": "solar"}, store, Killed(), "nova", FakeToolbox())
    traces = list(store.data_dir.glob("runs/agentcore/*/trace.jsonl"))
    data = traces[0].read_bytes()
    run, steps = loads(data)
    assert run.status == "running" and run.ended_at is None
    assert steps[0].name == "lgnd___toolbox_classifier_list"
    assert b'"run_end"' not in data


def test_caption_write_failure_does_not_leave_success_trace(store, monkeypatch):
    put = store.put

    def fail_caption(key, *args):
        if key.endswith("caption.json"):
            raise OSError("storage unavailable")
        return put(key, *args)

    monkeypatch.setattr(store, "put", fail_caption)
    with pytest.raises(RunFailure) as failed:
        agentcore.run_caption(
            {"chip_id": "solar"},
            store,
            Scripted(turn(use("submit_caption", CAPTION))),
            "nova",
            FakeToolbox(),
        )
    run, _ = loads(store.get(failed.value.details["trace_key"]))
    assert run.status == "stopped"


def test_lgnd_readiness_failure_stops_before_model_invocation(store):
    class Unauthorized(FakeToolbox):
        def call(self, *_args, **_kwargs):
            return ToolResult("consent required", True, "AuthorizationRequired")

    model = Scripted(turn(use("submit_caption", CAPTION)))
    with pytest.raises(RunFailure) as failed:
        agentcore.run_caption({"chip_id": "solar"}, store, model, "nova", Unauthorized())
    run, steps = loads(store.get(failed.value.details["trace_key"]))
    assert run.status == "stopped" and not model.requests
    assert steps[0].attributes["fault"]["attribution"] == "environment"


def test_case_access_canary_must_be_denied():
    from types import SimpleNamespace

    from botocore.exceptions import ClientError

    def denied(**_):
        raise ClientError({"Error": {"Code": "403", "Message": "denied"}}, "HeadObject")

    store = SimpleNamespace(
        bucket="bucket",
        _key=lambda k: "caption/" + k,
        s3=SimpleNamespace(head_object=denied),
    )
    assert agentcore._check_case_boundary(store)
    store.s3.head_object = lambda **_: {}
    with pytest.raises(RuntimeError, match="can read"):
        agentcore._check_case_boundary(store)
