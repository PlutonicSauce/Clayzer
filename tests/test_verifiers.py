"""A verifier per object class: routes, calibration on development Cases, and setting spread."""

import json

from test_verify import FOOTPRINT, draft

from clayzer import calibrate, lgnd, spread, verifiers
from clayzer.store import LocalStore
from clayzer.tools import ToolResult
from clayzer.verify import cell_centre, verify


def table(columns, rows):
    return {"columns": columns, "rows": rows}


class FakeGeo:
    """LGND Geo in its own response shapes. `sees(node, claim)` answers an imagery check;
    `labels[node]` is the classifier's label. Nodes are named after their point."""

    def __init__(self, sees=lambda node, claim: True, labels=None, classifiers=()):
        self.sees, self.labels = sees, labels or {}
        self.classifiers, self.calls = list(classifiers), []

    def server_for(self, name):
        return "lgnd"

    def call(self, name, args, timeout=None):
        self.calls.append((name, args))
        if name == "search_chip_lat_lon":
            node = f"naip/obs:{args['lat']},{args['lon']}"
            return ToolResult(json.dumps({"node": node, "observed": "2022-07-02"}), False)
        if name == "reasoning_imagery_check":
            rows = [[n, "yes" if self.sees(n, args["claim"]) else "no", f"looked at {n}"]
                    for n in args["nodes"]]  # fmt: skip
            yes = [r[0] for r in rows if r[1] == "yes"]
            verdict = ("supported" if len(yes) == len(rows) else
                       "partly supported" if yes else "not supported")  # fmt: skip
            places = table(["node", "answer", "reason"], rows)
            return ToolResult(json.dumps({"verdict": verdict, "supported_at": yes,
                                          "places": places}), False)  # fmt: skip
        if name == "toolbox_classifier_list":
            data = [{"name": n} for n in self.classifiers]
            return ToolResult(json.dumps({"data": data, "pagination": {}}), False)
        if name == "toolbox_classifier_build":
            self.classifiers.append(args["name"])
            return ToolResult(json.dumps({"name": args["name"], "version": 1}), False)
        if name == "toolbox_classifier_apply":
            rows = [[n, self.labels.get(n, "bare_ground"), 0.2, "close"] for n in args["nodes"]]
            body = {"results": table(["node", "label", "margin", "fit"], rows)}
            return ToolResult(json.dumps(body), False)
        if name == "search_place_find":
            rows = [[f"naip/obs:{i}", 35.0 + i, -118.0, 0.3] for i in range(3)]
            body = {"matches": table(["node", "lat", "lon", "similarity"], rows)}
            return ToolResult(json.dumps(body), False)
        return ToolResult(f"unknown tool {name}", True, "UnknownTool")


def routes_with(**methods):
    base = verifiers.load()
    return verifiers.Routes(base.version, base.default, base.index, base.examples,
                            {c: {"method": m} for c, m in methods.items()})  # fmt: skip


# ── LGND's shapes ───────────────────────────────────────────────────────────────────────


def test_tables_read_as_rows_and_lists_pass_through():
    assert lgnd.table(table(["node", "answer"], [["a", "yes"]])) == [{"node": "a", "answer": "yes"}]
    assert lgnd.table([{"node": "a"}, "junk"]) == [{"node": "a"}]
    assert lgnd.answers({"places": table(["node", "answer"], [["a", "no"]])})["a"]["answer"] == "no"


def test_the_classifier_name_follows_its_examples():
    a = lgnd.classifier_name("clayzer-objects", {"water": ["pond"]})
    assert a == lgnd.classifier_name("clayzer-objects", {"water": ["pond"]})
    assert a != lgnd.classifier_name("clayzer-objects", {"water": ["lake"]})
    assert len(verifiers.load().classifier) <= 32


def test_a_classifier_is_built_only_when_the_account_lacks_it():
    geo = FakeGeo(classifiers=["have-it"])
    assert lgnd.ensure_classifier(geo.call, "have-it", {"a": ["x"]}) is None
    assert [n for n, _ in geo.calls] == ["toolbox_classifier_list"]
    assert lgnd.ensure_classifier(geo.call, "new-one", {"a": ["x"], "b": ["y"]}) is None
    build = geo.calls[-1][1]
    assert build["examples"] == {"a": [{"text": "x"}], "b": [{"text": "y"}]}


