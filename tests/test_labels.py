"""Hand-made labels: the /label page's API, saving only with --calibrate, and label checks."""

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from clayzer.extract import check_claims
from clayzer.ui.app import STATIC
from clayzer.ui.labels import SETS, router

GOOD = {
    "objects": [
        {"id": "o1", "object": "solar_array", "count": 1, "position": "centre"},
        {"id": "o2", "object": "road", "count": None, "position": None},
    ],
    "relations": [{"subject": "o2", "relation": "west_of", "object": "o1"}],
    "uncertain": ["possibly a pond"],
}


@pytest.fixture
def labels(tmp_path):
    path = tmp_path / "sample.jsonl"
    rows = [{"id": "a", "text": "A solar farm.", "claims": None},
            {"id": "b", "text": "A road.", "claims": None}]  # fmt: skip
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return path


def client(path, calibrate):
    app = FastAPI()
    app.include_router(router(calibrate, STATIC, {"extraction": path}))
    return TestClient(app)


def test_read_only_shows_the_set_but_never_saves(labels):
    c = client(labels, calibrate=False)
    got = c.get("/api/labels/extraction").json()
    assert got["writable"] is False and [i["id"] for i in got["items"]] == ["a", "b"]
    assert {"solar_array", "road"} <= {o["id"] for o in got["vocabulary"]["objects"]}
    r = c.put("/api/labels/extraction/a", json={"claims": GOOD})
    assert r.status_code == 403 and "--calibrate" in r.json()["detail"]
    assert all(json.loads(line)["claims"] is None for line in labels.read_text().splitlines())


def test_calibrate_saves_one_label_and_leaves_the_rest(labels):
    c = client(labels, calibrate=True)
    assert c.put("/api/labels/extraction/a", json={"claims": GOOD}).json() == {
        "id": "a",
        "labelled": True,
        "source": "by hand",
    }
    rows = [json.loads(line) for line in labels.read_text().splitlines()]
    assert rows[0] == {"id": "a", "text": "A solar farm.", "claims": GOOD, "source": "by hand"}
    assert rows[1] == {"id": "b", "text": "A road.", "claims": None}
    assert c.get("/api/labels").json()["sets"] == [
        {"name": "extraction", "items": 2, "labelled": 1}
    ]
    c.put("/api/labels/extraction/a", json={"claims": None})
    assert json.loads(labels.read_text().splitlines()[0])["claims"] is None


@pytest.mark.parametrize("bad, reason", [
    ({**GOOD, "objects": [{"id": "o1", "object": "castle", "count": 1, "position": None}],
      "relations": []}, "isn't an ontology class"),
    ({**GOOD, "objects": [{"id": "o1", "object": "road", "count": 0, "position": None}],
      "relations": []}, "count must be"),
    ({**GOOD, "objects": [{"id": "o1", "object": "road", "count": 1, "position": "top"}],
      "relations": []}, "isn't a grid cell"),
    ({**GOOD, "relations": [{"subject": "o9", "relation": "west_of", "object": "o1"}]},
     "isn't one of the objects"),
    ({**GOOD, "relations": [{"subject": "o1", "relation": "near", "object": "o2"}]},
     "relation must be one of"),
])  # fmt: skip
def test_a_bad_label_is_refused_with_a_reason(labels, bad, reason):
    r = client(labels, calibrate=True).put("/api/labels/extraction/a", json={"claims": bad})
    assert r.status_code == 400 and reason in r.json()["detail"]


def test_unknown_items_and_sets(labels):
    c = client(labels, calibrate=True)
    assert c.put("/api/labels/extraction/zz", json={"claims": GOOD}).status_code == 404
    assert c.get("/api/labels/nope").status_code == 404


def test_the_page_is_served(labels):
    page = client(labels, calibrate=False).get("/label")
    assert page.status_code == 200 and "/static/label/label.js" in page.text


def test_the_committed_sample_is_well_formed():
    rows = [
        json.loads(line) for line in SETS["extraction"].read_text().splitlines() if line.strip()
    ]
    assert len(rows) == 20 and len({r["id"] for r in rows}) == 20
    for r in rows:
        assert r["text"] and (r["claims"] is None or check_claims(r["claims"]) == []), r["id"]
        assert not (r.get("blind") and r.get("proposed")), f"{r['id']} is blind but has a proposal"
        if r.get("proposed"):
            assert check_claims(r["proposed"]) == [] and r["proposed_by"], r["id"]
    blind = [r for r in rows if r.get("blind")]
    assert len(blind) == 5 and sum(1 for r in rows if r.get("proposed")) == 15
    assert len({r["id"].split("--")[1] for r in blind}) == 4, "the blind ones cover every Case"


