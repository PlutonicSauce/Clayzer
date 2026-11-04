// Clayzer team app: a hash-routed page per view, over the JSON API in ui/app.py.
// Every piece of text from the API goes through esc() or textContent.

const $view = document.getElementById("view");
let CONFIG = null;
let GLOSSARY = {};
// Bumped on every navigation; a page that finishes loading after the user has moved on
// must not overwrite the newer page.
let SEQ = 0;
const stale = (me) => me !== SEQ;

const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const f2 = (x) => (x === null || x === undefined ? "—" : Number(x).toFixed(2));
const api = async (path, opts) => {
  const r = await fetch(path, opts);
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || `${r.status} ${path}`);
  return r.json();
};
const badge = (score) => {
  if (score === null || score === undefined) return '<span class="badge b-na">—</span>';
  const cls = score >= 0.99 ? "b-ok" : score >= 0.5 ? "b-warn" : "b-bad";
  return `<span class="badge ${cls}">${f2(score)}</span>`;
};
// A capitalized glossary term with its definition on hover.
const term = (word, shown) => {
  const g = GLOSSARY[word];
  return g ? `<abbr title="${esc(g.definition)}">${esc(shown || word)}</abbr>` : esc(shown || word);
};

const STATUS = {
  done: ["b-ok", "done"], doing: ["b-info", "in progress"], todo: ["b-na", "to do"],
  blocked: ["b-bad", "blocked"], decide: ["b-warn", "needs a decision"],
};
const statusBadge = (s) => `<span class="badge ${STATUS[s]?.[0] || "b-na"}">${esc(STATUS[s]?.[1] || s)}</span>`;
const AREA_CLASS = {
  "Data and Cases": "area-data", Captioning: "area-captions", Evaluation: "area-evaluation",
  "Sandbox integration": "area-platform", "Demo and delivery": "area-delivery",
};
const AREAS = Object.keys(AREA_CLASS);

// ── The workflow, one step at a time ─────────────────────────────────────────────────────