def test_lookups_are_cached_in_the_store_but_outages_are_not(tmp_path):
    store = LocalStore(tmp_path / "data", tmp_path / "batches")
    geo = FakeGeo()
    first = lgnd.Lookups(geo.call, store)
    assert first(1.0, 2.0)["node"] == "naip/obs:1.0,2.0"
    first.save()
    again = lgnd.Lookups(geo.call, store)
    assert again(1.0, 2.0)["node"] == "naip/obs:1.0,2.0" and again.calls == 0
    down = lgnd.Lookups(lambda n, a: ToolResult("timed out", True, "TimeoutError"), store)
    assert down(5.0, 5.0) is None and "naip:5.000000,5.000000" not in down.cache


# ── Routes in verify-then-write ─────────────────────────────────────────────────────────


def test_with_no_routes_every_class_gets_the_imagery_check():
    routes = verifiers.load()
    assert routes.method("solar_array") == routes.default == "imagery_check"


def test_an_unrouted_check_reads_its_reason_from_lgnds_table():
    geo = FakeGeo(sees=lambda node, claim: "solar" in claim)
    _, report = verify(draft(), FOOTPRINT, geo, routes=routes_with())
    solar = report["checks"][0]
    assert solar["verdict"] == "supported" and solar["reason"].startswith("looked at naip/obs:")


def test_classes_go_to_their_routed_verifier():
    lat, lon = cell_centre(FOOTPRINT["bbox"], "west")
    geo = FakeGeo(sees=lambda node, claim: True, labels={f"naip/obs:{lat},{lon}": "road"})
    routes = routes_with(road="classifier", building="classifier", wind_turbine="none")
    cap, report = verify(draft(), FOOTPRINT, geo, routes=routes)
    by_id = {c["id"]: c for c in report["checks"]}
    assert by_id["o1"]["method"] == "imagery_check" and by_id["o1"]["verdict"] == "supported"
    assert by_id["o2"]["verdict"] == "skipped"  # wind: not checked, stays
    assert by_id["o3"]["verdict"] == "supported"  # the west cell's image is labelled road
    assert by_id["o4"]["verdict"] == "not supported"  # building, but labelled bare_ground
    assert [o["id"] for o in cap["objects"]] == ["o1", "o2", "o3"]
    assert (report["skipped"], report["moved"]) == (1, 1)
    names = [n for n, _ in geo.calls]
    # No lookup for the skipped Claim; one apply for both classifier Claims.
    assert names.count("search_chip_lat_lon") == 2 and names.count("toolbox_classifier_apply") == 1


def test_a_classifier_outage_leaves_its_claims_unverified():
    class Down(FakeGeo):
        def call(self, name, args, timeout=None):
            if name == "toolbox_classifier_apply":
                return ToolResult("ServiceUnavailable", True, "ServiceUnavailableException")
            return super().call(name, args, timeout)

    cap, report = verify(draft(), FOOTPRINT, Down(), routes=routes_with(road="classifier"))
    assert len(cap["objects"]) == 4
    assert {c["id"]: c["verdict"] for c in report["checks"]}["o3"] == "unverified"


# ── Choosing a route ────────────────────────────────────────────────────────────────────


def test_a_verifier_must_beat_keeping_every_claim():
    good = verifiers.rates(tp=5, fn=1, tn=5, fp=1)
    weak = verifiers.rates(tp=3, fn=3, tn=3, fp=3)
    none = verifiers.rates(6, 0, 0, 6)
    assert verifiers.choose({"imagery_check": good, "classifier": weak, "none": none},
                            "imagery_check")[0] == "imagery_check"  # fmt: skip
    assert verifiers.choose({"imagery_check": weak, "classifier": weak, "none": none},
                            "imagery_check")[0] == "none"  # fmt: skip
    better = verifiers.rates(tp=6, fn=0, tn=6, fp=0)
    assert verifiers.choose({"imagery_check": good, "classifier": better, "none": none},
                            "imagery_check")[0] == "classifier"  # fmt: skip


