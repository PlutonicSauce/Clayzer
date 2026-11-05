"""Demo Stories and the demo pack (REQ-09, REQ-13).

A Story is a recorded Run picked to show one point about the evaluation, with a note saying what
it shows (GLOSSARY.md). They're listed in demo/stories.toml. `pack` copies each Story's Batch
from the store into a local folder laid out like a LocalStore, so `clayzer ui --local-root`
shows them with no model, credentials, or network. Every text file is redacted on the way out,
and only the Story Runs' Traces, reports, and Chips are copied, plus the accepted Baseline so the
pack's Results page shows the scores the live site does.
"""

import json
import re
import shutil
import tempfile
import tomllib
from pathlib import Path

from clayzer import batch as batches
from clayzer.config import REPO
from clayzer.narrate import narrative_key
from clayzer.report_safety import redact
from clayzer.run_report import build, run_keys
from clayzer.store import LocalStore
from clayzer.summarize import summary_key
from clayzer.trace import trace_key

STORIES = REPO / "demo" / "stories.toml"
PACK = REPO / "demo" / "pack"
INDEX = "stories.json"  # in the pack's data/ folder, beside its Chips
NOTICE = REPO / "fixtures" / "caption" / "cases" / "NOTICE.md"
EMBEDDED_PNG = re.compile(r"data:image/png;base64,[A-Za-z0-9+/=]+")
REQUIRED = ("id", "title", "batch", "case", "repeat", "shows", "note")
# A Batch's own files; the gate and the Batch page need them whole, so they're copied complete.
BATCH_FILES = ("batch.json", "cases.jsonl", "results.jsonl", "captions.jsonl", "retrieval.jsonl",
               "summary.json", "prompt.txt", "judge-prompt.txt", "chips.json")  # fmt: skip


def load_stories(path: Path = STORIES) -> list[dict]:
    stories = tomllib.loads(path.read_text())["story"]
    seen = set()
    for s in stories:
        missing = [k for k in REQUIRED if not s.get(k)]
        if missing or s["id"] in seen:
            raise ValueError(f"Story {s.get('id')!r}: missing {missing} or a duplicate id")
        seen.add(s["id"])
    return stories


def _redacted(name: str, body: bytes) -> bytes:
    text = body.decode()
    if name.endswith(".json"):
        return (json.dumps(redact(json.loads(text)), indent=2) + "\n").encode()
    if name.endswith((".jsonl", ".ndjson")):
        rows = [redact(json.loads(line)) for line in text.splitlines() if line.strip()]
        return "".join(json.dumps(r) + "\n" for r in rows).encode()
    return redact(text).encode()


def copy_baseline(src: Path, pack_root: Path) -> None:
    """Copy the Baseline folder `src` into the pack's baselines/, redacted, under the same name."""
    dest = pack_root / "baselines" / src.name
    dest.mkdir(parents=True, exist_ok=True)
    for f in sorted(p for p in src.iterdir() if p.is_file()):
        (dest / f.name).write_bytes(_redacted(f.name, f.read_bytes()))


def pack(store, stories: list[dict], out: Path = PACK, baseline: Path | None = None) -> Path:
    """Write the demo pack for `stories` from `store` into `out`, replacing an older pack. With
    `baseline`, a Baseline folder such as baselines/default, the pack carries it too."""
    with tempfile.TemporaryDirectory() as tmp:
        built = Path(tmp) / "pack"
        local = LocalStore(built / "data", built / "batches")
        bids = {s["batch"] for s in stories} | {s["baseline"] for s in stories if s.get("baseline")}
        for bid in sorted(bids):
            for name in BATCH_FILES:
                key = f"batches/{bid}/{name}"
                if store.exists(key):
                    local.put(key, _redacted(name, store.get(key)))
        index = []
        for s in stories:
            b = batches.load(local, s["batch"])
            result = next(
                (
                    r
                    for r in b["results"]
                    if (r["case_id"], r["repeat"]) == (s["case"], s["repeat"])
                ),
                None,
            )
            if result is None:
                raise ValueError(f"Story {s['id']}: {s['case']} Repeat {s['repeat']} isn't in it")
            for key in (trace_key, summary_key, narrative_key):
                k = key(s["batch"], s["case"], s["repeat"])
                if store.exists(k):
                    local.put(k, _redacted(k, store.get(k)))
            case = next(c for c in b["cases"] if c["id"] == s["case"])
            # The page's thumbnail: the Chip the Run captioned (a Change Case's later one).
            index.append({**s, "chip": Path(case["chips"][-1]["uri"]).stem})
            for chip in case["chips"]:
                for uri in (chip["uri"], chip["uri"].removesuffix(".png") + ".json"):
                    if store.exists(uri):
                        local.put(uri, store.get(uri))
            html, record = build(local, b, result)
            hkey, jkey = run_keys(s["batch"], s["case"], s["repeat"])
            # The app serves the Chip, so the report links it instead of inlining the PNG.
            html = EMBEDDED_PNG.sub(f"/api/chips/{Path(case['chips'][-1]['uri']).stem}.png", html)
            local.put(hkey, redact(html).encode())
            local.put(jkey, (json.dumps(redact(record), indent=2, default=str) + "\n").encode())
        local.put(INDEX, (json.dumps(index, indent=2) + "\n").encode())
        if baseline is not None:
            copy_baseline(baseline, built)
        # Case files carry OpenStreetMap labels, so their folders keep the ODbL notice.
        for folder in sorted(
            {p.parent for p in built.rglob("*.jsonl") if '"source": "osm' in p.read_text()}
        ):
            shutil.copy(NOTICE, folder / "NOTICE.md")
        if out.exists():
            if not (out / "data" / INDEX).exists():
                raise ValueError(f"{out} exists and isn't a demo pack; refusing to replace it")
            shutil.rmtree(out)
        shutil.copytree(built, out)
    return out


def with_gates(store, stories: list[dict]) -> list[dict]:
    """The Stories, each gate Story with its verdict from gating the two recorded Batches."""
    from clayzer.gate import gate

    out = []
    for s in stories:
        if s.get("baseline"):
            r = gate(batches.load(store, s["baseline"]), batches.load(store, s["batch"]))
            s = {**s, "gate": {"verdict": r.verdict, "reasons": r.reasons}}
        out.append(s)
    return out
