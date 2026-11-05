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
import time
from contextlib import nullcontext
from dataclasses import asdict, dataclass, field, fields, replace
from datetime import UTC, datetime
from uuid import uuid4

from botocore.exceptions import BotoCoreError, ClientError

from clayzer import harness, lgnd, provenance, verifiers
from clayzer.agentcore.contract import ContractError
from clayzer.cases import parse_jsonl, to_jsonl
from clayzer.config import Settings, bedrock
from clayzer.cost import per, run_cost, verified_claims
from clayzer.faults import HARNESS_CODES
from clayzer.grounding import grounding
from clayzer.harness import CHANGE_PROMPT
from clayzer.judge import fidelity, self_judging
from clayzer.output_score import VERSION, grounding_by_class, preparation, score_caption
from clayzer.retrieval import freeze_queries, retrieval
from clayzer.summarize import SummarySink
from clayzer.tools import servers_named
from clayzer.trace import RunInfo, StoreSink, Tracer, watch_retries
from clayzer.workflow import score as workflow_score

# Bump when grounding or summary logic changes, so the regression gate warns that scores from
# before and after aren't comparable.
SCORER_VERSION = VERSION + "+workflow-1"  # correctness and coverage; the Workflow Score

HARNESSES = ("local", "agentcore")
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
    # Where the Harness runs: "local" (this process) or "agentcore" (an AgentCore Runtime, whose
    # ARN is `runtime`). Tools and verification then run inside the runtime.
    harness: str = "local"
    runtime: str | None = None
    runtime_build: str | None = None  # which build of the Runtime image answered (first Run)
    # The MCP servers used (ADR-0006): each one's pin when the Batch was created, and what each
    # reported on connecting (remote servers can't be pinned). None: not recorded yet.
    tool_servers: dict = field(default_factory=dict)
    tool_versions: dict | None = None
    # Feed the captioner class-level ontology guidance (ADR-0010): look-alikes, exemplars, and,
    # where prototypes and a Chip embedding exist, an embedding-nearest-class hint. Default off,
    # so cost and behaviour are unchanged until a Batch opts in.
    ontology_context: bool = False
    # Provenance (provenance.py). None means the Batch predates recording it.
    judge_prompt_sha: str | None = None
    # The change prompt's hash, set only when the Batch has a Change Case (harness.CHANGE_PROMPT).
    change_prompt_sha: str | None = None
    ontology_version: str | None = None
    ontology_sha: str | None = None
    chips_sha: str | None = None
    retrieval_queries_sha: str | None = None
    code_commit: str | None = None
    code_dirty: bool | None = None
    summary_model: str | None = None
    # A hash of ontology/verifiers.toml, the route each class's Claims are verified by; None
    # without verification.
    verifiers_sha: str | None = None
    # A replayed Batch: the recorded Batch whose Captions it rescored (replay), else None.
    replayed_from: str | None = None
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


def _ontology_context(cfg: BatchConfig, chip: dict) -> str | None:
    """Class-level ontology guidance for one Chip (ADR-0010), or None when there's nothing to add.

    Layer C exemplars always apply. Layer A look-alikes are MEASURED from the prototype file when
    one exists for this ontology version (data-driven), else hand-curated. Layer B's nearest-class
    hint applies only when the prototype file exists AND the Chip carries a Clay/LGND `embedding`.
    The prototype file is read once per Batch (prototypes.load_local is cached); no model call."""
    from clayzer import prototypes as proto
    from clayzer.ontology import load

    ont = load()
    protos = None
    # Load prototypes whenever the file exists, not only when this Chip has an embedding: the
    # learned look-alikes (Layer A) don't need a per-Chip embedding, only the Chip's does (Layer B).
    if cfg.ontology_version:
        path = proto.default_path(cfg.ontology_version)
        if path.exists():
            protos = proto.load_local(str(path))
    context = proto.caption_context(ont, protos, chip.get("embedding"), scoring_region=cfg.region)
    return context or None


