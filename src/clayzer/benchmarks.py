"""Local-only benchmark adapters. No downloader, license assumption, or bundled benchmark data.

Normalized outputs carry dataset versions and source hashes. RSICD captions/scene classes
are retrieval references, never object grounding. VRSBench boxes require an explicit reviewed
category crosswalk; unsupported categories are recorded, not guessed.
"""

import hashlib
import json
from pathlib import PurePosixPath

from clayzer.grid import GRID
from clayzer.ontology import load


def _provenance(dataset, version, license_note, raw):
    if not version or not license_note:
        raise ValueError("Dataset version and license note are required")
    return {
        "dataset": dataset,
        "version": version,
        "license": license_note,
        "source_sha256": hashlib.sha256(json.dumps(raw, sort_keys=True).encode()).hexdigest(),
    }


def rsicd(raw: dict, *, version: str, license_note: str, limit=100, split="test") -> dict:
    if limit < 1:
        raise ValueError("Positive sample limit required")
    items = sorted(
        (x for x in raw["images"] if x.get("split") == split), key=lambda x: x["filename"]
    )[:limit]
    rows, queries = [], []
    for image in items:
        name = image["filename"]
        if PurePosixPath(name).name != name:
            raise ValueError("Benchmark filename must be a basename")
        refs = sorted({s["raw"].strip() for s in image["sentences"] if s["raw"].strip()})
        rows.append(
            {
                "id": name,
                "image_uri": name,
                "reference_captions": refs,
                "reference_labels": None,
                "split": split,
            }
        )
        for text in refs:
            queries.append({"query": text, "relevant": [name], "relevance_complete": False})
    # Identical queries across images share a relevance set rather than becoming false negatives.
    merged = {}
    for q in queries:
        merged.setdefault(q["query"], set()).update(q["relevant"])
    return {
        "rows": rows,
        "queries": [
            {"id": str(i), "query": text, "relevant": sorted(ids), "relevance_complete": False}
            for i, (text, ids) in enumerate(sorted(merged.items()))
        ],
        "provenance": _provenance("RSICD", version, license_note, raw),
        "citation": "Lu et al. 2017, Exploring Models and Data for Remote Sensing Image Caption Generation, IEEE TGRS 56(4)",
        "status": "adapter_only; no real benchmark run",
    }


def vrsbench_boxes(
    raw: list[dict], width: int, height: int, crosswalk: dict, *, version: str, license_note: str
) -> dict:
    """Input: distinct objects {id, category, bbox:[left, top, right, bottom]} in pixel units.

    Bboxes must be deduplicated by instance id upstream; repeated referring expressions are
    not independent objects. Box coverage, not centroids, defines occupied grid cells.
    """
    if width <= 0 or height <= 0 or len({x["id"] for x in raw}) != len(raw):
        raise ValueError("Positive dimensions and distinct object instance ids required")
    labels, unsupported = {}, []
    for box in raw:
        obj = crosswalk.get(box["category"])
        if obj not in load().claimable():
            unsupported.append(box["category"])
            continue
        l, t, r, b = box["bbox"]
        if not (0 <= l < r <= width and 0 <= t < b <= height):
            raise ValueError("Box outside image or invalid pixel coordinates")
        cells = []
        for i, cell in enumerate(GRID):
            x, y = i % 3, i // 3
            if min(r, (x + 1) * width / 3) > max(l, x * width / 3) and min(
                b, (y + 1) * height / 3
            ) > max(t, y * height / 3):
                cells.append(cell)
        lb = labels.setdefault(
            obj,
            {
                "object": obj,
                "count": 0,
                "count_complete": False,
                "position": cells[0],
                "cells": [],
                "attributes": {},
                "source": "vrsbench",
                "source_ids": [],
            },
        )
        # Referring-expression boxes need not exhaust all visible instances.
        lb["count"] += 1
        lb["cells"] = sorted(set(lb["cells"]) | set(cells), key=GRID.index)
        lb["source_ids"].append(str(box["id"]))
    return {
        "reference_labels": list(labels.values()),
        "unsupported_categories": sorted(set(unsupported)),
        "provenance": {
            **_provenance("VRSBench", version, license_note, raw),
            "crosswalk": crosswalk,
            "image_size": [width, height],
        },
        "status": "adapter_only; no real benchmark run",
    }
