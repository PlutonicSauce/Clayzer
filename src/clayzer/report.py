"""The Markdown report for a Batch. Each criterion is reported on its own (CAP-15)."""

from clayzer import provenance
from clayzer.grounding import COMPARABILITY_NOTE, SCORE_SCOPE_NOTE, specificity_note


def lookalike_line(lookalikes: dict) -> str:
    """How often each look-alike kind fooled the captioner, e.g. "greenhouse 3 of 4 Runs"."""
    return ", ".join(f"{name.replace('_', ' ')} {k['fooled']} of {k['runs']} Runs"
                     for name, k in lookalikes.items())  # fmt: skip


def _f(x, digits: int = 2) -> str:
    return "—" if x is None else f"{x:.{digits}f}"


def _ms(d: dict | None) -> str:
    """Mean ± Spread."""
    if not d or d.get("mean") is None:
        return "—"
    return _f(d["mean"]) + (f" ± {d['spread']:.2f}" if d.get("spread") is not None else "")


def render(b: dict) -> str:
    cfg, s = b["config"], b["summary"]
    batch = s["batch"]
    runs = batch["runs"]
    unscored = batch["unscored_share"]
    lines = [
        f"# Caption Batch {cfg.batch_id}",
        "",
        (
            f"{len(cfg.case_ids)} Cases × {cfg.repeats} Repeats · Captions by `{cfg.caption_model}` "
            f"(prompt `{cfg.prompt_sha}`, {cfg.prompt_source}) · fidelity by "
            f"`{cfg.judge_model or 'not judged'}` · retrieval by `{cfg.embed_model}` · "
            f"Cases `{cfg.cases_sha}` · scorer `{cfg.scorer_version}`"
        ),
        *(
            ["", f"**{provenance.SELF_GRADED_NOTE}**"]
            if provenance.self_graded(cfg.caption_model, cfg.judge_model)
            else []
        ),
        "",
        (
            f"Runs: {runs['ok']} ok, {runs['harness_faults']} Harness Faults, "
            f"{runs['sandbox_failures']} Sandbox Failures, of {runs['planned']} planned."
        ),
    ]
    if s.get("stopped"):
        lines += ["", (f"**Stopped early:** {s['stopped']}. Resume with "
                      f"`clayzer batch --resume {cfg.batch_id}`.")]  # fmt: skip
    if s.get("replay"):
        replay = s["replay"]
        lines += [
            "",
            "**OFFLINE REPLAY** — no models called. Grounding and Workflow are recomputed where evidence is available; recorded Fidelity and retrieval retained.",
            f"Recorded evaluator: `{replay['original_scorer']}`; current: `{replay['current_scorer']}`.",
        ]
        lines += [f"- Replay warning: {w}" for w in replay["warnings"]]
    lines += [
        "",
        (
            f"**{SCORE_SCOPE_NOTE}** Count and position fields may be omitted or unevaluated; "
            "see each Run's field coverage."
        ),
        "",
        COMPARABILITY_NOTE,
        "",
        "| Criterion | Score | Note |",
        "|---|---|---|",
        (
            f"| Grounding correctness | {_f(batch['correctness'])} | of what Captions claimed, "
            f"how much is right; {_f(unscored * 100 if unscored is not None else None, 0)}% of "
            "Claims have no Answer Key |"
        ),
        (
            f"| Grounding coverage | {_f(batch['coverage'])} | how much of the Answer Key "
            "Captions mention |"
        ),
        f"| Fidelity | {_f(batch['fidelity'])} | model opinion; self-judged: {batch.get('fidelity_self_judged', 'not recorded')} |",
        f"| Retrieval | {_ms(batch['retrieval_mrr'])} | MRR per Repeat, mean ± Spread |",
        f"| Label preparation time | {_f(batch['label_prep_seconds'], 1)} s | observed Case/reference preparation (includes imagery for legacy Cases); {batch.get('label_preparation', {}).get('observed_cases', 'unknown')} measured |",
        (
            "| GPU cost | unavailable | Bedrock hides GPU seconds, count and type |\n"
            f"| Operational usage | {_f(batch['seconds_per_caption'], 1)} s, "
            f"{_f(batch['tokens_per_caption'], 0)} tokens per Caption | Bedrock hides GPU time |"
        ),
        (
            f"| Verified Claims per dollar | {_f(batch.get('verified_claims_per_dollar'), 0)} | "
            f"{_f(batch.get('verified_claims_per_caption'), 1)} per Caption at "
            f"${_f(batch.get('usd_per_caption'), 5)} each; per GPU-second "
            f"{_f(batch.get('verified_claims_per_gpu_second'))} |"
        ),
        *(
            [
                (
                    f"| Fooled by look-alikes | {lookalike_line(batch['lookalikes'])} | Runs "
                    "whose Caption called a look-alike what it imitates |"
                )
            ]
            if batch.get("lookalikes")
            else []
        ),
        "",
        "## Cases",
        "",
        "| Case | Correctness | Coverage | Fidelity | Runs | Faults |",
        "|---|---|---|---|---|---|",
    ]
    for case_id, c in s["cases"].items():
        faults = f"{c['harness_faults']} Harness, {c['sandbox_failures']} Sandbox"
        lines.append(
            f"| {case_id} | {_ms(c['correctness'])} | {_ms(c['coverage'])} | {_ms(c['fidelity'])} "
            f"| {c['runs']} | {faults} |"
        )

    lines += [
        "",
        "Unknown reference evidence is excluded from correctness, never counted as absence.",
        "Recall@1 is fraction of relevant documents retrieved, not the top-result hit rate.",
    ]
    lines += [f"- Retrieval caveat: {w}" for w in batch.get("retrieval_warnings", [])]
    captions = {(c["case_id"], c["repeat"]): c for c in b["captions"]}
    for case_id in s["cases"]:
        lines += ["", f"### {case_id}", ""]
        for r in sorted((r for r in b["results"] if r["case_id"] == case_id),
                        key=lambda r: r["repeat"]):  # fmt: skip
            cap = captions.get((case_id, r["repeat"]))
            if r["status"] == "sandbox_failure":
                lines.append(f"- Repeat {r['repeat']}: Sandbox Failure ({r['error']})")
                continue
            g = r["grounding"]
            fid = (r.get("fidelity") or {}).get("score")
            text = cap["text"] if cap and cap["text"] else "(no Caption)"
            lines.append(
                f"- Repeat {r['repeat']}: correctness {_f(g['correctness'])}, coverage "
                f"{_f(g['coverage'])}, fidelity {_f(fid)}. {text}"
            )
            lines.append(f"  {specificity_note(g)}")
    lines.append("")
    return "\n".join(lines)
