"""The Harness on AgentCore (task agentcore-runtime-harness): the Run contract, the Runtime app, and a
Batch that runs through it.

A loopback stands in for the AgentCore service: each request is serialised to JSON and answered by
the real Runtime code in this process, so what is tested is what would cross the wire. Nothing here
needs a network or an AWS account."""

import http.client
import importlib.util
import inspect
import io
import json
import socket
import sys
import threading
from dataclasses import replace
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
from botocore.exceptions import ClientError
from test_agentic import CAPTION, FakeToolbox, Scripted, turn, use
from test_loop import SOLAR, WIND, FakeBedrock, throttled
from test_verify import RewritingBedrock

from clayzer import batch as batches
from clayzer import harness, tools
from clayzer.agentcore import contract, remote, runtime
from clayzer.agentcore.contract import ContractError, RunRequest, RunResponse
from clayzer.agentcore.remote import RemoteHarness
from clayzer.agentcore.runtime import ToolboxCache
from clayzer.allowlist import ForbiddenServer
from clayzer.config import Settings
from clayzer.gate import compare, setting_changes
from clayzer.mcp_auth import NotSignedIn
from clayzer.store import LocalStore
from clayzer.tools import McpServer
from clayzer.trace import RunInfo, Tracer, loads, trace_key

ARN = "arn:aws:bedrock-agentcore:us-west-2:123456789012:runtime/clayzer-test"
CHIP = {"id": "c-solar", "uri": "chips/c-solar.png", "date": "2022-07-02", "bbox": [0, 0, 1, 1]}
needs_mcp = pytest.mark.skipif(
    importlib.util.find_spec("mcp") is None, reason="needs the tools extra: uv sync --extra tools"
)


def build_request(**kw):
    args = {
        "chip": CHIP, "png": b"c-solar", "prompt": "Caption {grid} {objects} {relations}",
        "model": "cap", "max_turns": 8, "tools": [], "verify": None, "footprint": None,
    }  # fmt: skip
    return RunRequest.build(**{**args, **kw})


def test_chip_pair_round_trips_through_remote_runtime():
    from types import SimpleNamespace

    from test_change import PairBedrock

    pair_chip = {**CHIP, "uri": ["chips/before.png", CHIP["uri"]]}
    images = [b"c-before", b"c-solar"]
    request = build_request(chip=pair_chip, png=images, prompt=harness.CHANGE_PROMPT)
    assert request.contract == 2
    assert RunRequest.from_json(request.to_json()).png() == images
    cfg = SimpleNamespace(caption_model="cap", max_turns=8, tools=[], verify="lgnd")
    loop = Loopback(PairBedrock())
    PairBedrock.requests = []
    cap, _ = RemoteHarness(ARN, client=loop).caption(
        cfg, pair_chip, images, harness.CHANGE_PROMPT, tracer(), None
    )
    assert cap["objects"]
    sent = json.loads(loop.payloads[0])
    assert sent["verify"] is None and sent["image_key"] == pair_chip["uri"]
    assert len([b for b in PairBedrock.requests[0] if "image" in b]) == 2
    with pytest.raises(ContractError, match="version 2"):
        RunRequest.from_json(json.dumps({**json.loads(request.to_json()), "contract": 1}))


class NoTools:
    """A tool cache for a Runtime that must not need any."""

    def __call__(self, names):
        raise AssertionError(f"no tools were expected, but {names} were asked for")


class FakeBox:
    """A Toolbox: one `lookup` tool, as test_agentic's FakeToolbox."""

    def __init__(self, names):
        self.names, self.closed = names, False
        self.versions = {"fake": "fake-server 1.0"}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.closed = True

    def view(self, servers):
        return FakeToolbox()


class Loopback:
    """A bedrock-agentcore client whose Runtime is this process."""

    def __init__(self, client=None, cache=None):
        self.client = client or FakeBedrock()
        self.cache = cache or ToolboxCache(factory=NoTools())
        self.payloads, self.calls = [], []

    def invoke_agent_runtime(self, **kw):
        self.calls.append(kw)
        self.payloads.append(kw["payload"])
        response = runtime.answer(kw["payload"], self.client, self.cache)
        return {"response": io.BytesIO(response.to_json())}


def tracer():
    run = RunInfo(run_id="r#1", task="caption", case_id="c", repeat=1, batch_id="b",
                  model_id="m", prompt_sha="p")  # fmt: skip
    return Tracer(run, [])