const FLOW = [
  {
    key: "case", title: "Case", sub: "a Chip and its Reference Labels", area: "Data and Cases",
    what: `A ${term("Case")} is one unit of work: a 512 × 512 px ${term("Chip")} of NAIP imagery (0.6 m, about 300 m across) plus the ${term("Reference Label", "Reference Labels")} a good ${term("Caption")} would agree with. Positives are cut around a USGS solar site or wind turbine; negatives are places USGS has nothing near. OSM adds roads, buildings, water, and land use.`,
    why: `Grounding needs something true to compare Claims against. The labels come from ${term("Answer Key", "Answer Keys")} (USGS, OSM) and are hidden from the Harness (ADR-0006): a Harness that could read them would score well by copying.`,
    code: ["uv run clayzer case uspvdb <site-id>", "src/clayzer/cases.py", "src/clayzer/answer_keys.py"],
    tasks: ["dev-cases", "lookalike-negatives", "fixtures", "texas-cases"],
  },
  {
    key: "harness", title: "Harness", sub: "Chip in, Caption out", area: "Captioning",
    what: `The ${term("Harness")} is the system under test. Today it's one Nova Pro call that sees only the Chip and returns a Caption: free text plus structured ${term("Claim", "Claims")}, each an object, a count, a cell of the 3×3 grid, and relations from a fixed vocabulary (ADR-0007).`,
    why: "Claims in a fixed format are what make grounding checkable by code; the text is the training data for Clay v2.",
    code: ["src/clayzer/harness.py", "caption-plan.md §5.2 (Caption format)"],
    tasks: ["skeleton", "prompt-loop", "second-captioner"],
  },
  {
    key: "verify", title: "Verify, then write", sub: "check Claims before committing", area: "Captioning",
    what: "Planned: the Harness drafts Claims, checks each with LGND Geo's imagery check at its grid cell over MCP, and writes the Caption only from Claims that passed; the rest go in “uncertain”.",
    why: "Fewer false Claims means better grounding, and verification calls show up in the Trace, so the Run gets a Workflow Score. The verifier is never an Answer Key and never used to score.",
    code: ["caption-plan.md §1.3", "LGND Geo: reasoning_imagery_check"],
    tasks: ["lgnd-client", "verify-then-write"],
  },
  {
    key: "score", title: "Score", sub: "five criteria, each on its own", area: "Evaluation",
    what: "Grounding compares Claims with Reference Labels in code, as two numbers: correctness (of what the Caption claimed, how much is right: precision, count, position, attributes, relations) and coverage (how much of the Answer Key it mentions). Fidelity: Opus 5.5 looks at the image and the Caption. Retrieval: can a text query (“find solar farms”) find the right Caption, using Titan embeddings. Plus label preparation time and cost (partial on Bedrock).",
    why: "These are Clay's five rubric criteria. Weights aren't set, so each is reported separately. Grounding is split so a terse-but-right Caption and a detailed-but-sloppy one look different instead of averaging to the same number.",
    code: ["src/clayzer/grounding.py", "src/clayzer/judge.py", "src/clayzer/retrieval.py"],
    tasks: ["grounding-fix", "rsicd", "label-prep", "workflow-score"],
  },
  {
    key: "batch", title: "Batch", sub: "every Case × Repeats", area: "Evaluation",
    what: `A ${term("Run")} is one Harness execution on one Case. A ${term("Batch")} runs every Case several times (${term("Repeat", "Repeats")}) under one fixed configuration, and reports each Case's mean and ${term("Spread")}.`,
    why: "Captions differ from Run to Run: Pine Tree Solar scored 0.70, 0.43, and 0.88 in three identical Runs. One Run can't tell a better prompt from luck.",
    code: ["uv run clayzer batch --repeats 3 --label <change>", "src/clayzer/batch.py"],
    tasks: ["eval-loop"],
  },
  {
    key: "compare", title: "Compare", sub: "what changed, by how much", area: "Evaluation",
    what: "Two Batches side by side: which settings differ (prompt, model…), and the change in every criterion, overall and per Case, next to the Spread.",
    why: "A change only counts if it moves scores by more than run-to-run variation. A different Judge or Case set is flagged: those change the measuring stick, not the captioner.",
    code: ["uv run clayzer compare <a> <b>", "src/clayzer/gate.py"],
    tasks: ["eval-loop"],
  },
  {
    key: "gate", title: "Regression gate", sub: "keep or reject the change", area: "Evaluation",
    what: `The candidate Batch against the accepted ${term("Baseline")}. A Case regresses when its correctness, coverage, or fidelity drops more than max(0.05, the Baseline's Spread). Exit 0 pass, 1 fail, 2 inconclusive (Sandbox Failures).`,
    why: "This is the improvement loop the pitch rests on: every change to the captioner is measured and kept only if nothing got worse.",
    code: ["uv run clayzer baseline accept <id>", "uv run clayzer gate <id>"],
    tasks: ["eval-loop", "gate-rule"],
  },
];

function stepState(step, tasks) {
  const mine = tasks.filter((t) => step.tasks.includes(t.id));
  if (mine.length && mine.every((t) => t.status === "done")) return ["built", "#2f6b3a"];
  if (mine.some((t) => ["done", "doing"].includes(t.status))) return ["partly built", "#8a5b0e"];
  return ["not built", "#b9b0ab"];
}

// ── Pages ────────────────────────────────────────────────────────────────────────────────