def test_good_claims_pass_the_check():
    assert (
        check_claims(GOOD) == []
        and check_claims({"objects": [], "relations": [], "uncertain": []}) == []
    )


@pytest.fixture
def proposed(tmp_path):
    path = tmp_path / "sample.jsonl"
    rows = [
        {"id": "p", "text": "A solar farm.", "claims": None, "proposed": GOOD, "proposed_by": "m"},
        {"id": "b", "text": "A road.", "claims": None, "blind": True},
        {"id": "h", "text": "A field.", "claims": None},
    ]
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return path


def test_each_label_records_where_it_came_from(proposed):
    c = client(proposed, calibrate=True)
    items = {i["id"]: i for i in c.get("/api/labels/extraction").json()["items"]}
    assert items["p"]["proposed"] == GOOD and items["p"]["proposed_by"] == "m"
    assert items["b"]["blind"] and items["b"]["proposed"] is None
    # The same Claims with other ids still count as accepting the proposal.
    renamed = json.loads(json.dumps(GOOD).replace('"o1"', '"x1"').replace('"o2"', '"x2"'))
    put = lambda i, claims: c.put(f"/api/labels/extraction/{i}", json={"claims": claims}).json()
    assert put("p", renamed)["source"] == "proposal accepted"
    assert put("p", {**GOOD, "uncertain": []})["source"] == "proposal edited"
    assert put("b", GOOD)["source"] == "blind"
    assert put("h", GOOD)["source"] == "by hand"
    saved = {json.loads(x)["id"]: json.loads(x) for x in proposed.read_text().splitlines()}
    assert saved["p"]["source"] == "proposal edited" and saved["p"]["proposed"] == GOOD


def test_comparing_a_proposal_with_mixed_counts_and_relations(proposed):
    # A relation between an object with a count and one without crashed the comparison (#18).
    mixed = {
        "objects": [
            {"id": "o1", "object": "solar_array", "count": 1, "position": "centre"},
            {"id": "o2", "object": "vegetation", "count": None, "position": None},
            {"id": "o3", "object": "road", "count": None, "position": "west"},
        ],
        "relations": [
            {"subject": "o1", "relation": "inside", "object": "o2"},
            {"subject": "o3", "relation": "west_of", "object": "o1"},
        ],
        "uncertain": [],
    }
    rows = [json.loads(x) for x in proposed.read_text().splitlines()]
    rows[0]["proposed"] = mixed
    proposed.write_text("".join(json.dumps(r) + "\n" for r in rows))
    c = client(proposed, calibrate=True)
    r = c.put("/api/labels/extraction/p", json={"claims": mixed})
    assert r.status_code == 200 and r.json()["source"] == "proposal accepted"
    changed = {**mixed, "relations": mixed["relations"][:1]}
    assert (
        c.put("/api/labels/extraction/p", json={"claims": changed}).json()["source"]
        == "proposal edited"
    )


def test_the_label_page_reuses_no_site_class():
    # The site's .grid3 (the overlay on Chip images) once hid the position grid and made it
    # unclickable: the page's own classes must not collide with the site stylesheet's.
    import re

    site = (STATIC / "style.css").read_text()
    page = (STATIC / "label" / "label.css").read_text()
    allowed = {"btn", "secondary", "badge", "b-ok", "b-warn", "sub"}  # meant to be shared
    mine = set(re.findall(r"\.([a-z][a-z0-9-]*)", page)) - allowed
    clashes = {c for c in mine if re.search(rf"\.{c}(?![a-z0-9-])", site)}
    # .meta is defined on the site only inside .task, so it can't reach this page.
    assert clashes <= {"meta"}, f"label.css reuses site classes: {sorted(clashes)}"


def test_a_label_must_give_every_count_and_position(labels):
    unset = {"objects": [{"id": "o1", "object": "road"}], "relations": [], "uncertain": []}
    r = client(labels, calibrate=True).put("/api/labels/extraction/a", json={"claims": unset})
    assert r.status_code == 400
    assert "give a count" in r.json()["detail"] and "give a position" in r.json()["detail"]


def test_changing_a_saved_blind_label_is_recorded_as_adjudicated(proposed):
    c = client(proposed, calibrate=True)
    put = lambda claims: c.put("/api/labels/extraction/b", json={"claims": claims}).json()
    assert put(GOOD)["source"] == "blind"
    assert put(GOOD)["source"] == "blind"  # saving it again unchanged
    fixed = {**GOOD, "objects": [{**GOOD["objects"][0], "count": 2}, GOOD["objects"][1]]}
    assert put(fixed)["source"] == "blind, adjudicated"
    assert put(GOOD)["source"] == "blind, adjudicated"  # once adjudicated, it stays so
    # Clearing and labelling again doesn't make it blind again.
    put(None)
    assert put(GOOD)["source"] == "blind, adjudicated"
