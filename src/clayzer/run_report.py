"""The per-Run evaluation report (REQ-08): one human-readable page and one machine-readable file
for each Run, next to the Batch report.

    batches/<batch-id>/runs/<case-id>--r<repeat>.html
    batches/<batch-id>/runs/<case-id>--r<repeat>.json

Each puts the Run's Trace summary, both scores with their reasons, its Steps, and its final
Caption together. They're built only from stored files (the Trace, its summary and saved
narrative, the results, the frozen Case), so they rebuild with no model or network (REQ-09).
"""

from __future__ import annotations

import json
from html import escape

from clayzer import provenance
from clayzer.report_html import (
    SCRIPT,
    STYLE,
    _chip_svg,
    _claim_table,
    _f,
    _trace_summary,
)
from clayzer.trace import loads, trace_key

STEP_STYLE = """
.steps { list-style: none; margin: 6px 0; padding: 0; }
.steps > li { border: 1px solid var(--line); border-radius: 8px; padding: 8px 12px; margin: 6px 0;
  background: #fff; }
.steps .head { display: flex; flex-wrap: wrap; gap: 6px 12px; align-items: baseline; }
.steps .head b { font-size: 14.5px; }
.steps .judge { opacity: .85; background: #faf7f5; }
.steps pre { white-space: pre-wrap; word-break: break-word; max-height: 360px; overflow: auto;
  background: #faf6f3; border: 1px solid var(--line); border-radius: 6px; padding: 8px 10px;
  font: 12px/1.45 ui-monospace, SFMono-Regular, Menlo, monospace; }
.scores { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px;
  margin: 8px 0 14px; }
.scores .card .big { font-size: 22px; }
.status-row { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin: 6px 0 0; }
section.block { margin: 22px 0; }
"""


def run_name(case_id: str, repeat: int) -> str:
    return f"{case_id}--r{repeat}"


def run_keys(batch_id: str, case_id: str, repeat: int) -> tuple[str, str]:
    base = f"batches/{batch_id}/runs/{run_name(case_id, repeat)}"
    return base + ".html", base + ".json"


def _clip_json(value, limit: int = 20_000) -> str:
    text = json.dumps(value, indent=2, default=str)
    return text if len(text) <= limit else text[:limit] + f"\n…[{len(text) - limit} characters cut]"


def _steps_html(steps) -> str:
    if not steps:
        return "<p class='sub'>No Trace for this Run (it was run before Traces were recorded).</p>"
    out = ["<ol class='steps'>"]
    for s in steps:
        a = s.attributes or {}
        fault = a.get("fault")
        tags = []
        if s.kind == "judge":
            tags.append("<span class='badge b-na'>evaluation, not the Harness</span>")
        if fault:
            label = {"harness": "Harness Fault", "environment": "Environment Fault",
                     "sandbox": "Sandbox Failure"}[fault["attribution"]]  # fmt: skip
            cls = "b-bad" if fault["attribution"] == "harness" else "b-warn"
            tags.append(f"<span class='badge {cls}' title='{escape(fault['reason'])}'>{label}"
                        f"{' (soft)' if fault['soft'] else ''}</span>")  # fmt: skip
        if a.get("retries"):
            tags.append(f"<span class='badge b-warn'>{a['retries']} retries</span>")
        tokens = (a.get("usage") or {}).get("totalTokens")
        meta = " · ".join(
            x
            for x in (
                escape(str(a.get("model_id") or "")),
                f"{_f((a.get('latency_ms') or 0) / 1000, 1)} s",
                f"{tokens:,} tokens" if tokens else "",
                f"Bedrock {a['provider_latency_ms']} ms" if a.get("provider_latency_ms") else "",
            )
            if x
        )
        prompt = (s.input or {}).get("prompt") if isinstance(s.input, dict) else None
        out.append(
            f"<li class='{'judge' if s.kind == 'judge' else ''}'><div class='head'>"
            f"<b>{s.index}. {escape(s.kind)} · {escape(s.name)}</b><span class='sub'>{meta}</span>"
            f"{''.join(tags)}</div>"
            + (f"<p class='sub'>{escape(fault['reason'])}</p>" if fault else "")
            + (f"<p class='sub'>Error: {escape(s.error)}</p>" if s.error else "")
            + (f"<details><summary>Prompt</summary><pre>{escape(prompt)}</pre></details>" if prompt else "")
            + f"<details><summary>Response</summary><pre>{escape(_clip_json(s.output))}</pre></details>"
            + f"<details><summary>Everything recorded</summary><pre>{escape(_clip_json({'input': s.input, 'attributes': a}))}</pre></details>"
            + "</li>"
        )  # fmt: skip
    out.append("</ol>")
    return "".join(out)