def _harness_fault(base: dict, case: dict, cfg: BatchConfig, tracer, error: str, step: dict):
    """A Run whose Harness produced no usable Caption: scored 0, since it's the fault of the
    system under test (module docstring)."""
    empty = {"text": "", "objects": [], "relations": [], "uncertain": []}
    result = {
        **base, "status": HARNESS_FAULT, "error": error,
        "grounding": {
            **grounding(empty, case["reference_labels"]),
            "correctness": 0.0,
            "coverage": 0.0 if case["reference_labels"] else None,
        },
        "fidelity": {"score": 0.0, "issues": ["no Caption"]} if cfg.judge_model else None,
        "seconds_to_caption": step.get("seconds"),
        "caption_tokens": (step.get("usage") or {}).get("totalTokens"),
    }  # fmt: skip
    result["faults"] = tracer.finish(HARNESS_FAULT, None, error)
    result["workflow"] = workflow_score(tracer.run, tracer.steps)
    result["cost"], result["verified_claims"] = run_cost(tracer.steps), 0
    return result, {**base, **empty}


def _run_one(
    client, cfg: BatchConfig, prompt: str, case: dict, repeat: int, store, toolbox=None,
    verifier=None, chip_shas: dict[str, str] | None = None, remote=None,
):  # fmt: skip
    """One Run: caption the Case's Chip, then score it. Returns (result, caption).

    Every model call is recorded in the Run's Trace, which is written whatever the outcome,
    including when expired credentials stop the Batch mid-Run. A Chip whose image no longer
    matches the one hashed when the Batch started is a Sandbox Failure: scoring it would score
    a different input under the same name.
    """
    chips = case["chips"]
    chip = chips[0]
    # A Change Case's Chip Pair (earlier first) goes to the Harness and the Judge as a list.
    pair = case.get("kind") == "change"
    run_id = f"{case['id']}#{repeat}"
    base = {"run_id": run_id, "case_id": case["id"], "repeat": repeat}
    # The Harness gets the Chip id and image only, read from chips/ and never from cases/
    # (ADR-0006).
    pngs, shas = [], []
    for c in chips:
        if not c["uri"].startswith("chips/"):
            raise ValueError(f"Chip uri must be a chips/ key: {c['uri']}")
        pngs.append(store.get(c["uri"]))
        shas.append((chip_shas or {}).get(c["uri"]))
        if shas[-1] and hashlib.sha256(pngs[-1]).hexdigest() != shas[-1]:
            error = f"{c['uri']} changed since the Batch started (SHA-256 no longer matches)"
            return {**base, "status": SANDBOX_FAILURE, "error": error}, None
    png = pngs if pair else pngs[0]
    uri = [c["uri"] for c in chips] if pair else chip["uri"]
    prompt_sha = cfg.prompt_sha
    if pair:
        # The Batch's prompt is for one Chip; a Chip Pair gets the change prompt, and its Trace
        # records that prompt's hash, not the Batch's.
        prompt, prompt_sha = harness.CHANGE_PROMPT, cfg.change_prompt_sha
    tracer = Tracer(
        RunInfo(run_id=run_id, task="caption", case_id=case["id"], repeat=repeat,
                batch_id=cfg.batch_id, model_id=cfg.caption_model, prompt_sha=prompt_sha,
                tools=[], metadata={"chip_id": [c["id"] for c in chips] if pair else chip["id"],
                          "chip_sha256": shas if pair else shas[0],
                          "judge_model": cfg.judge_model}),
        [StoreSink(store), SummarySink(store)],
    )  # fmt: skip
    try:
        try:
            # Only verification code gets the footprint; Change Cases are not verified.
            verifier = None if pair else verifier
            verifies = not pair and (verifier is not None or (remote is not None and cfg.verify))
            footprint = {"bbox": chip["bbox"], "date": chip.get("date")} if verifies else None
            onto_ctx = _ontology_context(cfg, chip) if cfg.ontology_context else None
            caption_started = time.monotonic()
            if remote is not None:
                remote_chip = {**chip, "uri": uri}
                # Context is already rendered; escape braces for the Runtime template pass.
                remote_prompt = prompt
                if onto_ctx:
                    remote_prompt += "\n" + onto_ctx.replace("{", "{{").replace("}", "}}")
                cap, step = remote.caption(cfg, remote_chip, png, remote_prompt, tracer, footprint)
            else:
                cap, step = harness.caption(
                    client,
                    cfg.caption_model,
                    chip["id"],
                    png,
                    prompt,
                    tracer,
                    uri,
                    toolbox,
                    cfg.max_turns,
                    verifier,
                    footprint,
                    onto_ctx,
                )
            step["seconds"] = round(time.monotonic() - caption_started, 2)
        except harness.HarnessFault as e:
            return _harness_fault(base, case, cfg, tracer, str(e), e.step)
        except (ClientError, BotoCoreError) as e:
            status = _classify(e)
            # A request the captioner's model rejected or answered malformed is the system under
            # test failing, as faults.py attributes it (ADR-0003): scored 0, not retried.
            code = e.response["Error"]["Code"] if isinstance(e, ClientError) else None
            if code in HARNESS_CODES:
                return _harness_fault(base, case, cfg, tracer, str(e)[:500], {})
            faults = tracer.finish(status, None, str(e)[:500])
            return {**base, "status": status, "error": str(e)[:500], "faults": faults}, None

        cap = {**base, **cap}
        output = score_caption(
            cap,
            case,
            judge_model=cfg.judge_model,
            generator=cfg.caption_model,
            seconds=step["seconds"],
            tokens=step["usage"].get("totalTokens"),
        )
        result = {
            **base, "status": OK, "error": None,
            **output,
            "seconds_to_caption": step["seconds"],
            "caption_tokens": step["usage"].get("totalTokens"),
            "verification": step.get("verification"),
        }  # fmt: skip
        if cfg.judge_model:
            try:
                result.update(
                    score_caption(
                        cap,
                        case,
                        client=client,
                        judge_model=cfg.judge_model,
                        generator=cfg.caption_model,
                        png=png,
                        tracer=tracer,
                        image_key=uri,
                        seconds=step["seconds"],
                        tokens=step["usage"].get("totalTokens"),
                        judge_fn=fidelity,
                    )
                )
            except (ClientError, BotoCoreError, RuntimeError) as e:
                if isinstance(e, ClientError | BotoCoreError):
                    _classify(e)
                # A Judge that fails leaves the Run without a valid fidelity score.
                faults = tracer.finish(SANDBOX_FAILURE, cap["text"], f"judge: {e}"[:500])
                failed = {**base, "status": SANDBOX_FAILURE, "error": f"judge: {e}"[:500]}
                return {**failed, "faults": faults}, cap
        result["faults"] = tracer.finish(OK, cap["text"])
        result["workflow"] = workflow_score(tracer.run, tracer.steps)
        result["cost"] = run_cost(tracer.steps)
        result["verified_claims"] = verified_claims(result["grounding"])
        return result, cap
    except ContractError as e:
        tracer.finish("stopped", None, f"AgentCore contract mismatch: {e}"[:500])
        raise
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
    ontology_context: bool = False,
    harness: str = "local",
    runtime: str | None = None,
) -> str:
    """Create a Batch and run it. Returns the Batch id."""
    batch_id = create(
        cases, settings, store, repeats, label, region, prompt, prompt_source, judge, tools,
        verify, harness=harness, runtime=runtime, ontology_context=ontology_context,
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
    ontology_context: bool = False,
    harness: str = "local",
    runtime: str | None = None,
) -> str:
    """Write a new Batch's configuration, prompt, and frozen Cases. Returns the Batch id.

    Refuses, before writing anything, a server the Harness may not use (ADR-0006): a forbidden
    one, or one that isn't registered. Records each server's pin in the configuration."""
    if harness not in HARNESSES:
        raise ValueError(f"unknown Harness {harness!r}; known: {', '.join(HARNESSES)}")
    if harness == "agentcore" and not runtime:
        raise ValueError("the agentcore Harness needs a Runtime ARN (CLAYZER_AGENTCORE_RUNTIME)")
    names = list(dict.fromkeys([*(tools or []), *([verify] if verify else [])]))
    servers = servers_named(names)
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
    queries = to_jsonl(
        freeze_queries(
            [
                {
                    "case_id": c["id"],
                    "objects": [
                        lb["object"] for lb in c["reference_labels"] if lb.get("count") != 0
                    ],
                }
                for c in cases
            ]
        )
    )
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
        harness=harness,
        runtime=runtime if harness == "agentcore" else None,
        tool_servers={s.name: s.pin() for s in servers},
        ontology_context=ontology_context,
        judge_prompt_sha=_sha(judge_prompt) if judge else None,
        change_prompt_sha=_sha(CHANGE_PROMPT.encode())
        if any(c.get("kind") == "change" for c in cases)
        else None,
        ontology_version=onto_version,
        ontology_sha=onto_sha,
        chips_sha=_sha(chips),
        retrieval_queries_sha=_sha(queries),
        code_commit=commit,
        code_dirty=dirty,
        summary_model=summary_model(),
        verifiers_sha=_sha(verifiers.DEFAULT.read_bytes()) if verify else None,
    )
    store.put(
        _key(batch_id, "batch.json"), (json.dumps(asdict(cfg), indent=2) + "\n").encode(), JSON
    )
    store.put(_key(batch_id, "prompt.txt"), prompt.encode(), "text/plain")
    store.put(_key(batch_id, "cases.jsonl"), frozen, NDJSON)
    store.put(_key(batch_id, "chips.json"), chips, JSON)
    store.put(_key(batch_id, "retrieval-queries.jsonl"), queries, NDJSON)
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
    query_key = _key(batch_id, "retrieval-queries.jsonl")
    query_body = store.get(query_key) if store.exists(query_key) else None
    if cfg.retrieval_queries_sha and (
        query_body is None or _sha(query_body) != cfg.retrieval_queries_sha
    ):
        raise ValueError("Frozen retrieval queries are missing or changed")
    queries = parse_jsonl(query_body) if query_body is not None else None
    if cfg.change_prompt_sha and _sha(harness.CHANGE_PROMPT.encode()) != cfg.change_prompt_sha:
        raise ValueError(f"the change prompt changed since {batch_id} started; start a new Batch")
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
    # On AgentCore the tools run inside the Runtime, so nothing is started here.
    remote = None
    if cfg.harness == "agentcore":
        from clayzer.agentcore.remote import RemoteHarness

        remote = RemoteHarness(cfg.runtime) if todo else None
        servers = []
    if servers and todo:
        from clayzer.tools import Toolbox

        tools = Toolbox.named(servers)
    else:
        tools = nullcontext()
    with tools as box:
        if box is not None:
            cfg = _record_tool_versions(store, cfg, dict(box.versions), progress)
        model_tools = box.view(cfg.tools) if box is not None and cfg.tools else None
        verifier = box.view([cfg.verify]) if box is not None and cfg.verify else None
        routes = verifiers.load()
        if verifier is not None and routes.uses_classifier():
            # Classifiers are saved per LGND account: build it once, before the first Run.
            # If that fails, classifier-routed Claims stay, unverified (verify.py).
            error = lgnd.ensure_classifier(verifier.call, routes.classifier, routes.examples)
            if error:
                progress(f"  the LGND classifier {routes.classifier} isn't available: {error}")
        for i, (case, repeat) in enumerate(todo, 1):
            try:
                result, cap = _run_one(
                    client, cfg, prompt, case, repeat, store,
                    toolbox=model_tools, verifier=verifier, chip_shas=chip_shas, remote=remote,
                )  # fmt: skip
            except CredentialsExpired as e:
                stopped = f"credentials expired after {i - 1} of {len(todo)} Runs: {e}"[:300]
                break
            except ContractError as e:
                stopped = f"AgentCore contract mismatch after {i - 1} of {len(todo)} Runs: {e}"[
                    :300
                ]
                break
            if remote is not None:
                cfg = _record_tool_versions(store, cfg, remote.versions, progress, remote.build)
            results.append(result)
            if cap is not None and result["status"] != SANDBOX_FAILURE:
                captions.append(cap)
            progress(f"  [{i}/{len(todo)}] {result['run_id']}: {_one_line(result)}")
            store.put(_key(batch_id, "results.jsonl"), to_jsonl(results), NDJSON)
            store.put(_key(batch_id, "captions.jsonl"), to_jsonl(captions), NDJSON)

    retr = [] if stopped else _retrieval(client, cfg, cases, captions, queries)
    if narrate and not stopped:
        from clayzer.narrate import narrate_batch

        narrate_batch(client, store, batch_id, results, progress=progress)
    store.put(_key(batch_id, "retrieval.jsonl"), to_jsonl(retr), NDJSON)
    summary = summarize(cfg, cases, results, retr)
    summary["stopped"] = stopped
    store.put(_key(batch_id, "summary.json"), (json.dumps(summary, indent=2) + "\n").encode(), JSON)
    write_reports(store, batch_id)
    return summary


