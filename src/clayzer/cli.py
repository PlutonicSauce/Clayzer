"""clayzer: build Cases, run Batches, compare them, and gate changes.

clayzer case uspvdb 400117                  a solar Case around USPVDB site 400117
clayzer case uswtdb 3072695                 a wind Case around USWTDB turbine 3072695
clayzer case neg -118.21 35.25 --n 1        a negative Case at lon lat
clayzer push [--from DIR]                   copy a local chips/ + cases/ folder into the store

clayzer batch --repeats 3 --label base      run every Case 3 times; writes a Batch
clayzer batch --resume <batch-id>           finish a Batch (expired credentials, failures)
clayzer batches                             list Batches
clayzer report <batch-id>                   rebuild a Batch's report.md and report.html
clayzer rescore <batch-id>                  score stored Captions again with the current scorer
clayzer compare <batch-a> <batch-b>         what changed, and by how much
clayzer baseline accept <batch-id>          make a Batch the Baseline (baselines/<name>/)
clayzer gate <batch-id>                     regression gate: exit 0 pass, 1 fail, 2 inconclusive
clayzer ui [--allow-launch]                 the team web app on http://127.0.0.1:8770

Everything is read from and written to the store: local folders, or CLAYZER_STORE=s3://...
"""

import argparse
import sys
from dataclasses import replace
from pathlib import Path

from clayzer.cases import cases_key, load_cases, parse_jsonl, save_case, to_jsonl
from clayzer.config import Settings, load_env
from clayzer.store import LocalStore, S3Store


def _local_report(store, settings: Settings, batch_id: str) -> Path:
    """A path to open the Batch's report.html from, downloading it when the store is S3."""
    key = f"batches/{batch_id}/report.html"
    if isinstance(store, LocalStore):
        return Path(store.url(key))
    path = settings.batches_dir / batch_id / "report.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(store.get(key))
    return path


def _push(store, src: Path) -> int:
    """Copy src/chips/* and src/cases/*.jsonl into the store, normalizing Chip uris."""
    n = 0
    for f in sorted((src / "chips").glob("*")):
        if f.suffix in (".png", ".json"):
            kind = "image/png" if f.suffix == ".png" else "application/json"
            store.put(f"chips/{f.name}", f.read_bytes(), kind)
            n += 1
    for f in sorted((src / "cases").glob("*.jsonl")):
        cases = parse_jsonl(f.read_bytes())
        for case in cases:
            for chip in case["chips"]:
                if not chip["uri"].startswith("chips/"):
                    chip["uri"] = f"chips/{Path(chip['uri']).name}"
        store.put(f"cases/{f.name}", to_jsonl(cases), "application/x-ndjson")
        n += 1
    return n


def _print_summary(summary: dict) -> None:
    b = summary["batch"]
    r = b["runs"]
    mrr = b["retrieval_mrr"]

    def f(x):
        return "—" if x is None else f"{x:.2f}"

    print(
        f"  correctness {f(b['correctness'])} · coverage {f(b['coverage'])} · "
        f"fidelity {f(b['fidelity'])} · retrieval "
        f"{f(mrr['mean'])} ± {f(mrr['spread'])} · unscored {f(b['unscored_share'])}"
    )
    print(
        f"  Runs: {r['ok']} ok, {r['harness_faults']} Harness Faults, "
        f"{r['sandbox_failures']} Sandbox Failures, of {r['planned']}"
    )
    if summary.get("stopped"):
        print(f"  STOPPED: {summary['stopped']}")