def test_too_few_probes_keep_the_current_route():
    few = verifiers.rates(tp=2, fn=0, tn=6, fp=0)
    method, why = verifiers.choose({"imagery_check": few, "none": few}, "classifier")
    assert method == "classifier" and "need 3" in why


def test_written_routes_load_back_and_keep_the_header(tmp_path):
    path = tmp_path / "verifiers.toml"
    path.write_text(verifiers.DEFAULT.read_text())
    routes = routes_with(water="classifier")
    routes.routes["water"] |= {"reason": 'kept "all"', "probes": {"true": 6, "false": 6},
                               "classifier": {"kept": 1.0, "removed": None}}  # fmt: skip
    path.write_text(verifiers.render(routes, path))
    again = verifiers.load(path)
    assert again.method("water") == "classifier" and again.examples == routes.examples
    assert again.routes["water"]["classifier"] == {"kept": 1.0}
    assert path.read_text().startswith("# Which verifier checks")


# ── Calibration ─────────────────────────────────────────────────────────────────────────


def case(cid, labels, bbox=(0.0, 0.0, 3.0, 3.0), date="2022-07-02"):
    return {"id": cid, "chips": [{"id": cid, "bbox": list(bbox), "date": date}],
            "reference_labels": [{"object": o, "count": 1, "position": cells[0], "cells": cells}
                                 for o, cells in labels]}  # fmt: skip


CASES = [
    case(f"fixed-dev-uspvdb-{i}", [("solar_array", ["centre"]), ("parking_lot", ["north"])],
         bbox=(i, 0.0, i + 3.0, 3.0))
    for i in range(4)
] + [case(f"fixed-dev-neg-{i}", [("road", ["west"])], bbox=(10.0 + i, 0.0, 13.0 + i, 3.0))
     for i in range(4)]  # fmt: skip


def test_probes_take_one_cell_per_case_and_prefer_look_alikes():
    plan = calibrate.probes(CASES, per_class=3, classes=["solar_array"])
    true = [p for p in plan if p["truth"]]
    false = [p for p in plan if not p["truth"]]
    assert len(true) == 3 and {p["cell"] for p in true} == {"centre"}
    assert len({p["case_id"] for p in true}) == 3
    # Parking lots are a solar confuser: false probes go to them first.
    assert len(false) == 3 and all(p["look_alike"] == ["parking_lot"] for p in false)


def test_calibration_scores_both_verifiers_and_finds_suspect_labels(tmp_path):
    store = LocalStore(tmp_path / "data", tmp_path / "batches")
    plan = calibrate.probes(CASES, per_class=4, classes=["solar_array"])
    truth = {f"naip/obs:{p['lat']},{p['lon']}": p["truth"] for p in plan}
    wrong = next(n for n, t in truth.items() if not t)  # an unmapped array the label misses

    def sees(node, claim):
        return truth.get(node, False) or node == wrong

    labels = {n: "solar_array" if t or n == wrong else "parking_lot" for n, t in truth.items()}
    geo = FakeGeo(sees=sees, labels=labels)
    result = calibrate.run(CASES, geo.call, store, per_class=4, routes=routes_with(),
                           classes=["solar_array"])  # fmt: skip
    solar = result["classes"]["solar_array"]
    assert solar["scores"]["imagery_check"]["kept"] == 1.0
    assert solar["scores"]["imagery_check"]["removed"] == 0.75
    assert solar["method"] == "imagery_check"  # tied with the classifier: today's verifier wins
    sus = calibrate.suspects(result["probes"])
    assert [f"naip/obs:{p['lat']},{p['lon']}" for p in sus] == [wrong]
    names = [n for n, _ in geo.calls]
    assert names.count("reasoning_imagery_check") == len(result["classes"])  # one per class
    assert names.count("toolbox_classifier_apply") == 1
    # The lookups are saved: a second calibration doesn't repeat them.
    again = FakeGeo(sees=sees, labels=labels, classifiers=[routes_with().classifier])
    calibrate.run(CASES, again.call, store, 4, routes_with(), ["solar_array"])
    assert "search_chip_lat_lon" not in [n for n, _ in again.calls]
    md = calibrate.to_markdown(result, routes_with())
    assert "| solar_array |" in md and "Suspect Reference Labels (1)" in md


