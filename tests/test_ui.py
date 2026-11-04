"""The team web app's API, offline, over a local store with one fake Batch."""

import pytest
from fastapi.testclient import TestClient
from test_loop import SOLAR, WIND, FakeBedrock

from clayzer import batch as batches
from clayzer.cases import save_case
from clayzer.config import REPO, Settings
from clayzer.gate import accept_baseline
from clayzer.store import LocalStore
from clayzer.ui.app import SAFE_ID, create_app, load_glossary, load_sources, load_tasks


@pytest.fixture
def client(tmp_path, monkeypatch):
    store = LocalStore(tmp_path / "data", tmp_path / "batches")
    for case in (SOLAR, WIND):
        chip = case["chips"][0]["id"]
        store.put(f"chips/{chip}.png", chip.encode())
        save_case(store, "cases/caption-dev.jsonl", case)
    settings = Settings(
        caption_model="cap", judge_model="judge", embed_model="embed",
        bedrock_endpoint_url=None, data_dir=tmp_path / "data",
        batches_dir=tmp_path / "batches", baselines_dir=tmp_path / "baselines",
        store_url=None, naip_source="pc",
    )  # fmt: skip
    monkeypatch.setattr(batches, "bedrock", lambda s: FakeBedrock())
    bid = batches.start([SOLAR, WIND], settings, store, 2, "base", "dev", progress=lambda _: None)
    accept_baseline(batches.load(store, bid), settings.baselines_dir)
    return TestClient(create_app(settings)), bid


def test_overview_has_the_latest_batch_baseline_and_tasks(client):
    c, bid = client
    o = c.get("/api/overview").json()
    assert o["latest"]["batch_id"] == bid
    assert o["baseline"]["batch_id"] == bid
    assert o["cases"] == 2
    assert o["tasks"]


def test_batches_report_gate_and_compare(client):
    c, bid = client
    assert c.get("/api/batches").json()[0]["batch_id"] == bid
    assert c.get(f"/api/batches/{bid}").json()["config"]["repeats"] == 2
    assert "Caption Batch" in c.get(f"/api/batches/{bid}/report.html").text
    g = c.get(f"/api/gate/{bid}").json()
    assert g["verdict"] == "pass" and g["exit_code"] == 0
    assert c.get(f"/api/compare?a={bid}&b={bid}").json()["settings"] == []


def test_cases_and_chips(client):
    c, _ = client
    cases = c.get("/api/cases").json()
    assert {x["id"] for x in cases} == {SOLAR["id"], WIND["id"]}
    assert c.get("/api/chips/c-solar.png").content == b"c-solar"
    assert c.get("/api/chips/nope.png").status_code == 404


def test_ids_cannot_escape_the_store(client):
    c, _ = client
    assert c.get("/api/batches/..%2F..%2Fdata").status_code in (400, 404)
    assert c.get("/api/batches/x..y").status_code == 400
    assert c.get("/api/chips/..c.png").status_code == 400


def test_launch_is_refused_unless_allowed(client):
    c, _ = client
    assert c.post("/api/batches", json={"repeats": 1}).status_code == 403


def test_the_page_and_static_files_load(client):
    c, _ = client
    assert "Clayzer" in c.get("/").text
    assert c.get("/static/app.js").status_code == 200


def test_the_real_task_board_and_glossary_parse():
    tasks = load_tasks()
    ids = {t["id"] for t in tasks}
    assert len(ids) == len(tasks), "task ids must be unique"
    for t in tasks:
        assert t["status"] in {"done", "doing", "todo", "blocked", "decide"}, t["id"]
        assert t["tier"] in {"Must", "Should", "Could"}, t["id"]
        assert set(t.get("after", [])) <= ids, t["id"]
    terms = {t["term"] for t in load_glossary()}
    assert {"Case", "Chip", "Batch", "Baseline", "Spread"} <= terms


