"""Batches: every Case run several times under one fixed configuration (caption-plan.md §6).

A Run is one Harness execution on one Case; a Batch holds `repeats` Runs per Case. Each Run
ends in one of three outcomes:
- ok               scored
- harness_fault    the Harness produced no usable Caption; scored 0, because it's the fault of
                   the system under test
- sandbox_failure  Bedrock, the network, or credentials failed; no valid score, excluded from
                   the summary, and run again by `resume`

Results are written after every Run, so a Batch interrupted by expired session credentials
keeps its progress. Expired credentials stop the Batch instead of failing every later Run.

Store layout, under batches/<batch-id>/:
    batch.json       the configuration: models, hashes of the prompt, Cases, Chips, Judge rubric
                     and ontology, repeats, scorer version, git commit (provenance.py)
    prompt.txt       the caption prompt template used
    judge-prompt.txt the Judge's rubric: its prompt and verdict tool
    cases.jsonl      the Cases as scored, frozen at the start
    chips.json       a SHA-256 of every Chip image, checked before each Run
    results.jsonl    one row per Run: outcome and scores
    captions.jsonl   one Caption per Run
    traces/          one Trace per Run (<case-id>--r<repeat>.jsonl): every model call as a Step
                     with its full request and response, timing, tokens, and retries (trace.py)
    retrieval.jsonl  retrieval over each Repeat's Captions
    summary.json     per-Case means and Spreads, and Batch-level scores
    report.md, report.html
    runs/            one report per Run: <case-id>--r<repeat>.html and .json (run_report.py)
"""

import hashlib
import json
import re
import statistics
from contextlib import nullcontext
from dataclasses import asdict, dataclass, field, fields
from datetime import UTC, datetime
from uuid import uuid4

from botocore.exceptions import BotoCoreError, ClientError

from clayzer import harness, provenance
from clayzer.cases import parse_jsonl, to_jsonl
from clayzer.config import Settings, bedrock
from clayzer.grounding import grounding
from clayzer.judge import fidelity
from clayzer.retrieval import retrieval
from clayzer.summarize import SummarySink
from clayzer.trace import RunInfo, StoreSink, Tracer, watch_retries
from clayzer.workflow import score as workflow_score

# Bump when grounding or summary logic changes, so the regression gate warns that scores from
# before and after aren't comparable.
SCORER_VERSION = "grounding-4+workflow-1"  # exact-cell position; the Workflow Score

OK, HARNESS_FAULT, SANDBOX_FAILURE = "ok", "harness_fault", "sandbox_failure"
EXPIRED = {
    "ExpiredToken", "ExpiredTokenException", "UnrecognizedClientException",
    "InvalidClientTokenId", "InvalidSignatureException",
}  # fmt: skip
NDJSON, JSON = "application/x-ndjson", "application/json"


class CredentialsExpired(Exception):
    pass


@dataclass(frozen=True)
class BatchConfig:
    batch_id: str
    label: str
    created: str
    region: str
    repeats: int
    case_ids: list[str]
    cases_sha: str
    caption_model: str
    judge_model: str | None
    embed_model: str
    prompt_sha: str
    prompt_source: str
    scorer_version: str = SCORER_VERSION
    # MCP servers the Harness may call (tools.py); empty means the single-call Harness.
    tools: list[str] = field(default_factory=list)
    max_turns: int = harness.MAX_TURNS
    # The MCP server that verifies drafted Claims (verify.py), or None for no verification.
    verify: str | None = None
    # Provenance (provenance.py). None means the Batch predates recording it.
    judge_prompt_sha: str | None = None
    ontology_version: str | None = None
    ontology_sha: str | None = None
    chips_sha: str | None = None
    code_commit: str | None = None
    code_dirty: bool | None = None
    summary_model: str | None = None
    # Settings this version doesn't know, from a Batch another branch wrote to the shared store.
    extra: dict = field(default_factory=dict)


_sha = provenance.sha


def _mean(xs):
    v = [x for x in xs if x is not None]
    return sum(v) / len(v) if v else None


def _spread(xs):
    v = [x for x in xs if x is not None]
    return statistics.stdev(v) if len(v) >= 2 else None


def _key(batch_id: str, name: str) -> str:
    return f"batches/{batch_id}/{name}"


def _load_jsonl(store, key: str) -> list[dict]:
    return parse_jsonl(store.get(key)) if store.exists(key) else []