@pytest.fixture(autouse=True)
def build_id(monkeypatch):
    monkeypatch.setenv("CLAYZER_BUILD", "test-build")


# ── The contract ────────────────────────────────────────────────────────────────────────


def test_a_request_survives_the_wire_and_checks_its_image():
    request = build_request(footprint={"bbox": [0, 0, 1, 1], "date": "2022-07-02"})
    again = RunRequest.from_json(request.to_json())
    assert again == request and again.png() == b"c-solar"
    damaged = replace(request, image_b64=request.image_b64[:-4] + "AAAA")
    with pytest.raises(ContractError, match="SHA-256"):
        damaged.png()


def test_a_request_with_a_field_the_contract_does_not_have_is_refused():
    # This is the door a Reference Label would come through (ADR-0006), so it is shut.
    body = json.loads(build_request().to_json())
    for extra in ("reference_labels", "labels", "answer_key"):
        with pytest.raises(ContractError, match="unknown field"):
            RunRequest.from_json(json.dumps({**body, extra: [{"object": "solar_array"}]}))
    with pytest.raises(ContractError, match="missing"):
        RunRequest.from_json(json.dumps({k: v for k, v in body.items() if k != "prompt"}))
    with pytest.raises(ContractError, match="not JSON"):
        RunRequest.from_json(b"{")


def test_the_builder_takes_a_chip_and_has_nowhere_to_put_a_case():
    params = set(inspect.signature(RunRequest.build).parameters)
    assert "chip" in params and not params & {"case", "reference_labels", "labels"}
    assert set(RunRequest.__dataclass_fields__).isdisjoint({"reference_labels", "labels", "case"})


def test_the_rules_apply_when_the_request_is_built_and_again_when_it_is_read():
    with pytest.raises(ForbiddenServer):
        build_request(tools=["openstreetmap"])
    with pytest.raises(ForbiddenServer):
        build_request(verify="overture")
    body = json.loads(build_request().to_json())
    for bad, why in (({"tools": ["osm"]}, "Answer Keys"), ({"contract": 99}, "contract version"),
                     ({"image_key": "cases/x.png"}, "chips/"), ({"max_turns": 0}, "max_turns"),
                     ({"footprint": {"bbox": [], "date": "d", "labels": []}}, "footprint")):  # fmt: skip
        with pytest.raises(ValueError, match=why):
            RunRequest.from_json(json.dumps({**body, **bad}))


# ── The Runtime ─────────────────────────────────────────────────────────────────────────


def test_a_run_comes_back_with_its_caption_and_every_step():
    response = runtime.answer(build_request().to_json(), FakeBedrock(), ToolboxCache(NoTools()))
    assert response.error is None and response.build == "test-build"
    assert response.caption["objects"][0]["object"] == "solar_array"
    assert [s["kind"] for s in response.steps] == ["llm"]
    assert response.steps[0]["input"]["prompt"]  # full request kept, for replay (ADR-0001)
    assert response.step["ok"] is True and response.step["usage"]["totalTokens"] == 100


def test_the_model_can_use_tools_in_the_runtime_and_they_stay_connected_between_runs():
    made = []

    def factory(names):
        made.append(names)
        return FakeBox(names)

    cache = ToolboxCache(factory)
    request = build_request(tools=["roda"])
    for _ in range(2):
        bedrock = Scripted(turn(use("lookup", {"place": "Mojave"})),
                           turn(use("submit_caption", CAPTION, "t2")))  # fmt: skip
        response = runtime.answer(request.to_json(), bedrock, cache)
        assert [s["kind"] for s in response.steps] == ["llm", "tool", "llm"]
    assert response.tools == ["submit_caption", "lookup"]
    assert response.tool_versions == {"fake": "fake-server 1.0"}
    assert response.metadata["turn_budget"]["turns"] == 2
    assert made == [["roda"]]  # connected once, reused for the second Run
    box = cache._boxes[("roda",)]
    cache.reset()
    assert box.closed and cache._boxes == {}


def test_a_model_that_never_submits_is_a_harness_fault_with_its_steps():
    bedrock = Scripted(turn(text="done"))
    response = runtime.answer(
        build_request(tools=["roda"]).to_json(), bedrock, ToolboxCache(FakeBox)
    )
    assert response.error["kind"] == contract.HARNESS_FAULT
    assert "without calling submit_caption" in response.error["message"]
    assert response.caption is None and response.step["ok"] is False and len(response.steps) == 1