def main(argv: list[str] | None = None) -> int:
    load_env()
    settings = Settings.from_env()

    p = argparse.ArgumentParser(prog="clayzer")
    p.add_argument("--region", default="dev")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("case", help="build one Case and add it to the region's Case set")
    c.add_argument("kind", choices=["uspvdb", "uswtdb", "neg"])
    c.add_argument("args", nargs="+", help="a USGS case_id, or lon lat for a negative")
    c.add_argument("--n", type=int, default=1, help="negative number")
    c.add_argument("--state", default="CA", help="state code for a negative")

    pu = sub.add_parser("push", help="copy a local chips/ + cases/ folder into the store")
    pu.add_argument("--from", dest="src", type=Path, default=settings.data_dir)

    b = sub.add_parser("batch", help="run every Case several times under one configuration")
    b.add_argument("--repeats", type=int, default=3)
    b.add_argument("--label", default="", help="a short name for the change being tested")
    b.add_argument("--prompt", type=Path, help="caption prompt template file")
    b.add_argument("--caption-model", help="override CLAYZER_CAPTION_MODEL")
    b.add_argument("--only", nargs="*", help="Case ids to run")
    b.add_argument("--no-judge", action="store_true", help="skip the fidelity Judge")
    b.add_argument("--resume", metavar="BATCH_ID", help="finish an existing Batch")

    sub.add_parser("batches", help="list Batches in the store")
    rp = sub.add_parser("report", help="rebuild a Batch's reports")
    rp.add_argument("batch_id")

    rs = sub.add_parser("rescore", help="score a Batch's stored Captions again, no model calls")
    rs.add_argument("batch_id")

    cp = sub.add_parser("compare", help="compare two Batches")
    cp.add_argument("a")
    cp.add_argument("b")

    bl = sub.add_parser("baseline", help="manage Baselines")
    bl_sub = bl.add_subparsers(dest="action", required=True)
    acc = bl_sub.add_parser("accept", help="make a Batch the Baseline")
    acc.add_argument("batch_id")
    acc.add_argument("--name", default="default")

    g = sub.add_parser("gate", help="regression gate: candidate Batch vs the Baseline")
    g.add_argument("batch_id")
    g.add_argument("--baseline", default="default")
    g.add_argument("--tolerance", type=float, default=None)
    g.add_argument("--max-token-increase", type=float, default=None, help="0.5 = +50%%")

    ui = sub.add_parser("ui", help="the team web app: workflow, tasks, Cases, Batches")
    ui.add_argument("--allow-launch", action="store_true", help="let the browser run Batches")
    ui.add_argument("--host", default="127.0.0.1")
    ui.add_argument("--port", type=int, default=8770)

    a = p.parse_args(argv)
    store = settings.store()
    key = cases_key(a.region)

    if a.cmd == "case":
        from clayzer.cases import build_negative, build_positive

        if a.kind == "neg":
            lon, lat = map(float, a.args)
            case = build_negative(lon, lat, a.n, a.state, a.region, store, settings.naip_source)
        else:
            case = build_positive(a.kind, int(a.args[0]), a.region, store, settings.naip_source)
        save_case(store, key, case)
        labels = [
            f"{lb['object']}×{lb['count'] if lb['count'] is not None else '-'}@{lb['position']}"
            for lb in case["reference_labels"]
        ]
        chip = case["chips"][0]
        print(f"{case['id']}: chip {chip['id']} ({chip['source']}), {case['prep_seconds']} s")
        print("  labels: " + (", ".join(labels) or "none"))
        print(f"  stored in {store.url(key)}")
        return 0

    if a.cmd == "push":
        if isinstance(store, LocalStore) and a.src.resolve() == settings.data_dir.resolve():
            print("the store is this local folder; set CLAYZER_STORE=s3://...", file=sys.stderr)
            return 1
        n = _push(store, a.src)
        dest = store.url("") if isinstance(store, S3Store) else settings.data_dir
        print(f"pushed {n} files from {a.src} to {dest}")
        return 0

    if a.cmd == "batch":
        from clayzer import batch as batches
        from clayzer.harness import PROMPT

        if a.resume:
            print(f"resuming {a.resume}")
            summary = batches.resume(a.resume, settings, store)
            batch_id = a.resume
        else:
            cases = load_cases(store, key)
            if a.only:
                cases = [c for c in cases if c["id"] in a.only]
            if not cases:
                print(
                    f"no Cases in {store.url(key)}; build some with `clayzer case`", file=sys.stderr
                )
                return 1
            if a.caption_model:
                settings = replace(settings, caption_model=a.caption_model)
            prompt = a.prompt.read_text() if a.prompt else PROMPT
            print(f"{len(cases)} Cases × {a.repeats} Repeats")
            batch_id = batches.start(
                cases, settings, store, a.repeats, a.label, a.region, prompt,
                str(a.prompt) if a.prompt else "built-in", judge=not a.no_judge,
            )  # fmt: skip
            summary = batches.load(store, batch_id)["summary"]
        print(f"Batch {batch_id} in {store.url(f'batches/{batch_id}/')}")
        _print_summary(summary)
        print(f"open {_local_report(store, settings, batch_id)}")
        return 0 if not summary.get("stopped") else 3

    if a.cmd == "batches":
        from clayzer import batch as batches

        for batch_id in batches.list_batches(store):
            s = batches.load(store, batch_id)["summary"]
            b = s["batch"] if s else {}

            def n(x):
                return "—" if x is None else f"{x:.2f}"

            print(
                f"{batch_id}  correctness {n(b.get('correctness'))}  "
                f"coverage {n(b.get('coverage'))}  fidelity {n(b.get('fidelity'))}"
            )
        return 0

    if a.cmd == "report":
        from clayzer.batch import write_reports

        write_reports(store, a.batch_id)
        print(f"open {_local_report(store, settings, a.batch_id)}")
        return 0

    if a.cmd == "rescore":
        from clayzer.batch import rescore

        print(f"rescored {a.batch_id}")
        _print_summary(rescore(a.batch_id, store))
        return 0

    if a.cmd == "compare":
        from clayzer.batch import load
        from clayzer.gate import compare, render_compare

        text = render_compare(compare(load(store, a.a), load(store, a.b)))
        store.put(f"batches/{a.b}/compare-{a.a}.md", text.encode(), "text/markdown")
        print(text)
        return 0

    if a.cmd == "baseline":
        from clayzer.batch import load
        from clayzer.gate import accept_baseline

        target = accept_baseline(load(store, a.batch_id), settings.baselines_dir, a.name)
        print(f"Baseline {a.name!r} is now {a.batch_id}: {target} (commit it to share)")
        return 0

    if a.cmd == "gate":
        from clayzer.batch import load
        from clayzer.gate import DEFAULT_TOLERANCE, gate, load_baseline, render_gate

        result = gate(
            load_baseline(settings.baselines_dir, a.baseline),
            load(store, a.batch_id),
            DEFAULT_TOLERANCE if a.tolerance is None else a.tolerance,
            a.max_token_increase,
        )
        print(render_gate(result), end="")
        return result.exit_code

    if a.cmd == "ui":
        try:
            from clayzer.ui.app import serve
        except ImportError:
            print("the web app needs the ui extra: uv sync --extra ui", file=sys.stderr)
            return 1
        mode = "can run Batches" if a.allow_launch else "read-only"
        print(f"Clayzer on http://{a.host}:{a.port} ({mode}; store {store.url('').rstrip('/')})")
        serve(settings, a.region, a.allow_launch, a.host, a.port)
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
