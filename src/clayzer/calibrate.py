"""Calibrate the verifiers: measure, per object class, how well each one sorts true Claims from
false ones on development Cases, and choose its route (ontology/verifiers.toml).

A probe is a Claim the code writes itself: "a <class> is visible here", at one cell of one
Chip, whose truth the Case's Reference Labels give. True probes are cells a label of the class
covers; false probes are cells no label of it covers, preferring cells with one of the class's
confusers (ontology), because a captioner's wrong Claims are mostly look-alikes, not random.
One probe per Case per class, so no single Chip dominates.

Each probe's cell gets one image lookup (cached: lgnd.Lookups), then:
- imagery_check  one `reasoning_imagery_check` per class, all its probes in one call (≤ 30)
- classifier     one `toolbox_classifier_apply` for every probe image
so a calibration costs about one call per cell plus one per class. A probe whose LGND image is
from another year than its Chip is left out: the Reference Labels describe the Chip's year.

Reference Labels are wrong sometimes too ("every reference lies"). Where both verifiers
disagree with the label, the report lists the probe as a suspect label to look at by eye.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from clayzer import lgnd, verifiers
from clayzer.grid import GRID
from clayzer.ontology import load as load_ontology
from clayzer.verify import cell_centre, claim_text, classifier_verdict

CHECK_LIMIT = 30  # reasoning_imagery_check judges the first 30 places


def _present(case: dict) -> dict[str, set[str]]:
    """cell -> the classes some Reference Label of the Case covers there."""
    out: dict[str, set[str]] = {cell: set() for cell in GRID}
    for label in (lb for lb in case["reference_labels"] if lb.get("count") != 0):
        for cell in label.get("cells") or [label["position"]]:
            out[cell].add(label["object"])
    return out


def probes(cases: list[dict], per_class: int = 6, classes: list[str] | None = None) -> list[dict]:
    """Up to `per_class` true and `per_class` false probes for each keyed class."""
    onto = load_ontology()
    classes = classes or sorted(onto.keyed())
    present = {c["id"]: _present(c) for c in cases}
    by_id = {c["id"]: c for c in cases}
    chosen: set[tuple[str, str]] = set()  # cells already looked up: reuse them first
    out: list[dict] = []
    for cls in classes:
        confusers = set(onto.classes[cls].confusers)
        for truth in (True, False):
            cands = [(cid, cell) for cid in sorted(present) for cell in GRID
                     if (cls in present[cid][cell]) == truth]  # fmt: skip

            def key(c, truth=truth, confusers=confusers):
                look_alike = bool(confusers & present[c[0]][c[1]])
                return (truth or not look_alike, c not in chosen, c[0], GRID.index(c[1]))

            used: set[str] = set()
            for cid, cell in sorted(cands, key=key):
                if len(used) == per_class:
                    break
                if cid in used:
                    continue
                used.add(cid)
                chosen.add((cid, cell))
                chip = by_id[cid]["chips"][0]
                lat, lon = cell_centre(chip["bbox"], cell)
                out.append({
                    "class": cls, "truth": truth, "case_id": cid, "cell": cell,
                    "lat": lat, "lon": lon, "date": chip.get("date"),
                    "look_alike": sorted(confusers & present[cid][cell]),
                })  # fmt: skip
    return out


def estimate(plan: list[dict], lookups: lgnd.Lookups, routes) -> int:
    """LGND calls a calibration of `plan` will make, at most."""
    cells = {(p["lat"], p["lon"]) for p in plan}
    uncached = sum(f"{lgnd.INDEX}:{lat:.6f},{lon:.6f}" not in lookups.cache for lat, lon in cells)
    checks = sum(-(-n // CHECK_LIMIT) for n in _count(plan).values())
    applies = -(-len(cells) // lgnd.APPLY_LIMIT)
    return uncached + checks + applies + 2  # + list and build the classifier


def _count(plan: list[dict]) -> dict[str, int]:
    out: dict[str, int] = {}
    for p in plan:
        out[p["class"]] = out.get(p["class"], 0) + 1
    return out


def run(cases: list[dict], call, store=None, per_class: int = 6, routes=None, classes=None) -> dict:
    """Probe every keyed class with both verifiers. `call(name, arguments)` returns a ToolResult.
    Returns {"probes", "classes": {class: {"scores", "method", "reason", ...}}, "calls"}."""
    routes = routes or verifiers.load()
    calls = {"n": 0}

    def counted(name, args, **kw):
        calls["n"] += 1
        return call(name, args, **kw)

    lookups = lgnd.Lookups(counted, store)
    names = {c.id: c.name for c in load_ontology().classes.values()}
    plan = probes(cases, per_class, classes)
    for p in plan:
        found = lookups(p["lat"], p["lon"])
        if not found:
            p["excluded"] = "no LGND image here"
        elif (found.get("observed") or "")[:4] != (p["date"] or "")[:4]:
            p["excluded"] = (
                f"LGND's image is from {found.get('observed')}, the Chip from {p['date']}"
            )
        p["node"] = (found or {}).get("node")
    lookups.save()
    live = [p for p in plan if not p.get("excluded")]

    for cls in dict.fromkeys(p["class"] for p in live):
        mine = [p for p in live if p["class"] == cls]
        nodes = list(dict.fromkeys(p["node"] for p in mine))
        judged: dict[str, dict] = {}
        for i in range(0, len(nodes), CHECK_LIMIT):
            r = counted("reasoning_imagery_check", {
                "claim": claim_text({"object": cls}, names), "kind": "place",
                "nodes": nodes[i : i + CHECK_LIMIT],
            })  # fmt: skip
            result = lgnd.parse(r.text) if not r.is_error else None
            judged |= lgnd.answers(result) if result else {}
        for p in mine:
            place = judged.get(p["node"])
            if place:
                p["imagery_check"] = {"kept": place.get("answer") == "yes",
                                      "reason": (place.get("reason") or "")[:200]}  # fmt: skip

    error = lgnd.ensure_classifier(counted, routes.classifier, routes.examples, routes.index)
    labels, apply_error = (
        ({}, error) if error else lgnd.apply(counted, routes.classifier, [p["node"] for p in live])
    )
    for p in live:
        if p["node"] in labels:
            verdict, reason = classifier_verdict(labels[p["node"]], p["class"])
            p["classifier"] = {"kept": verdict == "supported", "reason": reason}

    classes = {}
    for cls in dict.fromkeys(p["class"] for p in plan):
        mine = [p for p in live if p["class"] == cls]
        scores = {m: _rates(mine, m) for m in ("imagery_check", "classifier")}
        pos = sum(p["truth"] for p in mine)
        scores["none"] = verifiers.rates(pos, 0, 0, len(mine) - pos)
        method, reason = verifiers.choose(scores, routes.method(cls))
        classes[cls] = {"scores": scores, "method": method, "reason": reason,
                        "excluded": sum(1 for p in plan if p["class"] == cls and p.get("excluded"))}  # fmt: skip
    return {"probes": plan, "classes": classes, "calls": calls["n"],
            "classifier": routes.classifier, "classifier_error": apply_error}  # fmt: skip


def _rates(probes_: list[dict], method: str) -> dict:
    judged = [p for p in probes_ if method in p]
    tp = sum(p["truth"] and p[method]["kept"] for p in judged)
    fn = sum(p["truth"] and not p[method]["kept"] for p in judged)
    tn = sum(not p["truth"] and not p[method]["kept"] for p in judged)
    fp = sum(not p["truth"] and p[method]["kept"] for p in judged)
    return verifiers.rates(tp, fn, tn, fp)


def suspects(plan: list[dict]) -> list[dict]:
    """Probes both verifiers judged against their Reference Label: look at these by eye."""
    return [p for p in plan
            if all(m in p and p[m]["kept"] != p["truth"] for m in ("imagery_check", "classifier"))]  # fmt: skip


def updated(routes, result: dict, today: str | None = None):
    """`routes` with each calibrated class's new route and its evidence."""
    today = today or datetime.now(UTC).date().isoformat()
    new = dict(routes.routes)
    for cls, c in result["classes"].items():
        s = c["scores"]
        new[cls] = {
            "method": c["method"], "reason": c["reason"], "calibrated": today,
            "probes": {"true": s["none"]["tp"], "false": s["none"]["fp"]},
            **{m: {"kept": s[m]["kept"], "removed": s[m]["removed"]}
               for m in ("imagery_check", "classifier")},
        }  # fmt: skip
    return verifiers.Routes(routes.version, routes.default, routes.index, routes.examples, new)


