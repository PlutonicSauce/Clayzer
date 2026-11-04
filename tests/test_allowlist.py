"""The ADR-0006 tool list in code (issue #19): a forbidden MCP server can't be used, and every
Batch records which servers it used."""

from dataclasses import replace

import pytest
from test_loop import SOLAR, WIND

from clayzer import allowlist, tools
from clayzer import batch as batches
from clayzer.allowlist import ForbiddenServer
from clayzer.config import Settings
from clayzer.gate import setting_changes
from clayzer.store import LocalStore
from clayzer.tools import McpServer, Toolbox


@pytest.fixture
def env(tmp_path):
    store = LocalStore(tmp_path / "data", tmp_path / "batches")
    for case in (SOLAR, WIND):
        store.put(f"chips/{case['chips'][0]['id']}.png", case["chips"][0]["id"].encode())
    settings = Settings(
        caption_model="cap", judge_model="judge", embed_model="embed",
        bedrock_endpoint_url=None, data_dir=tmp_path / "data",
        batches_dir=tmp_path / "batches", baselines_dir=tmp_path / "baselines",
        store_url=None, naip_source="pc",
    )  # fmt: skip
    return store, settings


@pytest.mark.parametrize(
    "name",
    ["openstreetmap-mcp-server", "mcp-nominatim", "osm", "OSM-tools", "overturemaps", "Overture"],
)
def test_names_that_read_an_answer_key_are_forbidden(name):
    assert allowlist.is_forbidden(name)
    with pytest.raises(ForbiddenServer, match="ADR-0006"):
        allowlist.check_names([name])


@pytest.mark.parametrize(
    "name", ["roda", "lgnd", "awslabs.roda-mcp-server==0.1.7", "cosmos", "bosmer", "stac-mcp"]
)
def test_other_names_are_allowed(name):
    # Whole words only: `cosmos` and `bosmer` merely contain the letters "osm".
    assert not allowlist.is_forbidden(name)
    allowlist.check_names([name])


def test_a_server_is_checked_by_name_url_package_and_arguments_but_not_file_paths():
    with pytest.raises(ForbiddenServer):
        allowlist.check_server(McpServer("maps", url="https://osm.example/mcp"))
    with pytest.raises(ForbiddenServer):
        allowlist.check_server(McpServer("maps", "uvx", ["openstreetmap-mcp-server"]))
    with pytest.raises(ForbiddenServer):
        allowlist.check_server(McpServer("maps", "uvx", package="geo-nominatim==1.0"))
    # A server started from a folder called "osm" is not an OSM server.
    allowlist.check_server(McpServer("fake", "/home/osm/bin/python", ["/home/osm/server.py"]))


def test_a_toolbox_refuses_a_forbidden_server_however_it_is_built():
    with pytest.raises(ForbiddenServer, match="openstreetmap"):
        Toolbox.named(["openstreetmap"])
    with pytest.raises(ForbiddenServer):
        Toolbox([McpServer("sneaky", "uvx", ["openstreetmap-mcp-server"])])


def test_an_unregistered_server_is_still_refused_as_unknown():
    with pytest.raises(ValueError, match="unknown MCP server"):
        Toolbox.named(["nonsense"])


def test_a_batch_refuses_to_start_with_a_forbidden_server_and_writes_nothing(env):
    store, settings = env
    for kwargs in ({"tools": ["openstreetmap-mcp-server"]}, {"verify": "overture"},
                   {"tools": ["roda"], "verify": "nominatim"}):  # fmt: skip
        with pytest.raises(ForbiddenServer):
            batches.create([SOLAR, WIND], settings, store, 1, "bad", "dev", **kwargs)
    assert not list(store.batches_dir.iterdir()) if store.batches_dir.exists() else True


def test_a_batch_records_each_servers_pin(env, monkeypatch):
    store, settings = env
    fake = McpServer("fake", "uvx", ["fake-mcp==1.2.3"], package="fake-mcp==1.2.3")
    monkeypatch.setitem(tools.SERVERS, "fake", fake)
    bid = batches.create([SOLAR, WIND], settings, store, 1, "pins", "dev", tools=["fake"],
                         verify="lgnd")  # fmt: skip
    cfg = batches.load_config(store, bid)
    assert cfg.tool_servers == {"fake": "fake-mcp==1.2.3", "lgnd": "https://geo.lgnd.ai/mcp"}
    assert cfg.tool_versions is None  # nothing has connected yet


def test_what_a_server_reports_is_recorded_once_and_a_later_difference_is_noted(env):
    store, settings = env
    bid = batches.create([SOLAR, WIND], settings, store, 1, "ver", "dev")
    cfg = batches.load_config(store, bid)
    notes = []

    cfg = batches._record_tool_versions(store, cfg, {"lgnd": "mcp-server 4.0.10"}, notes.append)
    assert batches.load_config(store, bid).tool_versions == {"lgnd": "mcp-server 4.0.10"}
    assert notes == []

    again = batches._record_tool_versions(store, cfg, {"lgnd": "mcp-server 4.1.0"}, notes.append)
    assert again.tool_versions == {"lgnd": "mcp-server 4.0.10"}  # the first record stands
    assert "4.1.0" in notes[0] and "4.0.10" in notes[0]
    assert batches._record_tool_versions(store, cfg, {}, notes.append) is cfg  # nothing to record


def test_compare_shows_the_harness_and_tool_settings(env):
    store, settings = env
    bid = batches.create([SOLAR, WIND], settings, store, 1, "cmp", "dev")
    cfg = batches.load_config(store, bid)
    changed = replace(cfg, harness="agentcore", verify="lgnd", tool_versions={"lgnd": "x"})
    kinds = {s["setting"]: s["kind"] for s in setting_changes(cfg, changed)}
    # A new Harness or verifier is expected to change scores, so it is shown, not warned about.
    assert kinds["harness"] == kinds["verify"] == "captioner"
    assert kinds["tool_versions"] == "not recorded"  # the older Batch never recorded it


def test_the_workflow_score_flags_only_real_forbidden_calls():
    from test_workflow import CALL, SUBMIT, info, llm, scored, tool

    cosmos = [llm(0, CALL), tool(1, "cosmos_lookup", server="cosmos-mcp"), llm(2, SUBMIT)]
    assert scored(info(tools=["x"]), cosmos)["components"]["tool_plan"]["score"] == 1.0