def load_config(store, batch_id: str) -> BatchConfig:
    return config_from(json.loads(store.get(_key(batch_id, "batch.json"))))


def config_from(raw: dict) -> BatchConfig:
    """A BatchConfig from its JSON; settings this version doesn't know are kept in `extra`."""
    known = {f.name for f in fields(BatchConfig)}
    extra = {**raw.get("extra", {}), **{k: v for k, v in raw.items() if k not in known}}
    return BatchConfig(**{k: v for k, v in raw.items() if k in known and k != "extra"}, extra=extra)


def load_summary(store, batch_id: str) -> tuple[BatchConfig, dict | None]:
    """Just the configuration and summary: what a list of Batches needs."""
    key = _key(batch_id, "summary.json")
    return load_config(store, batch_id), json.loads(store.get(key)) if store.exists(key) else None


def load(store, batch_id: str) -> dict:
    """Everything a report, comparison, or regression gate needs from a stored Batch."""
    summary_key = _key(batch_id, "summary.json")
    return {
        "config": load_config(store, batch_id),
        "cases": _load_jsonl(store, _key(batch_id, "cases.jsonl")),
        "results": _load_jsonl(store, _key(batch_id, "results.jsonl")),
        "captions": _load_jsonl(store, _key(batch_id, "captions.jsonl")),
        "retrieval": _load_jsonl(store, _key(batch_id, "retrieval.jsonl")),
        "summary": json.loads(store.get(summary_key)) if store.exists(summary_key) else None,
    }


# ── Running ─────────────────────────────────────────────────────────────────────────────


def _classify(e: Exception) -> str:
    if isinstance(e, ClientError) and e.response["Error"]["Code"] in EXPIRED:
        raise CredentialsExpired(str(e)) from e
    return SANDBOX_FAILURE


def _run_one(
    client, cfg: BatchConfig, prompt: str, case: dict, repeat: int, store, toolbox=None,
    verifier=None, chip_shas: dict[str, str] | None = None,
):  # fmt: skip
    """One Run: caption the Case's Chip, then score it. Returns (result, caption).

    Every model call is recorded in the Run's Trace, which is written whatever the outcome,
    including when expired credentials stop the Batch mid-Run. A Chip whose image no longer
    matches the one hashed when the Batch started is a Sandbox Failure: scoring it would score
    a different input under the same name.
    """
    chip = case["chips"][0]
    run_id = f"{case['id']}#{repeat}"
    base = {"run_id": run_id, "case_id": case["id"], "repeat": repeat}
    # The Harness gets the Chip id and image only, read from chips/ and never from cases/
    # (ADR-0006).
    if not chip["uri"].startswith("chips/"):
        raise ValueError(f"Chip uri must be a chips/ key: {chip['uri']}")
    png = store.get(chip["uri"])
    expected = (chip_shas or {}).get(chip["uri"])
    if expected and hashlib.sha256(png).hexdigest() != expected:
        error = f"{chip['uri']} changed since the Batch started (SHA-256 no longer matches)"
        return {**base, "status": SANDBOX_FAILURE, "error": error}, None
    tracer = Tracer(
        RunInfo(run_id=run_id, task="caption", case_id=case["id"], repeat=repeat,
                batch_id=cfg.batch_id, model_id=cfg.caption_model, prompt_sha=cfg.prompt_sha,
                tools=[], metadata={"chip_id": chip["id"], "chip_sha256": expected,
                          "judge_model": cfg.judge_model}),
        [StoreSink(store), SummarySink(store)],
    )  # fmt: skip
    try:
        try:
            # The verifier, not the model, gets the Chip's footprint (ADR-0009).
            footprint = {"bbox": chip["bbox"], "date": chip.get("date")} if verifier else None
            cap, step = harness.caption(
                client, cfg.caption_model, chip["id"], png, prompt, tracer, chip["uri"],
                toolbox, cfg.max_turns, verifier, footprint,
            )  # fmt: skip
        except harness.HarnessFault as e:
            empty = {"text": "", "objects": [], "relations": [], "uncertain": []}
            result = {
                **base, "status": HARNESS_FAULT, "error": str(e),
                "grounding": {
                    **grounding(empty, case["reference_labels"]),
                    "correctness": 0.0,
                    "coverage": 0.0 if case["reference_labels"] else None,
                },
                "fidelity": {"score": 0.0, "issues": ["no Caption"]} if cfg.judge_model else None,
                "seconds_to_caption": e.step["seconds"],
                "caption_tokens": e.step["usage"].get("totalTokens"),
            }  # fmt: skip
            result["faults"] = tracer.finish(HARNESS_FAULT, None, str(e))
            result["workflow"] = workflow_score(tracer.run, tracer.steps)
            return result, {**base, **empty}
        except (ClientError, BotoCoreError) as e:
            status = _classify(e)
            faults = tracer.finish(status, None, str(e)[:500])
            return {**base, "status": status, "error": str(e)[:500], "faults": faults}, None

        cap = {**base, **cap}
        result = {
            **base, "status": OK, "error": None,
            "grounding": grounding(cap, case["reference_labels"]),
            "fidelity": None,
            "seconds_to_caption": step["seconds"],
            "caption_tokens": step["usage"].get("totalTokens"),
            "verification": step.get("verification"),
        }  # fmt: skip
        if cfg.judge_model:
            try:
                verdict, _ = fidelity(client, cfg.judge_model, cap, png, tracer, chip["uri"])
                result["fidelity"] = verdict
            except (ClientError, BotoCoreError, RuntimeError) as e:
                if isinstance(e, ClientError | BotoCoreError):
                    _classify(e)
                # A Judge that fails leaves the Run without a valid fidelity score.
                faults = tracer.finish(SANDBOX_FAILURE, cap["text"], f"judge: {e}"[:500])
                failed = {**base, "status": SANDBOX_FAILURE, "error": f"judge: {e}"[:500]}
                return {**failed, "faults": faults}, cap
        result["faults"] = tracer.finish(OK, cap["text"])
        result["workflow"] = workflow_score(tracer.run, tracer.steps)
        return result, cap
    except CredentialsExpired as e:
        tracer.finish("stopped", None, f"credentials expired: {e}"[:500])
        raise


