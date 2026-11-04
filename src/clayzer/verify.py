"""Verify, then write (caption-plan.md §1.3): check each drafted Claim before the Caption commits.

For every object Claim the Harness drafted, find LGND Geo's NAIP image at the centre of the
Claim's grid cell (`search_chip_lat_lon`; LGND's images are about 160 m across, roughly one
cell of a Chip) and ask LGND's image model whether it shows the object (`reasoning_imagery_check`).
Each lookup and check is a `tool` Step in the Trace, with `role: verify`.

The policy, in order:
- "supported"                                     the Claim stays in the Caption
- "not supported", "partly supported", "unchecked" the Claim moves to `uncertain`
- the lookup or the check itself failed            the Claim stays, marked unverified: a
                                                   verifier outage must not quietly empty the
                                                   Caption (that would turn an Environment
                                                   Fault into a quality score)
Relations to a moved object are dropped.

The code, not the captioning model, does this, using the Chip's footprint. The model still
sees only the image (ADR-0009). LGND reads imagery and an image model, never an Answer Key, and
is never used in scoring (ADR-0006).
"""

from __future__ import annotations

import json
import time

from clayzer.grid import GRID
from clayzer.ontology import load as load_ontology

INDEX = "naip"
SUPPORTED = "supported"


def cell_centre(bbox, cell: str) -> tuple[float, float]:
    """(lat, lon) of a grid cell's centre on a north-up Chip with bbox (W, S, E, N)."""
    west, south, east, north = bbox
    i = GRID.index(cell)
    col, row = i % 3, i // 3
    lon = west + (col + 0.5) / 3 * (east - west)
    lat = north - (row + 0.5) / 3 * (north - south)
    return round(lat, 6), round(lon, 6)


def claim_text(obj: dict, names: dict[str, str]) -> str:
    noun = names.get(obj["object"], obj["object"].replace("_", " ")).lower()
    article = "An" if noun[0] in "aeiou" else "A"
    return f"{article} {noun} is visible here."


def _parse(text: str) -> dict | None:
    try:
        value = json.loads(text)
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _call(toolbox, tracer, name: str, arguments: dict, claim_id: str):
    """Call a verification tool and record it as a `tool` Step."""
    t0 = time.time()
    r = toolbox.call(name, arguments)
    if tracer is not None:
        tracer.tool(name, arguments, t0, time.time(), r.text,
                    r.text[:1000] if r.is_error else None, {
                        "role": "verify", "claim": claim_id,
                        "server": toolbox.server_for(name),
                        "is_error": r.is_error, "error_code": r.error_code,
                    })  # fmt: skip
    return r


def verify(caption: dict, footprint: dict, toolbox, tracer=None) -> tuple[dict, dict]:
    """Check the drafted Caption's object Claims. Returns the Caption with unconfirmed Claims
    moved to `uncertain`, and a report: one check per Claim plus counts.

    `footprint` is the Chip's {"bbox": [W, S, E, N], "date": "YYYY-MM-DD"}.
    """
    names = {c.id: c.name for c in load_ontology().classes.values()}
    lookups: dict[str, dict] = {}  # one image lookup per cell, shared by its Claims
    checks, kept, moved = [], [], []
    for obj in caption["objects"]:
        cell = obj["position"]
        check = {"id": obj["id"], "object": obj["object"], "position": cell}
        if cell not in lookups:
            lat, lon = cell_centre(footprint["bbox"], cell)
            r = _call(toolbox, tracer, "search_chip_lat_lon",
                      {"index": INDEX, "lat": lat, "lon": lon}, obj["id"])  # fmt: skip
            found = None if r.is_error else _parse(r.text)
            lookups[cell] = found if found and found.get("node") else {}
        found = lookups[cell]
        if not found:
            check |= {"verdict": "unverified", "reason": "no LGND image found for this cell"}
            kept.append(obj)
            checks.append(check)
            continue
        check |= {"node": found["node"], "observed": found.get("observed"),
                  "same_date": found.get("observed") == footprint.get("date")}  # fmt: skip
        claim = claim_text(obj, names)
        r = _call(toolbox, tracer, "reasoning_imagery_check",
                  {"claim": claim, "kind": "place", "nodes": [found["node"]]}, obj["id"])  # fmt: skip
        result = None if r.is_error else _parse(r.text)
        if not result or "verdict" not in result:
            check |= {"claim": claim, "verdict": "unverified", "reason": r.text[:200]}
            kept.append(obj)
        else:
            places = result.get("places") or [{}]
            check |= {"claim": claim, "verdict": result["verdict"],
                      "reason": (places[0].get("reason") or "")[:300]}  # fmt: skip
            (kept if result["verdict"] == SUPPORTED else moved).append(obj)
        checks.append(check)

    gone = {o["id"] for o in moved}
    doubts = [
        f"{o['count']} × {names.get(o['object'], o['object']).lower()} at {o['position']}"
        for o in moved
    ]
    verified = {
        **caption,
        "objects": kept,
        "relations": [
            r for r in caption["relations"] if r["subject"] not in gone and r["object"] not in gone
        ],
        "uncertain": list(caption["uncertain"]) + doubts,
    }
    counts = {
        "claims": len(checks),
        "confirmed": sum(c["verdict"] == SUPPORTED for c in checks),
        "moved": len(moved),
        "unverified": sum(c["verdict"] == "unverified" for c in checks),
        "different_date": sum(c.get("same_date") is False for c in checks),
    }
    return verified, {"checks": checks, **counts}