def test_a_bedrock_failure_inside_the_runtime_keeps_its_error_code_and_steps():
    client = FakeBedrock(fail={1: throttled()})
    response = runtime.answer(build_request().to_json(), client, ToolboxCache(NoTools()))
    assert (
        response.error["kind"] == contract.BEDROCK
        and response.error["code"] == "ThrottlingException"
    )
    assert response.steps[0]["error"] and response.steps[0]["attributes"]["error_code"]


def test_a_missing_sign_in_and_a_bad_request_and_a_crash_each_say_what_they_are():
    def unsigned(names):
        raise NotSignedIn("lgnd needs a sign-in: run `clayzer agentcore login lgnd` first")

    req = build_request(verify="lgnd", footprint={"bbox": [0, 0, 1, 1], "date": None}).to_json()
    out = runtime.answer(req, FakeBedrock(), ToolboxCache(unsigned))
    assert out.error["kind"] == contract.NOT_SIGNED_IN and "agentcore login" in out.error["message"]

    out = runtime.answer(b'{"nope": 1}', FakeBedrock(), ToolboxCache(NoTools()))
    assert out.error["kind"] == contract.CONTRACT

    class Crash:
        def converse(self, **kw):
            raise KeyError("boom")

    cache = ToolboxCache(FakeBox)
    cache.get(["roda"], None)
    out = runtime.answer(build_request().to_json(), Crash(), cache)
    assert out.error["kind"] == contract.INTERNAL and out.error["code"] == "KeyError"
    assert cache._boxes == {}  # a crash drops the connections, so the next Run starts clean


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_the_http_server_answers_ping_and_invocations():
    runtime.Handler.client, runtime.Handler.cache = FakeBedrock(), ToolboxCache(NoTools())
    port = free_port()
    server = ThreadingHTTPServer(("127.0.0.1", port), runtime.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        conn.request("GET", "/ping")
        assert json.loads(conn.getresponse().read()) == {"status": "Healthy"}
        conn.request("POST", "/invocations", build_request().to_json())
        reply = conn.getresponse()
        body = RunResponse.from_json(reply.read())
        assert reply.status == 200 and body.error is None and body.caption["text"]
        conn.request("POST", "/invocations", b"{")  # a bad request is still a structured answer
        reply = conn.getresponse()
        assert (
            reply.status == 200 and RunResponse.from_json(reply.read()).error["kind"] == "contract"
        )
        conn.request("GET", "/nope")
        assert conn.getresponse().status == 404
    finally:
        server.shutdown()
        thread.join(5)


# ── The Batch's side ────────────────────────────────────────────────────────────────────


def settings_for(tmp_path):
    return Settings(
        caption_model="cap", judge_model="judge", embed_model="embed",
        bedrock_endpoint_url=None, data_dir=tmp_path / "data",
        batches_dir=tmp_path / "batches", baselines_dir=tmp_path / "baselines",
        store_url=None, naip_source="pc",
    )  # fmt: skip


@pytest.fixture
def env(tmp_path, monkeypatch):
    store = LocalStore(tmp_path / "data", tmp_path / "batches")
    for case in (SOLAR, WIND):
        store.put(f"chips/{case['chips'][0]['id']}.png", case["chips"][0]["id"].encode())
    monkeypatch.setattr(batches, "bedrock", lambda s: FakeBedrock())  # Judge and retrieval
    loop = Loopback()
    monkeypatch.setattr(remote, "runtime_client", lambda region=None: loop)
    return store, settings_for(tmp_path), loop


def run_batch(env, cases=(SOLAR, WIND), repeats=2, **kw):
    store, settings, _ = env
    bid = batches.start(list(cases), settings, store, repeats, kw.pop("label", "x"), "dev",
                        narrate=False, progress=lambda _: None, **kw)  # fmt: skip
    return batches.load(store, bid)


def test_the_remote_harness_returns_what_the_local_one_does_and_extends_the_trace():
    loop = Loopback(FakeBedrock(), ToolboxCache(FakeBox))
    cfg = type(
        "Cfg", (), {"caption_model": "cap", "max_turns": 8, "tools": ["roda"], "verify": None}
    )()
    bedrock = Scripted(
        turn(use("lookup", {"place": "x"})), turn(use("submit_caption", CAPTION, "t2"))
    )
    loop.client = bedrock
    t = tracer()
    cap, step = RemoteHarness(ARN, client=loop).caption(
        cfg, CHIP, b"c-solar", "p {grid} {objects} {relations}", t, None
    )
    assert cap["objects"][0]["object"] == "solar_array" and step["turns"] == 2
    assert [s.kind for s in t.steps] == ["llm", "tool", "llm"]
    assert [s.index for s in t.steps] == [0, 1, 2] and {s.run_id for s in t.steps} == {"r#1"}
    assert all(s.attributes["harness"] == "agentcore" for s in t.steps)
    assert t.run.tools == ["submit_caption", "lookup"]
    assert t.run.metadata["turn_budget"]["turns"] == 2


def test_each_kind_of_failure_reaches_the_batch_as_the_error_it_is():
    cfg = type("Cfg", (), {"caption_model": "cap", "max_turns": 8, "tools": [], "verify": None})()

    def ask(client):
        return RemoteHarness(ARN, client=Loopback(client)).caption(
            cfg, CHIP, b"c-solar", "p", tracer(), None
        )

    with pytest.raises(harness.HarnessFault, match="submit_caption") as fault:
        ask(FakeBedrock(no_caption={"c-solar"}))
    assert fault.value.step["seconds"] is not None  # the Batch scores a fault from this
    with pytest.raises(ClientError) as err:
        ask(FakeBedrock(fail={1: throttled()}))
    assert err.value.response["Error"]["Code"] == "ThrottlingException"

    class Refusing(Loopback):
        def invoke_agent_runtime(self, **kw):
            fail = RunResponse.failure(contract.CONTRACT, "ContractError", "bad", build="b")
            return {"response": io.BytesIO(fail.to_json())}

    with pytest.raises(ContractError, match="Runtime refused"):
        RemoteHarness(ARN, client=Refusing()).caption(cfg, CHIP, b"c-solar", "p", tracer(), None)


def test_a_batch_on_agentcore_scores_exactly_like_a_local_one(env):
    local = run_batch(env, label="local")
    on_agentcore = run_batch(env, label="agentcore", harness="agentcore", runtime=ARN)
    assert on_agentcore["config"].harness == "agentcore" and on_agentcore["config"].runtime == ARN
    assert [r["status"] for r in on_agentcore["results"]] == ["ok"] * 4
    # The same Cases through the same scorers: nothing about the scores depends on where it ran.
    a, b = local["summary"]["batch"], on_agentcore["summary"]["batch"]
    for key in ("correctness", "coverage", "fidelity", "workflow"):
        assert a[key] == pytest.approx(b[key])
    assert on_agentcore["config"].runtime_build == "test-build"
    # Compare shows the difference as a captioner change, not a measurement change.
    kinds = {s["setting"]: s["kind"] for s in compare(local, on_agentcore)["settings"]}
    assert kinds["harness"] == kinds["runtime"] == "captioner"


def test_the_trace_written_by_the_batch_holds_the_runtimes_steps(env):
    result = run_batch(env, cases=(SOLAR,), repeats=1, harness="agentcore", runtime=ARN)
    store, bid = env[0], result["config"].batch_id
    info, steps = loads(store.get(trace_key(bid, SOLAR["id"], 1)))
    assert info.status == "ok" and info.run_id == f"{SOLAR['id']}#1"
    assert [(s.kind, s.name) for s in steps] == [("llm", "caption"), ("judge", "fidelity")]
    assert steps[0].attributes["harness"] == "agentcore" and steps[0].input["prompt"]
    assert "harness" not in steps[1].attributes  # the Judge ran here, not in the Runtime


def test_no_reference_label_ever_leaves_the_batch(env):
    leaky = {**SOLAR, "reference_labels": [{**SOLAR["reference_labels"][0],
                                            "source_ids": ["LEAK-1234567"]}]}  # fmt: skip
    run_batch(env, cases=(leaky,), repeats=1, harness="agentcore", runtime=ARN)
    payloads = env[2].payloads
    assert payloads  # the Runtime was used
    for payload in payloads:
        text = payload.decode()
        assert "LEAK-1234567" not in text and "reference_labels" not in text
        assert "uspvdb" not in text  # the Answer Key's name travels nowhere either


def test_a_failed_run_is_scored_and_classified_like_a_local_one(env):
    # Call 1 is the first caption; the Runtime's Bedrock throttles it. A Sandbox Failure, retried
    # by `resume`, not a score.
    loop = env[2]
    loop.client = FakeBedrock(fail={1: throttled()})
    first = run_batch(env, cases=(SOLAR,), repeats=1, harness="agentcore", runtime=ARN)
    assert first["results"][0]["status"] == "sandbox_failure"
    assert "ThrottlingException" in first["results"][0]["error"]
    # A model that never submits is the Harness's fault: scored zero.
    loop.client = FakeBedrock(no_caption={"c-solar"})
    second = run_batch(env, cases=(SOLAR,), repeats=1, harness="agentcore", runtime=ARN)
    assert second["results"][0]["status"] == "harness_fault"
    assert second["results"][0]["grounding"]["correctness"] == 0.0


def test_a_batch_on_agentcore_starts_no_local_tools(env, monkeypatch):
    def never(names, **kw):
        raise AssertionError("tools run in the Runtime, not here")

    monkeypatch.setattr(tools.Toolbox, "named", staticmethod(never))
    env[2].cache = ToolboxCache(FakeBox)
    env[2].client = Scripted(
        turn(use("lookup", {"place": "x"})), turn(use("submit_caption", CAPTION, "t2")),
        turn(use("lookup", {"place": "x"})), turn(use("submit_caption", CAPTION, "t2")),
    )  # fmt: skip
    result = run_batch(
        env, cases=(SOLAR,), repeats=1, harness="agentcore", runtime=ARN, tools=["roda"]
    )
    cfg = result["config"]
    assert (cfg.tools, cfg.harness) == (["roda"], "agentcore")
    assert cfg.tool_servers == {"roda": tools.SERVERS["roda"].pin()}
    assert cfg.tool_versions == {"fake": "fake-server 1.0"}  # what the Runtime's servers reported


def test_a_batch_refuses_a_bad_harness_setting_before_writing_anything(env):
    store, settings, _ = env
    with pytest.raises(ValueError, match="unknown Harness"):
        batches.create([SOLAR], settings, store, 1, "x", "dev", harness="elsewhere")
    with pytest.raises(ValueError, match="Runtime ARN"):
        batches.create([SOLAR], settings, store, 1, "x", "dev", harness="agentcore")
    assert not (store.batches_dir.exists() and list(store.batches_dir.iterdir()))


def test_ontology_guidance_reaches_both_harnesses_identically(env, monkeypatch):
    guidance = 'General guidance with literal braces: {"class": "solar_array"}'
    monkeypatch.setattr(batches, "_ontology_context", lambda cfg, chip: guidance)
    prompts = []
    configs = []
    for mode in ("local", "agentcore"):
        result = run_batch(
            env, cases=(SOLAR,), repeats=1, harness=mode, runtime=ARN, ontology_context=True
        )
        cfg = result["config"]
        configs.append(cfg)
        _, steps = loads(env[0].get(trace_key(cfg.batch_id, SOLAR["id"], 1)))
        prompts.append(next(s.input["prompt"] for s in steps if s.kind == "llm"))
    assert prompts[0] == prompts[1]
    assert guidance in prompts[1]
    from dataclasses import replace

    changed = setting_changes(configs[0], replace(configs[0], ontology_context=False))
    assert "ontology_context" in {s["setting"] for s in changed}


def test_the_gate_and_compare_see_the_harness_settings(env):
    local = run_batch(env, label="local", repeats=1)
    on_agentcore = run_batch(env, label="ac", repeats=1, harness="agentcore", runtime=ARN)
    changed = {s["setting"] for s in setting_changes(local["config"], on_agentcore["config"])}
    assert {"harness", "runtime"} <= changed


@needs_mcp
def test_verification_runs_inside_the_runtime_through_real_mcp(env, monkeypatch):
    # The same fake LGND the local --verify test uses, now reached from the Runtime.
    fake = McpServer("lgnd", sys.executable, [str(Path(__file__).with_name("fake_lgnd_server.py"))])
    monkeypatch.setitem(tools.SERVERS, "lgnd", fake)
    loop = env[2]
    loop.client, loop.cache = RewritingBedrock(), ToolboxCache()
    try:
        result = run_batch(env, repeats=1, harness="agentcore", runtime=ARN, verify="lgnd")
    finally:
        loop.cache.reset()
    assert not result["summary"]["stopped"], result["summary"]["stopped"]
    rows = {r["case_id"]: r for r in result["results"]}
    assert rows[SOLAR["id"]]["verification"]["confirmed"] == 1
    assert rows[WIND["id"]]["verification"]["moved"] == 1
    captions = {c["case_id"]: c for c in result["captions"]}
    assert (
        captions[WIND["id"]]["objects"] == []
        and captions[WIND["id"]]["text"] == "Nothing confirmed."
    )
    assert result["config"].tool_versions and "lgnd" in result["config"].tool_servers


def test_old_runtime_refusing_pairs_finishes_trace_and_batch_reports(env, monkeypatch):
    case = {**SOLAR, "kind": "change", "chips": [SOLAR["chips"][0], SOLAR["chips"][0]]}

    def old_runtime(**kw):
        assert json.loads(kw["payload"])["contract"] == 2
        return {
            "response": io.BytesIO(
                RunResponse.failure(
                    contract.CONTRACT,
                    "ContractError",
                    "this Runtime speaks v1; redeploy for Chip Pairs",
                ).to_json()
            )
        }

    monkeypatch.setattr(env[2], "invoke_agent_runtime", old_runtime)
    result = run_batch(env, cases=(case,), repeats=1, harness="agentcore", runtime=ARN)
    assert "contract mismatch" in result["summary"]["stopped"]
    bid = result["config"].batch_id
    run, _ = loads(env[0].get(trace_key(bid, case["id"], 1)))
    assert run.status == "stopped"
    assert env[0].exists(f"batches/{bid}/report.html")


def test_tool_versions_add_later_servers_without_replacing_first_version(env):
    store, settings, _ = env
    bid = batches.create([SOLAR], settings, store, 1, "versions", "dev")
    cfg = batches.load_config(store, bid)
    notes = []
    cfg = batches._record_tool_versions(store, cfg, {"roda": "1"}, notes.append)
    cfg = batches._record_tool_versions(store, cfg, {"roda": "1", "lgnd": "2"}, notes.append)
    assert cfg.tool_versions == {"roda": "1", "lgnd": "2"} and not notes
    cfg = batches._record_tool_versions(store, cfg, {"roda": "3"}, notes.append)
    assert cfg.tool_versions["roda"] == "1" and len(notes) == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("footprint", [["bbox"]]),
        ("tools", [[]]),
        ("model", {}),
        ("prompt", 1),
        ("image_b64", "not base64!"),
    ],
)
def test_malformed_requests_do_not_reset_live_tool_connections(field, value):
    from unittest.mock import Mock

    cache = Mock()
    data = json.loads(build_request().to_json())
    response = runtime.answer(json.dumps({**data, field: value}), FakeBedrock(), cache)
    assert response.error["kind"] == contract.CONTRACT
    cache.reset.assert_not_called()


