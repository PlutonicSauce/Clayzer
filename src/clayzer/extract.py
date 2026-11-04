"""Claims from free text (CAP-20): a model reads a caption and writes the Claims it asserts.

Most caption sets are text only, but grounding scores structured Claims (ADR-0007), so a caption
without them gets them extracted first. The extraction is the evaluation's work, not a
Harness's: it reads only the text, never the image (it records what the caption says, not what
is on the ground), and it's recorded as a `judge` Step (`role: scoring`), so a failed extraction
is a Sandbox Failure and the Workflow Score ignores it. Being a model's judgement, it's
calibrated like the Judge: `agreement` compares extracted Claims with Claims made another way
(the Harness's own structured Claims for the same text, or people's).

What the text doesn't say stays unsaid: a count or position the caption doesn't give is null,
and grounding skips it rather than scoring a guess.
"""

from __future__ import annotations

import os

from clayzer.grid import GRID, RELATIONS, cell_distance
from clayzer.ontology import load as load_ontology

PROMPT = """\
Below is a caption of an aerial image (north is up). List the Claims the caption makes about
what is in the image, and submit them with the submit_claims tool. Record what the caption
says, not what you think is likely: the image isn't shown to you.

- objects: each object type the caption asserts, with
  - object: one of the types below (use the closest; skip things that match none)
  - count: the number the caption gives ("a", "an", "one" = 1, "two" = 2, ...); null when it
    gives none ("several", "some", "many", or a plural without a number)
  - position: the cell of a 3x3 grid the caption places it in, from: {grid}. Map words to
    cells: top = north, bottom = south, left = west, right = east, upper left = north_west,
    middle or center = centre. null when the caption doesn't say where. One thing that spans
    cells ("a large solar array in the west and center") is one Claim, at the first cell
    named. Several things, or spread land cover, in different areas ("several buildings to the
    north and west", "vegetation in the north and west") is one Claim per area. But a group
    with one total spread over areas ("two wind turbines in the west and north-west") is one
    Claim with that count, at the first cell named.
- relations: how objects sit relative to each other, from: {relations}; only when the caption
  states it, never ones that follow from positions. Refer to objects by their id. "X surrounded
  by Y", "X within Y", "Y around X" = X inside Y; "X next to Y", "X bordering Y" = X
  adjacent_to Y; "X between Y and Z" = X between Y.
- uncertain: anything the caption hedges ("may be", "possibly", "appears to be", "likely").
  Don't list those as objects.

Object types and words that mean them:
{types}

Caption: {text}
"""


def _types_block() -> tuple[str, list[str]]:
    classes = [c for c in load_ontology().classes.values() if c.claimable]
    lines = [f"- {c.id}: {c.name.lower()}" + (f"; also {', '.join(c.synonyms)}" if c.synonyms else "")
             for c in classes]  # fmt: skip
    return "\n".join(lines), [c.id for c in classes]


def _nullable(schema: dict) -> dict:
    return {"anyOf": [schema, {"type": "null"}]}


def _tool(object_ids: list[str]) -> dict:
    return {"toolSpec": {
        "name": "submit_claims",
        "description": "Submit the Claims the caption makes.",
        "inputSchema": {"json": {
            "type": "object",
            "required": ["objects", "relations", "uncertain"],
            "properties": {
                "objects": {"type": "array", "items": {
                    "type": "object",
                    "required": ["id", "object", "count", "position"],
                    "properties": {
                        "id": {"type": "string", "description": "o1, o2, ..."},
                        "object": {"type": "string", "enum": object_ids},
                        "count": _nullable({"type": "integer", "minimum": 1}),
                        "position": _nullable({"type": "string", "enum": list(GRID)}),
                    },
                }},
                "relations": {"type": "array", "items": {
                    "type": "object",
                    "required": ["subject", "relation", "object"],
                    "properties": {
                        "subject": {"type": "string"},
                        "relation": {"type": "string", "enum": list(RELATIONS)},
                        "object": {"type": "string"},
                    },
                }},
                "uncertain": {"type": "array", "items": {"type": "string"}},
            },
        }},
    }}  # fmt: skip


def extract_model(settings) -> str:
    """The extraction model: CLAYZER_EXTRACT_MODEL, else the Judge's, so it isn't the model
    that wrote our own Captions."""
    return os.environ.get("CLAYZER_EXTRACT_MODEL") or settings.judge_model


def _clean(c: dict, object_ids: list[str]) -> dict:
    objects = []
    for o in c.get("objects", []):
        if o.get("object") not in object_ids:
            continue
        count = o.get("count")
        position = o.get("position")
        objects.append({
            "id": str(o.get("id") or f"o{len(objects) + 1}"),
            "object": o["object"],
            "count": count if isinstance(count, int) and count >= 1 else None,
            "position": position if position in GRID else None,
        })  # fmt: skip
    ids = {o["id"] for o in objects}
    relations = [
        r for r in c.get("relations", [])
        if r.get("relation") in RELATIONS and r.get("subject") in ids and r.get("object") in ids
    ]  # fmt: skip
    return {"objects": objects, "relations": relations,
            "uncertain": [str(u) for u in c.get("uncertain", [])]}  # fmt: skip