async function overview() {
  const me = SEQ;
  const o = await api("/api/overview");
  if (stale(me)) return;
  const tasks = o.tasks;
  const must = tasks.filter((t) => t.tier === "Must");
  const mustDone = must.filter((t) => t.status === "done").length;
  const decide = tasks.filter((t) => t.status === "decide");
  const L = o.latest, B = o.baseline;
  const card = (title, big, note, cls = "") =>
    `<div class="card ${cls}"><small>${esc(title)}</small><div class="big">${big}</div><small>${note}</small></div>`;

  $view.innerHTML = `
    <h1>What we're building</h1>
    <p>A caption generator for the text-native Clay v2 model, and the evaluation loop that proves it
    gets measurably better: every change is a new ${term("Batch")}, scored on Clay's five criteria and
    kept only if the regression gate passes. Click a step to see what it is, why it's there, where it
    lives in the code, and what's left to do.</p>
    <div class="flow" id="flow">${FLOW.map((s, i) => {
      const [label, color] = stepState(s, tasks);
      return `<button class="${AREA_CLASS[s.area]}" data-i="${i}" aria-pressed="${i === 0}">
        <span class="dot" style="background:${color}" title="${label}"></span>
        <b>${i + 1}. ${esc(s.title)}</b><small>${esc(s.sub)}</small><small>${esc(s.area)}</small></button>`;
    }).join("")}</div>
    <div class="legend"><span><i style="background:#2f6b3a"></i>built</span>
      <span><i style="background:#8a5b0e"></i>partly built</span>
      <span><i style="background:#b9b0ab"></i>not built</span>
      <span>Colours are the functional areas (caption-plan.md §4).</span></div>
    <div id="step"></div>

    <h2>Where we are</h2>
    <div class="cards">
      ${card("Must tasks done", `${mustDone} / ${must.length}`,
        `<div class="progress"><span style="width:${must.length ? (100 * mustDone) / must.length : 0}%"></span></div>`, "data")}
      ${card("Cases", o.cases, "development Cases in the store; the plan needs ~60", "data")}
      ${L ? card("Latest grounding: correctness · coverage", `${f2(L.correctness)} · ${f2(L.coverage)}`, `<a href="#/batches/${esc(L.batch_id)}">${esc(L.batch_id)}</a>`) : card("Latest Batch", "—", "none yet")}
      ${L ? card("Latest fidelity · retrieval", `${f2(L.fidelity)} · ${f2(L.retrieval?.mean)}`, `${L.cases} Cases × ${L.repeats} Repeats`) : ""}
      ${B ? card("Baseline: correctness · coverage", `${f2(B.correctness)} · ${f2(B.coverage)}`, `${esc(B.batch_id)} · ${B.cases} Cases × ${B.repeats}`, "platform") : card("Baseline", "—", "none accepted yet", "platform")}
    </div>
    ${decide.length ? `<h2>Waiting on a team decision</h2>
      <table><tr><th>Task</th><th>Area</th><th>What's open</th></tr>
      ${decide.map((t) => `<tr><td><b>${esc(t.title)}</b></td><td>${esc(t.area)}</td><td>${esc(t.notes || "")}</td></tr>`).join("")}
      </table>` : ""}
    <p class="sub">Next: see <a href="#/tasks">Tasks</a> for everything left, by functional area.</p>`;

  const show = (i) => {
    const s = FLOW[i];
    const mine = tasks.filter((t) => s.tasks.includes(t.id));
    document.querySelectorAll("#flow button").forEach((b) => b.setAttribute("aria-pressed", String(+b.dataset.i === i)));
    document.getElementById("step").innerHTML = `<div class="panel">
      <div><h2 style="margin-top:0">${i + 1}. ${esc(s.title)}</h2>
        <h3>What it is</h3><p>${s.what}</p>
        <h3>Why it's there</h3><p>${s.why}</p>
        <h3>Where it lives</h3><p>${s.code.map((c) => `<code>${esc(c)}</code>`).join("<br>")}</p></div>
      <div><h3>Tasks for this step</h3>
        ${mine.map((t) => `<p>${statusBadge(t.status)} <span class="badge b-na">${esc(t.tier)}</span><br>${esc(t.title)}</p>`).join("") || '<p class="sub">None listed.</p>'}
      </div></div>`;
  };
  document.querySelectorAll("#flow button").forEach((b) => b.addEventListener("click", () => show(+b.dataset.i)));
  show(0);
}