def start(
    cases: list[dict],
    settings: Settings,
    store,
    repeats: int,
    label: str,
    region: str,
    prompt: str = harness.PROMPT,
    prompt_source: str = "built-in",
    judge: bool = True,
    progress=print,
    narrate: bool = True,
    tools: list[str] | None = None,
    verify: str | None = None,
) -> str:
    """Create a Batch and run it. Returns the Batch id."""
    batch_id = create(
        cases, settings, store, repeats, label, region, prompt, prompt_source, judge, tools,
        verify,
    )  # fmt: skip
    resume(batch_id, settings, store, progress, narrate)
    return batch_id


def create(
    cases: list[dict],
    settings: Settings,
    store,
    repeats: int,
    label: str,
    region: str,
    prompt: str = harness.PROMPT,
    prompt_source: str = "built-in",
    judge: bool = True,
    tools: list[str] | None = None,
    verify: str | None = None,
) -> str:
    """Write a new Batch's configuration, prompt, and frozen Cases. Returns the Batch id."""
    # Labels become part of store keys, so only letters, digits, dashes and underscores.
    label = re.sub(r"[^A-Za-z0-9_-]+", "-", label).strip("-")[:40]
    batch_id = (
        datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        + f"-{uuid4().hex}"
        + (f"-{label}" if label else "")
    )
    frozen = to_jsonl(cases)
    judge_prompt = provenance.judge_prompt().encode()
    chips = (json.dumps(provenance.chip_manifest(store, cases), indent=2) + "\n").encode()
    onto_version, onto_sha = provenance.ontology_version()
    commit, dirty = provenance.code_version()
    from clayzer.narrate import summary_model

    cfg = BatchConfig(
        batch_id=batch_id,
        label=label,
        created=datetime.now(UTC).isoformat(timespec="seconds"),
        region=region,
        repeats=repeats,
        case_ids=[c["id"] for c in cases],
        cases_sha=_sha(frozen),
        caption_model=settings.caption_model,
        judge_model=settings.judge_model if judge else None,
        embed_model=settings.embed_model,
        prompt_sha=_sha(prompt.encode()),
        prompt_source=prompt_source,
        tools=list(tools or []),
        verify=verify,
        judge_prompt_sha=_sha(judge_prompt) if judge else None,
        ontology_version=onto_version,
        ontology_sha=onto_sha,
        chips_sha=_sha(chips),
        code_commit=commit,
        code_dirty=dirty,
        summary_model=summary_model(),
    )
    store.put(
        _key(batch_id, "batch.json"), (json.dumps(asdict(cfg), indent=2) + "\n").encode(), JSON
    )
    store.put(_key(batch_id, "prompt.txt"), prompt.encode(), "text/plain")
    store.put(_key(batch_id, "cases.jsonl"), frozen, NDJSON)
    store.put(_key(batch_id, "chips.json"), chips, JSON)
    if judge:
        store.put(_key(batch_id, "judge-prompt.txt"), judge_prompt, "text/plain")
    return batch_id