def _record_tool_versions(
    store, cfg: BatchConfig, versions: dict, progress, runtime_build: str | None = None
) -> BatchConfig:
    """Save what each MCP server reported on connecting (and which build of the AgentCore
    Runtime image answered), the first time the Batch sees them.

    Remote servers like LGND Geo can't be pinned, so a change on their side would otherwise go
    unseen. If a resumed Batch finds a different one, say so and keep the first record."""
    changes = {}
    recorded = cfg.tool_versions or {}
    added = {name: version for name, version in versions.items() if name not in recorded}
    if added:
        changes["tool_versions"] = recorded | added
    changed = {name: version for name, version in versions.items()
               if name in recorded and recorded[name] != version}  # fmt: skip
    if changed:
        progress(f"  note: MCP servers report {changed}, not {recorded} as at the start")
    if runtime_build and cfg.runtime_build is None:
        changes["runtime_build"] = runtime_build
    elif runtime_build and cfg.runtime_build != runtime_build:
        progress(f"  note: the Runtime is build {runtime_build}, not {cfg.runtime_build}")
    if not changes:
        return cfg
    cfg = replace(cfg, **changes)
    store.put(
        _key(cfg.batch_id, "batch.json"), (json.dumps(asdict(cfg), indent=2) + "\n").encode(), JSON
    )
    return cfg


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