async function tasksPage() {
  const me = SEQ;
  const tasks = await api("/api/tasks");
  if (stale(me)) return;
  const byId = Object.fromEntries(tasks.map((t) => [t.id, t]));
  const state = { tier: "", status: "open" };
  const render = () => {
    const keep = (t) =>
      (!state.tier || t.tier === state.tier) &&
      (state.status === "all" || (state.status === "open" ? t.status !== "done" : t.status === state.status));
    const blockedBy = (t) => (t.after || []).filter((id) => byId[id] && byId[id].status !== "done");
    document.getElementById("areas").innerHTML = AREAS.map((area) => {
      const all = tasks.filter((t) => t.area === area);
      const shown = all.filter(keep);
      const done = all.filter((t) => t.status === "done").length;
      return `<section class="area"><header class="${AREA_CLASS[area]}"><span>${esc(area)}</span>
        <small>${done}/${all.length} done</small></header>
        ${shown.map((t) => {
          const wait = blockedBy(t);
          return `<div class="task ${t.status === "done" ? "done" : ""}">
            <div class="t">${esc(t.title)}</div>
            <div class="meta">${statusBadge(t.status)} <span class="badge b-na">${esc(t.tier)}</span>
              <span class="ids">${(t.closes || []).map((c) => `<code>${esc(c)}</code>`).join("")}</span></div>
            ${t.notes ? `<div class="sub">${esc(t.notes)}</div>` : ""}
            ${wait.length ? `<div class="sub">After: ${wait.map((id) => esc(byId[id].title)).join("; ")}</div>` : ""}
            <div class="start">Start: <span class="mono">${esc(t.start || "")}</span>
              · Owner: ${esc(t.owner || "open")}</div></div>`;
        }).join("") || '<div class="task sub">Nothing matches the filter.</div>'}</section>`;
    }).join("");
  };
  $view.innerHTML = `<h1>Tasks</h1>
    <p>Everything left to finish the hackathon project, by functional area. Pick one that isn't
    waiting on another, put your name in <code>docs/tasks.toml</code>, and open a PR. The ids are the
    requirements a task closes (<a href="#/concepts">Concepts</a> explains them).</p>
    <div class="filters">
      <label>Tier <select id="tier"><option value="">all</option><option>Must</option><option>Should</option><option>Could</option></select></label>
      <label>Status <select id="status"><option value="open">not done</option><option value="all">all</option>
        <option value="decide">needs a decision</option><option value="doing">in progress</option>
        <option value="todo">to do</option><option value="blocked">blocked</option><option value="done">done</option></select></label>
    </div><div class="areas" id="areas"></div>`;
  document.getElementById("tier").addEventListener("change", (e) => { state.tier = e.target.value; render(); });
  document.getElementById("status").addEventListener("change", (e) => { state.status = e.target.value; render(); });
  render();
}

async function casesPage() {
  const me = SEQ;
  const cases = await api("/api/cases");
  if (stale(me)) return;
  $view.innerHTML = `<h1>Cases</h1>
    <p>The development ${term("Case")} set in the store (${cases.length}). Each Chip's ${term("Reference Label", "Reference Labels")}
    are what grounding checks Claims against; the Harness never sees them (ADR-0006).</p>
    ${cases.length ? "" : '<p class="empty">No Cases yet: <code>uv run clayzer case uspvdb &lt;site-id&gt;</code></p>'}
    <div class="case-grid">${cases.map((c) => `<div class="case-card">
      <img src="/api/chips/${encodeURIComponent(c.chip.id)}.png" alt="Chip ${esc(c.chip.id)}" loading="lazy">
      <div class="body"><b>${esc(c.id)}</b><br><small class="mono">${esc(c.chip.id)} · NAIP ${esc(c.chip.date)} · ${esc(c.chip.source)}</small>
      <ul>${c.labels.map((l) => `<li>${l.count !== null ? `${esc(l.count)} × ` : ""}${esc(l.object.replace(/_/g, " "))}
        at ${esc(l.position)} <small>(${esc(l.source)})</small></li>`).join("") || "<li>no labels</li>"}</ul>
      <small>Built in ${f2(c.prep_seconds)} s</small></div></div>`).join("")}</div>`;
}