def resume(batch_id: str, settings: Settings, store, progress=print, narrate: bool = True) -> dict:
    """Run every Run the Batch doesn't have a final outcome for, then summarize. With `narrate`,
    a model writes a readable summary of each Run's Trace, saved for replay (narrate.py)."""
    b = load(store, batch_id)
    cfg, cases = b["config"], b["cases"]
    prompt = store.get(_key(batch_id, "prompt.txt")).decode()
    chips_key = _key(batch_id, "chips.json")
    chip_shas = json.loads(store.get(chips_key)) if store.exists(chips_key) else None
    if cfg.judge_prompt_sha and _sha(provenance.judge_prompt().encode()) != cfg.judge_prompt_sha:
        # Finishing with a different rubric would mix two Judges in one Batch.
        raise ValueError(f"the Judge's rubric changed since {batch_id} started; start a new Batch")
    client = bedrock(settings)  # models come from the Batch's own config, not the settings
    watch_retries(client)
    done = {(r["case_id"], r["repeat"]) for r in b["results"] if r["status"] != SANDBOX_FAILURE}
    results = [r for r in b["results"] if r["status"] != SANDBOX_FAILURE]
    captions = [c for c in b["captions"] if (c["case_id"], c["repeat"]) in done]

    todo = [(c, r) for r in range(1, cfg.repeats + 1) for c in cases if (c["id"], r) not in done]
    stopped = None
    # MCP servers start once per Batch, and only if a Run is left to do. The model is offered
    # only its own servers' tools; the verifier's stay out of its prompt.
    servers = list(dict.fromkeys(cfg.tools + ([cfg.verify] if cfg.verify else [])))
    if servers and todo:
        from clayzer.tools import Toolbox

        tools = Toolbox.named(servers)
    else:
        tools = nullcontext()
    with tools as box:
        model_tools = box.view(cfg.tools) if box is not None and cfg.tools else None
        verifier = box.view([cfg.verify]) if box is not None and cfg.verify else None
        for i, (case, repeat) in enumerate(todo, 1):
            try:
                result, cap = _run_one(
                    client, cfg, prompt, case, repeat, store,
                    toolbox=model_tools, verifier=verifier, chip_shas=chip_shas,
                )  # fmt: skip
            except CredentialsExpired as e:
                stopped = f"credentials expired after {i - 1} of {len(todo)} Runs: {e}"[:300]
                break
            results.append(result)
            if cap is not None and result["status"] != SANDBOX_FAILURE:
                captions.append(cap)
            progress(f"  [{i}/{len(todo)}] {result['run_id']}: {_one_line(result)}")
            store.put(_key(batch_id, "results.jsonl"), to_jsonl(results), NDJSON)
            store.put(_key(batch_id, "captions.jsonl"), to_jsonl(captions), NDJSON)

    retr = [] if stopped else _retrieval(client, cfg, cases, captions)
    if narrate and not stopped:
        from clayzer.narrate import narrate_batch

        narrate_batch(client, store, batch_id, results, progress=progress)
    store.put(_key(batch_id, "retrieval.jsonl"), to_jsonl(retr), NDJSON)
    summary = summarize(cfg, cases, results, retr)
    summary["stopped"] = stopped
    store.put(_key(batch_id, "summary.json"), (json.dumps(summary, indent=2) + "\n").encode(), JSON)
    write_reports(store, batch_id)
    return summary


def _one_line(r: dict) -> str:
    if r["status"] == SANDBOX_FAILURE:
        return f"Sandbox Failure ({(r['error'] or '')[:80]})"
    g = r["grounding"]
    f = (r.get("fidelity") or {}).get("score")
    tag = "Harness Fault, " if r["status"] == HARNESS_FAULT else ""

    def n(x):
        return "—" if x is None else f"{x:.2f}"

    return f"{tag}correctness {n(g['correctness'])}, coverage {n(g['coverage'])}" + (
        f", fidelity {f:.2f}" if f is not None else ""
    )


