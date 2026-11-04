"""Verify, then write: each drafted Claim checked with LGND Geo before the Caption commits."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest
from test_agentic import Scripted, turn, use
from test_loop import SOLAR, WIND, FakeBedrock

from clayzer import batch as batches
from clayzer import harness, tools
from clayzer.config import Settings
from clayzer.store import LocalStore
from clayzer.tools import McpServer, ToolResult
from clayzer.trace import RunInfo, Tracer, loads, trace_key
from clayzer.verify import cell_centre, verify
from clayzer.workflow import score

FOOTPRINT = {"bbox": [0.0, 0.0, 3.0, 3.0], "date": "2022-07-02"}


class FakeLgnd:
    """LGND's two tools: `verdicts` maps an object word to a verdict; a missing word fails."""

    def __init__(self, verdicts, images=True):
        self.verdicts, self.images, self.calls = verdicts, images, []
        self.specs = []

    def server_for(self, name):
        return "lgnd"

    def call(self, name, args):
        self.calls.append((name, args))
        if name == "search_chip_lat_lon":
            if not self.images:
                return ToolResult(json.dumps({"error": "no chip here"}), False)
            node = f"naip/obs:{args['lat']},{args['lon']}"
            return ToolResult(json.dumps({"node": node, "observed": "2022-07-02"}), False)
        word = next((w for w in self.verdicts if w in args["claim"].lower()), None)
        if word is None:
            return ToolResult("ServiceUnavailable: try later", True, "ServiceUnavailableException")
        return ToolResult(json.dumps({"verdict": self.verdicts[word],
                                      "places": [{"reason": f"looked for {word}"}]}), False)  # fmt: skip


def draft():
    return {
        "text": "A solar array in the south-east, a wind turbine to the north, a road west.",
        "objects": [
            {"id": "o1", "object": "solar_array", "count": 1, "position": "south_east"},
            {"id": "o2", "object": "wind_turbine", "count": 1, "position": "north"},
            {"id": "o3", "object": "road", "count": 1, "position": "west"},
            {"id": "o4", "object": "building", "count": 2, "position": "south_east"},
        ],
        "relations": [
            {"subject": "o2", "relation": "north_of", "object": "o1"},
            {"subject": "o3", "relation": "west_of", "object": "o1"},
        ],
        "uncertain": [],
    }


def tracer():
    run = RunInfo(run_id="r", task="caption", case_id="c", repeat=1, batch_id="b",
                  model_id="m", prompt_sha="p")  # fmt: skip
    return Tracer(run, [])


def test_cell_centres_follow_a_north_up_grid():
    assert cell_centre([0, 0, 3, 3], "centre") == (1.5, 1.5)
    assert cell_centre([0, 0, 3, 3], "north_west") == (2.5, 0.5)
    assert cell_centre([0, 0, 3, 3], "south_east") == (0.5, 2.5)


def test_only_confirmed_claims_stay():
    lgnd = FakeLgnd({"solar": "supported", "wind": "not supported", "building": "supported"})
    t = tracer()
    cap, report = verify(draft(), FOOTPRINT, lgnd, t)
    # Confirmed stay; rejected move to uncertain; a failed check keeps the Claim, unverified.
    assert [o["id"] for o in cap["objects"]] == ["o1", "o3", "o4"]
    assert cap["uncertain"] == ["1 × wind turbine at north"]
    assert cap["relations"] == [{"subject": "o3", "relation": "west_of", "object": "o1"}]
    assert (report["claims"], report["confirmed"], report["moved"], report["unverified"]) == (
        4,
        2,
        1,
        1,
    )
    # One image lookup per cell (o1 and o4 share south_east), one check per Claim.
    names = [n for n, _ in lgnd.calls]
    assert names.count("search_chip_lat_lon") == 3 and names.count("reasoning_imagery_check") == 4
    assert lgnd.calls[0][1] == {"index": "naip", "lat": 0.5, "lon": 2.5}
    check = lgnd.calls[1][1]
    assert check == {"claim": "A solar array is visible here.", "kind": "place",
                     "nodes": ["naip/obs:0.5,2.5"]}  # fmt: skip
    # Every call is a tool Step with role verify.
    assert len(t.steps) == 7 and all(
        s.kind == "tool" and s.attributes["role"] == "verify" for s in t.steps
    )


def test_no_image_leaves_the_claim_unverified():
    cap, report = verify(draft(), FOOTPRINT, FakeLgnd({}, images=False))
    assert len(cap["objects"]) == 4 and report["unverified"] == 4 and report["moved"] == 0


