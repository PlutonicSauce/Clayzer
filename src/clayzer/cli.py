"""clayzer: build Cases, run Batches, compare them, and gate changes.

clayzer case uspvdb 400117                  a solar Case around USPVDB site 400117
clayzer case uswtdb 3072695                 a wind Case around USWTDB turbine 3072695
clayzer case neg -118.21 35.25 --n 1        a negative Case at lon lat
clayzer push [--from DIR]                   copy a local chips/ + cases/ folder into the store

clayzer batch --repeats 3 --label base      run every Case 3 times; writes a Batch
clayzer batch --resume <batch-id>           finish a Batch (expired credentials, failures)
clayzer batches                             list Batches
clayzer report <batch-id>                   rebuild a Batch's report.md and report.html
clayzer replay <batch-id> [--cases KEY]     rescore a recorded Batch against updated Cases, offline
clayzer rescore <batch-id>                  score stored Captions again with the current scorer
clayzer trace <batch-id> <case-id> [-r N]   show one Run's summary and Trace, Step by Step
clayzer summarize <batch-id>                rebuild every Run's summary from its Trace, offline
clayzer compare <batch-a> <batch-b>         what changed, and by how much
clayzer baseline accept <batch-id>          make a Batch the Baseline (baselines/<name>/)
clayzer gate <batch-id>                     regression gate: exit 0 pass, 1 fail, 2 inconclusive
clayzer listen <batch-id> [--play]          a spoken summary of the result (Nova Pro + Polly MP3)
clayzer experiment <id> --hypothesis TEXT   record a gated attempt; --accept keeps it if it passes
clayzer ui [--allow-launch]                 the team web app on http://127.0.0.1:8770
clayzer ui --calibrate                      also let /label save hand-made labels into labels/

clayzer login lgnd                          sign in to an MCP server that needs it (browser, once)
clayzer tools roda                          list an MCP server's tools
clayzer tools lgnd --call TOOL --args JSON  call one tool and print the result
clayzer verifier calibrate [--write]        measure each class's verifier on dev Cases; choose routes
clayzer verifier routes                     which verifier checks each class, and why
clayzer spread [--suggest]                  how varied the Cases' surroundings are, and the gaps

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


def _ontology_command(a, settings) -> int:
    """`clayzer ontology embed-cases | build-prototypes | show`: the Layer B index (ADR-0010)."""
    from clayzer import prototypes as proto
    from clayzer.ontology import load

    version = load().version

    if a.action == "show":
        path = proto.default_path(version)
        if not path.exists():
            print(f"no prototype index at {path}; build one with "
                  "`clayzer ontology build-prototypes`", file=sys.stderr)  # fmt: skip
            return 1
        p = proto.LocalPrototypes(path).load()
        print(f"prototypes v{p.ontology_version}  dim {p.dim}  built on region "
              f"{p.build_region!r} from {p.source} ({p.embedding_model})")  # fmt: skip
        for cid in sorted(p.centroids):
            conf = ", ".join(p.learned_confusers.get(cid, [])) or "—"
            print(f"  {cid:14s} n={p.counts.get(cid, 0):<4d} nearest: {conf}")
        return 0

    store = settings.store()
    key = cases_key(a.region)

    if a.action == "embed-cases":
        from clayzer import embeddings as emb

        cases = load_cases(store, key)
        if not cases:
            print(f"no Cases in {store.url(key)}; build some with `clayzer case`", file=sys.stderr)
            return 1
        if a.source == "file":
            if not a.emb_file:
                print("--source file needs --from <jsonl|parquet>", file=sys.stderr)
                return 1
            source = emb.load_precomputed(a.emb_file)
        else:
            from clayzer.config import bedrock

            source = emb.TitanImageEmbedding(bedrock(settings), a.model)
        n = emb.attach_to_cases(cases, source, store)
        store.put(key, to_jsonl(cases), "application/x-ndjson")  # one write, not one per Case
        print(f"embedded {n} Chips in {len(cases)} Cases of region {a.region!r} → {store.url(key)}")
        print("  next: `clayzer ontology build-prototypes --build-region "
              f"{a.region}` (on a region you will NOT score)")  # fmt: skip
        return 0

    # build-prototypes: from an exemplar JSONL, or from --region's embedded Cases
    from clayzer import embeddings as emb

    build_region = a.build_region or a.region
    if a.embeddings:
        pairs = []
        for line in a.embeddings.read_text().splitlines():
            if line.strip():
                rec = json.loads(line)
                pairs.append((rec["class_id"], [float(x) for x in rec["embedding"]]))
    else:
        cases = load_cases(store, key)
        pairs = emb.pairs_from_cases(cases)
        if not pairs:
            print(f"no embedded Cases in {store.url(key)}; run `clayzer ontology embed-cases` "
                  "first, or pass an exemplar JSONL", file=sys.stderr)  # fmt: skip
            return 1
    protos = proto.build(
        pairs, ontology_version=version, build_region=build_region,
        source=a.source, embedding_model=a.embedding_model,
    )  # fmt: skip
    out = a.out or proto.default_path(version)
    proto.LocalPrototypes(out).save(protos)
    kept = ", ".join(f"{c}×{protos.counts[c]}" for c in sorted(protos.centroids))
    dropped = sorted({c for c, _ in pairs} - set(protos.centroids))
    print(f"built {len(protos.centroids)} class prototypes (dim {protos.dim}) → {out}")
    print(f"  kept (Layer B classes seen in the data): {kept}")
    if dropped:
        print(
            f"  dropped (outside LAYER_B_CLASSES for this embedding resolution): {', '.join(dropped)}"
        )
    print(f"  CIRCULARITY: built on region {build_region!r}; do NOT score this region with it")
    return 0


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
    # Local report commands must work without loading credentials or a configured S3 store.
    args = argv if argv is not None else sys.argv[1:]
    command_args = args[2:] if args[:1] == ["--region"] else args
    if command_args and command_args[0].startswith("--region="):
        command_args = command_args[1:]
    local_replay = command_args[:1] == ["replay"] and (
        any(x.split("=", 1)[0] in {"--data", "--output"} for x in command_args)
        or (len(command_args) > 1 and ("/" in command_args[1] or Path(command_args[1]).is_dir()))
    )
    local_report = (
        local_replay
        or command_args[:1] == ["evaluate"]
        or (
            command_args[:1] == ["ui"]
            and any(x.split("=", 1)[0] == "--local-root" for x in command_args)
        )
    )
    if not local_report:
        load_env()
    settings = Settings.from_env()

    p = argparse.ArgumentParser(prog="clayzer")
    p.add_argument("--region", default="dev")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("case", help="build one Case and add it to the region's Case set")
    c.add_argument("kind", choices=["uspvdb", "uswtdb", "neg"])
    c.add_argument("args", nargs="+", help="a USGS case_id, or lon lat for a negative")
    c.add_argument("--n", type=int, default=1, help="negative number")
    c.add_argument("--dated-by", choices=["usgs", "grw"],
                   help="with --change: which date to use when USGS and GRW disagree, after a look")  # fmt: skip
    c.add_argument("--change", action="store_true",
                   help="a Change Case: the site before and after its install year (a Chip Pair)")  # fmt: skip
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
    b.add_argument("--no-listen", action="store_true",
                   help="don't make the spoken summary (Nova Pro + Polly) at the end")  # fmt: skip
    b.add_argument("--no-narrate", action="store_true",
                   help="skip the model-written Trace summaries")  # fmt: skip
    b.add_argument(
        "--ontology-context", action="store_true",
        help="feed the captioner class-level ontology guidance: look-alikes, exemplars, and an "
             "embedding-nearest-class hint where prototypes exist (ADR-0010)",
    )  # fmt: skip

    sub.add_parser("batches", help="list Batches in the store")
    rp = sub.add_parser("report", help="rebuild a Batch's reports")
    rp.add_argument("batch_id")

    rs = sub.add_parser("rescore", help="score a Batch's stored Captions again, no model calls")
    rs.add_argument("batch_id")

    replay = sub.add_parser(
        "replay", help="rebuild a local recorded Batch into a fresh directory; no network"
    )
    replay.add_argument(
        "source",
        help="recorded Batch id, or local directory containing batch.json and frozen Cases",
    )
    replay.add_argument(
        "--data", type=Path, help="local data/ or fixtures/caption directory with Chips"
    )
    replay.add_argument(
        "--output", type=Path, help="new output directory; defaults to a fresh temporary directory"
    )

    replay.add_argument("--cases", metavar="KEY", help="updated Case file for a stored Batch")
    replay.add_argument("--label", default="replay", help="name for the updated-Case Batch")
    replay.add_argument("--no-reports", action="store_true", help="skip stored Batch reports")

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

    li = sub.add_parser("listen", help="a spoken summary of a Batch's result, saved as an MP3")
    li.add_argument("batch_id")
    li.add_argument("--baseline", default="default")
    li.add_argument("--no-model", action="store_true", help="use the code-written script")
    li.add_argument(
        "--force", action="store_true", help="rewrite it even if the facts are the same"
    )
    li.add_argument("--play", action="store_true", help="then play it (macOS afplay)")

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
    ui.add_argument("--calibrate", action="store_true",
                    help="let the /label page save hand-made labels into labels/")  # fmt: skip
    ui.add_argument("--host", default="127.0.0.1")
    ui.add_argument("--port", type=int, default=8770)
    ui.add_argument(
        "--local-root",
        type=Path,
        help="read a local replay/demo root (data/ and batches/), ignoring S3 and .env",
    )

    on = sub.add_parser("ontology", help="the data-driven Object Ontology (ADR-0010)")
    on_sub = on.add_subparsers(dest="action", required=True)

    ec = on_sub.add_parser(
        "embed-cases",
        help="attach a Clay/LGND embedding to every Chip in --region's Cases (one-time, prep step)",
    )
    ec.add_argument("--source", choices=["file", "titan"], default="file",
                    help="file: reuse published Clay/LGND vectors; titan: Bedrock multimodal")  # fmt: skip
    ec.add_argument("--from", dest="emb_file", type=Path,
                    help="for --source file: a JSONL/Parquet of {chip_id, embedding}")  # fmt: skip
    ec.add_argument("--model", default="amazon.titan-embed-image-v1",
                    help="for --source titan: the Bedrock image embedding model")  # fmt: skip

    bp = on_sub.add_parser(
        "build-prototypes",
        help="build Layer B class prototypes from embedded Cases, or an exemplar embeddings file",
    )
    bp.add_argument(
        "embeddings", type=Path, nargs="?",
        help="JSONL of exemplars: one {\"class_id\": ..., \"embedding\": [...]} per line. Omit to "
             "build from --region's embedded Cases (run embed-cases first)",
    )  # fmt: skip
    bp.add_argument(
        "--build-region",
        help="provenance name for the region the exemplars come from; MUST differ from any scored "
             "region. Defaults to --region",
    )  # fmt: skip
    bp.add_argument("--source", default="lgnd-embeddings", help="where the embeddings came from")
    bp.add_argument("--embedding-model", default="clay-v1", help="the embedding model id")
    bp.add_argument("--out", type=Path, help="output path (default ontology/prototypes/vN.json)")
    on_sub.add_parser("show", help="print the current prototype index, if built")

    im = sub.add_parser("import", help="a Caption Set from any source becomes Cases")
    im.add_argument(
        "file", nargs="?", type=Path, help="JSON Lines or GeoParquet, one caption per row"
    )
    im.add_argument("--name", help="the Caption Set's name: Cases go to cases/import-<name>.jsonl")
    im.add_argument("--from-batch", metavar="BATCH_ID",
                    help="import a Batch's own Captions, to check the importer against known Cases")  # fmt: skip
    im.add_argument("--export", type=Path, metavar="JSONL",
                    help="with --from-batch: also write the Caption Set itself to this file")  # fmt: skip

    rs = sub.add_parser("rsicd", help="RSICD's human captions as a Caption Set file, to import")
    rs.add_argument("--split", choices=["train", "val", "test"], default="test")
    rs.add_argument("--limit", type=int, help="only the split's first N images (5 captions each)")
    rs.add_argument(
        "--out", type=Path, help="JSON Lines to write (default data/rsicd-<split>.jsonl)"
    )

    sub.add_parser("embeddings",
                   help="LGND's Clay embeddings for the region's Chips (anonymous; CC BY 4.0)")  # fmt: skip

    ex = sub.add_parser("extract", help="the Claims a caption's text makes; or calibrate that")
    ex.add_argument("text", nargs="?", help="a caption")
    ex.add_argument("--check", metavar="BATCH_ID",
                    help="extract from every Caption in a Batch; compare with its Claims")  # fmt: skip
    ex.add_argument("--labels", type=Path, metavar="JSONL",
                    help='compare with hand-made Claims: lines of {"id", "text", "claims"}')  # fmt: skip

    lg = sub.add_parser("login", help="sign in to an MCP server that needs it (opens a browser)")
    lg.add_argument("server")
    tl = sub.add_parser("tools", help="list an MCP server's tools, or call one")
    tl.add_argument("server")
    tl.add_argument("--call", metavar="TOOL", help="call this tool")
    tl.add_argument("--args", default="{}", help="the tool's arguments as JSON")

    vf = sub.add_parser("verifier", help="which verifier checks each object class")
    vf_sub = vf.add_subparsers(dest="action", required=True)
    cal = vf_sub.add_parser("calibrate", help="measure the verifiers on development Cases")
    cal.add_argument("--per-class", type=int, default=6,
                     help="true and false probes per class, each (at most 15)")  # fmt: skip
    cal.add_argument("--write", action="store_true", help="save the chosen routes to "
                     "ontology/verifiers.toml")  # fmt: skip
    cal.add_argument("--max-calls", type=int, default=100,
                     help="stop before starting if it would take more LGND calls")  # fmt: skip
    vf_sub.add_parser("routes", help="show the routes in ontology/verifiers.toml")

    sp = sub.add_parser("spread", help="how varied the Cases' surroundings are, and the gaps")
    sp.add_argument("--suggest", action="store_true",
                    help="search LGND for each gap and print `clayzer case` commands")  # fmt: skip
    sp.add_argument("--max-calls", type=int, default=100,
                    help="stop before starting if it would take more LGND calls")  # fmt: skip
    co = sub.add_parser("corroborate",
                        help="check the Cases' USGS labels against OSM's power mapping")  # fmt: skip
    co.add_argument("cases", nargs="+", type=Path, help="Case files (.jsonl)")
    co.add_argument("--json", type=Path, help="also write every Case's result here")

    ev = sub.add_parser(
        "evaluate", help="score normalized JSONL captions offline, without a Harness"
    )
    ev.add_argument("input", type=Path)
    ev.add_argument("--output", type=Path, required=True)
    ev.add_argument("--cases", type=Path, help="independent frozen Cases as JSONL")
    ev.add_argument("--queries", type=Path, help="frozen query/relevance JSON array")
    ev.add_argument("--recording", type=Path, help="saved matching text embedding recording")

    a = p.parse_args(argv)
    if a.cmd == "replay" and (a.data or a.output or Path(a.source).is_dir() or "/" in a.source):
        from clayzer.replay import replay

        try:
            target = replay(Path(a.source), data=a.data, output=a.output)
        except ValueError as exc:
            p.error(str(exc))
        print(
            target
            / "batches"
            / json.loads((Path(a.source) / "batch.json").read_text())["batch_id"]
            / "report.html"
        )
        return 0
    if a.cmd == "evaluate":
        from clayzer.imported_score import evaluate, write_evaluation

        rows = parse_jsonl(a.input.read_bytes())
        cases = {c["id"]: c for c in parse_jsonl(a.cases.read_bytes())} if a.cases else None
        report = evaluate(
            rows,
            cases=cases,
            queries=json.loads(a.queries.read_text()) if a.queries else None,
            recording=json.loads(a.recording.read_text()) if a.recording else None,
        )
        write_evaluation(report, a.output)
        print(a.output / "output-score.html")
        return 0
    if a.cmd in ("login", "tools"):
        return _tools_command(a)
    if a.cmd == "ontology":
        return _ontology_command(a, settings)
    if a.cmd == "verifier" and a.action == "routes":
        from clayzer import verifiers

        routes = verifiers.load()
        print(f"default {routes.default}; classifier {routes.classifier}")
        for cls, r in routes.routes.items():
            print(f"  {cls:<14} {r['method']:<14} {r.get('reason', '')}")
        return 0

    if a.cmd == "ui" and a.local_root:
        settings = replace(
            settings,
            store_url=None,
            data_dir=a.local_root / "data",
            batches_dir=a.local_root / "batches",
            baselines_dir=a.local_root / "baselines",
        )
    store = settings.store()
    key = cases_key(a.region)

    if a.cmd == "case":
        from clayzer.cases import build_negative, build_positive

        if a.change:
            from clayzer.cases import build_change

            if a.kind == "neg":
                print("--change needs a USGS site: uspvdb or uswtdb", file=sys.stderr)
                return 2
            from clayzer.grw import Flagged

            try:
                case = build_change(a.kind, int(a.args[0]), a.region, store,
                                    settings.naip_source, a.dated_by)  # fmt: skip
            except Flagged as e:
                print(f"not built: {e}", file=sys.stderr)
                return 2
        elif a.kind == "neg":
            lon, lat = map(float, a.args)
            case = build_negative(lon, lat, a.n, a.state, a.region, store, settings.naip_source)
        else:
            case = build_positive(a.kind, int(a.args[0]), a.region, store, settings.naip_source)
        save_case(store, key, case)
        labels = [
            f"{lb['object']}×{lb['count'] if lb['count'] is not None else '-'}@{lb['position']}"
            + (f" ({lb['change']})" if lb.get("change") else "")
            for lb in case["reference_labels"]
        ]
        chips = " → ".join(f"{c['id']} ({c['source']})" for c in case["chips"])
        print(f"{case['id']}: chip {chips}, {case['prep_seconds']} s")
        print("  labels: " + (", ".join(labels) or "none"))
        if d := case.get("dating"):
            print(f"  dated by {d['source']}: USGS {d['usgs_year'] or 'no year'}, "
                  f"GRW {', '.join(d['grw']) or 'no match'}")  # fmt: skip
            if d["flag"]:
                print(f"  flagged: {d['flag']}; dated by {d['source']}, chosen by {d['chosen_by']}")
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
                ontology_context=a.ontology_context,
            )  # fmt: skip
            summary = batches.load(store, batch_id)["summary"]
        print(f"Batch {batch_id} in {store.url(f'batches/{batch_id}/')}")
        _print_summary(summary)
        print(f"open {_local_report(store, settings, batch_id)}")
        if not a.no_listen and not summary.get("stopped"):
            from clayzer.listen import after_batch

            after_batch(store, settings, batch_id)
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
            # A tool Step's output is the tool's text; an llm Step's is a dict.
            out = st.output if isinstance(st.output, dict) else {}
            result = st.error or out.get("stop_reason", "")
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

    if a.cmd == "listen":
        import subprocess
        import tempfile

        from clayzer.config import bedrock
        from clayzer.gate import load_baseline
        from clayzer.listen import audio_key, listen, polly

        try:
            base = load_baseline(settings.baselines_dir, a.baseline)
        except FileNotFoundError:
            base = None
        try:
            rec = listen(store, a.batch_id, base, None if a.no_model else bedrock(settings),
                         polly(), force=a.force)  # fmt: skip
        except (ValueError, FileNotFoundError) as e:
            p.error(str(e))
        print(rec["text"])
        how = f"{rec['model']} wrote it" if rec["source"] == "model" else "code wrote it"
        state = "written" if rec["written"] else "already up to date"
        print(f"\n({how}; read by Polly {rec['voice']}, {rec['engine']}; {state})")
        print(store.url(audio_key(a.batch_id)))
        if a.play:
            with tempfile.NamedTemporaryFile(suffix=".mp3") as tmp:
                tmp.write(store.get(audio_key(a.batch_id)))
                tmp.flush()
                subprocess.run(["afplay", tmp.name], check=False)
        return 0

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

    if a.cmd == "replay":
        from clayzer import batch as batches

        cases_file = a.cases or key
        new_id = batches.replay(a.source, store, load_cases(store, cases_file), a.label,
                                reports=not a.no_reports)  # fmt: skip
        print(
            f"replayed {a.source} against {store.url(cases_file)} as {new_id}, with no model calls"
        )
        _print_summary(batches.load(store, new_id)["summary"])
        return 0

    if a.cmd == "import":
        from clayzer.importer import caption_rows, import_key, import_rows, read_rows

        if a.from_batch:
            from clayzer import batch as batches

            rows, name = caption_rows(batches.load(store, a.from_batch)), a.name or a.from_batch
            if a.export:
                a.export.write_text("".join(json.dumps(r) + "\n" for r in rows))
                print(f"wrote the Caption Set to {a.export}")
        elif a.file:
            rows, name = read_rows(a.file), a.name or a.file.stem
        else:
            print("give a Caption Set file, or --from-batch <batch-id>", file=sys.stderr)
            return 2
        print(f"{len(rows)} captions → {store.url(import_key(name))}")
        result = import_rows(rows, name)
        store.put(import_key(name), to_jsonl(result.cases), "application/x-ndjson")
        located = sum(c["located"] for c in result.cases)
        small = sum(1 for c in result.cases if c["imported"]["too_small"])
        unknown = sum(1 for c in result.cases if c["imported"]["too_small"] is None)
        print(f"  {len(result.cases)} Cases ({located} located), {len(result.skipped)} skipped, "
              f"{small} with Claims possibly too small for their imagery"
              + (f", {unknown} with no imagery resolution to check against" if unknown else ""))  # fmt: skip
        for s in result.skipped[:10]:
            print(f"  skipped {s['caption_id']}: {s['reason']}")
        return 0 if result.cases else 1

    if a.cmd == "rsicd":
        from clayzer import rsicd

        rows = rsicd.rows(json.loads(rsicd.captions_file().read_text()), a.split, a.limit)
        out = a.out or settings.data_dir / f"rsicd-{a.split}.jsonl"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("".join(json.dumps(r) + "\n" for r in rows))
        images = len({r["chip_id"] for r in rows})
        print(f"{len(rows)} captions of {images} RSICD {a.split} images → {out}")
        print("  never commit it (no license stated; cite Lu et al. 2017). Next:")
        print(f"  uv run clayzer import {out} --name rsicd-{a.split}")
        return 0

    if a.cmd == "embeddings":
        from clayzer import embeddings as emb

        points = emb.chip_points(load_cases(store, cases_key(a.region)))
        print(f"{len(points)} Chips in {cases_key(a.region)}; reading {emb.ROOT} anonymously")
        rows = emb.for_chips(points)
        store.put(emb.embeddings_key(a.region), to_jsonl(rows), "application/x-ndjson")
        missing = [r for r in rows if "missing" in r]
        print(f"  {len(rows) - len(missing)} joined to a cell, {len(missing)} without one; "
              f"saved in {store.url(emb.embeddings_key(a.region))}")  # fmt: skip
        for r in missing:
            print(f"  {r['chip_id']}: {r['missing']}")
        print(f"  {emb.ATTRIBUTION}")
        return 0

    if a.cmd == "extract":
        from clayzer.config import bedrock
        from clayzer.extract import batch_items, calibrate, extract, extract_model

        model = extract_model(settings)
        client = bedrock(settings)
        if a.text and not (a.check or a.labels):
            claims, _ = extract(client, model, a.text)
            print(json.dumps(claims, indent=2))
            return 0
        if a.check:
            items, prefix = batch_items(store, a.check), f"batches/{a.check}/extraction"
        elif a.labels:
            rows = [json.loads(line) for line in a.labels.read_text().splitlines() if line.strip()]
            items = [r for r in rows if r.get("claims")]  # lines nobody has labelled yet wait
            prefix = f"calibration/extraction/{a.labels.stem}"
        else:
            print("give a caption, --check <batch-id>, or --labels <file>", file=sys.stderr)
            return 2
        print(f"{len(items)} captions, extracted by {model}")
        r = calibrate(client, model, items, store, prefix)
        keys = ("type_precision", "type_recall", "count_exact", "position_exact",
                "position_within_one", "count_not_stated", "position_not_stated")  # fmt: skip
        print("  " + " · ".join(f"{k.replace('_', ' ')} {r[k]}" for k in keys))
        for source, g in r.get("by_source", {}).items():
            print(f"  {source} ({g['captions']}): " + " · ".join(
                f"{k.replace('_', ' ')} {g[k]}" for k in keys[:4]))  # fmt: skip
        if r.get("edit_rate") is not None:
            print(f"  proposals a person changed: {r['edit_rate']:.0%}")
        print(f"  {r['failed']} failed; saved in {store.url(prefix)}/agreement.json")
        return 0

    if a.cmd == "corroborate":
        from clayzer import corroborate

        cases = [c for f in a.cases for c in parse_jsonl(f.read_bytes())]
        done = {}
        if a.json and a.json.exists():  # resume an interrupted run
            done = {r["case"]: r for r in json.loads(a.json.read_text())["cases"]}

        def save(rows):
            if a.json:
                a.json.write_text(json.dumps(
                    {"summary": corroborate.summary(rows), "cases": rows}, indent=2) + "\n")  # fmt: skip

        print(f"{len(cases)} Cases, {len(done)} done before: one Overpass query per "
              f"{corroborate.BATCH} Chips", flush=True)  # fmt: skip
        rows = corroborate.corroborate(cases, done=done, save=save,
                                       progress=lambda m: print(m, flush=True))  # fmt: skip
        s = corroborate.summary(rows)
        print(f"solar agrees on {s['solar_agree']} of {s['solar_cases']} Cases with solar; "
              f"wind on {s['wind_agree']} of {s['wind_cases']} with turbines")  # fmt: skip
        print("to check by eye: " + (", ".join(s["to_check"]) or "none"))
        print("OSM candidate classes, Cases with each: "
              + (", ".join(f"{k} {v}" for k, v in s["candidate_cases"].items()) or "none"))  # fmt: skip
        if s["failed"]:
            print(f"{len(s['failed'])} failed; run the same command again to retry them")
        if a.json:
            print(f"written to {a.json}")
        return 1 if s["failed"] else 0

    if a.cmd in ("verifier", "spread"):
        return _lgnd_command(a, store, load_cases(store, key))

    if a.cmd == "ui":
        try:
            from clayzer.ui.app import serve
        except ImportError:
            print("the web app needs the ui extra: uv sync --extra ui", file=sys.stderr)
            return 1
        mode = "can run Batches" if a.allow_launch else "read-only"
        if a.calibrate:
            mode += f"; labels at http://{a.host}:{a.port}/label"
        print(f"Clayzer on http://{a.host}:{a.port} ({mode}; store {store.url('').rstrip('/')})")
        serve(settings, a.region, a.allow_launch, a.host, a.port, a.calibrate)
        return 0
    return 1


def _lgnd_command(a, store, cases: list[dict]) -> int:
    """`clayzer verifier calibrate` and `clayzer spread`: both read the region's Cases and spend
    LGND's daily calls (150 on the free tier), so each says what it will cost first."""
    from clayzer import lgnd

    if a.region == "test":
        print("calibrate and measure on development Cases only (CAP-16)", file=sys.stderr)
        return 2
    cases = [c for c in cases if c["id"].startswith("fixed-")]
    if not cases:
        print(f"no Cases for region {a.region!r}; `clayzer push --from fixtures/caption`",
              file=sys.stderr)  # fmt: skip
        return 1
    cached = lgnd.Lookups(None, store)
    if a.cmd == "verifier":
        from clayzer import calibrate, verifiers

        routes = verifiers.load()
        plan = calibrate.probes(cases, min(a.per_class, 15))
        cost = calibrate.estimate(plan, cached, routes)
        print(f"{len(plan)} probes from {len(cases)} Cases: about {cost} LGND calls")
    else:
        from clayzer import spread

        cost = spread.estimate(cases, cached, a.suggest)
        print(f"{len(cases)} Cases: at most {cost} LGND calls")
    if cost > a.max_calls:
        print(f"that's over --max-calls {a.max_calls}; raise it, or use --per-class",
              file=sys.stderr)  # fmt: skip
        return 2
    try:
        from clayzer.mcp_auth import NotSignedIn
        from clayzer.tools import Toolbox
    except ImportError:
        print("MCP tools need the tools extra: uv sync --extra tools", file=sys.stderr)
        return 1
    try:
        with Toolbox.named(["lgnd"]) as box:
            if a.cmd == "verifier":
                result = calibrate.run(cases, box.call, store, a.per_class, routes)
                prefix = calibrate.save(store, result, routes)
                print(calibrate.to_markdown(result, routes))
                print(f"saved in {store.url(prefix)}")
                if a.write:
                    new = calibrate.updated(routes, result)
                    verifiers.DEFAULT.write_text(verifiers.render(new))
                    print(f"routes written to {verifiers.DEFAULT} (commit it to share)")
                return 0
            measured = spread.measure(cases, box.call, store)
            found = spread.suggest(cases, measured, box.call) if a.suggest else None
            text = spread.to_markdown(measured, found)
    except NotSignedIn as e:
        print(e, file=sys.stderr)
        return 1
    from datetime import UTC, datetime

    key = f"spread/{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}/report.md"
    store.put(key, text.encode(), "text/markdown")
    print(text)
    print(f"saved in {store.url(key)}")
    return 0


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
