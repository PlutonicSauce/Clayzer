"""The agentic Harness: the tool-use loop, the MCP Toolbox, and a Batch that uses tools."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest
from test_loop import SOLAR, WIND, FakeBedrock

from clayzer import batch as batches
from clayzer import harness, tools
from clayzer.config import Settings
from clayzer.faults import classify
from clayzer.store import LocalStore
from clayzer.tools import McpServer, Toolbox, ToolResult, ToolSpec
from clayzer.trace import RunInfo, Tracer, loads, trace_key

FAKE_SERVER = McpServer(
    "fake", sys.executable, [str(Path(__file__).with_name("fake_mcp_server.py"))]
)
CAPTION = {"text": "A solar array.", "objects": [
    {"id": "o1", "object": "solar_array", "count": 1, "position": "centre"}],
    "relations": [], "uncertain": []}  # fmt: skip


def turn(*uses, text=None):
    content = ([{"text": text}] if text else []) + [{"toolUse": u} for u in uses]
    return {"output": {"message": {"content": content}}, "stopReason": "tool_use",
            "usage": {"inputTokens": 10, "outputTokens": 5, "totalTokens": 15}}  # fmt: skip


def use(name, args, i="t1"):
    return {"toolUseId": i, "name": name, "input": args}


class Scripted:
    """Bedrock that plays back model turns and keeps every request."""

    def __init__(self, *turns):
        self.turns, self.requests = list(turns), []

    def converse(self, **request):
        self.requests.append(json.loads(json.dumps(request, default=str)))
        return self.turns.pop(0)


COVERED = ToolResult("NAIP 2022 covers it", False)


class FakeToolbox:
    def __init__(self, result=COVERED):
        self.specs = [ToolSpec("lookup", "fake", "Look a place up", {"type": "object"})]
        self.result, self.calls = result, []

    def server_for(self, name):
        return "fake" if name == "lookup" else None

    def call(self, name, arguments):
        self.calls.append((name, arguments))
        return self.result


def tracer():
    run = RunInfo(run_id="r", task="caption", case_id="c", repeat=1, batch_id="b",
                  model_id="m", prompt_sha="p")  # fmt: skip
    return Tracer(run, [])


def test_the_model_calls_a_tool_then_submits():
    bedrock = Scripted(
        turn(use("lookup", {"place": "Mojave"})), turn(use("submit_caption", CAPTION, "t2"))
    )
    box, t = FakeToolbox(), tracer()
    cap, step = harness.caption(bedrock, "m", "chip", b"png", tracer=t, toolbox=box)
    assert cap["objects"][0]["object"] == "solar_array"
    assert box.calls == [("lookup", {"place": "Mojave"})]
    assert (step["turns"], step["tool_calls"], step["usage"]["totalTokens"]) == (2, 1, 30)
    assert [s.kind for s in t.steps] == ["llm", "tool", "llm"]
    tool_step = t.steps[1]
    assert tool_step.name == "lookup" and tool_step.input == {"place": "Mojave"}
    assert tool_step.output == "NAIP 2022 covers it" and tool_step.error is None
    assert tool_step.attributes["server"] == "fake" and "latency_ms" in tool_step.attributes
    assert t.run.tools == ["submit_caption", "lookup"]
    assert t.run.metadata["turn_budget"] == {
        "max_turns": harness.MAX_TURNS,
        "turns": 2,
        "exhausted": False,
    }
    # The model chooses (no forced tool), sees every tool, and gets the tool result back.
    first, second = bedrock.requests
    assert first["toolConfig"]["toolChoice"] == {"auto": {}}
    assert [t["toolSpec"]["name"] for t in first["toolConfig"]["tools"]] == [
        "submit_caption",
        "lookup",
    ]
    result = second["messages"][-1]["content"][0]["toolResult"]
    assert result["toolUseId"] == "t1" and result["status"] == "success"
    # Only the first turn's Step records the prompt and image.
    assert "prompt" in t.steps[0].input and "prompt" not in t.steps[2].input


def test_the_turn_budget_stops_a_runaway_loop():
    bedrock = Scripted(*[turn(use("lookup", {"place": "x"}, f"t{i}")) for i in range(3)])
    t = tracer()
    with pytest.raises(harness.HarnessFault, match="3-turn budget") as e:
        harness.caption(bedrock, "m", "chip", b"png", tracer=t, toolbox=FakeToolbox(), max_turns=3)
    assert e.value.step["stop_reason"] == "turn_budget" and e.value.step["tool_calls"] == 3
    assert t.run.metadata["turn_budget"]["exhausted"] is True


def test_stopping_without_a_caption_is_a_harness_fault():
    t = tracer()
    with pytest.raises(harness.HarnessFault, match="without calling submit_caption"):
        harness.caption(
            Scripted(turn(text="done")), "m", "chip", b"png", tracer=t, toolbox=FakeToolbox()
        )
    assert classify(t.steps[0])["attribution"] == "harness"


def test_a_failing_tool_is_recorded_and_the_model_sees_the_error():
    bedrock = Scripted(
        turn(use("lookup", {"place": "x"})), turn(use("submit_caption", CAPTION, "t2"))
    )
    box, t = FakeToolbox(ToolResult("lookup timed out after 60 s", True, "TimeoutError")), tracer()
    harness.caption(bedrock, "m", "chip", b"png", tracer=t, toolbox=box)
    step = t.steps[1]
    assert (
        step.error
        and step.attributes["is_error"]
        and step.attributes["error_code"] == "TimeoutError"
    )
    assert classify(step)["attribution"] == "environment"
    assert bedrock.requests[1]["messages"][-1]["content"][0]["toolResult"]["status"] == "error"


def test_without_tools_the_harness_is_one_forced_call():
    bedrock = Scripted(turn(use("submit_caption", CAPTION)))
    harness.caption(bedrock, "m", "chip", b"png", toolbox=None)
    (request,) = bedrock.requests
    assert request["toolConfig"]["toolChoice"] == {"tool": {"name": "submit_caption"}}
    assert len(request["toolConfig"]["tools"]) == 1


needs_mcp = pytest.mark.skipif(
    importlib.util.find_spec("mcp") is None, reason="needs the tools extra: uv sync --extra tools"
)


@needs_mcp
def test_the_toolbox_talks_to_a_real_stdio_server():
    with Toolbox([FAKE_SERVER]) as box:
        assert sorted(s.name for s in box.specs) == ["broken", "lookup"]
        assert box.server_for("lookup") == "fake"
        ok = box.call("lookup", {"place": "Mojave"})
        assert (ok.text, ok.is_error) == ("NAIP 2022 covers Mojave", False)
        assert box.call("broken", {}).is_error
        assert box.call("nope", {}).error_code == "UnknownTool"


@needs_mcp
def test_toolbox_filters_disallowed_names_before_bedrock_validation(tmp_path):
    server = tmp_path / "server.py"
    server.write_text(
        "from mcp.server.mcpserver import MCPServer\n"
        'server = MCPServer("filtered")\n'
        '@server.tool(name="' + "excluded_" * 10 + '")\n'
        'def excluded() -> str:\n    return "excluded"\n'
        "@server.tool()\n"
        'def lookup() -> str:\n    return "allowed"\n'
        "server.run()\n"
    )
    with Toolbox(
        [McpServer("fake", sys.executable, [str(server)])],
        allowed_tools=frozenset({"lookup"}),
    ) as box:
        assert [spec.name for spec in box.specs] == ["lookup"]
        assert box.call("lookup", {}).text == "allowed"


def test_unknown_servers_are_refused():
    with pytest.raises(ValueError, match="unknown MCP server"):
        Toolbox.named(["nonsense"])
    # A forbidden server is refused by name with the reason (ADR-0006), not as merely unknown;
    # tests/test_allowlist.py covers the list itself.
    with pytest.raises(ValueError, match="Answer Keys"):
        Toolbox.named(["openstreetmap"])


@needs_mcp
def test_a_batch_with_tools_records_them(tmp_path, monkeypatch):
    store = LocalStore(tmp_path / "data", tmp_path / "batches")
    for case in (SOLAR, WIND):
        store.put(f"chips/{case['chips'][0]['id']}.png", case["chips"][0]["id"].encode())
    settings = Settings(
        caption_model="cap", judge_model="judge", embed_model="embed",
        bedrock_endpoint_url=None, data_dir=tmp_path / "data",
        batches_dir=tmp_path / "batches", baselines_dir=tmp_path / "baselines",
        store_url=None, naip_source="pc",
    )  # fmt: skip
    monkeypatch.setattr(batches, "bedrock", lambda s: FakeBedrock())
    monkeypatch.setitem(tools.SERVERS, "fake", FAKE_SERVER)
    bid = batches.start([SOLAR, WIND], settings, store, 1, "tools", "dev", tools=["fake"],
                        progress=lambda _: None)  # fmt: skip
    cfg = batches.load_config(store, bid)
    assert (cfg.tools, cfg.max_turns) == (["fake"], harness.MAX_TURNS)
    # The servers used are on record (ADR-0006): the pin at creation, and what each reported.
    assert set(cfg.tool_servers) == {"fake"} and set(cfg.tool_versions) == {"fake"}
    run, _ = loads(store.get(trace_key(bid, SOLAR["id"], 1)))
    assert {"submit_caption", "lookup", "broken"} <= set(run.tools)
    assert run.metadata["turn_budget"]["turns"] == 1
    assert all(r["status"] == "ok" for r in batches.load(store, bid)["results"])
