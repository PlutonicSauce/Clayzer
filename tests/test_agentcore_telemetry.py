"""AgentCore Observability spans (telemetry.py): the Runtime emits a parent caption span with a
child span per model turn and per tool call. Uses an in-memory OTEL exporter; falls back to
checking the no-op path when OpenTelemetry isn't installed."""

import pytest
from test_agentic import CAPTION, Scripted, turn, use

from clayzer.agentcore import runtime
from clayzer.agentcore.runtime import ToolboxCache

pytest.importorskip("opentelemetry", reason="needs opentelemetry (the Runtime image has it)")
pytest.importorskip("opentelemetry.sdk", reason="needs the opentelemetry SDK")


def build_request(**kw):
    from clayzer.agentcore.contract import RunRequest

    args = {"chip": {"id": "c-solar", "uri": "chips/c-solar.png", "date": "2022-07-02",
                     "bbox": [0, 0, 1, 1]},
            "png": b"c-solar", "prompt": "Caption {grid} {objects} {relations}", "model": "cap",
            "max_turns": 8, "tools": [], "verify": None, "footprint": None}  # fmt: skip
    return RunRequest.build(**{**args, **kw})


class FakeBox:
    """A Toolbox exposing one `lookup` tool, as test_agentic's FakeToolbox."""

    def __init__(self, names):
        self.versions = {"fake": "fake-server 1.0"}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass

    def view(self, servers):
        from test_agentic import FakeToolbox

        return FakeToolbox()


@pytest.fixture
def spans(monkeypatch):
    """Capture spans in memory for one test, with a fresh tracer each time."""
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    from clayzer.agentcore import telemetry

    monkeypatch.setattr(telemetry, "_tracer", provider.get_tracer("test"))
    return exporter


def by_name(exporter):
    return {s.name: s for s in exporter.get_finished_spans()}


def test_a_run_with_a_tool_call_produces_a_caption_span_with_turn_and_tool_children(spans):
    bedrock = Scripted(
        turn(use("lookup", {"place": "Mojave"})), turn(use("submit_caption", CAPTION, "t2"))
    )
    runtime.run_request(build_request(tools=["roda"]), bedrock, ToolboxCache(FakeBox))
    names = by_name(spans)
    # The parent, one span per model turn, and the tool call.
    assert "caption" in names
    assert "tool.lookup" in names
    assert "llm.caption" in names
    tool = names["tool.lookup"]
    assert tool.attributes["gen_ai.operation.name"] == "execute_tool"
    assert tool.attributes["gen_ai.tool.name"] == "lookup"
    assert tool.attributes["clayzer.tool.server"] == "fake"
    # The tool and turn spans are children of the caption span (same trace, parented to it).
    caption = names["caption"]
    assert caption.attributes["gen_ai.request.model"] == "cap"
    assert caption.attributes["clayzer.tools"] == "roda"
    assert tool.parent.span_id == caption.context.span_id
    assert tool.context.trace_id == caption.context.trace_id


def test_llm_spans_carry_token_usage(spans):
    bedrock = Scripted(
        turn(use("lookup", {"place": "x"})), turn(use("submit_caption", CAPTION, "t2"))
    )
    runtime.run_request(build_request(tools=["roda"]), bedrock, ToolboxCache(FakeBox))
    llm = by_name(spans)["llm.caption"]
    assert llm.attributes["gen_ai.operation.name"] == "chat"
    # The scripted turns report input/output tokens (the single-call fake reports only a total).
    assert llm.attributes["gen_ai.usage.input_tokens"] == 10
    assert llm.attributes["gen_ai.usage.output_tokens"] == 5


def test_a_harness_fault_marks_the_caption_span_without_raising(spans):
    # The model never submits: a Harness Fault, reported in the response, with a span event.
    runtime.run_request(build_request(tools=["roda"]), Scripted(turn(text="done")),
                        ToolboxCache(FakeBox))  # fmt: skip
    caption = by_name(spans)["caption"]
    assert any(e.name == "caption.harness_fault" for e in caption.events)


def test_the_module_is_a_no_op_without_opentelemetry(monkeypatch):
    from clayzer.agentcore import telemetry

    monkeypatch.setattr(telemetry, "_tracer", None)
    with telemetry.span("x", foo="bar") as s:
        assert s is None
    assert telemetry.set_session("sid") is None
    telemetry.detach(None)
    telemetry.add_event("evt", k="v")  # must not raise


def test_a_session_id_is_attached_as_baggage(spans):
    from opentelemetry import baggage

    from clayzer.agentcore import telemetry

    token = telemetry.set_session("batch-123")
    try:
        assert baggage.get_baggage("session.id") == "batch-123"
    finally:
        telemetry.detach(token)
