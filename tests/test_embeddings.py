"""Chip embeddings: the LGND partition/cell join, and the Layer B sources (ADR-0010)."""

import base64
import io
import json

from clayzer import embeddings as emb


class FakeTitan:
    """Bedrock Titan multimodal: echoes the input image's length so tests can tell calls apart."""

    def __init__(self):
        self.seen = []

    def invoke_model(self, modelId, body):
        payload = json.loads(body)
        self.seen.append(payload)
        img = base64.b64decode(payload["inputImage"])
        return {"body": io.BytesIO(json.dumps({"embedding": [float(len(img)), 1.0]}).encode())}


def _case(cid, obj, embedding=None):
    chip = {"id": cid, "uri": f"chips/{cid}.png"}
    if embedding is not None:
        chip["embedding"] = embedding
    return {"id": f"fixed-{cid}", "chips": [chip],
            "reference_labels": [{"object": obj, "count": 1, "position": "centre"}]}  # fmt: skip


def test_precomputed_looks_up_by_chip_id():
    source = emb.PrecomputedEmbedding({"c-1": [0.1, 0.2]})
    assert source.embed_chip({"id": "c-1"}, None) == [0.1, 0.2]
    assert source.embed_chip({"id": "missing"}, None) is None


def test_titan_embeds_the_png_and_calls_once_per_chip():
    source = emb.TitanImageEmbedding(FakeTitan())
    vec = source.embed_chip({"id": "c-1"}, b"PNGDATA")
    assert vec == [7.0, 1.0]  # len(b"PNGDATA") == 7
    assert source.embed_chip({"id": "c-2"}, None) is None  # no image → no call


def test_attach_to_cases_sets_embedding_and_counts():
    cases = [_case("c-1", "solar_array"), _case("c-2", "water")]
    source = emb.PrecomputedEmbedding({"c-1": [1.0, 0.0], "c-2": [0.0, 1.0]})
    n = emb.attach_to_cases(cases, source)
    assert n == 2
    assert cases[0]["chips"][0]["embedding"] == [1.0, 0.0]


def test_pairs_from_cases_uses_reference_labels_as_class_membership():
    cases = [_case("c-1", "solar_array", [1.0, 0.0]), _case("c-2", "water", [0.0, 1.0])]
    pairs = emb.pairs_from_cases(cases)
    assert ("solar_array", [1.0, 0.0]) in pairs
    assert ("water", [0.0, 1.0]) in pairs
    # A Case with no embedding contributes nothing.
    assert emb.pairs_from_cases([_case("c-3", "field")]) == []


def test_load_precomputed_reads_jsonl(tmp_path):
    p = tmp_path / "e.jsonl"
    p.write_text('{"chip_id": "c-1", "embedding": [0.5, 0.5]}\n')
    source = emb.load_precomputed(p)
    assert source.embed_chip({"id": "c-1"}, None) == [0.5, 0.5]


def test_geohash_matches_the_partitions_our_regions_fall_in():
    assert emb.geohash(-118.2, 35.0) == "9q"  # Mojave / Tehachapi
    assert emb.geohash(-100.0, 31.0) == "9v"  # Texas
    assert emb.geohash(-105.5, 40.0) == "9x"  # the dataset README's example box


def test_a_partition_is_one_geohash_and_month():
    path = emb.partition("9q", 2022, 5)
    assert path.endswith("chip_size=1280m/dims=256/geohash=9q/year=2022/month=05/*.parquet")
    assert path.startswith("s3://us-west-2.opendata.source.coop/clay/lgnd-embeddings/")


def test_months_wrap_across_years():
    assert emb.months_away(2022, 1, -1) == (2021, 12)
    assert emb.months_away(2022, 12, 2) == (2023, 2)


def case(cid, *chips):
    return {"id": cid, "chips": [{"id": i, "bbox": [lon - 0.0015, lat - 0.0015, lon + 0.0015,
                                                    lat + 0.0015], "date": d}
                                 for i, lon, lat, d in chips]}  # fmt: skip


def test_each_distinct_chip_once_with_every_case_it_is_in():
    cases = [case("fixed-a", ("k1", -118.2, 35.0, "2022-05-04")),
             case("change-a", ("k0", -118.2, 35.0, "2014-05-14"), ("k1", -118.2, 35.0, "2022-05-04")),
             {"id": "import-x", "chips": [{"id": "r1", "bbox": None, "date": None}]}]  # fmt: skip
    points = {p["chip_id"]: p for p in emb.chip_points(cases)}
    assert sorted(points) == ["k0", "k1"]  # an unlocated imported Chip has no cell
    assert points["k1"]["case_ids"] == ["fixed-a", "change-a"]
    assert points["k1"]["lon"] == -118.2


def cell(cid, w, s, e, n):
    return {"cell_id": cid, "embedding_id": f"e-{cid}", "datetime": "2022-05-18T18:44:54+00:00",
            "stac_item_id": "S2A_11SLU_20220518_0_L2A", "bbox": [w, s, e, n],
            "embedding": [0.1] * emb.DIMS}  # fmt: skip


def test_a_chip_joins_the_cell_holding_its_centre():
    p = {"lon": -118.2, "lat": 35.0}
    near, far = (
        cell("c1", -118.21, 34.99, -118.195, 35.005),
        cell("c2", -118.2, 35.0, -118.18, 35.02),
    )
    assert emb.match(p, [far, near])["cell_id"] == "c1"  # both boxes touch it: the nearer centre
    assert emb.match({"lon": -117.0, "lat": 35.0}, [near]) is None


def test_a_chip_without_a_row_in_its_month_takes_the_nearest_month():
    asked = []

    def query_fn(gh, y, m, pts):
        asked.append((gh, y, m, [p["chip_id"] for p in pts]))
        return [cell("c1", -118.21, 34.99, -118.19, 35.01)] if (y, m) == (2022, 4) else []

    points = emb.chip_points([case("a", ("k1", -118.2, 35.0, "2022-05-04"))])
    (row,) = emb.for_chips(points, query_fn, progress=lambda _: None)
    assert asked[:2] == [("9q", 2022, 5, ["k1"]), ("9q", 2022, 4, ["k1"])]  # its month, then -1
    assert row["cell_id"] == "c1" and row["months_away"] == -1 and row["cell_size_m"] == 1280
    assert len(row["embedding"]) == 256 and row["attribution"] == emb.ATTRIBUTION


def test_chips_are_grouped_by_partition_and_old_ones_have_none():
    asked = []

    def query_fn(gh, y, m, pts):
        asked.append((gh, y, m, len(pts)))
        return [cell("c1", -118.3, 34.9, -118.1, 35.1), cell("t1", -100.1, 30.9, -99.9, 31.1)]

    points = emb.chip_points([
        case("a", ("k1", -118.2, 35.0, "2022-05-04"), ("k2", -118.15, 35.05, "2022-05-20")),
        case("b", ("t1", -100.0, 31.0, "2022-05-10")),
        case("c", ("old", -118.2, 35.0, "2014-05-14")),
    ])  # fmt: skip
    rows = {r["chip_id"]: r for r in emb.for_chips(points, query_fn, progress=lambda _: None)}
    assert sorted(asked) == [("9q", 2022, 5, 2), ("9v", 2022, 5, 1)]  # one query per partition
    assert rows["k1"]["cell_id"] == rows["k2"]["cell_id"] == "c1" and rows["t1"]["cell_id"] == "t1"
    assert "before the embeddings start" in rows["old"]["missing"]
    assert rows["old"]["license"] == "CC BY 4.0"