def _retrieval(client, cfg: BatchConfig, cases: list[dict], captions: list[dict]) -> list[dict]:
    """Retrieval over each Repeat's Captions: one corpus per Repeat, like one captioning pass."""
    labels = {c["id"]: {lb["object"] for lb in c["reference_labels"]} for c in cases}
    rows = []
    for repeat in range(1, cfg.repeats + 1):
        docs = [
            {"case_id": c["case_id"], "text": c["text"], "objects": labels[c["case_id"]]}
            for c in captions
            if c["repeat"] == repeat and c["text"]
        ]
        if len(docs) > 1:
            rows.append({"repeat": repeat, **retrieval(client, cfg.embed_model, docs)})
    return rows


# ── Summarizing ─────────────────────────────────────────────────────────────────────────

COMPONENTS = ("precision", "recall", "count", "position", "attributes", "relations")


def summarize(cfg: BatchConfig, cases: list[dict], results: list[dict], retr: list[dict]) -> dict:
    by_case: dict[str, list[dict]] = {c["id"]: [] for c in cases}
    for r in results:
        by_case.setdefault(r["case_id"], []).append(r)

    per_case = {}
    for case in cases:
        rows = by_case[case["id"]]
        scored = [r for r in rows if r["status"] != SANDBOX_FAILURE]
        corr = [r["grounding"]["correctness"] for r in scored]
        wf = [(r.get("workflow") or {}).get("score") for r in scored]
        cov = [r["grounding"]["coverage"] for r in scored]
        f = [(r.get("fidelity") or {}).get("score") for r in scored]
        per_case[case["id"]] = {
            "runs": len(scored),
            "harness_faults": sum(r["status"] == HARNESS_FAULT for r in rows),
            "sandbox_failures": sum(r["status"] == SANDBOX_FAILURE for r in rows),
            "correctness": {"mean": _mean(corr), "spread": _spread(corr)},
            # How the Harness worked, from its Traces (REQ-06); None for Runs from before Traces.
            "workflow": {"mean": _mean(wf), "spread": _spread(wf)},
            "coverage": {"mean": _mean(cov), "spread": _spread(cov)},
            "fidelity": {"mean": _mean(f), "spread": _spread(f)},
            "components": {k: _mean(r["grounding"][k] for r in scored) for k in COMPONENTS},
            "unscored_share": _mean(r["grounding"]["unscored_share"] for r in scored),
        }

    scored = [r for r in results if r["status"] != SANDBOX_FAILURE]
    mrr = [row["mrr"] for row in retr if row["mrr"] is not None]
    # The rubric's measure: how often the right Caption is the top result for a query.
    top1 = [row["recall@1"] for row in retr if row.get("recall@1") is not None]
    prep = [c.get("prep_seconds") for c in cases if c.get("prep_seconds") is not None]
    return {
        "batch_id": cfg.batch_id,
        "cases": per_case,
        "batch": {
            "correctness": _mean(c["correctness"]["mean"] for c in per_case.values()),
            "workflow": _mean(c["workflow"]["mean"] for c in per_case.values()),
            "coverage": _mean(c["coverage"]["mean"] for c in per_case.values()),
            "fidelity": _mean(c["fidelity"]["mean"] for c in per_case.values()),
            "retrieval_mrr": {"mean": _mean(mrr), "spread": _spread(mrr)},
            "retrieval_recall_at_1": {"mean": _mean(top1), "spread": _spread(top1)},
            "unscored_share": _mean(c["unscored_share"] for c in per_case.values()),
            "label_prep_seconds": sum(c.get("prep_seconds") or 0 for c in cases),
            "label_prep_seconds_per_case": _mean(prep),
            # Cost is partial on Bedrock: time to output and tokens, no GPU time (CAP-12).
            "seconds_per_caption": _mean(r.get("seconds_to_caption") for r in scored),
            "tokens_per_caption": _mean(r.get("caption_tokens") for r in scored),
            "runs": {
                "planned": len(cases) * cfg.repeats,
                "ok": sum(r["status"] == OK for r in results),
                "harness_faults": sum(r["status"] == HARNESS_FAULT for r in results),
                "sandbox_failures": sum(r["status"] == SANDBOX_FAILURE for r in results),
            },
            # Failed Steps by who's to blame (ADR-0003), over every Run including failed ones.
            "step_faults": {
                k: sum((r.get("faults") or {}).get(k, 0) for r in results)
                for k in ("harness", "environment", "sandbox", "soft")
            },
        },
    }


