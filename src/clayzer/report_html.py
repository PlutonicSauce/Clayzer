"""A self-contained HTML report for a Run: each Chip with its Claims and Reference Labels drawn
on the 3×3 grid, next to the scores. Opens from the file; no server, no network.

Styling follows prototype/flow-walkthrough.html. Captions and Judge notes are model output, so
every piece of text is escaped.
"""

import base64
from html import escape

from clayzer.grid import GRID
from clayzer.report import imported_note

CELL = 512 / 3

STYLE = """
:root {
  --ink: #252323; --muted: #6b6461; --paper: #fffdfb; --line: #e4dbd6;
  --captions: #f4dcd4; --captions-line: #e8beb2;
  --evaluation: #dfe9df; --evaluation-line: #c9d7c9;
  --platform: #dde7e9; --platform-line: #c9d6d8;
  --hidden: #a1352b; --ok: #2f6b3a; --warn: #8a5b0e;
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--paper); color: var(--ink);
  font: 15px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }
header { padding: 20px 28px 4px; }
h1 { margin: 0; font-size: 22px; }
h2 { font-size: 18px; margin: 0 0 4px; }
h3 { font-size: 13px; margin: 14px 0 4px; text-transform: uppercase; letter-spacing: .04em;
  color: var(--muted); }
.sub { color: var(--muted); margin: 4px 0 0; }
code, .mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12.5px; }
main { padding: 8px 28px 40px; }
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 12px;
  margin: 8px 0 24px; }
.card { border: 1px solid var(--evaluation-line); background: var(--evaluation); border-radius: 8px;
  padding: 10px 12px; }
.card.platform { border-color: var(--platform-line); background: var(--platform); }
.card .big { font-size: 26px; font-weight: 650; font-variant-numeric: tabular-nums; }
.card small { color: var(--muted); display: block; }
.bar { display: flex; gap: 16px; align-items: center; flex-wrap: wrap; margin: 0 0 12px;
  color: var(--muted); }
section.case { border-top: 1px solid var(--line); padding: 20px 0; display: grid;
  grid-template-columns: 420px minmax(0, 1fr); gap: 24px; }
@media (max-width: 900px) { section.case { grid-template-columns: 1fr; } }
.chip svg { width: 100%; height: auto; border-radius: 6px; border: 1px solid var(--line);
  display: block; }
.chip .meta { color: var(--muted); font-size: 12.5px; margin-top: 6px; }
blockquote { margin: 8px 0; padding: 8px 12px; background: var(--captions);
  border-left: 3px solid var(--captions-line); border-radius: 4px; }
table { border-collapse: collapse; width: 100%; margin: 6px 0; }
th, td { text-align: left; padding: 5px 8px; border-bottom: 1px solid var(--line);
  vertical-align: top; }
th { font-size: 12.5px; color: var(--muted); font-weight: 600; }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
.badge { display: inline-block; padding: 1px 7px; border-radius: 999px; font-size: 12px;
  border: 1px solid; white-space: nowrap; }
.b-ok { color: var(--ok); border-color: #b9d3bd; background: #eef6ef; }
.b-bad { color: var(--hidden); border-color: #e6b8b1; background: #fbefed; }
.b-warn { color: var(--warn); border-color: #e3cfa8; background: #fbf4e6; }
.b-na { color: var(--muted); border-color: var(--line); background: #f7f3f1; }
ul.issues { margin: 4px 0; padding-left: 18px; }
.trace-summary { margin: 10px 0; padding: 10px 14px; border-radius: 8px; background: #faf6f3;
  border: 1px solid var(--line); }
.trace-summary .verdict { margin: 0 0 4px; font-weight: 650; }
.trace-summary ol, .trace-summary ul { margin: 2px 0 6px; padding-left: 20px; font-size: 13.5px; }
.trace-summary h3 { margin: 8px 0 2px; }
.trace-summary.narrative p { margin: 4px 0; }
.trace-summary .facts { margin-top: 8px; border: 0; padding: 0; }
.trace-summary .facts .trace-summary { background: #fff; }
details { border: 1px solid var(--line); border-radius: 6px; padding: 6px 10px; margin: 6px 0; }
details > summary { cursor: pointer; }
small { color: var(--muted); }
.legend { display: flex; gap: 14px; font-size: 12.5px; color: var(--muted); margin-top: 4px; }
.legend i { display: inline-block; width: 12px; height: 12px; border-radius: 3px;
  vertical-align: -2px; margin-right: 4px; }
body.hide-claims .claims, body.hide-refs .refs, body.hide-grid .grid { display: none; }
"""