def test_the_harness_rewrites_from_the_confirmed_claims_only():
    d = draft()
    rewritten = {**d, "text": "A solar array and two buildings in the south-east; a road west."}
    bedrock = Scripted(turn(use("submit_caption", d)), turn(use("submit_caption", rewritten, "t2")))
    t = tracer()
    lgnd = FakeLgnd({"solar": "supported", "wind": "not supported", "building": "supported",
                     "road": "supported"})  # fmt: skip
    cap, step = harness.caption(bedrock, "m", "chip", b"png", tracer=t,
                                verifier=lgnd, footprint=FOOTPRINT)  # fmt: skip
    assert cap["text"] == rewritten["text"]
    # The rewrite listed every drafted Claim, but only the verifier's survive.
    assert [o["id"] for o in cap["objects"]] == ["o1", "o3", "o4"]
    assert step["verification"]["moved"] == 1 and step["usage"]["totalTokens"] == 30
    draft_req, rewrite_req = bedrock.requests
    assert "image" in draft_req["messages"][0]["content"][0]
    assert all("image" not in c for c in rewrite_req["messages"][0]["content"])
    assert [s.name for s in t.steps if s.kind == "llm"] == ["caption", "rewrite"]
    assert t.run.metadata["verification"]["checks"][1]["verdict"] == "not supported"
    # The Run still finishes through submit_caption, so the tool plan holds.
    t.run.status = "ok"
    assert score(t.run, t.steps)["components"]["tool_plan"]["score"] == 1.0


def test_nothing_rejected_means_no_rewrite():
    bedrock = Scripted(turn(use("submit_caption", draft())))
    lgnd = FakeLgnd({"solar": "supported", "wind": "supported", "building": "supported",
                     "road": "supported"})  # fmt: skip
    cap, step = harness.caption(bedrock, "m", "chip", b"png", verifier=lgnd, footprint=FOOTPRINT)
    assert cap["text"] == draft()["text"] and len(bedrock.requests) == 1
    assert step["verification"]["confirmed"] == 4


class RewritingBedrock(FakeBedrock):
    """FakeBedrock, plus the text-only rewrite call."""

    def converse(self, modelId, messages, toolConfig, inferenceConfig):
        content = messages[0]["content"]
        if "image" not in content[0]:
            self.calls += 1
            body = {"text": "Nothing confirmed.", "objects": [], "relations": [], "uncertain": []}
            block = {"toolUse": {"toolUseId": "w", "name": "submit_caption", "input": body}}
            return {"output": {"message": {"content": [block]}}, "stopReason": "tool_use",
                    "usage": {"totalTokens": 20}}  # fmt: skip
        assert [t["toolSpec"]["name"] for t in toolConfig["tools"]] in (
            ["submit_caption"],
            ["submit_verdict"],
        ), "the verifier's tools must not be offered to the model"
        return super().converse(modelId, messages, toolConfig, inferenceConfig)


@pytest.mark.skipif(importlib.util.find_spec("mcp") is None, reason="needs the tools extra")
def test_a_batch_with_verification(tmp_path, monkeypatch):
    store = LocalStore(tmp_path / "data", tmp_path / "batches")
    for case in (SOLAR, WIND):
        store.put(f"chips/{case['chips'][0]['id']}.png", case["chips"][0]["id"].encode())
    settings = Settings(
        caption_model="cap", judge_model="judge", embed_model="embed",
        bedrock_endpoint_url=None, data_dir=tmp_path / "data",
        batches_dir=tmp_path / "batches", baselines_dir=tmp_path / "baselines",
        store_url=None, naip_source="pc",
    )  # fmt: skip
    monkeypatch.setattr(batches, "bedrock", lambda s: RewritingBedrock())
    fake = McpServer("lgnd", sys.executable, [str(Path(__file__).with_name("fake_lgnd_server.py"))])
    monkeypatch.setitem(tools.SERVERS, "lgnd", fake)
    bid = batches.start([SOLAR, WIND], settings, store, 1, "verify", "dev", verify="lgnd",
                        narrate=False, progress=lambda _: None)  # fmt: skip
    assert batches.load_config(store, bid).verify == "lgnd"
    results = {r["case_id"]: r for r in batches.load(store, bid)["results"]}
    assert results[SOLAR["id"]]["verification"]["confirmed"] == 1
    assert results[WIND["id"]]["verification"]["moved"] == 1
    captions = {c["case_id"]: c for c in batches.load(store, bid)["captions"]}
    assert (
        captions[WIND["id"]]["objects"] == []
        and captions[WIND["id"]]["text"] == "Nothing confirmed."
    )
    _, steps = loads(store.get(trace_key(bid, WIND["id"], 1)))
    assert [s.name for s in steps if s.attributes.get("role") == "verify"] == [
        "search_chip_lat_lon",
        "reasoning_imagery_check",
    ]