def rescore(batch_id: str, store) -> dict:
    """Score a Batch's stored Captions again with the current scorer, without calling any model.

    Grounding is recomputed against the Batch's frozen Cases, and the Workflow Score from each
    Run's stored Trace (Runs from before Traces get none); fidelity and retrieval are kept (they
    don't depend on the scorers). Harness Faults stay scored as 0.
    """
    from dataclasses import replace

    from clayzer.trace import loads, trace_key

    b = load(store, batch_id)
    labels = {c["id"]: c["reference_labels"] for c in b["cases"]}
    captions = {(c["case_id"], c["repeat"]): c for c in b["captions"]}
    for r in b["results"]:
        cap = captions.get((r["case_id"], r["repeat"]))
        if r["status"] == OK and cap is not None:
            r["grounding"] = grounding(cap, labels[r["case_id"]])
        elif r["status"] == HARNESS_FAULT:
            empty = {"text": "", "objects": [], "relations": [], "uncertain": []}
            r["grounding"] = {
                **grounding(empty, labels[r["case_id"]]),
                "correctness": 0.0,
                "coverage": 0.0 if labels[r["case_id"]] else None,
            }
        tkey = trace_key(batch_id, r["case_id"], r["repeat"])
        if r["status"] in (OK, HARNESS_FAULT) and store.exists(tkey):
            r["workflow"] = workflow_score(*loads(store.get(tkey)))
    cfg = replace(b["config"], scorer_version=SCORER_VERSION)
    store.put(
        _key(batch_id, "batch.json"), (json.dumps(asdict(cfg), indent=2) + "\n").encode(), JSON
    )
    store.put(_key(batch_id, "results.jsonl"), to_jsonl(b["results"]), NDJSON)
    summary = summarize(cfg, b["cases"], b["results"], b["retrieval"])
    summary["stopped"] = (b["summary"] or {}).get("stopped")
    summary["rescored"] = datetime.now(UTC).isoformat(timespec="seconds")
    store.put(_key(batch_id, "summary.json"), (json.dumps(summary, indent=2) + "\n").encode(), JSON)
    write_reports(store, batch_id)
    return summary


def load_summaries(store, batch_id: str, results: list[dict]) -> dict:
    """Each Run's Trace summary, keyed by (case id, repeat); Runs without one are left out."""
    from clayzer.summarize import summary_key

    out = {}
    for r in results:
        key = summary_key(batch_id, r["case_id"], r["repeat"])
        if store.exists(key):
            out[(r["case_id"], r["repeat"])] = json.loads(store.get(key))
    return out


def load_narratives(store, batch_id: str, results: list[dict]) -> dict:
    """Each Run's saved model-written narrative, keyed by (case id, repeat)."""
    from clayzer.narrate import narrative_key

    out = {}
    for r in results:
        key = narrative_key(batch_id, r["case_id"], r["repeat"])
        if store.exists(key):
            out[(r["case_id"], r["repeat"])] = json.loads(store.get(key))
    return out


def resummarize(batch_id: str, store) -> int:
    """Rebuild every Run's summary from its recorded Trace, with no model or network beyond the
    store. Returns how many were written."""
    from clayzer.summarize import SummarySink
    from clayzer.trace import loads, trace_key

    sink, n = SummarySink(store), 0
    for r in _load_jsonl(store, _key(batch_id, "results.jsonl")):
        key = trace_key(batch_id, r["case_id"], r["repeat"])
        if store.exists(key):
            sink.write(*loads(store.get(key)))
            n += 1
    write_reports(store, batch_id)
    return n


def write_reports(store, batch_id: str) -> None:
    from clayzer.report import render
    from clayzer.report_html import render_html

    b = load(store, batch_id)
    b["summaries"] = load_summaries(store, batch_id, b["results"])
    b["narratives"] = load_narratives(store, batch_id, b["results"])
    store.put(_key(batch_id, "report.md"), render(b).encode(), "text/markdown")
    html = render_html(b, store).encode()
    store.put(_key(batch_id, "report.html"), html, "text/html; charset=utf-8")
    from clayzer.run_report import write_run_reports

    write_run_reports(store, b)


def list_batches(store) -> list[str]:
    return sorted(store.list_dirs("batches/"))