SCRIPT = """
for (const box of document.querySelectorAll('input[data-hide]')) {
  box.addEventListener('change', () =>
    document.body.classList.toggle(box.dataset.hide, !box.checked));
}
"""


def _f(x, digits: int = 2) -> str:
    return "—" if x is None else f"{x:.{digits}f}"


def _badge(score) -> str:
    if score is None:
        return '<span class="badge b-na">—</span>'
    cls = "b-ok" if score >= 0.99 else "b-warn" if score >= 0.5 else "b-bad"
    return f'<span class="badge {cls}">{score:.2f}</span>'


def _cell_xy(cell: str) -> tuple[float, float]:
    i = GRID.index(cell)
    return (i % 3 + 0.5) * CELL, (i // 3 + 0.5) * CELL


def _short(obj: str) -> str:
    return obj.replace("_", " ")


def chip_meta(case: dict, chip: dict) -> str:
    """The line under a Chip: its id, date, and source. An imported caption's image may be any
    sensor's, or have no date."""
    date = escape(chip.get("date") or "undated")
    return (f"{escape(chip['id'])} · {'' if case.get('imported') else 'NAIP '}{date} · "
            f"{escape(chip['source'])}")  # fmt: skip


def _chip_svg(png: bytes | None, labels: list[dict], rows: list[dict]) -> str:
    img = base64.b64encode(png).decode() if png else ""
    parts = [
        '<svg viewBox="0 0 512 512" xmlns="http://www.w3.org/2000/svg" role="img">',
        f'<image href="data:image/png;base64,{img}" width="512" height="512"/>',
        (
            '<g class="grid" stroke="#fffdfb" stroke-opacity=".7" stroke-width="1.5"'
            ' stroke-dasharray="6 5">'
        ),
    ]
    for k in (1, 2):
        parts.append(f'<line x1="{k * CELL}" y1="0" x2="{k * CELL}" y2="512"/>')
        parts.append(f'<line x1="0" y1="{k * CELL}" x2="512" y2="{k * CELL}"/>')
    parts.append("</g>")

    # Reference Labels: a dashed outline on every cell some label covers, and each type named
    # in its main cell. Each label's full cell list is in the table beside the Chip.
    parts.append('<g class="refs">')
    covered = {cell for lb in labels for cell in lb["cells"]}
    for cell in sorted(covered, key=GRID.index):
        i = GRID.index(cell)
        parts.append(
            f'<rect x="{i % 3 * CELL + 4}" y="{i // 3 * CELL + 4}" width="{CELL - 8}" '
            f'height="{CELL - 8}" fill="none" stroke="#2f6b3a" stroke-opacity=".8" '
            'stroke-width="2" stroke-dasharray="4 4"/>'
        )
    ref_rows: dict[str, int] = {}
    for lb in labels:
        x, y = _cell_xy(lb["position"])
        n = ref_rows.get(lb["position"], 0)
        ref_rows[lb["position"]] = n + 1
        count = f"{lb['count']} × " if lb["count"] is not None else ""
        text = escape(f"{count}{_short(lb['object'])}")
        ty = y + CELL / 2 - 12 - 18 * n
        parts.append(
            f'<rect x="{x - CELL / 2 + 8}" y="{ty - 12}" width="{CELL - 16}" height="16" rx="3" '
            'fill="#eef6ef" fill-opacity=".92"/>'
            f'<text x="{x}" y="{ty}" text-anchor="middle" font-size="11" fill="#2f6b3a">'
            f"{text}</text>"
        )
    parts.append("</g>")

    # Claims: a dot per Claim at its cell, coloured by verdict.
    parts.append('<g class="claims">')
    per_cell: dict[str, int] = {}
    for row in rows:
        cl = row["claim"]
        x, y = _cell_xy(cl["position"])
        n = per_cell.get(cl["position"], 0)
        per_cell[cl["position"]] = n + 1
        y = y - CELL / 2 + 22 + 20 * n
        if row["verdict"] == "false positive":
            color = "#a1352b"
        else:
            color = "#2f6b3a" if row.get("position") == 1.0 else "#8a5b0e"
        text = escape(f"{cl['count']} × {_short(cl['object'])}")
        parts.append(
            f'<rect x="{x - CELL / 2 + 8}" y="{y - 12}" width="{CELL - 16}" height="17" rx="8" '
            f'fill="{color}" fill-opacity=".9"/>'
            f'<text x="{x}" y="{y + 1}" text-anchor="middle" font-size="11" fill="#fffdfb" '
            f'font-weight="600">{text}</text>'
        )
    parts.append("</g></svg>")
    return "".join(parts)


def _claim_table(g: dict, labels: list[dict]) -> str:
    refs = {lb["object"]: lb for lb in labels}
    out = [
        (
            "<table><tr><th>Claim</th><th>Verdict</th><th>Reference Label</th>"
            '<th class="num">Position</th></tr>'
        )
    ]
    for row in g["rows"]:
        cl = row["claim"]
        attrs = " ".join(f"{k}={v}" for k, v in (cl.get("attributes") or {}).items())
        claim = f"{cl['count']} × {_short(cl['object'])} at {cl['position']} {attrs}".strip()
        if cl.get("change"):  # a Change Case's Claim
            claim += f" ({cl['change']})"
        ref = refs.get(cl["object"])
        if ref:
            ref_attrs = " ".join(f"{k}={v}" for k, v in ref["attributes"].items())
            count = f"{ref['count']} × " if ref["count"] is not None else ""
            reference = (
                f"{count}{_short(ref['object'])} at {ref['position']} "
                f"(covers {', '.join(ref['cells'])}) {ref_attrs}"
                + (f" ({ref['change']})" if ref.get("change") else "")
                + f" · {ref['source']}"
            )
            verdict = '<span class="badge b-ok">matched</span>'
        else:
            reference = "none"
            verdict = '<span class="badge b-bad">false positive</span>'
        if "change" in row:  # scored only where the label's change is known
            ok = row["change"] == 1.0
            verdict += f' <span class="badge {"b-ok" if ok else "b-bad"}">change {"right" if ok else "wrong"}</span>'
        out.append(
            f"<tr><td>{escape(claim)}</td><td>{verdict}</td><td>{escape(reference)}</td>"
            f'<td class="num">{_badge(row.get("position"))}</td></tr>'
        )
    for obj in g["missed"]:
        ref = refs[obj]
        out.append(
            f"<tr><td>—</td><td><span class='badge b-bad'>missed</span></td>"
            f"<td>{escape(f'{_short(obj)} at {ref["position"]} · {ref["source"]}')}</td>"
            "<td></td></tr>"
        )
    for obj in g["unscored"]:
        out.append(
            f"<tr><td>{escape(_short(obj))}</td><td><span class='badge b-na'>unscored</span></td>"
            "<td>no Answer Key covers this type</td><td></td></tr>"
        )
    out.append("</table>")
    if g.get("counts"):
        counts = "; ".join(
            f"{_short(o)}: {c['claimed']} claimed, {c['reference']} in the Answer Key"
            for o, c in g["counts"].items()
        )
        out.append(f'<p class="sub">Counts: {escape(counts)}</p>')
    if g["relation_rows"]:
        rels = "; ".join(
            f"{_short(r['subject'])} {r['relation']} {_short(r['object'])} "
            f"{'✓' if r['ok'] else '✗'}"
            for r in g["relation_rows"]
        )
        out.append(f'<p class="sub">Relations: {escape(rels)}</p>')
    return "".join(out)


def _ms(d: dict | None) -> str:
    """Mean ± Spread, with a badge on the mean."""
    if not d or d.get("mean") is None:
        return _badge(None)
    spread = f" <small>± {d['spread']:.2f}</small>" if d.get("spread") is not None else ""
    return _badge(d["mean"]) + spread


def _markdown(text: str) -> str:
    """The small Markdown a narrative uses (### headings, - bullets, **bold**, `code`), as
    escaped HTML."""
    import re

    html, items = [], []

    def flush():
        if items:
            html.append("<ul>" + "".join(f"<li>{i}</li>" for i in items) + "</ul>")
            items.clear()

    for line in text.splitlines():
        line = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", escape(line.strip()))
        line = re.sub(r"`([^`]+)`", r"<code>\1</code>", line)
        if not line:
            flush()
        elif line.startswith("### "):
            flush()
            html.append(f"<h3>{line[4:]}</h3>")
        elif line.startswith(("- ", "* ")):
            items.append(line[2:])
        else:
            flush()
            html.append(f"<p>{line}</p>")
    flush()
    return "".join(html)


def _trace_summary(summary: dict | None, narrative: dict | None = None) -> str:
    """The Run's Trace summary: the saved model-written narrative if there is one (narrate.py),
    with the code-written facts (summarize.py) under it; otherwise the facts alone."""
    if narrative and narrative.get("markdown"):
        facts = (
            f"<details class='facts'><summary>Facts from the Trace</summary>{_trace_summary(summary)}</details>"
            if summary
            else ""
        )
        return (
            f"<div class='trace-summary narrative'>{_markdown(narrative['markdown'])}"
            f"<p class='sub'>Written by {escape(narrative['model'].removeprefix('us.'))} from this "
            f"Run's Trace alone; saved, so replays don't call a model.</p>{facts}</div>"
        )
    if not summary:
        return ""
    struggled = [x for x in summary["struggled"] if x != "Nothing notable."]
    out = [
        "<div class='trace-summary'>",
        f"<p class='verdict'>{escape(summary['verdict'])}</p>",
        "<h3>What the Harness did</h3><ol>",
        *[f"<li>{escape(x)}</li>" for x in summary["did"]],
        "</ol>",
        "<h3>Where it struggled</h3>",
        ("<ul>" + "".join(f"<li>{escape(x)}</li>" for x in struggled) + "</ul>")
        if struggled
        else "<p class='sub'>Nothing notable.</p>",
    ]
    if summary.get("evaluation"):
        out.append(
            "<p class='sub'>Evaluation: " + escape("; ".join(summary["evaluation"])) + "</p>"
        )
    out.append("</div>")
    return "".join(out)


def _repeat_row(
    r: dict,
    cap: dict | None,
    labels: list[dict],
    summary: dict | None = None,
    narrative: dict | None = None,
) -> str:
    """One Repeat: a summary line that opens into its Trace summary, Caption, Claims, and Judge
    notes."""
    if r["status"] == "sandbox_failure":
        return (
            f"<details><summary>Repeat {r['repeat']} · "
            "<span class='badge b-na'>Sandbox Failure</span></summary>"
            f"<p class='sub'>{escape(r.get('error') or '')}</p>"
            f"{_trace_summary(summary, narrative)}</details>"
        )
    g = r["grounding"]
    fid = r.get("fidelity") or {}
    fault = (
        " · <span class='badge b-bad'>Harness Fault</span>"
        if r["status"] == "harness_fault"
        else ""
    )
    out = [
        (
            f"<details><summary>Repeat {r['repeat']} · correctness {_badge(g['correctness'])} · "
            f"coverage {_badge(g['coverage'])} · "
            f"fidelity {_badge(fid.get('score'))} · "
            f"workflow {_badge((r.get('workflow') or {}).get('score'))}{fault}</summary>"
        ),
        _trace_summary(summary, narrative),
        f"<blockquote>{escape(cap['text'] if cap and cap['text'] else '(no Caption)')}</blockquote>",
        _claim_table(g, labels),
    ]
    if fid.get("issues"):
        out.append("<h3>Judge</h3><ul class='issues'>")
        out += [f"<li>{escape(i)}</li>" for i in fid["issues"]]
        out.append("</ul>")
    if cap and cap.get("uncertain"):
        out.append("<h3>Left uncertain by the Harness</h3><ul class='issues'>")
        out += [f"<li>{escape(u)}</li>" for u in cap["uncertain"]]
        out.append("</ul>")
    out.append(
        f"<p class='sub'>Caption in {_f(r.get('seconds_to_caption'), 1)} s, "
        f"{r.get('caption_tokens')} tokens · "
        f"<a href='runs/{escape(r['case_id'])}--r{r['repeat']}.html' target='_blank' rel='noopener'>"
        "Open this Run's full report: Steps, prompts, responses</a></p></details>"
    )
    return "".join(out)


def render_html(b: dict, store) -> str:
    cfg, s = b["config"], b["summary"]
    batch = s["batch"]
    unscored = batch["unscored_share"] * 100 if batch["unscored_share"] is not None else None
    mrr = batch["retrieval_mrr"]
    runs = batch["runs"]
    cards = [
        ("Grounding correctness", _f(batch["correctness"]),
         f"of what was claimed, how much is right; {_f(unscored, 0)}% of Claims unscored", ""),
        ("Grounding coverage", _f(batch["coverage"]), "how much of the Answer Key is mentioned", ""),
        ("Fidelity", _f(batch["fidelity"]), "image-aware Judge", ""),
        (
            "Retrieval",
            _f(mrr["mean"]),
            f"MRR per Repeat, Spread {_f(mrr['spread'])}",
            "",
        ),
        ("Label preparation", f"{_f(batch['label_prep_seconds'], 0)} s",
         (f"building {len(cfg.case_ids)} Cases; writing a Caption "
         f"{_f(batch['seconds_per_caption'], 1)} s (both until Clay says which it means)"),
         " platform"),
        ("Cost (partial)", f"{_f(batch['seconds_per_caption'], 1)} s",
         f"{_f(batch['tokens_per_caption'], 0)} tokens per Caption; no GPU time on Bedrock",
         " platform"),
    ]  # fmt: skip
    html = [
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>",
        f"<title>Caption Batch {escape(cfg.batch_id)}</title>",
        f"<style>{STYLE}</style></head><body>",
        f"<header><h1>Caption Batch {escape(cfg.batch_id)}</h1>",
        (
            f"<p class='sub'>{len(cfg.case_ids)} Cases × {cfg.repeats} Repeats · Captions by "
            f"<code>{escape(cfg.caption_model)}</code> (prompt <code>{escape(cfg.prompt_sha)}"
            f"</code>, {escape(cfg.prompt_source)}) · fidelity by "
            f"<code>{escape(cfg.judge_model or 'not judged')}</code> · retrieval by "
            f"<code>{escape(cfg.embed_model)}</code> · Cases <code>{escape(cfg.cases_sha)}</code>"
            f" · each criterion reported on its own</p>"
        ),
        (
            f"<p class='sub'>Runs: {runs['ok']} ok · {runs['harness_faults']} Harness Faults · "
            f"{runs['sandbox_failures']} Sandbox Failures · {runs['planned']} planned</p>"
        ),
    ]
    if imported_note(batch):
        html.append(f"<p class='sub'>{escape(imported_note(batch))}</p>")
    if s.get("stopped"):
        html.append(
            f"<p class='badge b-warn'>Stopped early: {escape(s['stopped'])}. Resume with "
            f"clayzer batch --resume {escape(cfg.batch_id)}</p>"
        )
    html += ["</header><main><div class='cards'>"]
    for title, big, note, cls in cards:
        html.append(
            f"<div class='card{cls}'><small>{title}</small><div class='big'>{big}</div>"
            f"<small>{escape(note)}</small></div>"
        )
    html += [
        "</div>",
        (
            "<div class='bar'>Show:"
            "<label><input type='checkbox' data-hide='hide-claims' checked> Claims</label>"
            "<label><input type='checkbox' data-hide='hide-refs' checked> Reference Labels</label>"
            "<label><input type='checkbox' data-hide='hide-grid' checked> 3×3 grid</label>"
            "<span class='legend'><span><i style='background:#2f6b3a'></i>Claim in the right cell"
            "</span><span><i style='background:#8a5b0e'></i>wrong cell</span>"
            "<span><i style='background:#a1352b'></i>false positive</span>"
            "<span><i style='border:2px dashed #2f6b3a'></i>Reference Label cells</span></span>"
            "<span>The Chip shows Repeat 1's Claims.</span></div>"
        ),
    ]

    captions = {(c["case_id"], c["repeat"]): c for c in b["captions"]}
    by_id = {c["id"]: c for c in b["cases"]}
    for case_id, summ in s["cases"].items():
        case = by_id[case_id]
        # The later Chip of a Change Case's pair: Claims' positions are in it.
        chip = case["chips"][-1]
        rows = sorted(
            (r for r in b["results"] if r["case_id"] == case_id), key=lambda r: r["repeat"]
        )
        first = next((r for r in rows if r["status"] != "sandbox_failure"), None)
        comp = summ["components"]
        cols = [
            ("Correctness", _ms(summ["correctness"])), ("Coverage", _ms(summ["coverage"])),
            ("Fidelity", _ms(summ["fidelity"])),
            ("Workflow", _ms(summ.get("workflow"))),
            ("Precision", _badge(comp["precision"])), ("Recall", _badge(comp["recall"])),
            ("Count", _badge(comp["count"])), ("Position", _badge(comp["position"])),
            ("Attributes", _badge(comp["attributes"])), ("Relations", _badge(comp["relations"])),
        ]  # fmt: skip
        html += [
            "<section class='case'><div class='chip'>",
            _chip_svg(
                store.get(chip["uri"]) if chip.get("uri") and store.exists(chip["uri"]) else None,
                case["reference_labels"],
                first["grounding"]["rows"] if first else [],
            ),
            (f"<div class='meta mono'>{chip_meta(case, chip)}</div></div><div>"),
            f"<h2>{escape(case_id)}</h2>",
            (
                f"<p class='sub'>{summ['runs']} scored Runs · {summ['harness_faults']} Harness "
                f"Faults · {summ['sandbox_failures']} Sandbox Failures · mean ± Spread across "
                "Repeats</p>"
            ),
            "<table><tr>" + "".join(f'<th class="num">{n}</th>' for n, _ in cols) + "</tr>",
            "<tr>" + "".join(f'<td class="num">{v}</td>' for _, v in cols) + "</tr></table>",
            "<h3>Repeats</h3>",
        ]
        html += [
            _repeat_row(
                r,
                captions.get((case_id, r["repeat"])),
                case["reference_labels"],
                (b.get("summaries") or {}).get((case_id, r["repeat"])),
                (b.get("narratives") or {}).get((case_id, r["repeat"])),
            )
            for r in rows
        ]
        html.append("</div></section>")

    if b["retrieval"]:
        html.append(
            "<h2>Retrieval</h2><table><tr><th>Repeat</th><th>Query</th><th>Relevant Cases</th>"
            '<th>Ranking</th><th class="num">Reciprocal rank</th></tr>'
        )
        for row in b["retrieval"]:
            for q in row["queries"]:
                ranking = " › ".join(
                    f"<b>{escape(c)}</b>" if c in q["relevant"] else escape(c) for c in q["ranked"]
                )
                html.append(
                    f"<tr><td>{row['repeat']}</td><td>{escape(q['query'])}</td>"
                    f"<td>{escape(', '.join(q['relevant']))}</td>"
                    f"<td class='mono'>{ranking}</td>"
                    f'<td class="num">{_badge(q["reciprocal_rank"])}</td></tr>'
                )
        html.append("</table>")
    html.append(f"</main><script>{SCRIPT}</script></body></html>")
    return "\n".join(html)