def extract(client, model: str, text: str, tracer=None) -> tuple[dict, dict]:
    """The Claims a caption's text makes. Returns them and a summary of the call. Raises
    RuntimeError when the model submits nothing, which a Batch counts as a Sandbox Failure."""
    import time

    types, object_ids = _types_block()
    prompt = PROMPT.format(grid=", ".join(GRID), relations=", ".join(RELATIONS),
                           types=types, text=text)  # fmt: skip
    request = {
        "modelId": model,
        "messages": [{"role": "user", "content": [{"text": prompt}]}],
        # No forced tool choice: Opus 5.5, the default model, rejects one.
        "toolConfig": {"tools": [_tool(object_ids)]},
        "inferenceConfig": {"maxTokens": 1200},
    }
    started = time.monotonic()
    if tracer is None:
        resp = client.converse(**request)
    else:
        recorded = {"prompt": prompt, "tools": ["submit_claims"], "max_tokens": 1200}
        resp = tracer.converse(client, "judge", "extract_claims", request, recorded,
                               {"expects_tool": "submit_claims"})  # fmt: skip
    blocks = resp["output"]["message"]["content"]
    got = next((b["toolUse"]["input"] for b in blocks if "toolUse" in b), None)
    step = {"step": "extract", "model": model, "seconds": round(time.monotonic() - started, 2),
            "usage": resp.get("usage", {}), "ok": got is not None}  # fmt: skip
    if got is None:
        raise RuntimeError(f"{model} returned no submit_claims call")
    return _clean(got, object_ids), step


def agreement(pairs: list[tuple[dict, dict]]) -> dict:
    """How far extracted Claims agree with reference Claims for the same captions.

    `pairs` is (extracted, reference), each with `objects`. Per caption, object types are
    compared as sets; for each type in both, the count (when both give one) and the nearest
    pair of positions (when both give one). Rates are over all captions.
    """
    tp = fp = fn = 0
    counts = positions = near = 0
    n_count = n_position = no_count = no_position = 0
    for got, ref in pairs:
        g = {}
        for o in got["objects"]:
            g.setdefault(o["object"], []).append(o)
        r = {}
        for o in ref["objects"]:
            r.setdefault(o["object"], []).append(o)
        tp += len(g.keys() & r.keys())
        fp += len(g.keys() - r.keys())
        fn += len(r.keys() - g.keys())
        for obj in g.keys() & r.keys():
            gc = [o["count"] for o in g[obj]]
            rc = [o["count"] for o in r[obj]]
            if None in gc:
                no_count += 1
            elif None not in rc:
                n_count += 1
                counts += sum(gc) == sum(rc)
            gp = [o["position"] for o in g[obj] if o["position"]]
            rp = [o["position"] for o in r[obj] if o["position"]]
            if not gp:
                no_position += 1
            elif rp:
                n_position += 1
                d = min(cell_distance(a, b) for a in gp for b in rp)
                positions += d == 0
                near += d <= 1

    def rate(a, b):
        return round(a / b, 3) if b else None

    return {
        "captions": len(pairs),
        "type_precision": rate(tp, tp + fp),
        "type_recall": rate(tp, tp + fn),
        "count_exact": rate(counts, n_count),
        "position_exact": rate(positions, n_position),
        "position_within_one": rate(near, n_position),
        "count_not_stated": rate(no_count, tp),
        "position_not_stated": rate(no_position, tp),
    }


# ── Calibration ────────────────────────────────────────────────────────────────────────


class _KeySink:
    """Writes one extraction's Trace to a fixed store key."""

    def __init__(self, store, key: str):
        self.store, self.key = store, key

    def write(self, run, steps) -> None:
        from clayzer.trace import dumps

        self.store.put(self.key, dumps(run, steps), "application/x-ndjson")