def _retrieval(
    client, cfg: BatchConfig, cases: list[dict], captions: list[dict], queries=None
) -> list[dict]:
    """Retrieval over each Repeat's Captions: one corpus per Repeat, like one captioning pass."""
    labels = {
        c["id"]: {lb["object"] for lb in c["reference_labels"] if lb.get("count") != 0}
        for c in cases
    }
    rows = []
    for repeat in range(1, cfg.repeats + 1):
        docs = [
            {"case_id": c["case_id"], "text": c["text"], "objects": labels[c["case_id"]]}
            for c in captions
            if c["repeat"] == repeat and c["text"]
        ]
        if len(docs) > 1:
            rows.append(
                {"repeat": repeat, **retrieval(client, cfg.embed_model, docs, queries=queries)}
            )
    return rows


# ── Summarizing ─────────────────────────────────────────────────────────────────────────

COMPONENTS = ("precision", "recall", "count", "position", "attributes", "relations")


def _lookalikes(cases: list[dict], results: list[dict]) -> dict | None:
    """Per look-alike kind (fixtures/caption-lookalike): in how many Runs a Caption claimed the
    thing the Case imitates, which grounding already marks a false positive. None without any."""
    by_id = {c["id"]: c for c in cases if c.get("lookalike")}
    if not by_id:
        return None
    kinds: dict[str, dict] = {}
    for r in results:
        case = by_id.get(r["case_id"])
        if case is None or r["status"] == SANDBOX_FAILURE:
            continue
        of = case["lookalike"]["of"]
        rows = (r.get("grounding") or {}).get("rows", [])
        fooled = any(x["verdict"] == "false positive" and x["claim"]["object"] == of for x in rows)
        k = kinds.setdefault(
            case["lookalike"]["kind"], {"of": of, "cases": set(), "runs": 0, "fooled": 0}
        )
        k["cases"].add(case["id"])
        k["runs"] += 1
        k["fooled"] += fooled
    return {name: {**k, "cases": len(k["cases"])} for name, k in sorted(kinds.items())}


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
    # Recall is fraction of relevant captions found, hit rate is whether any was found.
    top1 = [row["recall@1"] for row in retr if row.get("recall@1") is not None]
    hit1 = [row["hit@1"] for row in retr if row.get("hit@1") is not None]
    measurements = [preparation(c)["reference_preparation"] for c in cases]
    prep = [m["value"] for m in measurements if m.get("value") is not None]
    # Verified Claims per dollar and per GPU-second, over the Runs whose cost is known: Runs
    # from before Traces, or with an unpriced model, are left out of both sums (CAP-12).
    priced = [r for r in scored if (r.get("cost") or {}).get("usd") is not None]
    gpu = [r for r in scored if (r.get("cost") or {}).get("gpu_seconds")]
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
            "retrieval_hit_at_1": {"mean": _mean(hit1), "spread": _spread(hit1)},
            "unscored_share": _mean(c["unscored_share"] for c in per_case.values()),
            "label_prep_seconds": sum(prep) if prep else None,
            "label_prep_seconds_per_case": _mean(prep),
            "label_preparation": {
                "measurements": measurements,
                "observed_cases": len(prep),
                "total_cases": len(cases),
                "units": "seconds",
                "by_scope": {
                    scope: {
                        "observed_cases": sum(
                            m["scope"] == scope and m.get("value") is not None for m in measurements
                        ),
                        "sum_seconds": sum(
                            m["value"]
                            for m in measurements
                            if m["scope"] == scope and m.get("value") is not None
                        )
                        if any(
                            m["scope"] == scope and m.get("value") is not None for m in measurements
                        )
                        else None,
                    }
                    for scope in ("case_build", "reference_labels")
                },
                "scope": "case_build_or_explicit_reference_labels",
                "caption_generation_seconds": _mean(r.get("seconds_to_caption") for r in scored),
            },
            "cost": {
                "gpu_seconds": None,
                "gpu_count": None,
                "gpu_type": None,
                "status": "unavailable: hosted Bedrock does not expose GPU metrics",
            },
            "fidelity_kind": "model_opinion",
            "fidelity_self_judged": self_judging(cfg.caption_model, cfg.judge_model),
            "retrieval_warnings": sorted({w for row in retr for w in row.get("warnings", [])}),
            # Cost is partial on Bedrock: time to output and tokens, no GPU time (CAP-12).
            "seconds_per_caption": _mean(r.get("seconds_to_caption") for r in scored),
            "tokens_per_caption": _mean(r.get("caption_tokens") for r in scored),
            "usd_per_caption": _mean(r["cost"]["usd"] for r in priced),
            "verified_claims_per_caption": _mean(r.get("verified_claims") for r in scored),
            "verified_claims_per_dollar": per(
                sum(r["verified_claims"] for r in priced), sum(r["cost"]["usd"] for r in priced)
            ),
            "verified_claims_per_gpu_second": per(
                sum(r["verified_claims"] for r in gpu), sum(r["cost"]["gpu_seconds"] for r in gpu)
            ),
            "runs": {
                "planned": len(cases) * cfg.repeats,
                "ok": sum(r["status"] == OK for r in results),
                "harness_faults": sum(r["status"] == HARNESS_FAULT for r in results),
                "sandbox_failures": sum(r["status"] == SANDBOX_FAILURE for r in results),
            },
            # Look-alike negatives a Caption mistook for what they imitate; not a gated metric.
            "lookalikes": _lookalikes(cases, results),
            # Failed Steps by who's to blame (ADR-0003), over every Run including failed ones.
            "step_faults": {
                k: sum((r.get("faults") or {}).get(k, 0) for r in results)
                for k in ("harness", "environment", "sandbox", "soft")
            },
        },
    }


