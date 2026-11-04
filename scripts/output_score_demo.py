"""Offline synthetic contract demo. All model answers/embeddings are scripted, not evaluations.

Run: uv run python scripts/output_score_demo.py --output /tmp/clayzer-output-demo
Creates a native Batch, the same captions as an imported set, and self-contained reports.
"""

import argparse
import hashlib
import io
import json
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw

from clayzer import batch
from clayzer.config import Settings
from clayzer.imported_score import evaluate, write_evaluation
from clayzer.store import LocalStore


class SyntheticProvider:
    def __init__(self, captions):
        self.captions = captions

    def converse(self, **request):
        name = request["toolConfig"]["tools"][0]["toolSpec"]["name"]
        if name == "submit_verdict":
            value = {"score": 0.75, "issues": ["SCRIPTED FIXTURE: no vision model was invoked"]}
        else:
            png = request["messages"][0]["content"][0]["image"]["source"]["bytes"]
            value = self.captions[hashlib.sha256(png).hexdigest()]
        return {
            "output": {
                "message": {
                    "content": [
                        {"toolUse": {"name": name, "toolUseId": "synthetic", "input": value}}
                    ]
                }
            },
            "usage": {},
        }  # no invented usage or billing measurements

    def invoke_model(self, **request):
        text = json.loads(request["body"])["inputText"].lower()
        vector = [float("building" in text), float("water" in text), 0.1]
        return {"body": io.BytesIO(json.dumps({"embedding": vector}).encode())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    settings = Settings(
        caption_model="scripted-fixture",
        judge_model="scripted-fixture-judge",
        embed_model="scripted-bag-of-words",
        bedrock_endpoint_url=None,
        data_dir=args.output / "data",
        batches_dir=args.output / "batches",
        baselines_dir=args.output / "baselines",
        store_url=None,
        naip_source="pc",
    )
    store = LocalStore(settings.data_dir, settings.batches_dir)
    cases, rows, images, captions = [], [], {}, {}
    for obj, text, count in [
        ("building", "Two buildings in the north.", 2),
        ("water", "Water in the south.", None),
    ]:
        position = "north" if obj == "building" else "south"
        image = Image.new("RGB", (300, 300), "white")
        draw = ImageDraw.Draw(image)
        if obj == "building":
            draw.rectangle((110, 10, 130, 60), fill="gray")
            draw.rectangle((150, 10, 170, 60), fill="gray")
        else:
            draw.rectangle((100, 220, 200, 290), fill="blue")
        out = io.BytesIO()
        image.save(out, format="PNG")
        png = out.getvalue()
        key = f"chips/synthetic-{obj}.png"
        store.put(key, png)
        images[key] = png
        cap = {
            "text": text,
            "objects": [{"id": "o1", "object": obj, "count": count or 1, "position": position}],
            "relations": [],
            "uncertain": [],
        }
        captions[hashlib.sha256(png).hexdigest()] = cap
        case = {
            "id": f"synthetic-{obj}",
            "region": "synthetic",
            "terrain": "synthetic",
            "kind": "fixed",
            "chips": [
                {
                    "id": f"synthetic-{obj}",
                    "uri": key,
                    "date": "not an acquisition: synthetic fixture",
                    "bbox": [0, 0, 1, 1],
                    "source": "synthetic-pillow",
                }
            ],
            "reference_labels": [
                {
                    "object": obj,
                    "count": count,
                    "count_complete": True,
                    "position": position,
                    "cells": [position],
                    "attributes": {},
                    "source": "synthetic-fixture",
                    "source_ids": ["drawn"],
                }
            ],
        }
        cases.append(case)
        rows.append(
            {
                "id": case["id"],
                "case_id": case["id"],
                "image_uri": key,
                "generator": "scripted-fixture",
                "provider": "synthetic",
                **cap,
            }
        )
    provider = SyntheticProvider(captions)
    with patch("clayzer.batch.bedrock", return_value=provider):
        bid = batch.start(
            cases, settings, store, 3, "SYNTHETIC-OUTPUT-DEMO", "synthetic", narrate=False
        )
    imported = evaluate(
        rows,
        cases={c["id"]: c for c in cases},
        client=provider,
        judge_model="scripted-fixture-judge",
        embed_model="scripted-bag-of-words",
        image_loader=images.__getitem__,
    )
    imported["demo_notice"] = (
        "SYNTHETIC SCRIPTED PROVIDER: contract demo, no measured model accuracy"
    )
    write_evaluation(imported, args.output / "imported")
    (args.output / "captions.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))
    (args.output / "cases.jsonl").write_text("".join(json.dumps(case) + "\n" for case in cases))
    (args.output / "queries.json").write_text(json.dumps(imported["queries"], indent=2) + "\n")
    (args.output / "embeddings.json").write_text(
        json.dumps(imported["retrieval"]["recording"], indent=2) + "\n"
    )
    print("SYNTHETIC SCRIPTED PROVIDER — no real model accuracy or benchmark results")
    print("Native:", store.url(f"batches/{bid}/report.html"))
    print("Imported:", args.output / "imported/output-score.html")


if __name__ == "__main__":
    main()