def test_classifier_setup_is_cached_and_errors_are_reported(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock

    routes = SimpleNamespace(uses_classifier=lambda: True, classifier="c", examples={})
    monkeypatch.setattr(runtime.verifiers, "load", lambda: routes)
    ensure = Mock(return_value="classifier unavailable")
    monkeypatch.setattr(runtime.lgnd, "ensure_classifier", ensure)
    cache = ToolboxCache(FakeBox)
    request = build_request(verify="lgnd")
    for _ in range(2):
        response = runtime.run_request(request, FakeBedrock(), cache)
        assert response.metadata["classifier_setup_error"] == "classifier unavailable"
    ensure.assert_called_once()


def test_verification_data_mismatch_stops_before_scoring():
    from types import SimpleNamespace

    cfg = SimpleNamespace(
        caption_model="cap",
        max_turns=8,
        tools=[],
        verify="lgnd",
        ontology_sha="wrong",
        verifiers_sha="wrong",
    )
    loop = Loopback(cache=ToolboxCache(FakeBox))
    with pytest.raises(ContractError, match="redeploy matching"):
        RemoteHarness(ARN, client=loop).caption(cfg, CHIP, b"c-solar", "p", tracer(), None)


@pytest.mark.parametrize(
    "body",
    [
        b"\xff",
        json.dumps({**json.loads(build_request().to_json()), "tools": ["osm"]}).encode(),
    ],
)
def test_bad_encoding_or_forbidden_server_keeps_tool_connections(body):
    from unittest.mock import Mock

    cache = Mock()
    assert runtime.answer(body, FakeBedrock(), cache).error["kind"] == contract.CONTRACT
    cache.reset.assert_not_called()