def _regrade(r: dict, cap: dict | None, labels: list[dict], trace: bytes | None) -> None:
    """Ground one scored Run again against labels, and take its Workflow Score and cost from its
    Trace (Runs from before Traces get none). Harness Faults stay scored as 0."""
    from clayzer.trace import loads

    if r["status"] == OK and cap is not None:
        r["grounding"] = grounding(cap, labels)
        if "grounding_by_class" in r:
            r["grounding_by_class"] = grounding_by_class(cap, labels)
    elif r["status"] == HARNESS_FAULT:
        empty = {"text": "", "objects": [], "relations": [], "uncertain": []}
        r["grounding"] = {
            **grounding(empty, labels),
            "correctness": 0.0,
            "coverage": 0.0 if labels else None,
        }
    if r["status"] in (OK, HARNESS_FAULT):
        r["verified_claims"] = verified_claims(r["grounding"])
        if trace is not None:
            run, steps = loads(trace)
            r["workflow"] = workflow_score(run, steps)
            r["cost"] = run_cost(steps)


def rescore(batch_id: str, store) -> dict:
    """Score a Batch's stored Captions again with the current scorer, without calling any model.

    Grounding and verified Claims are recomputed against the Batch's frozen Cases, and the
    Workflow Score and cost from each Run's stored Trace (Runs from before Traces get none);
    fidelity and retrieval are kept (they don't depend on the scorers), so the Judge's saved
    verdicts are reused, never requested again. Harness Faults stay scored as 0.
    """
    from dataclasses import replace

    from clayzer.trace import trace_key

    b = load(store, batch_id)
    labels = {c["id"]: c["reference_labels"] for c in b["cases"]}
    captions = {(c["case_id"], c["repeat"]): c for c in b["captions"]}
    for r in b["results"]:
        tkey = trace_key(batch_id, r["case_id"], r["repeat"])
        trace = store.get(tkey) if store.exists(tkey) else None
        _regrade(r, captions.get((r["case_id"], r["repeat"])), labels[r["case_id"]], trace)
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