def test_launch_runs_a_batch_in_the_background(client, tmp_path):
    import time

    # A second app over the fixture's store, with launching allowed.
    del client
    s = Settings(
        caption_model="cap", judge_model="judge", embed_model="embed",
        bedrock_endpoint_url=None, data_dir=tmp_path / "data",
        batches_dir=tmp_path / "batches", baselines_dir=tmp_path / "baselines",
        store_url=None, naip_source="pc",
    )  # fmt: skip
    launcher = TestClient(create_app(s, allow_launch=True))
    job = launcher.post("/api/batches", json={"repeats": 1, "label": "from ui!"}).json()
    assert job["state"] == "running"
    assert job["batch_id"].endswith("-from-ui")  # label made safe for store keys
    for _ in range(50):
        jobs = launcher.get("/api/jobs").json()
        if jobs[-1]["state"] != "running":
            break
        time.sleep(0.05)
    assert jobs[-1]["state"] == "done", jobs[-1]["lines"]
    assert any(b["batch_id"] == job["batch_id"] for b in launcher.get("/api/batches").json())


def test_the_data_sources_parse_and_point_at_real_code(client):
    c, _ = client
    sources = load_sources()
    assert c.get("/api/sources").json() == sources
    task_ids = {t["id"] for t in load_tasks()}
    ids = [s["id"] for s in sources]
    assert len(ids) == len(set(ids)), "source ids must be unique"
    for s in sources:
        assert s["status"] in {"used", "partial", "planned", "waiting", "unused"}, s["id"]
        assert set(s.get("tasks", [])) <= task_ids, s["id"]
        if s["status"] in {"used", "partial"}:
            assert s["used_in"], f"{s['id']} is {s['status']} but lists no code"
        for im in s.get("images", []):
            src = im["src"]
            chip = src.startswith("chip:") and SAFE_ID.match(src.removeprefix("chip:"))
            assert src.startswith("https://") or chip, src
            assert im["caption"], src
        for u in s["used_in"]:
            path = REPO / u["path"]
            assert path.exists(), (s["id"], u["path"])
            assert u["symbol"] in path.read_text(), (s["id"], u["path"], u["symbol"])


def test_every_task_belongs_to_a_how_it_works_step():
    import re
    from pathlib import Path

    js = (Path(__file__).parents[1] / "src/clayzer/ui/static/app.js").read_text()
    flow = js[js.index("const FLOW = [") : js.index("function stepState(")]
    steps = re.findall(r'key: "([a-z]+)", phase:', flow)
    tasks = load_tasks()
    assert len(steps) == 10
    for t in tasks:
        assert t.get("step") in steps, f"{t['id']} has step {t.get('step')!r}"
    assert {t["step"] for t in tasks} == set(steps), "every step needs at least one task"


def test_every_task_has_a_brief_with_real_references_and_requirements():
    from pathlib import Path

    from clayzer.ui.app import load_requirements

    root = Path(__file__).parents[1]
    reqs = load_requirements()
    areas = {"Data and Cases", "Captioning", "Evaluation", "Platform", "Demo and delivery"}
    for t in load_tasks():
        assert t["area"] in areas, f"{t['id']}: unknown area {t['area']!r}"
        assert t.get("context"), f"{t['id']} has no context"
        assert t.get("done_when"), f"{t['id']} has no done_when"
        assert t.get("refs"), f"{t['id']} has no refs"
        for ref in t["refs"]:
            path = ref.split(" ")[0]
            assert (root / path).exists(), f"{t['id']}: {path} doesn't exist"
        for rid in t.get("closes", []):
            assert rid in reqs, f"{t['id']}: {rid} isn't in caption-design.md §2"


def test_requirements_endpoint(client):
    c, _ = client
    reqs = c.get("/api/requirements").json()
    assert reqs["CAP-10"].startswith("Grounding")
    assert {"REQ-06", "AWS-05"} <= set(reqs)
