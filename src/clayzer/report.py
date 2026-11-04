"""The Markdown report for a Batch. Each criterion is reported on its own (CAP-15)."""


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
        "",
        (
            f"Runs: {runs['ok']} ok, {runs['harness_faults']} Harness Faults, "
            f"{runs['sandbox_failures']} Sandbox Failures, of {runs['planned']} planned."
        ),
    ]
    if s.get("stopped"):
        lines += ["", (f"**Stopped early:** {s['stopped']}. Resume with "
                      f"`clayzer batch --resume {cfg.batch_id}`.")]  # fmt: skip
    lines += [
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
        f"| Fidelity | {_f(batch['fidelity'])} | image-aware Judge |",
        f"| Retrieval | {_ms(batch['retrieval_mrr'])} | MRR per Repeat, mean ± Spread |",
        (
            f"| Retrieval recall@1 | {_ms(batch.get('retrieval_recall_at_1'))} | "
            f"{_ms(batch.get('retrieval_recall_at_1_expanded'))} with queries expanded by "
            "synonyms |"
        ),
        f"| Label preparation time | {_f(batch['label_prep_seconds'], 1)} s | building all Cases |",
        (
            f"| Cost (partial) | {_f(batch['seconds_per_caption'], 1)} s, "
            f"{_f(batch['tokens_per_caption'], 0)} tokens per Caption | Bedrock hides GPU time |"
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
    lines.append("")
    return "\n".join(lines)