def _rerank(rows: list[dict], cases: list[dict]) -> tuple[list[dict], list[str]]:
    """Retrieval rows rescored for new Reference Labels, offline. A stored row keeps each
    query's full ranking, which depends only on Caption text, so only relevance changes. A query
    that had nothing relevant before was never ranked; it's returned as not replayable."""
    from clayzer.retrieval import QUERIES

    labels = {
        c["id"]: {lb["object"] for lb in c["reference_labels"] if lb.get("count") != 0}
        for c in cases
    }
    out, missing = [], set()
    for row in rows:
        k = next((key for key in row if key.startswith("recall@")), "recall@1")
        n = int(k.split("@")[1])
        stored = {q["query"]: q for q in row["queries"]}
        docs = stored[next(iter(stored))]["ranked"] if stored else []
        queries = []
        for query, target in QUERIES.items():
            relevant = {cid for cid in docs if target in labels.get(cid, set())}
            if not relevant:
                continue
            if query not in stored:
                missing.add(query)
                continue
            ids = stored[query]["ranked"]
            first = next(i for i, cid in enumerate(ids) if cid in relevant)
            queries.append({"query": query, "relevant": sorted(relevant), "ranked": ids,
                            "reciprocal_rank": 1 / (first + 1),
                            k: len(relevant & set(ids[:n])) / len(relevant)})  # fmt: skip
        m = len(queries)
        out.append({"repeat": row["repeat"], "queries": queries,
                    "mrr": sum(q["reciprocal_rank"] for q in queries) / m if m else None,
                    k: sum(q[k] for q in queries) / m if m else None})  # fmt: skip
    return out, sorted(missing)