def _workflow_html(wf: dict | None) -> str:
    """The Workflow Score's components, each with its reason (workflow.py)."""
    if not wf:
        return ("<section class='block'><h2>How the Harness worked</h2><p class='sub'>No Workflow "
                "Score: this Run has no valid score, or no Trace.</p></section>")  # fmt: skip
    rows = "".join(
        f"<tr><td>{escape(name.replace('_', ' '))}</td><td class='num'>{_f(c['score'])}</td>"
        f"<td>{escape(c['reason'])}</td></tr>"
        for name, c in wf["components"].items()
    )
    env = wf.get("environment_faults") or 0
    note = f" {env} Environment Faults didn't count against it." if env else ""
    return (
        "<section class='block'><h2>How the Harness worked</h2>"
        f"<p class='sub'>The Workflow Score, {_f(wf['score'])}, is the weighted mean of the parts "
        f"that apply, from the Trace alone.{note} A part that doesn't apply is left out.</p>"
        "<table><tr><th>Part</th><th class='num'>Score</th><th>Why</th></tr>"
        f"{rows}</table></section>"
    )


def build(store, b: dict, result: dict) -> tuple[str, dict]:
    """The HTML page and the JSON record for one Run of a loaded Batch."""
    cfg = b["config"]
    case_id, repeat = result["case_id"], result["repeat"]
    case = next(c for c in b["cases"] if c["id"] == case_id)
    cap = next(
        (c for c in b["captions"] if c["case_id"] == case_id and c["repeat"] == repeat), None
    )
    summary = (b.get("summaries") or {}).get((case_id, repeat))
    narrative = (b.get("narratives") or {}).get((case_id, repeat))
    tkey = trace_key(cfg.batch_id, case_id, repeat)
    info, steps = loads(store.get(tkey)) if store.exists(tkey) else (None, [])
    # The later Chip of a Change Case's pair: Claims' positions are in it.
    chip = case["chips"][-1]
    g = result.get("grounding") or {}
    fid = result.get("fidelity") or {}

    record = {
        "run_id": result["run_id"],
        "batch_id": cfg.batch_id,
        "case_id": case_id,
        "repeat": repeat,
        "status": result["status"],
        "error": result.get("error"),
        "scores": {
            "grounding": {
                k: g.get(k)
                for k in (
                    "correctness",
                    "coverage",
                    "precision",
                    "recall",
                    "count",
                    "position",
                    "attributes",
                    "relations",
                    "change",
                    "unscored_share",
                )
            },
            "grounding_detail": {
                k: g.get(k)
                for k in (
                    "rows",
                    "counts",
                    "missed",
                    "unscored",
                    "relation_rows",
                    "relations_unscored",
                )
            },
            "fidelity": {"score": fid.get("score"), "issues": fid.get("issues", [])},
        },
        "faults": result.get("faults"),
        "workflow": result.get("workflow"),
        "seconds_to_caption": result.get("seconds_to_caption"),
        "caption_tokens": result.get("caption_tokens"),
        "summary": summary,
        "narrative": narrative,
        "caption": cap,
        "chip": chip,
        "trace": tkey if steps else None,
        "config": {
            "caption_model": cfg.caption_model,
            "judge_model": cfg.judge_model,
            "self_graded": provenance.self_graded(cfg.caption_model, cfg.judge_model),
            # A Change Case's Run used the change prompt; its Trace records which.
            "prompt_sha": info.prompt_sha if info is not None else cfg.prompt_sha,
            "cases_sha": cfg.cases_sha,
            "scorer_version": cfg.scorer_version,
        },
    }

    status_cls = {"ok": "b-ok", "harness_fault": "b-bad"}.get(result["status"], "b-warn")
    verdict = (summary or {}).get("verdict", "")
    cards = [
        ("Grounding: right", g.get("correctness"), "of what was claimed checks out"),
        ("Grounding: enough", g.get("coverage"), "of what the map shows was mentioned"),
        ("Fidelity", fid.get("score"), "the Judge's rating against the image"),
        (
            "Workflow Score",
            (result.get("workflow") or {}).get("score"),
            "how well the Harness worked, from its Trace",
        ),
    ]
    if g.get("change") is not None:  # a Change Case
        cards.insert(
            2,
            (
                "Grounding: change",
                g["change"],
                "of Claims that got appeared, disappeared, or unchanged right",
            ),
        )
    png = store.get(chip["uri"]) if store.exists(chip["uri"]) else None
    html = [
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>",
        f"<title>Run {escape(result['run_id'])}</title>",
        "<link rel='icon' href='/static/favicon.ico'>",
        f"<style>{STYLE}{STEP_STYLE}</style></head><body>",
        f"<header><h1>Run {escape(result['run_id'])}</h1>",
        (f"<p class='sub'>Batch {escape(cfg.batch_id)} · Repeat {repeat} · {escape(cfg.caption_model)}"
        f" · prompt <code>{escape(record['config']['prompt_sha'])}</code></p>"),
        (f"<p class='status-row'><span class='badge {status_cls}'>{escape(result['status'].replace('_', ' '))}</span>"
        f"<b>{escape(verdict)}</b></p>"
        + (f"<p class='badge b-warn'>{escape(provenance.SELF_GRADED_NOTE)}</p>"
           if provenance.self_graded(cfg.caption_model, cfg.judge_model) else "")
        + "</header><main>"),
        "<div class='scores'>" + "".join(
            f"<div class='card'><small>{escape(t)}</small><div class='big'>{_f(v)}</div><small>{escape(n)}</small></div>"
            for t, v, n in cards) + "</div>",
        "<section class='case'><div class='chip'>",
        _chip_svg(png, case["reference_labels"], g.get("rows", [])),
        f"<div class='meta mono'>{escape(chip['id'])} · NAIP {escape(chip['date'])} · {escape(chip['source'])}</div>",
        "</div><div>",
        "<h2>Caption</h2>",
        f"<blockquote>{escape(cap['text'] if cap and cap.get('text') else '(no Caption)')}</blockquote>",
    ]  # fmt: skip
    if cap and cap.get("uncertain"):
        html += ["<h3>Left uncertain</h3><ul class='issues'>"]
        html += [f"<li>{escape(u)}</li>" for u in cap["uncertain"]] + ["</ul>"]
    html += ["<h3>Grounding: Claims against the Reference Labels</h3>",
             _claim_table(g, case["reference_labels"]) if g else "<p class='sub'>Not scored.</p>"]  # fmt: skip
    if fid.get("issues"):
        html += ["<h3>Fidelity: the Judge's notes</h3><ul class='issues'>"]
        html += [f"<li>{escape(i)}</li>" for i in fid["issues"]] + ["</ul>"]
    html += [
        "</div></section>",
        _workflow_html(result.get("workflow")),
        "<section class='block'><h2>What happened</h2>",
        _trace_summary(summary, narrative) or "<p class='sub'>No summary for this Run.</p>",
        "</section>",
        (
            f"<section class='block'><h2>Steps</h2><p class='sub'>Every model call in order, from the "
            f"Trace ({escape(tkey) if steps else 'none'}).</p>"
        ),
        _steps_html(steps),
        "</section>",
        f"</main><script>{SCRIPT}</script></body></html>",
    ]
    if info is not None:
        record["trace_status"] = info.status
    return "\n".join(html), record


def write_run_reports(store, b: dict) -> int:
    """Write the HTML and JSON report for every Run in a loaded Batch. Returns how many."""
    cfg = b["config"]
    n = 0
    for result in b["results"]:
        html, record = build(store, b, result)
        hkey, jkey = run_keys(cfg.batch_id, result["case_id"], result["repeat"])
        store.put(hkey, html.encode(), "text/html; charset=utf-8")
        store.put(
            jkey, (json.dumps(record, indent=2, default=str) + "\n").encode(), "application/json"
        )
        n += 1
    return n
