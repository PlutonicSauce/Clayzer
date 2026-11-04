// Label Claims by hand (labels/extraction/sample.jsonl): one caption at a time, its text only.
// A caption may come with a model's proposed label to check and fix, or be blind (no proposal:
// label from scratch); the server records which, per label. Saving needs `clayzer ui
// --calibrate`; the server checks every label against the Claim format (ADR-0007).
//
//   Ctrl/Cmd+Enter  save and go to the next unlabelled caption

import { render } from "preact";
import { useEffect, useState } from "preact/hooks";
import { html } from "/static/deck/html.js";

const SET = "extraction";
const empty = () => ({ objects: [], relations: [], uncertain: [] });
const clone = (x) => JSON.parse(JSON.stringify(x));
const label = (cell) => cell.replace("_", "-");

function nextId(objects) {
  const n = Math.max(0, ...objects.map((o) => parseInt(String(o.id).replace(/\D/g, ""), 10) || 0));
  return `o${n + 1}`;
}

function PositionGrid({ value, grid, onChange, disabled }) {
  return html`<div class="pos">
    <div class="lab-cells" role="radiogroup" aria-label="Position">
      ${grid.map((cell) => html`<button type="button" role="radio" aria-checked=${value === cell}
        title=${label(cell)} disabled=${disabled} class=${value === cell ? "on" : ""}
        onClick=${() => onChange(cell)}></button>`)}
    </div>
    <button type="button" class=${`ns ${value === null ? "on" : ""}`} aria-pressed=${value === null}
      disabled=${disabled} onClick=${() => onChange(null)}>not stated</button>
    ${value === undefined
      ? html`<small class="unset">choose a cell, or not stated</small>`
      : html`<small>${value ? label(value) : "where: not stated"}</small>`}
  </div>`;
}

function ObjectRow({ o, vocab, onChange, onRemove, disabled }) {
  const set = (k, v) => onChange({ ...o, [k]: v });
  return html`<div class="row obj">
    <code class="oid">${o.id}</code>
    <label class="cls">Object
      <select value=${o.object || ""} disabled=${disabled} onChange=${(e) => set("object", e.target.value)}>
        <option value="" disabled>choose…</option>
        ${vocab.objects.map((c) => html`<option value=${c.id}>
          ${c.name}${c.synonyms.length ? ` (${c.synonyms.join(", ")})` : ""}</option>`)}
      </select>
    </label>
    <label class="cnt">Count
      <input type="number" min="1" step="1" value=${o.count ?? ""} disabled=${disabled || o.count === null}
        placeholder="how many?"
        onInput=${(e) => set("count", e.target.value === "" ? undefined : Math.max(1, parseInt(e.target.value, 10) || 1))} />
      <span><input type="checkbox" checked=${o.count === null} disabled=${disabled}
        onChange=${(e) => set("count", e.target.checked ? null : undefined)} /> not stated</span>
      ${o.count === undefined && html`<span class="unset">a number, or not stated</span>`}
    </label>
    <${PositionGrid} value=${o.position} grid=${vocab.grid} disabled=${disabled}
      onChange=${(p) => set("position", p)} />
    <button type="button" class="rm" disabled=${disabled} onClick=${onRemove}
      aria-label=${`Remove ${o.id}`}>✕</button>
  </div>`;
}

function RelationRow({ r, objects, vocab, onChange, onRemove, disabled }) {
  const pick = (k) => html`<select value=${r[k] || ""} disabled=${disabled}
      onChange=${(e) => onChange({ ...r, [k]: e.target.value })}>
    <option value="" disabled>${k}…</option>
    ${objects.map((o) => html`<option value=${o.id}>${o.id} · ${(vocab.objects.find((c) => c.id === o.object) || {}).name || "?"}</option>`)}
  </select>`;
  return html`<div class="row rel">
    ${pick("subject")}
    <select value=${r.relation || ""} disabled=${disabled} onChange=${(e) => onChange({ ...r, relation: e.target.value })}>
      <option value="" disabled>relation…</option>
      ${vocab.relations.map((x) => html`<option value=${x}>${x.replace(/_/g, " ")}</option>`)}
    </select>
    ${pick("object")}
    <button type="button" class="rm" disabled=${disabled} onClick=${onRemove} aria-label="Remove relation">✕</button>
  </div>`;
}

