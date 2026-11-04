"""Provenance: what each Batch was run and judged with, so every score traces back to its inputs.

The vision brief asks that "every scored run keeps its traces, inputs, and the rubric/reference
it was judged against". A Batch freezes its prompt and Cases (batch.py); this module adds the
rest of what moves a score:
- the Judge's rubric: its prompt and verdict tool, saved as judge-prompt.txt and hashed
- the ontology Grounding scores against: its version and a hash of the file
- every Chip's image, hashed into chips.json, and checked before each Run, so a Chip
  replaced under the same key can't be scored as if it were the original
- the code: the git commit and whether it had uncommitted changes

Batches from before this was recorded show these items as "not recorded".
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor

from clayzer import judge, ontology
from clayzer.config import REPO

# A Batch's settings, in the order the Provenance panel lists them: (key, what it is, group).
SETTINGS = [
    ("caption_model", "Caption model", "What was tested"),
    ("prompt_sha", "Caption prompt", "What was tested"),
    ("prompt_source", "Prompt source", "What was tested"),
    ("tools", "MCP servers", "What was tested"),
    ("max_turns", "Turn budget", "What was tested"),
    ("judge_model", "Judge model", "What it was judged with"),
    ("judge_prompt_sha", "Judge rubric", "What it was judged with"),
    ("embed_model", "Embedding model", "What it was judged with"),
    ("cases_sha", "Cases and Reference Labels", "What it was judged with"),
    ("chips_sha", "Chip images", "What it was judged with"),
    ("ontology_version", "Ontology version", "What it was judged with"),
    ("ontology_sha", "Ontology file", "What it was judged with"),
    ("scorer_version", "Scorer version", "What it was judged with"),
    ("summary_model", "Narrative model", "How it was reported"),
    ("code_commit", "Git commit", "The code"),
    ("code_dirty", "Uncommitted changes", "The code"),
    ("repeats", "Repeats", "The run"),
    ("region", "Region", "The run"),
    ("created", "Started", "The run"),
]
# Recorded only by Batches since this module: None means "not recorded".
RECORDED_SINCE = {"judge_prompt_sha", "chips_sha", "ontology_version", "ontology_sha",
                  "code_commit", "code_dirty", "summary_model"}  # fmt: skip

# A Batch's stored files, in the order the Provenance panel lists them: (name, what it is).
BATCH_FILES = [
    ("batch.json", "the configuration"),
    ("prompt.txt", "the caption prompt"),
    ("judge-prompt.txt", "the Judge's rubric: its prompt and verdict tool"),
    ("cases.jsonl", "the Cases and Reference Labels, frozen at the start"),
    ("chips.json", "a SHA-256 of every Chip image"),
    ("results.jsonl", "one row per Run: outcome and scores"),
    ("captions.jsonl", "one Caption per Run"),
    ("retrieval.jsonl", "retrieval over each Repeat's Captions"),
    ("summary.json", "per-Case means and Spreads"),
    ("report.md", "the report, as Markdown"),
]
# A Run's stored files, as suffixes of <case-id>--r<repeat>.
RUN_FILES = [
    ("traces/{run}.jsonl", "the Trace: every model and tool call"),
    ("traces/{run}.summary.json", "the code-written summary"),
    ("traces/{run}.narrative.json", "the model-written narrative"),
    ("runs/{run}.json", "the Run report, as JSON"),
]
_RUN_FILE = re.compile(r"^(traces/[A-Za-z0-9_.-]+--r\d+(\.summary|\.narrative)?\.json(l)?"
                       r"|runs/[A-Za-z0-9_.-]+--r\d+\.(json|html))$")  # fmt: skip


def sha(data: bytes) -> str:
    """The short hash used in configurations: the first 12 hex digits of SHA-256."""
    return hashlib.sha256(data).hexdigest()[:12]


def judge_prompt() -> str:
    """The Judge's rubric as one text: the prompt template and the verdict tool it fills in."""
    return (
        judge.PROMPT + "\n# submit_verdict tool\n" + json.dumps(judge.VERDICT_TOOL, indent=2) + "\n"
    )


def ontology_version() -> tuple[str, str]:
    """The ontology's declared version, and a hash of the file (which catches unbumped edits)."""
    return ontology.load().version, sha(ontology.DEFAULT.read_bytes())


def code_version() -> tuple[str | None, bool | None]:
    """The git commit, and whether tracked files had uncommitted changes; None outside git."""

    def git(*args: str) -> str:
        return subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True,
                              check=True, timeout=10).stdout.strip()  # fmt: skip

    try:
        return git("rev-parse", "HEAD"), bool(git("status", "--porcelain", "--untracked-files=no"))
    except (OSError, subprocess.SubprocessError):
        return None, None


def chip_manifest(store, cases: list[dict]) -> dict[str, str]:
    """Every Chip's store key -> the SHA-256 of its image, as the Batch starts."""
    uris = sorted({chip["uri"] for case in cases for chip in case["chips"]})
    with ThreadPoolExecutor(8) as pool:
        return dict(zip(uris, pool.map(lambda u: hashlib.sha256(store.get(u)).hexdigest(), uris)))


def allowed_file(name: str) -> bool:
    """Whether a Batch-relative name is a file the app may serve."""
    if ".." in name:
        return False
    return name in {n for n, _ in BATCH_FILES} or bool(_RUN_FILE.match(name))


def console_url(store, key: str) -> str | None:
    """The AWS console page for an S3 object; None for a local store."""
    bucket = getattr(store, "bucket", None)
    if not bucket:
        return None
    return f"https://s3.console.aws.amazon.com/s3/object/{bucket}?prefix={store._key(key)}"


def files(store, batch_id: str, names: list[tuple[str, str]]) -> list[dict]:
    """The listed files with where to find each: in the app, in the store, in the AWS console."""

    def entry(item: tuple[str, str]) -> dict:
        name, what = item
        key = f"batches/{batch_id}/{name}"
        return {
            "name": name,
            "what": what,
            "exists": store.exists(key),
            "href": f"/api/batches/{batch_id}/files/{name}",
            "store_url": store.url(key),
            "console_url": console_url(store, key),
        }

    with ThreadPoolExecutor(8) as pool:
        return list(pool.map(entry, names))


def run_files(store, batch_id: str, case_id: str, repeat: int) -> list[dict]:
    run = f"{case_id}--r{repeat}"
    return files(store, batch_id, [(p.format(run=run), what) for p, what in RUN_FILES])