def _pct(x) -> str:
    return "—" if x is None else f"{x:.0%}"


def to_markdown(result: dict, routes) -> str:
    error = result["classifier_error"]
    lines = [
        "# Verifier calibration", "",
        f"{len(result['probes'])} probes, {result['calls']} LGND calls. "
        f"Classifier `{result['classifier']}`"
        + (f": **unavailable** ({error})" if error else "") + ".", "",
        ("Kept = true Claims kept; removed = false Claims removed. Keeping every Claim scores "
         "kept 100%, removed 0%."), "",
        ("| Class | True / false probes | imagery_check kept · removed "
         "| classifier kept · removed | Route now | Chosen | Why |"),
        "|---|---|---|---|---|---|---|",
    ]  # fmt: skip
    for cls, c in result["classes"].items():
        s = c["scores"]
        ex = f" ({c['excluded']} left out)" if c["excluded"] else ""
        lines.append(
            f"| {cls} | {s['none']['tp']} / {s['none']['fp']}{ex} "
            f"| {_pct(s['imagery_check']['kept'])} · {_pct(s['imagery_check']['removed'])} "
            f"| {_pct(s['classifier']['kept'])} · {_pct(s['classifier']['removed'])} "
            f"| {routes.method(cls)} | **{c['method']}** | {c['reason']} |"
        )
    sus = suspects(result["probes"])
    lines += ["", f"## Suspect Reference Labels ({len(sus)})", "",
              "Both verifiers disagree with the label. Look at the Chip on the Cases page.", ""]  # fmt: skip
    for p in sus:
        said = "present" if p["truth"] else "absent"
        lines.append(f"- `{p['case_id']}` {p['cell']}: label says {p['class']} {said}; "
                     f"LGND: {p['imagery_check']['reason']}")  # fmt: skip
    disagree = [p for p in result["probes"] if "imagery_check" in p
                and p["imagery_check"]["kept"] != p["truth"] and p not in sus]  # fmt: skip
    lines += ["", f"## Imagery check disagreements ({len(disagree)})", ""]
    for p in disagree:
        said = "present" if p["truth"] else "absent"
        alike = f" (look-alike: {', '.join(p['look_alike'])})" if p["look_alike"] else ""
        lines.append(f"- `{p['case_id']}` {p['cell']}: {p['class']} {said}{alike}; "
                     f"LGND: {p['imagery_check']['reason']}")  # fmt: skip
    return "\n".join(lines) + "\n"


def save(store, result: dict, routes) -> str:
    """Write the report and probes under calibration/verifiers/<time>/; returns the prefix."""
    prefix = f"calibration/verifiers/{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}/"
    store.put(prefix + "report.md", to_markdown(result, routes).encode(), "text/markdown")
    body = "".join(json.dumps(p) + "\n" for p in result["probes"]).encode()
    store.put(prefix + "probes.jsonl", body, "application/x-ndjson")
    return prefix