// What the server would reject, said before saving. A count or position nobody set is
// `undefined`, never a default: an untouched field mustn't be saved as an answer.
function problems(c) {
  const out = [];
  c.objects.forEach((o) => {
    if (!o.object) out.push(`${o.id}: choose an object`);
    if (o.count === undefined) out.push(`${o.id}: give a count, or tick not stated`);
    if (o.position === undefined) out.push(`${o.id}: choose a cell, or not stated`);
  });
  c.relations.forEach((r, i) => {
    if (!r.subject || !r.relation || !r.object) out.push(`relation ${i + 1}: fill all three`);
    else if (r.subject === r.object) out.push(`relation ${i + 1}: an object can't relate to itself`);
  });
  return out;
}

function Labeler() {
  const [data, setData] = useState(null);
  const [i, setI] = useState(0);
  const [draft, setDraft] = useState(empty());
  const [dirty, setDirty] = useState(false);
  const [msg, setMsg] = useState("");

  useEffect(() => {
    fetch(`/api/labels/${SET}`).then((r) => r.json()).then((d) => {
      setData(d);
      const fromHash = parseInt(location.hash.slice(1), 10) - 1;
      const firstOpen = d.items.findIndex((x) => x.claims === null);
      go(d, Number.isFinite(fromHash) ? fromHash : Math.max(0, firstOpen), true);
    }).catch((e) => setMsg(`Couldn't load the labels: ${e.message}`));
  }, []);

  function go(d, n, force = false) {
    if (!force && dirty && !confirm("Leave this caption without saving?")) return;
    const k = Math.min(Math.max(n, 0), d.items.length - 1);
    setI(k);
    const it = d.items[k];
    setDraft(clone(it.claims ?? it.proposed ?? empty()));
    setDirty(false);
    setMsg("");
    history.replaceState(null, "", `#${k + 1}`);
  }

  const edit = (c) => { setDraft(c); setDirty(true); };

  async function save(claims, then) {
    const item = data.items[i];
    const r = await fetch(`/api/labels/${SET}/${encodeURIComponent(item.id)}`, {
      method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ claims }),
    });
    const body = await r.json().catch(() => ({}));
    if (!r.ok) {
      setMsg(body.detail || `Not saved (HTTP ${r.status})`);
      return;
    }
    const items = data.items.map((x, k) => (k === i ? { ...x, claims, source: body.source ?? null } : x));
    const d = { ...data, items };
    setData(d);
    setDirty(false);
    setMsg(claims === null ? "Label cleared." : "Saved.");
    if (then === "next") {
      const after = items.findIndex((x, k) => k > i && x.claims === null);
      const open = after >= 0 ? after : items.findIndex((x) => x.claims === null);
      if (open >= 0) go(d, open, true);
      else setMsg("Saved. Every caption is labelled.");
    }
  }

  useEffect(() => {
    const onKey = (e) => {
      if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && data?.writable && !problems(draft).length) {
        e.preventDefault();
        save(draft, "next");
      }
    };
    addEventListener("keydown", onKey);
    return () => removeEventListener("keydown", onKey);
  });

  if (!data) return html`<main class="lab"><p class="sub">${msg || "Loading…"}</p></main>`;
  if (!data.items.length) return html`<main class="lab"><p>No captions to label in <code>labels/${SET}/sample.jsonl</code>.</p></main>`;

  const item = data.items[i];
  const done = data.items.filter((x) => x.claims !== null).length;
  const ro = !data.writable;
  const issues = problems(draft);
  const setObj = (k, o) => edit({ ...draft, objects: draft.objects.map((x, j) => (j === k ? o : x)) });
  const rmObj = (k) => {
    const gone = draft.objects[k].id;
    edit({ ...draft, objects: draft.objects.filter((_, j) => j !== k),
      relations: draft.relations.filter((r) => r.subject !== gone && r.object !== gone) });
  };

  return html`<main class="lab">
    <header class="lab-head">
      <a href="/">← Clayzer</a>
      <h1>Label Claims</h1>
      <span class="sub">${done} of ${data.items.length} labelled</span>
      <progress max=${data.items.length} value=${done}></progress>
    </header>
    ${ro && html`<p class="warn">Read-only. Start the app with <code>uv run clayzer ui --calibrate</code> to save labels.</p>`}
    <p class="how">Label what the <b>text</b> says, not what you think is in the image. A count or
      position the text doesn't give is <i>not stated</i>; hedged things ("likely", "may be") go under
      Uncertain. One object in two cells is one object, at the first cell named.
      <a href="/docs/labels/extraction/README.md" target="_blank">Rules</a></p>

    <div class="lab-body">
      <nav class="items" aria-label="Captions">
        <ol>${data.items.map((x, k) => html`<li>
          <button type="button" class=${k === i ? "cur" : ""} aria-current=${k === i ? "true" : null}
            title=${x.blind ? "blind: no proposal" : x.proposed ? "has a proposal to check" : ""}
            onClick=${() => go(data, k)}>${x.claims !== null ? "✓" : "·"} ${k + 1}${x.blind ? " (blind)" : ""}</button></li>`)}</ol>
      </nav>

      <section class="item">
        <p class="meta"><span>Caption ${i + 1} of ${data.items.length}</span> <code>${item.id}</code>
          ${item.claims !== null && html`<span class="badge b-ok">labelled${item.source ? `: ${item.source}` : ""}</span>`}
          ${dirty && html`<span class="badge b-warn">unsaved</span>`}</p>
        <blockquote class="caption">${item.text}</blockquote>
        ${item.claims === null && item.blind && html`<p class="notice blind"><b>Blind.</b> No
          proposal for this one: label it from scratch. These are the unbiased check.</p>`}
        ${item.claims === null && !item.blind && item.proposed && html`<p class="notice proposed">
          <b>Proposed by a model (${item.proposed_by || "the extractor"}).</b> Check every field against
          the text and fix anything wrong, then save. Don't accept it just because it's there.</p>`}

        <h2>Objects</h2>
        ${draft.objects.length ? "" : html`<p class="sub">None yet. A caption that claims nothing is labelled by saving it empty.</p>`}
        ${draft.objects.map((o, k) => html`<${ObjectRow} key=${o.id} o=${o} vocab=${data.vocabulary} disabled=${ro}
          onChange=${(x) => setObj(k, x)} onRemove=${() => rmObj(k)} />`)}
        <button type="button" class="btn secondary" disabled=${ro}
          onClick=${() => edit({ ...draft, objects: [...draft.objects, { id: nextId(draft.objects), object: "", count: undefined, position: undefined }] })}>+ Object</button>

        <h2>Relations <small>only ones the text states</small></h2>
        ${draft.relations.map((r, k) => html`<${RelationRow} r=${r} objects=${draft.objects} vocab=${data.vocabulary} disabled=${ro}
          onChange=${(x) => edit({ ...draft, relations: draft.relations.map((y, j) => (j === k ? x : y)) })}
          onRemove=${() => edit({ ...draft, relations: draft.relations.filter((_, j) => j !== k) })} />`)}
        <button type="button" class="btn secondary" disabled=${ro || draft.objects.length < 2}
          onClick=${() => edit({ ...draft, relations: [...draft.relations, { subject: "", relation: "", object: "" }] })}>+ Relation</button>

        <h2>Uncertain <small>hedged phrases, as written</small></h2>
        ${draft.uncertain.map((u, k) => html`<div class="row unc">
          <input type="text" value=${u} disabled=${ro} aria-label=${`Uncertain ${k + 1}`}
            onInput=${(e) => edit({ ...draft, uncertain: draft.uncertain.map((y, j) => (j === k ? e.target.value : y)) })} />
          <button type="button" class="rm" disabled=${ro} aria-label="Remove"
            onClick=${() => edit({ ...draft, uncertain: draft.uncertain.filter((_, j) => j !== k) })}>✕</button></div>`)}
        <button type="button" class="btn secondary" disabled=${ro}
          onClick=${() => edit({ ...draft, uncertain: [...draft.uncertain, ""] })}>+ Uncertain</button>

        <div class="actions">
          <button type="button" class="btn" disabled=${ro || issues.length > 0}
            onClick=${() => save({ ...draft, uncertain: draft.uncertain.filter((u) => u.trim()) }, "next")}>Save and next</button>
          <button type="button" class="btn secondary" onClick=${() => go(data, i - 1)} disabled=${i === 0}>← Previous</button>
          <button type="button" class="btn secondary" onClick=${() => go(data, i + 1)} disabled=${i === data.items.length - 1}>Next →</button>
          ${item.claims !== null && html`<button type="button" class="btn secondary" disabled=${ro}
            onClick=${() => confirm("Clear this caption's label?") && save(null)}>Clear label</button>`}
          <small class="sub">Ctrl/⌘+Enter saves and moves on</small>
        </div>
        ${issues.length > 0 && html`<ul class="issues">${issues.map((x) => html`<li>${x}</li>`)}</ul>`}
        <p class="msg" aria-live="polite">${msg}</p>
      </section>
    </div>
  </main>`;
}

render(html`<${Labeler} />`, document.getElementById("label"));