def calibrate(client, model: str, items: list[dict], store=None, prefix: str | None = None,
              progress=print) -> dict:  # fmt: skip
    """Extract Claims from each item's `text` and compare them with its reference `claims`.

    Items are {"id", "text", "claims"}, optionally with the label's `source` (labels.py). With
    a store and prefix, each extraction's Trace goes to <prefix>/<id>.jsonl and the result to
    <prefix>/agreement.json. A failed extraction is left out of the agreement and counted.

    With sources, agreement is also given per source, since a checked proposal leans toward the
    model's answer and only blind labels don't, and `edit_rate` is the share of proposals a
    person changed.
    """
    from clayzer.trace import RunInfo, Tracer

    pairs, rows, failed, by_source = [], [], 0, {}
    for i, item in enumerate(items, 1):
        sinks = [_KeySink(store, f"{prefix}/{item['id']}.jsonl")] if store and prefix else []
        run = RunInfo(run_id=item["id"], task="extract", case_id=item.get("case_id", item["id"]),
                      repeat=item.get("repeat", 1), batch_id=item.get("batch_id", ""),
                      model_id=model, prompt_sha="")  # fmt: skip
        tracer = Tracer(run, sinks)
        try:
            got, _ = extract(client, model, item["text"], tracer)
        except Exception as e:  # noqa: BLE001 - a failed extraction is counted, not fatal
            tracer.finish("sandbox_failure", None, str(e)[:500])
            failed += 1
            progress(f"  [{i}/{len(items)}] {item['id']}: extraction failed ({e})"[:160])
            continue
        tracer.finish("ok")
        pairs.append((got, item["claims"]))
        if item.get("source"):
            by_source.setdefault(item["source"], []).append((got, item["claims"]))
        one = agreement([(got, item["claims"])])
        rows.append({"id": item["id"], "text": item["text"], "extracted": got,
                     "reference": item["claims"], **one})  # fmt: skip
        progress(f"  [{i}/{len(items)}] {item['id']}: types P {one['type_precision']} "
                 f"R {one['type_recall']}")  # fmt: skip
    result = {"model": model, "failed": failed, **agreement(pairs), "items": rows}
    sources = [i.get("source") for i in items]
    if any(sources):
        result["by_source"] = {k: agreement(v) for k, v in sorted(by_source.items())}
        accepted, edited = sources.count("proposal accepted"), sources.count("proposal edited")
        result["edit_rate"] = round(edited / (accepted + edited), 3) if accepted + edited else None
    if store and prefix:
        import json

        store.put(f"{prefix}/agreement.json", (json.dumps(result, indent=2) + "\n").encode(),
                  "application/json")  # fmt: skip
    return result


def batch_items(store, batch_id: str) -> list[dict]:
    """A Batch's Captions as calibration items: the text, and the Claims the Harness wrote."""
    from clayzer import batch as batches

    items = []
    for c in batches.load(store, batch_id)["captions"]:
        if not c.get("text") or not c.get("objects"):
            continue
        claims = {"objects": c["objects"], "relations": c.get("relations", []),
                  "uncertain": c.get("uncertain", [])}  # fmt: skip
        items.append({"id": f"{c['case_id']}--r{c['repeat']}", "case_id": c["case_id"],
                      "repeat": c["repeat"], "batch_id": batch_id, "text": c["text"],
                      "claims": claims})  # fmt: skip
    return items


def _object_problems(where: str, o, object_ids, ids: set) -> list[str]:
    """What's wrong with one hand-made object; records its id in `ids`."""
    if not isinstance(o, dict):
        return [f"{where} isn't an object"]
    problems = []
    if o.get("object") not in object_ids:
        problems.append(f"{where}: {o.get('object')!r} isn't an ontology class")
    for key in ("count", "position"):
        if key not in o:
            problems.append(f"{where}: give a {key}, or null for not stated")
    count = o.get("count")
    if count is not None and not (isinstance(count, int) and not isinstance(count, bool)
                                  and count >= 1):  # fmt: skip
        problems.append(f"{where}: count must be a whole number of at least 1, or null")
    if o.get("position") is not None and o.get("position") not in GRID:
        problems.append(f"{where}: {o.get('position')!r} isn't a grid cell")
    if not o.get("id") or o["id"] in ids:
        problems.append(f"{where}: needs its own id")
    ids.add(o.get("id"))
    return problems


def _relation_problems(where: str, r, ids: set) -> list[str]:
    """What's wrong with one hand-made relation, given the ids of the objects."""
    if not isinstance(r, dict) or r.get("relation") not in RELATIONS:
        return [f"{where}: relation must be one of {', '.join(RELATIONS)}"]
    problems = [
        f"{where}: {side} {r.get(side)!r} isn't one of the objects"
        for side in ("subject", "object")
        if r.get(side) not in ids
    ]
    if r.get("subject") == r.get("object"):
        problems.append(f"{where}: an object can't relate to itself")
    return problems


def check_claims(claims) -> list[str]:
    """What's wrong with hand-made Claims, as reasons; empty when they're valid. Unlike `_clean`,
    which quietly fixes a model's output, a person's label is rejected so they can fix it."""
    _, object_ids = _types_block()
    if not isinstance(claims, dict):
        return ["claims must be an object with objects, relations, and uncertain"]
    problems, ids = [], set()
    for i, o in enumerate(claims.get("objects", [])):
        problems += _object_problems(f"object {i + 1}", o, object_ids, ids)
    for i, r in enumerate(claims.get("relations", [])):
        problems += _relation_problems(f"relation {i + 1}", r, ids)
    uncertain = claims.get("uncertain", [])
    if not isinstance(uncertain, list) or not all(isinstance(u, str) for u in uncertain):
        problems.append("uncertain must be a list of phrases")
    return problems


def vocabulary() -> dict:
    """What a label can say: the claimable classes with their synonyms, the grid, the relations."""
    classes = [c for c in load_ontology().classes.values() if c.claimable]
    return {
        "objects": [{"id": c.id, "name": c.name, "synonyms": list(c.synonyms)} for c in classes],
        "grid": list(GRID),
        "relations": list(RELATIONS),
    }