def replay(batch_id: str, store, cases: list[dict], label: str = "", reports: bool = True) -> str:
    """A new Batch from a recorded one, scored against `cases`: the same Cases and Chips with
    updated Reference Labels. No model, MCP server, credentials, or network beyond the store
    (REQ-09). Returns the new Batch's id.

    The Harness never sees Reference Labels (ADR-0006) and the Judge doesn't either, so the
    recorded Captions, Traces, fidelity verdicts, summaries, and narratives all stand. Grounding
    and the Workflow Score are recomputed, and retrieval is re-ranked from the stored rankings.
    Raises if the Cases or their Chips differ, or a retrieval query can't be replayed.
    """
    from dataclasses import replace

    from clayzer.narrate import narrative_key
    from clayzer.summarize import summary_key
    from clayzer.trace import trace_key

    b = load(store, batch_id)
    if b["config"].scorer_version != SCORER_VERSION:
        # Replay regrades grounding only; a Batch from another scorer lacks the current one's
        # other scores, so stamping it with this scorer version would misreport it.
        raise ValueError(
            f"{batch_id} was scored by {b['config'].scorer_version}, not {SCORER_VERSION}; "
            "run a new Batch instead"
        )
    old = {c["id"]: c for c in b["cases"]}
    new = {c["id"]: c for c in cases}
    if set(old) != set(new):
        raise ValueError(f"replay needs the same Cases: {sorted(set(old) ^ set(new))[:5]} differ")
    for cid, c in new.items():
        if [x["uri"] for x in c["chips"]] != [x["uri"] for x in old[cid]["chips"]]:
            raise ValueError(f"{cid}'s Chips differ from the recorded Batch's")
    retr, missing = _rerank(b["retrieval"], cases)
    if missing:
        raise ValueError(f"can't replay retrieval for {missing}: nothing was relevant before")

    label = re.sub(r"[^A-Za-z0-9_-]+", "-", label).strip("-")[:40]
    new_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + (f"-{label}" if label else "")
    frozen = to_jsonl(cases)
    cfg = replace(b["config"], batch_id=new_id, label=label, scorer_version=SCORER_VERSION,
                  created=datetime.now(UTC).isoformat(timespec="seconds"),
                  cases_sha=_sha(frozen), replayed_from=batch_id)  # fmt: skip
    captions = {(c["case_id"], c["repeat"]): c for c in b["captions"]}
    results = []
    for r in b["results"]:
        r = dict(r)
        labels, cap = (
            new[r["case_id"]]["reference_labels"],
            captions.get((r["case_id"], r["repeat"])),
        )
        tkey = trace_key(batch_id, r["case_id"], r["repeat"])
        trace = store.get(tkey) if store.exists(tkey) else None
        if trace is not None:
            store.put(trace_key(new_id, r["case_id"], r["repeat"]), trace, NDJSON)
        _regrade(r, cap, labels, trace)
        for key in (summary_key, narrative_key):
            src = key(batch_id, r["case_id"], r["repeat"])
            if store.exists(src):
                store.put(key(new_id, r["case_id"], r["repeat"]), store.get(src), JSON)
        results.append(r)

    store.put(_key(new_id, "batch.json"), (json.dumps(asdict(cfg), indent=2) + "\n").encode(), JSON)
    store.put(_key(new_id, "cases.jsonl"), frozen, NDJSON)
    for name in ("prompt.txt", "judge-prompt.txt", "chips.json"):
        if store.exists(_key(batch_id, name)):
            store.put(_key(new_id, name), store.get(_key(batch_id, name)))
    store.put(_key(new_id, "results.jsonl"), to_jsonl(results), NDJSON)
    store.put(_key(new_id, "captions.jsonl"), to_jsonl(b["captions"]), NDJSON)
    store.put(_key(new_id, "retrieval.jsonl"), to_jsonl(retr), NDJSON)
    summary = summarize(cfg, cases, results, retr)
    summary["stopped"] = (b["summary"] or {}).get("stopped")
    summary["replayed_from"] = batch_id
    store.put(_key(new_id, "summary.json"), (json.dumps(summary, indent=2) + "\n").encode(), JSON)
    if reports:
        write_reports(store, new_id)
    return new_id


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
    from clayzer.report_safety import redact

    b = load(store, batch_id)
    b["summaries"] = load_summaries(store, batch_id, b["results"])
    b["narratives"] = load_narratives(store, batch_id, b["results"])
    store.put(_key(batch_id, "report.md"), redact(render(b)).encode(), "text/markdown")
    html = redact(render_html(b, store)).encode()
    store.put(_key(batch_id, "report.html"), html, "text/html; charset=utf-8")
    from clayzer.run_report import write_run_reports

    write_run_reports(store, b)


def list_batches(store) -> list[str]:
    # Interrupted creation and older standalone AgentCore Runs are not scored Batches.
    from concurrent.futures import ThreadPoolExecutor

    names = sorted(store.list_dirs("batches/"))
    with ThreadPoolExecutor(max_workers=8) as pool:
        present = pool.map(lambda name: store.exists(_key(name, "batch.json")), names)
        return [name for name, exists in zip(names, present, strict=True) if exists]