def test_a_probe_whose_lgnd_image_is_another_year_is_left_out():
    old = [case("fixed-dev-uspvdb-9", [("solar_array", ["centre"])], date="2020-05-01")]
    result = calibrate.run(old, FakeGeo().call, None, per_class=1, routes=routes_with())
    assert result["classes"]["solar_array"]["excluded"] == 2


# ── Setting spread ──────────────────────────────────────────────────────────────────────


def test_evenness_runs_from_one_setting_to_all_alike():
    assert spread.evenness({"a": 4, "b": 0}) == 0
    assert round(spread.evenness({"a": 2, "b": 2}), 6) == 1


def test_the_context_cell_avoids_the_cases_subject():
    c = case("fixed-dev-uspvdb-1", [("solar_array", ["north_west", "north", "centre"])])
    assert spread.context_cell(c, "solar_array") == "north_east"
    full = case("fixed-dev-uspvdb-2", [("solar_array", list(spread.ORDER))])
    assert spread.context_cell(full, "solar_array") == "north_west"


def test_spread_counts_settings_per_group_and_names_the_gaps(tmp_path):
    store = LocalStore(tmp_path / "data", tmp_path / "batches")
    geo = FakeGeo()
    geo.labels = {}
    for c in CASES:
        cell = spread.context_cell(c, spread.group(c))
        lat, lon = cell_centre(c["chips"][0]["bbox"], cell)
        geo.labels[f"naip/obs:{lat},{lon}"] = "town" if "neg" in c["id"] else "desert_scrub"
    measured = spread.measure(CASES, geo.call, store)
    solar = measured["groups"]["solar_array"]
    assert solar["n"] == 4 and solar["counts"]["desert_scrub"] == 4 and solar["evenness"] == 0
    assert "woodland" in solar["gaps"] and "desert_scrub" not in solar["gaps"]
    assert measured["groups"]["negative"]["counts"]["town"] == 4
    found = spread.suggest(CASES, measured, geo.call,
                           near=lambda lat, lon, g: "uspvdb 42", per_gap=2)  # fmt: skip
    woodland = next(s for s in found if s["group"] == "solar_array" and s["setting"] == "woodland")
    assert woodland["query"] == ["solar farm", "woodland"]
    assert [m["command"] for m in woodland["matches"]] == ["clayzer case uspvdb 42"]  # once
    neg = next(s for s in found if s["group"] == "negative")
    assert neg["matches"][0]["command"].startswith("clayzer case neg -118.00000 35.00000")
    assert "## To fill the gaps" in spread.to_markdown(measured, found)
    assert spread.estimate(CASES, lgnd.Lookups(None, store)) == 3  # every lookup is cached


def test_a_build_that_timed_out_but_finished_on_lgnds_side_counts():
    class Slow(FakeGeo):
        def call(self, name, args, timeout=None):
            if name == "toolbox_classifier_build":
                self.calls.append((name, timeout))
                self.classifiers.append(args["name"])  # LGND finishes it anyway
                return ToolResult("toolbox_classifier_build timed out after 300 s", True)
            return super().call(name, args, timeout)

    geo = Slow()
    assert lgnd.ensure_classifier(geo.call, "slow-one", {"a": ["x"], "b": ["y"]}) is None
    assert ("toolbox_classifier_build", lgnd.BUILD_TIMEOUT) in geo.calls


def test_suggestions_skip_usgs_sites_that_are_already_cases():
    measured = {"groups": {"solar_array": {"gaps": ["woodland"]}}}
    sites = iter(["uspvdb 2", "uspvdb 77", "uspvdb 2"])  # uspvdb 2 is CASES' fixed-dev-uspvdb-2
    found = spread.suggest(CASES, measured, FakeGeo().call, near=lambda lat, lon, g: next(sites))
    assert [m["command"] for m in found[0]["matches"]] == ["clayzer case uspvdb 77"]
