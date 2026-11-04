"""Offline Report demo: synthetic recorded Runs plus a real development-Case reference-only gallery.

No model-generated captions are evaluated against the real development Cases. The gallery is a review
of genuine imagery and independent references, not a caption accuracy benchmark.
"""

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

from clayzer import batch
from clayzer.cases import parse_jsonl, to_jsonl
from clayzer.config import REPO
from clayzer.imported_score import write_evaluation
from clayzer.provenance import sha
from clayzer.replay import replay
from clayzer.store import LocalStore


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="new directory only")
    args = parser.parse_args()
    root = args.output.resolve()
    if root.exists():
        parser.error("Output already exists; choose a new directory")
    root.mkdir(parents=True)
    synthetic = root / "synthetic-recording"
    subprocess.run(
        [
            sys.executable,
            str(REPO / "scripts" / "output_score_demo.py"),
            "--output",
            str(synthetic),
        ],
        check=True,
    )
    recording = next((synthetic / "batches").iterdir())
    target = replay(recording, data=synthetic / "data", output=root / "replayed")
    # The imported set belongs to the same clearly synthetic provider demo.
    imported = json.loads((synthetic / "imported" / "output-score.json").read_text())
    imported["dataset_metadata"] = {
        "name": "Synthetic Output Score contract demo",
        "source": "Scripted provider + Pillow images",
        "split": "synthetic",
        "provenance": "No model accuracy measured",
    }
    write_evaluation(imported, target / "data" / "datasets" / "synthetic-output")
    fixtures = REPO / "fixtures" / "caption"
    cases = parse_jsonl((fixtures / "cases" / "caption-dev.jsonl").read_bytes())
    bid = f"DEV-{len(cases)}-REFERENCE-PREVIEW"
    config = batch.BatchConfig(
        batch_id=bid,
        label="REFERENCE PREVIEW — NO CAPTIONS EVALUATED",
        created="recorded Case fixture dates",
        region="dev",
        repeats=1,
        case_ids=[c["id"] for c in cases],
        cases_sha=sha(to_jsonl(cases)),
        caption_model="none: no Captions evaluated",
        judge_model=None,
        embed_model="none",
        prompt_sha=sha(b""),
        prompt_source="not run",
        extra={"demo": "Real NAIP / USGS / OSM reference gallery only"},
    )
    source = root / "reference-recording" / bid
    source.mkdir(parents=True)
    (source / "batch.json").write_text(json.dumps(asdict(config), indent=2) + "\n")
    (source / "cases.jsonl").write_bytes(to_jsonl(cases))
    (source / "results.jsonl").write_text("")
    preview = replay(source, data=fixtures, output=root / "reference-preview")
    # Combine disjoint demo names into the replay UI store, never the user's normal store.
    shutil.copytree(preview / "batches" / bid, target / "batches" / bid)
    shutil.copytree(preview / "data" / "chips", target / "data" / "chips", dirs_exist_ok=True)
    store = LocalStore(target / "data", target / "batches")
    store.put("cases/caption-dev.jsonl", to_jsonl(cases))
    notice = fixtures / "cases" / "NOTICE.md"
    store.put("cases/NOTICE.md", notice.read_bytes())
    print("\nOFFLINE REPORT DEMO — synthetic Runs and real reference-only Cases")
    print("Synthetic replay:", target / "batches" / recording.name / "report.html")
    print(
        f"Real Case preview ({len(cases)} Cases; NO CAPTIONS EVALUATED):",
        target / "batches" / bid / "report.html",
    )
    print("Dataset card:", target / "data/datasets/synthetic-output/dataset-card.html")
    print(f"UI: uv run clayzer ui --local-root {target} --port 8772")


if __name__ == "__main__":
    main()