async function batchesPage() {
  const me = SEQ;
  const [list, jobs] = await Promise.all([api("/api/batches"), api("/api/jobs")]);
  if (stale(me)) return;
  const running = jobs.filter((j) => j.state === "running");
  $view.innerHTML = `<h1>Batches</h1>
    <p>Every ${term("Batch")} in the store, newest first. Tick two to compare them; open one to see its
    report and its regression gate against the ${term("Baseline")}.</p>
    ${CONFIG.allow_launch ? `<div class="launch"><b>Run a Batch</b> on every Case in the store
      (${esc(CONFIG.caption_model)}, judged by ${esc(CONFIG.judge_model)}).<br>
      <label>Repeats <input id="repeats" type="number" min="1" max="10" value="3" style="width:60px"></label>
      <label>Label <input id="label" placeholder="what changed" maxlength="40"></label>
      <label><input id="judge" type="checkbox" checked> Judge fidelity</label>
      <button class="btn" id="go" ${running.length ? "disabled" : ""}>Run</button>
      <div id="joblog"></div></div>`
      : `<p class="sub">Read-only. Start the app with <code>--allow-launch</code> to run Batches from here; or <code>uv run clayzer batch</code>.</p>`}
    <p><button class="btn secondary" id="cmp" disabled>Compare the two ticked</button></p>
    <table><tr><th></th><th>Batch</th><th>Size</th><th class="num">Correctness</th><th class="num">Coverage</th><th class="num">Fidelity</th>
      <th class="num">Retrieval</th><th>Runs</th><th>Captioner</th></tr>
    ${list.map((b) => `<tr><td><input type="checkbox" class="pick" value="${esc(b.batch_id)}"></td>
      <td><a href="#/batches/${esc(b.batch_id)}">${esc(b.batch_id)}</a>${b.complete ? "" : ' <span class="badge b-warn">incomplete</span>'}</td>
      <td>${b.cases} × ${b.repeats}</td><td class="num">${badge(b.correctness)}</td><td class="num">${badge(b.coverage)}</td><td class="num">${badge(b.fidelity)}</td>
      <td class="num">${badge(b.retrieval?.mean)}</td>
      <td><small>${b.runs ? `${b.runs.ok} ok · ${b.runs.harness_faults} HF · ${b.runs.sandbox_failures} SF` : "running"}</small></td>
      <td><small class="mono">${esc(b.caption_model)} · prompt ${esc(b.prompt_sha)}</small></td></tr>`).join("")}
    </table>${list.length ? "" : '<p class="empty">No Batches yet.</p>'}`;

  const picks = () => [...document.querySelectorAll(".pick:checked")].map((x) => x.value);
  document.querySelectorAll(".pick").forEach((x) => x.addEventListener("change", () => {
    document.getElementById("cmp").disabled = picks().length !== 2;
  }));
  document.getElementById("cmp").addEventListener("click", () => {
    const [b, a] = picks(); // list is newest first, so the older one is A
    location.hash = `#/compare/${encodeURIComponent(a)}/${encodeURIComponent(b)}`;
  });
  if (CONFIG.allow_launch) {
    document.getElementById("go").addEventListener("click", async () => {
      const body = {
        repeats: +document.getElementById("repeats").value,
        label: document.getElementById("label").value,
        judge: document.getElementById("judge").checked,
      };
      try {
        await api("/api/batches", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
        pollJobs();
      } catch (e) { document.getElementById("joblog").textContent = e.message; }
    });
    if (running.length) pollJobs();
  }
}

let polling = null;
async function pollJobs() {
  clearTimeout(polling);
  const log = document.getElementById("joblog");
  if (!log) return;
  const jobs = await api("/api/jobs");
  const job = jobs.at(-1);
  if (!job) return;
  log.innerHTML = `<p><b>${esc(job.batch_id)}</b> · ${esc(job.state)}</p><div class="log mono"></div>`;
  log.querySelector(".log").textContent = job.lines.join("\n");
  if (job.state === "running") polling = setTimeout(pollJobs, 3000);
  else setTimeout(route, 1500);
}

async function batchPage(id) {
  const me = SEQ;
  const b = await api(`/api/batches/${encodeURIComponent(id)}`);
  let gateHtml = "";
  try {
    const g = await api(`/api/gate/${encodeURIComponent(id)}`);
    const cls = { pass: "b-ok", fail: "b-bad", inconclusive: "b-warn" }[g.verdict];
    gateHtml = `<h2>Regression gate against the Baseline</h2>
      <p><span class="badge ${cls} verdict">${esc(g.verdict.toUpperCase())}</span>
      <small> exit ${g.exit_code} · Baseline ${esc(g.baseline_id)}</small></p>
      ${g.reasons.map((r) => `<p>${esc(r)}</p>`).join("")}
      ${g.warnings.map((w) => `<p class="sub">Warning: ${esc(w)}</p>`).join("")}
      <table><tr><th>Case</th><th>Metric</th><th class="num">Baseline</th><th class="num">Candidate</th>
        <th class="num">Allowed drop</th><th>Status</th></tr>
      ${g.checks.map((c) => `<tr><td>${esc(c.case_id)}</td><td>${esc(c.metric)}</td><td class="num">${f2(c.baseline)}</td>
        <td class="num">${f2(c.candidate)}</td><td class="num">${f2(c.allowed_drop)}</td>
        <td>${{ ok: '<span class="badge b-na">ok</span>', improved: '<span class="badge b-ok">improved</span>',
                regressed: '<span class="badge b-bad">regressed</span>', missing: '<span class="badge b-bad">missing</span>',
                "n/a": '<span class="badge b-na">n/a</span>' }[c.status]}</td></tr>`).join("")}</table>`;
  } catch (e) {
    gateHtml = `<p class="sub">Regression gate: ${esc(e.message)}</p>`;
  }
  if (stale(me)) return;
  const c = b.config;
  $view.innerHTML = `<p><a href="#/batches">← Batches</a></p><h1>${esc(c.batch_id)}</h1>
    <p class="sub">${c.case_ids.length} Cases × ${c.repeats} Repeats · ${esc(c.caption_model)} · prompt
    <code>${esc(c.prompt_sha)}</code> (${esc(c.prompt_source)}) · Judge ${esc(c.judge_model || "off")} · Cases
    <code>${esc(c.cases_sha)}</code></p>
    ${gateHtml}
    <h2>Report</h2>
    <p class="sub">The same self-contained report the CLI writes; <a href="/api/batches/${encodeURIComponent(id)}/report.html" target="_blank">open it on its own</a>.</p>
    <iframe class="report" sandbox="allow-scripts" src="/api/batches/${encodeURIComponent(id)}/report.html" title="Batch report"></iframe>`;
}

async function comparePage(a, b) {
  const me = SEQ;
  const c = await api(`/api/compare?a=${encodeURIComponent(a)}&b=${encodeURIComponent(b)}`);
  if (stale(me)) return;
  const delta = (d, spread) => {
    if (d === null || d === undefined) return "—";
    const big = spread !== null && spread !== undefined && Math.abs(d) > Math.max(0.05, spread);
    const cls = !big ? "b-na" : d > 0 ? "b-ok" : "b-bad";
    return `<span class="badge ${cls}">${d > 0 ? "+" : ""}${f2(d)}</span>`;
  };
  $view.innerHTML = `<p><a href="#/batches">← Batches</a></p><h1>Compare</h1>
    <p class="mono">A ${esc(c.a)}<br>B ${esc(c.b)}</p>
    <h2>What changed</h2>
    ${c.settings.length ? `<table><tr><th>Setting</th><th>A</th><th>B</th><th>Kind</th></tr>
      ${c.settings.map((s) => `<tr><td>${esc(s.setting)}</td><td class="mono">${esc(s.a)}</td><td class="mono">${esc(s.b)}</td>
        <td>${s.kind === "measurement" ? '<span class="badge b-warn">measurement: scores may not be comparable</span>' : '<span class="badge b-na">captioner</span>'}</td></tr>`).join("")}</table>`
      : '<p>No settings changed, so any difference is run-to-run variation.</p>'}
    <h2>Batch</h2><table><tr><th>Metric</th><th class="num">A</th><th class="num">B</th><th class="num">Change</th></tr>
      ${c.batch.map((r) => `<tr><td>${esc(r.metric)}</td><td class="num">${f2(r.a)}</td><td class="num">${f2(r.b)}</td>
        <td class="num">${r.delta === null ? "—" : (r.delta > 0 ? "+" : "") + f2(r.delta)}</td></tr>`).join("")}</table>
    <h2>Cases</h2>
    <p class="sub">A change is coloured only when it's bigger than max(0.05, Spread): smaller ones are within run-to-run variation.</p>
    <table><tr><th>Case</th><th>Metric</th><th class="num">A</th><th class="num">B</th><th class="num">Change</th><th class="num">Spread</th></tr>
      ${c.cases.map((r) => `<tr><td>${esc(r.case_id)}</td><td>${esc(r.metric)}</td><td class="num">${f2(r.a)}</td>
        <td class="num">${f2(r.b)}</td><td class="num">${delta(r.delta, r.spread ?? 0)}</td><td class="num">${f2(r.spread)}</td></tr>`).join("")}</table>`;
}

async function conceptsPage() {
  const me = SEQ;
  const terms = await api("/api/glossary");
  if (stale(me)) return;
  const sections = [...new Set(terms.map((t) => t.section))];
  $view.innerHTML = `<h1>Concepts</h1>
    <p>The team's shared vocabulary, from <code>GLOSSARY.md</code>. Capitalized terms on every page mean exactly
    this. Requirement ids: <code>CAP-*</code> are caption requirements (caption-design.md §2.1), <code>REQ-*</code>
    the evaluation loop's (caption-design.md §2.3), <code>AWS-*</code> AWS integration (caption-design.md §2.2).</p>
    ${sections.map((s) => `<h2>${esc(s)}</h2><div class="terms">${terms.filter((t) => t.section === s).map((t) => `
      <div class="term"><b>${esc(t.term)}</b><br>${esc(t.definition)}
      ${t.avoid ? `<br><small>Avoid: ${esc(t.avoid)}</small>` : ""}</div>`).join("")}</div>`).join("")}`;
}

const USE = {
  used: ["b-ok", "used"], partial: ["b-info", "partly used"], planned: ["b-warn", "planned"],
  waiting: ["b-warn", "waiting on Clay"], unused: ["b-na", "not used"],
};
// Escaped text with `backticks` shown as code.
const inline = (s) => esc(s).replace(/`([^`]+)`/g, "<code>$1</code>");
const useBadge = (s) => `<span class="badge ${USE[s]?.[0] || "b-na"}">${esc(USE[s]?.[1] || s)}</span>`;

async function sourcesPage() {
  const me = SEQ;
  const [sources, tasks] = await Promise.all([api("/api/sources"), api("/api/tasks")]);
  if (stale(me)) return;
  const byId = Object.fromEntries(tasks.map((t) => [t.id, t]));
  const groups = [...new Set(sources.map((s) => s.group))];
  const state = { status: "" };
  const link = (url) => (/^https?:\/\//.test(url) ? `<a href="${esc(url)}" target="_blank" rel="noopener">${esc(url)}</a>`
    : url ? `<code>${esc(url)}</code>` : "");
  // `chip:<id>` is a Chip in the store, drawn with the 3×3 grid that positions refer to;
  // anything else is a figure hotlinked from the dataset's own repo, never copied here.
  const shot = (im) => {
    const chip = im.src.startsWith("chip:");
    const src = chip ? `/api/chips/${encodeURIComponent(im.src.slice(5))}.png` : im.src;
    return `<figure class="${chip ? "chip" : "figure"}"><a href="${esc(src)}" target="_blank" rel="noopener">
      <span class="frame"><img src="${esc(src)}" alt="${esc(im.caption)}" loading="lazy" referrerpolicy="no-referrer"
        onerror="this.closest('figure').classList.add('missing')">${chip ? '<span class="grid3"></span>' : ""}</span></a>
      <figcaption>${inline(im.caption)}<span class="gone"> (not available${chip ? " in this store" : ""})</span></figcaption></figure>`;
  };
  const card = (s) => `<article class="source" id="src-${esc(s.id)}">
    <header><b>${esc(s.name)}</b> ${useBadge(s.status)}<br><small>${link(s.url)}${s.url ? " · " : ""}${esc(s.license)}</small></header>
    <div class="cols"><div>
      <h3>What the data is</h3><p>${inline(s.data)}</p>
      <h3>Format</h3><p>${inline(s.format)}</p>
      <h3>Access</h3><p>${inline(s.access)}</p>
      ${s.notes ? `<h3>Notes</h3><p>${inline(s.notes)}</p>` : ""}
    </div><div>
      <h3>Used in Clayzer</h3>
      ${(s.used_in || []).length ? `<ul class="uses">${s.used_in.map((u) => `<li><code>${esc(u.path)}</code>
        <code class="sym">${esc(u.symbol)}</code><br><small>${inline(u.what)}</small></li>`).join("")}</ul>`
        : '<p class="sub">Nowhere in the code yet.</p>'}
      ${(s.tasks || []).length ? `<h3>Tasks</h3>${s.tasks.filter((id) => byId[id]).map((id) =>
        `<p>${statusBadge(byId[id].status)} ${esc(byId[id].title)}</p>`).join("")}` : ""}
    </div></div>
    ${(s.images || []).length ? `<h3>What it looks like</h3><div class="shots">${s.images.map(shot).join("")}</div>` : ""}
    ${s.sample ? `<h3>Sample</h3><pre class="sample mono"></pre><small>${esc(s.sample_from)}</small>` : ""}
  </article>`;
  const render = () => {
    const shown = sources.filter((s) => !state.status || s.status === state.status);
    const list = document.getElementById("sources");
    list.innerHTML = groups.map((g) => {
      const mine = shown.filter((s) => s.group === g);
      return mine.length ? `<h2>${esc(g)}</h2>${mine.map(card).join("")}` : "";
    }).join("") || '<p class="empty">Nothing matches the filter.</p>';
    // Samples are raw JSON and text: set them as text, not HTML.
    shown.forEach((s) => {
      const pre = list.querySelector(`#src-${CSS.escape(s.id)} .sample`);
      if (pre) pre.textContent = s.sample.replace(/^\n/, "");
    });
  };
  const count = (st) => sources.filter((s) => s.status === st).length;
  $view.innerHTML = `<h1>Data sources</h1>
    <p>Every External Dependency in <code>docs/vision-hackathon.md</code>: what kind of data it is, a real
    sample, and whether Clayzer uses it and where. Edit <code>docs/sources.toml</code> in a PR when that
    changes; a test fails if a listed code location stops existing.</p>
    <div class="cards">
      <div class="card"><small>Used</small><div class="big">${count("used")}</div><small>read by the code today</small></div>
      <div class="card platform"><small>Partly used</small><div class="big">${count("partial")}</div><small>some of it, or by the team by hand</small></div>
      <div class="card data"><small>Planned or waiting</small><div class="big">${count("planned") + count("waiting")}</div><small>a task will use it</small></div>
      <div class="card data"><small>Not used</small><div class="big">${count("unused")}</div><small>deliberately, see the notes</small></div>
    </div>
    <div class="filters"><label>Status <select id="use"><option value="">all</option>
      ${Object.entries(USE).map(([k, [, label]]) => `<option value="${k}">${esc(label)}</option>`).join("")}</select></label>
      <span class="sub">Jump to: ${sources.map((s) => `<a href="#/sources" data-to="${esc(s.id)}">${esc(s.name.split(" (")[0])}</a>`).join(" · ")}</span></div>
    <div id="sources"></div>`;
  document.getElementById("use").addEventListener("change", (e) => { state.status = e.target.value; render(); });
  document.querySelectorAll("[data-to]").forEach((a) => a.addEventListener("click", (e) => {
    e.preventDefault();
    document.getElementById(`src-${a.dataset.to}`)?.scrollIntoView({ behavior: "smooth" });
  }));
  render();
}

