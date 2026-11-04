import json

from clayzer.cases import load_cases, save_case
from clayzer.chips import aws_key
from clayzer.cli import _push
from clayzer.store import LocalStore


def test_local_store_maps_batches_and_data_to_their_folders(tmp_path):
    store = LocalStore(tmp_path / "data", tmp_path / "batches")
    store.put("chips/a.png", b"png")
    store.put("batches/b1/summary.json", b"{}")
    assert (tmp_path / "data/chips/a.png").read_bytes() == b"png"
    assert (tmp_path / "batches/b1/summary.json").exists()
    assert store.list_dirs("batches/") == ["b1"]
    assert store.exists("chips/a.png") and not store.exists("chips/b.png")
    store.delete("chips/a.png")
    assert not store.exists("chips/a.png")


def test_save_case_replaces_by_id(tmp_path):
    store = LocalStore(tmp_path, tmp_path)
    save_case(store, "cases/c.jsonl", {"id": "x", "v": 1})
    save_case(store, "cases/c.jsonl", {"id": "y", "v": 1})
    save_case(store, "cases/c.jsonl", {"id": "x", "v": 2})
    assert load_cases(store, "cases/c.jsonl") == [{"id": "y", "v": 1}, {"id": "x", "v": 2}]


def test_aws_key_from_planetary_computer_href():
    href = (
        "https://naipeuwest.blob.core.windows.net/naip/v002/ca/2022/ca_060cm_2022/35118/"
        "m_3511855_nw_11_060_20220702.tif?st=2026&sig=abc"
    )
    assert aws_key(href) == "ca/2022/60cm/rgb/35118/m_3511855_nw_11_060_20220702.tif"
    assert aws_key("https://example.com/other.tif") is None


def test_push_copies_chips_and_cases_and_normalizes_uris(tmp_path):
    src = tmp_path / "src"
    (src / "chips").mkdir(parents=True)
    (src / "cases").mkdir()
    (src / "chips/c1.png").write_bytes(b"png")
    (src / "chips/c1.json").write_text("{}")
    case = {"id": "x", "chips": [{"id": "c1", "uri": "c1.png"}]}
    (src / "cases/caption-dev.jsonl").write_text(json.dumps(case) + "\n")

    store = LocalStore(tmp_path / "dest", tmp_path / "batches")
    assert _push(store, src) == 3
    assert store.get("chips/c1.png") == b"png"
    assert load_cases(store, "cases/caption-dev.jsonl")[0]["chips"][0]["uri"] == "chips/c1.png"


def test_offsets_put_the_point_in_every_cell_equally_and_inside_the_margin():
    from collections import Counter

    from clayzer.chips import OFFSET_MARGIN_M, RES, SIZE, offset_for
    from clayzer.grid import cell_at

    assert offset_for("uspvdb-400117") == offset_for("uspvdb-400117")  # repeatable
    cells = Counter()
    for i in range(2700):
        east, north = offset_for(f"uspvdb-{i}")
        col, row = SIZE / 2 - east / RES, SIZE / 2 + north / RES
        margin = OFFSET_MARGIN_M / RES
        assert margin <= col <= SIZE - margin and margin <= row <= SIZE - margin
        cells[cell_at(col, row, SIZE)] += 1
    assert len(cells) == 9
    assert min(cells.values()) > 240 and max(cells.values()) < 360  # about 300 each
