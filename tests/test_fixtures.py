"""The committed development Cases: complete, licensed, nothing private, and loadable by push."""

import re

from test_loop import CAPTIONS, FakeBedrock

from clayzer import batch as batches
from clayzer.cases import load_cases, parse_jsonl
from clayzer.cli import _push
from clayzer.config import REPO, Settings
from clayzer.store import LocalStore

ROOT = REPO / "fixtures" / "caption"
CASES = parse_jsonl((ROOT / "cases" / "caption-dev.jsonl").read_bytes())


def test_every_case_has_its_chip_and_no_chip_is_orphaned():
    uris = {chip["uri"] for case in CASES for chip in case["chips"]}
    assert all(u.startswith("chips/") for u in uris)
    on_disk = {f"chips/{f.name}" for f in (ROOT / "chips").glob("*.png")}
    assert uris == on_disk
    assert all((ROOT / u.replace(".png", ".json")).exists() for u in uris)


def test_the_set_is_the_planned_mix():
    kinds = [case["id"].split("-")[2] for case in CASES]
    assert len({c["id"] for c in CASES}) == len(CASES)
    assert kinds.count("neg") >= 20 and kinds.count("uspvdb") + kinds.count("uswtdb") >= 40


def test_osm_labels_carry_the_odbl_notice():
    assert any(lbl["source"] == "osm" for case in CASES for lbl in case["reference_labels"])
    notice = (ROOT / "cases" / "NOTICE.md").read_text()
    assert "© OpenStreetMap contributors" in notice and "ODbL" in notice


def test_nothing_private_or_signed_is_committed():
    pattern = re.compile(r"https?://|s3://|amazonaws|\b\d{12}\b|sig=|token", re.IGNORECASE)
    for f in [ROOT / "cases" / "caption-dev.jsonl", *(ROOT / "chips").glob("*.json")]:
        assert not pattern.search(f.read_text()), f.name


def test_push_fills_an_empty_store_and_a_batch_runs_on_it(tmp_path, monkeypatch):
    store = LocalStore(tmp_path / "data", tmp_path / "batches")
    assert _push(store, ROOT) == len(list((ROOT / "chips").glob("*"))) + 1
    cases = load_cases(store, "cases/caption-dev.jsonl")
    assert len(cases) == len(CASES)
    settings = Settings(
        caption_model="cap", judge_model="judge", embed_model="embed",
        bedrock_endpoint_url=None, data_dir=tmp_path / "data",
        batches_dir=tmp_path / "batches", baselines_dir=tmp_path / "baselines",
        store_url=None, naip_source="pc",
    )  # fmt: skip
    # The fake Bedrock reads a Chip's id from its image bytes, so stand ids in for the PNGs.
    for case in cases[:3]:
        chip = case["chips"][0]
        store.put(chip["uri"], chip["id"].encode())
        monkeypatch.setitem(CAPTIONS, chip["id"], CAPTIONS["c-solar"])
    monkeypatch.setattr(batches, "bedrock", lambda s: FakeBedrock())
    bid = batches.start(cases[:3], settings, store, 1, "", "dev", progress=lambda _: None)
    runs = batches.load(store, bid)["summary"]["batch"]["runs"]
    assert runs["planned"] == 3 and runs["sandbox_failures"] == 0