// ── Router ───────────────────────────────────────────────────────────────────────────────

async function route() {
  const me = ++SEQ;
  const parts = (location.hash.replace(/^#\/?/, "") || "").split("/").map(decodeURIComponent);
  const page = parts[0] || "";
  document.querySelectorAll("#nav a").forEach((a) => {
    const target = a.getAttribute("href").replace(/^#\/?/, "");
    a.toggleAttribute("aria-current", target === page || (page === "compare" && target === "batches"));
    if (a.hasAttribute("aria-current")) a.setAttribute("aria-current", "page");
  });
  $view.innerHTML = '<p class="sub">Loading…</p>';
  try {
    if (page === "") await overview();
    else if (page === "tasks") await tasksPage();
    else if (page === "cases") await casesPage();
    else if (page === "batches" && parts[1]) await batchPage(parts[1]);
    else if (page === "batches") await batchesPage();
    else if (page === "compare") await comparePage(parts[1], parts[2]);
    else if (page === "sources") await sourcesPage();
    else if (page === "concepts") await conceptsPage();
    else $view.innerHTML = '<p class="empty">No such page.</p>';
  } catch (e) {
    if (!stale(me)) $view.innerHTML = `<p class="empty">Couldn't load this page: ${esc(e.message)}</p>`;
  }
}

(async () => {
  CONFIG = await api("/api/config");
  document.getElementById("store").textContent = `store: ${CONFIG.store}`;
  GLOSSARY = Object.fromEntries((await api("/api/glossary")).map((t) => [t.term, t]));
  window.addEventListener("hashchange", route);
  route();
})();
