"""The dataset-level verdict: cheap checks on the whole set, the Judge on a stratified sample,
every rate with a 95% Wilson interval, overall and per stratum."""

import json

import pytest
from test_importer import keys, row  # noqa: F401
from test_loop import env  # noqa: F401
from test_score_imported import CLAIMS, ExtractingBedrock

from clayzer import batch as batches
from clayzer import cli
from clayzer import verdict as vd
from clayzer.cases import save_case
from clayzer.importer import import_key, import_rows

MISCOUNT = {**CLAIMS, "objects": [dict(CLAIMS["objects"][0], count=5)]}
ROAD = {**CLAIMS, "objects": [{"id": "o1", "object": "road", "count": 1, "position": "north"}]}


def test_wilson_intervals():
    r = vd.wilson(50, 100)
    assert r["p"] == 0.5 and r["lo"] == pytest.approx(0.404, abs=1e-3)
    assert r["hi"] == pytest.approx(0.596, abs=1e-3)
    none = vd.wilson(0, 10)
    assert none["lo"] == 0.0 and none["hi"] == pytest.approx(0.278, abs=1e-3)
    assert vd.wilson(0, 0)["p"] is None
    # Equal weights are an ordinary proportion.
    assert vd._weighted([(True, 2.0), (False, 2.0)])["p"] == 0.5
    assert vd._weighted([(True, 2.0), (False, 2.0)])["lo"] == pytest.approx(vd.wilson(1, 2)["lo"])


@pytest.fixture
def caption_set(env, keys):  # noqa: F811
    store, settings, fake = env
    fake["client"] = ExtractingBedrock()
    rows = [
        row("a", "k1", claims=CLAIMS, image_uri="chips/c-solar.png"),
        row("b", "k1", claims=CLAIMS, image_uri="chips/c-solar.png"),  # same text as a
        row("c", "k1", caption="Five solar arrays.", claims=MISCOUNT,
            image_uri="chips/c-solar.png"),
        row("d", "k1", caption="A road up north.", claims=ROAD, image_uri="chips/c-solar.png"),
        row("e", "r1", caption="An airport.", geometry=None, datetime=None, gsd_m=None,
            sensor="rsicd", scene="airport", claims={"objects": [], "relations": [],
                                                     "uncertain": []}),
    ]  # fmt: skip
    for c in import_rows(rows, "set", progress=lambda *_: None).cases:
        save_case(store, import_key("set"), c)
    return store, settings


def test_cheap_checks_cover_the_whole_set_and_the_judge_a_sample(caption_set):
    store, settings = caption_set
    cases = [json.loads(x) for x in store.get(import_key("set")).decode().splitlines()]
    quiet = {"progress": lambda *_: None}
    fid = batches.create(cases, settings, store, 1, "all", "import-set", judge=False,
                         source="imported")  # fmt: skip
    batches.resume(fid, settings, store, **quiet)
    full = batches.load(store, fid)

    ids = vd.sample(full, per_stratum=1)
    # One per primary class: solar_array (a, b, c), road (d), none (e).
    assert len(ids) == 3 and "import-set-d" in ids and "import-set-e" in ids
    assert vd.sample(full, 1) == ids  # a fixed seed

    jid = batches.create([c for c in cases if c["id"] in ids], settings, store, 1, "judged",
                         "import-set", source="imported")  # fmt: skip
    batches.resume(jid, settings, store, **quiet)
    v = vd.build(full, batches.load(store, jid))

    r = v["rates"]
    assert v["captions"] == 5
    assert (r["duplicate"]["k"], r["duplicate"]["n"]) == (2, 5)  # a and b
    assert (r["miscount"]["k"], r["miscount"]["n"]) == (1, 4)  # c; e isn't located
    # d claims a road the Answer Key doesn't have (it has the solar site only).
    assert (r["false_claim"]["k"], r["false_claim"]["n"]) == (1, 4)
    assert r["too_small"]["n"] == 4  # e has no imagery resolution
    assert all(0 <= x["lo"] <= x["p"] <= x["hi"] <= 1 for x in r.values() if x["p"] is not None)
    # The Judge's fake gives 0.8: nothing unfaithful, over the two judged captions with images.
    assert v["judged"] == 2 and r["unfaithful"]["p"] == 0.0

    strata = v["strata"]
    assert set(strata["class"]) == {"none", "road", "solar_array"}
    assert strata["class"]["solar_array"]["captions"] == 4  # d's Answer Key has the site too
    assert set(strata["region"]) == {"utm-11", "unlocated"}
    assert strata["terrain"]["airport"]["captions"] == 1
    assert strata["class"]["road"]["rates"]["unfaithful"]["n"] == 1

    md = vd.render(v)
    assert "| Repeats another caption's text | 40% [" in md
    assert "## By terrain" in md and "## Vocabulary" in md


def test_verdict_from_the_cli_and_rebuilt_from_its_batches(caption_set, monkeypatch, capsys):
    store, settings = caption_set
    monkeypatch.setattr(cli, "load_env", lambda: None)
    monkeypatch.setenv("CLAYZER_DATA_DIR", str(settings.data_dir))
    monkeypatch.setenv("CLAYZER_BATCHES_DIR", str(settings.batches_dir))
    monkeypatch.setenv("CLAYZER_JUDGE_MODEL", "judge")
    monkeypatch.delenv("CLAYZER_STORE", raising=False)
    assert cli.main(["verdict", "set", "--per-stratum", "1"]) == 0
    assert "judging a stratified sample of 3" in capsys.readouterr().out
    saved = json.loads(store.get(vd.verdict_key("set")))
    assert store.exists("verdicts/set.md")

    # Rebuilt from the same two Batches, with no model call: the same verdict.
    assert cli.main(["verdict", "set", "--full", saved["full_batch"],
                     "--judged", saved["judged_batch"]]) == 0  # fmt: skip
    assert json.loads(store.get(vd.verdict_key("set"))) == saved
    assert cli.main(["verdict", "missing"]) == 2
