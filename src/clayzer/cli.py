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
clayzer trace <batch-id> <case-id> [-r N]   show one Run's summary and Trace, Step by Step
clayzer summarize <batch-id>                rebuild every Run's summary from its Trace, offline
clayzer compare <batch-a> <batch-b>         what changed, and by how much
clayzer baseline accept <batch-id>          make a Batch the Baseline (baselines/<name>/)
clayzer gate <batch-id>                     regression gate: exit 0 pass, 1 fail, 2 inconclusive
clayzer experiment <id> --hypothesis TEXT   record a gated attempt; --accept keeps it if it passes
clayzer ui [--allow-launch]                 the team web app on http://127.0.0.1:8770

clayzer login lgnd                          sign in to an MCP server that needs it (browser, once)
clayzer tools roda                          list an MCP server's tools
clayzer tools lgnd --call TOOL --args JSON  call one tool and print the result

Everything is read from and written to the store: local folders, or CLAYZER_STORE=s3://...
"""

import argparse
import json
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
    b.add_argument(
        "--tools", nargs="+", metavar="SERVER", help="MCP servers the Harness may call, e.g. roda"
    )
    b.add_argument(
        "--verify", action="store_true",
        help="check each drafted Claim with LGND Geo before writing (needs `clayzer login lgnd`)",
    )  # fmt: skip
    b.add_argument("--resume", metavar="BATCH_ID", help="finish an existing Batch")
    b.add_argument("--no-narrate", action="store_true",
                   help="skip the model-written Trace summaries")  # fmt: skip

    sub.add_parser("batches", help="list Batches in the store")
    rp = sub.add_parser("report", help="rebuild a Batch's reports")
    rp.add_argument("batch_id")

    rs = sub.add_parser("rescore", help="score a Batch's stored Captions again, no model calls")
    rs.add_argument("batch_id")

    tr = sub.add_parser("trace", help="show one Run's Trace, Step by Step")
    tr.add_argument("batch_id")
    tr.add_argument("case_id")
    tr.add_argument("-r", "--repeat", type=int, default=1)
    tr.add_argument("--json", action="store_true", help="print the raw Trace")

    sm = sub.add_parser("summarize", help="rebuild every Run's summary from its Trace, offline")
    sm.add_argument("batch_id")
    sm.add_argument("--narrate", action="store_true",
                    help="also have a model write missing narratives (needs Bedrock)")  # fmt: skip
    sm.add_argument("--force", action="store_true", help="with --narrate, rewrite all of them")

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

    ex = sub.add_parser("experiment", help="record one labelled prompt experiment, offline")
    ex.add_argument("batch_id")
    ex.add_argument("--hypothesis", required=True, help="what this one change should improve")
    ex.add_argument("--baseline", default="default")
    ex.add_argument("--tolerance", type=float, default=None)
    ex.add_argument("--max-token-increase", type=float, default=None, help="0.5 = +50%%")
    ex.add_argument("--accept", action="store_true", help="keep a passing, comparable candidate")
    recovery = sub.add_parser("experiment-recover", help="recover a kept log after a store failure")
    recovery.add_argument("--baseline", default="default")

    ui = sub.add_parser("ui", help="the team web app: workflow, tasks, Cases, Batches")
    ui.add_argument("--allow-launch", action="store_true", help="let the browser run Batches")
    ui.add_argument("--host", default="127.0.0.1")
    ui.add_argument("--port", type=int, default=8770)

    lg = sub.add_parser("login", help="sign in to an MCP server that needs it (opens a browser)")
    lg.add_argument("server")
    tl = sub.add_parser("tools", help="list an MCP server's tools, or call one")
    tl.add_argument("server")
    tl.add_argument("--call", metavar="TOOL", help="call this tool")
    tl.add_argument("--args", default="{}", help="the tool's arguments as JSON")

    a = p.parse_args(argv)
    if a.cmd in ("login", "tools"):
        return _tools_command(a)
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
            summary = batches.resume(a.resume, settings, store, narrate=not a.no_narrate)
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
                narrate=not a.no_narrate, tools=a.tools,
                verify="lgnd" if a.verify else None,
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

    if a.cmd == "trace":
        from clayzer.trace import loads, trace_key

        key = trace_key(a.batch_id, a.case_id, a.repeat)
        if not store.exists(key):
            print(f"no Trace at {store.url(key)}", file=sys.stderr)
            return 1
        body = store.get(key)
        if a.json:
            print(body.decode(), end="")
            return 0
        info, steps = loads(body)
        from clayzer.narrate import narrative_key
        from clayzer.summarize import summarize, to_markdown

        nkey = narrative_key(a.batch_id, a.case_id, a.repeat)
        if store.exists(nkey):
            narrative = json.loads(store.get(nkey))
            print(narrative["markdown"])
            print(f"\n(written by {narrative['model']} from this Trace)\n")
        else:
            print(to_markdown(summarize(info, steps)))
        took = (info.ended_at or info.started_at) - info.started_at
        print(f"Run {info.run_id} · {info.status} · {took:.1f} s · {info.model_id}")
        if info.error:
            print(f"  error: {info.error}")
        faults = info.metadata.get("faults") or {}
        if any(faults.values()):
            print("  faults: " + ", ".join(f"{k} {v}" for k, v in faults.items() if v))
        print(f"  {'#':>2} {'kind':<6} {'name':<10} {'ms':>7} {'tokens':>7} {'retries':>7}  result")
        for st in steps:
            at = st.attributes
            tokens = (at.get("usage") or {}).get("totalTokens", "")
            result = st.error or (st.output or {}).get("stop_reason", "")
            if at.get("fault"):
                f = at["fault"]
                result = (
                    f"{f['attribution'].upper()}{' (soft)' if f['soft'] else ''}: {f['reason']}"
                )
            print(
                f"  {st.index:>2} {st.kind:<6} {st.name:<10} {at.get('latency_ms', ''):>7} "
                f"{tokens:>7} {at.get('retries', ''):>7}  {str(result)[:70]}"
            )
        if info.final_answer:
            print(f"  Caption: {info.final_answer}")
        return 0

    if a.cmd == "summarize":
        from clayzer.batch import _key, _load_jsonl, resummarize

        if a.narrate:
            from clayzer.config import bedrock
            from clayzer.narrate import narrate_batch

            results = _load_jsonl(store, _key(a.batch_id, "results.jsonl"))
            counts = narrate_batch(bedrock(settings), store, a.batch_id, results, force=a.force)
            print(f"narratives: {counts['written']} written, {counts['skipped']} already up to date, "
                  f"{counts['no trace']} Runs without a Trace, {counts['rejected']} rejected, "
                  f"{counts['failed']} failed")  # fmt: skip
        n = resummarize(a.batch_id, store)
        print(f"rebuilt {n} summaries for {a.batch_id} from their Traces; reports updated")
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

        try:
            target = accept_baseline(load(store, a.batch_id), settings.baselines_dir, a.name)
        except (ValueError, OSError) as e:
            p.error(str(e))
        print(f"Baseline {a.name!r} is now {a.batch_id}: {target} (commit it to share)")
        return 0

    if a.cmd == "gate":
        from clayzer.batch import load
        from clayzer.gate import DEFAULT_TOLERANCE, gate, load_baseline, render_gate

        try:
            result = gate(
                load_baseline(settings.baselines_dir, a.baseline),
                load(store, a.batch_id),
                DEFAULT_TOLERANCE if a.tolerance is None else a.tolerance,
                a.max_token_increase,
            )
        except (ValueError, FileNotFoundError) as e:
            p.error(str(e))
        print(render_gate(result), end="")
        return result.exit_code

    if a.cmd == "experiment":
        from clayzer.batch import load
        from clayzer.experiments import record_experiment
        from clayzer.gate import DEFAULT_TOLERANCE, render_gate

        try:
            result, record = record_experiment(
                load(store, a.batch_id),
                store,
                settings.baselines_dir,
                a.hypothesis,
                baseline_name=a.baseline,
                accept=a.accept,
                tolerance=DEFAULT_TOLERANCE if a.tolerance is None else a.tolerance,
                max_token_increase=a.max_token_increase,
            )
        except (ValueError, OSError) as e:
            p.error(str(e))
        print(render_gate(result), end="")
        print(f"Experiment record: {store.url(record + '.json')}")
        print(f"PR log: {store.url(record + '.md')}")
        if a.accept and result.verdict == "pass":
            print(f"Kept {a.batch_id} as Baseline {a.baseline!r} (commit it to share)")
        return result.exit_code

    if a.cmd == "experiment-recover":
        from clayzer.experiments import recover_experiment

        try:
            record = recover_experiment(store, settings.baselines_dir, a.baseline)
        except (ValueError, OSError) as e:
            p.error(str(e))
        print(f"Recovered experiment: {store.url(record + '.json')}")
        print(f"PR log: {store.url(record + '.md')}")
        return 0

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


def _tools_command(a) -> int:
    """`clayzer login <server>` and `clayzer tools <server>`."""
    try:
        from clayzer.mcp_auth import NotSignedIn, auth_dir
        from clayzer.tools import Toolbox
    except ImportError:
        print("MCP tools need the tools extra: uv sync --extra tools", file=sys.stderr)
        return 1
    args = json.loads(a.args) if a.cmd == "tools" else {}
    try:
        with Toolbox.named([a.server], interactive=a.cmd == "login") as box:
            version = box.versions.get(a.server, "")
            if a.cmd == "login":
                print(f"Signed in to {a.server} ({version}): {len(box.specs)} tools.")
                print(f"The sign-in is saved in {auth_dir()}, outside the repo.")
                return 0
            if not a.call:
                print(f"{a.server} ({version}): {len(box.specs)} tools")
                for t in box.specs:
                    first = (t.description or "").strip().splitlines()[0:1]
                    print(f"  {t.name}: {first[0][:100] if first else ''}")
                return 0
            result = box.call(a.call, args)
            print(result.text)
            return 1 if result.is_error else 0
    except NotSignedIn as e:
        print(e, file=sys.stderr)
        return 1
    except ValueError as e:
        print(e, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
