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
  Platform: "area-platform", "Demo and delivery": "area-delivery",
};
const AREAS = Object.keys(AREA_CLASS);

// ── The workflow, one step at a time ─────────────────────────────────────────────────────

// The phases, in order. `core` marks the brief's "heart of the build": observe, summarize,
// score, report.
const PHASES = [
  { key: "prepare", label: "Prepare" },
  { key: "run", label: "Run" },
  { key: "observe", label: "Observe", core: true },
  { key: "score", label: "Score", core: true },
  { key: "report", label: "Report", core: true },
  { key: "improve", label: "Improve" },
  { key: "ship", label: "Ship" },
];

// Each task in docs/tasks.toml names its step with `step = "<key>"`.
const FLOW = [
  {
    key: "case", phase: "prepare", title: "Case", sub: "a Chip and its Reference Labels", area: "Data and Cases",
    what: `A ${term("Case")} is one unit of work: a 512 × 512 px ${term("Chip")} of NAIP imagery (0.6 m, about 300 m across) plus the ${term("Reference Label", "Reference Labels")} a good ${term("Caption")} would agree with. Positives are cut around a USGS solar site or wind turbine, offset so the site can land in any grid cell; negatives are places USGS has nothing near. OSM adds roads, buildings, water, and land use.`,
    why: `Scoring needs something true to compare against. The labels come from ${term("Answer Key", "Answer Keys")} (USGS, OSM) and are hidden from the Harness (ADR-0006): a Harness that could read them would score well by copying.`,
    code: ["uv run clayzer case uspvdb <site-id>", "src/clayzer/cases.py", "src/clayzer/answer_keys.py"],
    docs: [{ href: "/docs/docs/caption-plan.md#12-where-the-data-goes", label: "Plan §1.2: where the data goes" }, { href: "/docs/docs/caption-plan.md#3-data", label: "Plan §3: data, regions, and selection rules" }, { href: "/docs/docs/caption-plan.md#51-case-format", label: "Plan §5.1: the Case format" }, { href: "/docs/docs/caption-design.md#31-cases-built-from-answer-keys", label: "Design §3.1: Cases built from Answer Keys" }, { href: "/docs/docs/adr/0006-answer-keys-are-hidden-from-caption-inputs.md", label: "ADR-0006: Answer Keys are hidden from the Harness" }],
  },
  {
    key: "harness", phase: "run", title: "Harness", sub: "an agent with geospatial tools", area: "Captioning",
    what: `The ${term("Harness")} is the system under test: the model, its prompt, and its tools. It sees only the Chip and returns a Caption with ${term("Claim", "Claims")} on the 3×3 grid. By default it's one Nova Pro call; with \`--tools\` it's an agent in a plain tool-use loop that can call geospatial tools over MCP before it writes (RODA today; LGND Geo's imagery check and classifiers next), within an 8-turn budget. Only tools on the ADR-0006 list are allowed.`,
    why: "The briefs' first success criterion is a Harness that performs the task by calling geospatial tools via MCP, and tool calls are what give the Workflow Score something to judge. The model sits behind an abstraction so it can be swapped (Nova Pro, Opus 5.5, an open VLM on a GPU).",
    code: ["src/clayzer/harness.py", "src/clayzer/tools.py (MCP servers behind a Toolbox)", "uv run clayzer batch --tools roda", "caption-plan.md §3 (allowed and forbidden MCP servers)"],
    docs: [{ href: "/docs/docs/caption-plan.md#13-how-the-harness-writes-a-caption", label: "Plan §1.3: how the Harness writes a Caption" }, { href: "/docs/docs/caption-plan.md#52-caption-format", label: "Plan §5.2: the Caption format" }, { href: "/docs/docs/caption-design.md#32-caption-harness", label: "Design §3.2: the caption Harness" }, { href: "/docs/docs/adr/0002-reference-harness-is-a-plain-loop.md", label: "ADR-0002: the Harness is a plain loop" }, { href: "/docs/docs/adr/0007-claims-use-a-grid-and-a-fixed-relation-vocabulary.md", label: "ADR-0007: Claims use a 3×3 grid" }],
  },
  {
    key: "capture", phase: "observe", title: "Capture", sub: "record every Step in a Trace", area: "Platform",
    what: `Every ${term("Run")} is recorded as a ${term("Trace")}: one ${term("Step")} per model turn or tool call, in order, with its arguments, result, failures and retries, latency, and cost. For captions, cost means GPU time and GPU count and size, not tokens; Bedrock only reports time and tokens, so cost stays partial there. Traces are kept in the store, so a Run can be judged later without running it again.`,
    why: "Clay's ask is to evaluate agentic workflows, and what isn't recorded can't be evaluated. Every model call is now a Step with its full prompt and response, timing, tokens, retries, and error codes, and Judge calls are marked as scoring. Each failed Step is attributed (ADR-0003): a Harness Fault counts against the Harness, an Environment Fault (throttling, network, access) doesn't, and a failed Judge is a Sandbox Failure. Tool-call Steps arrive with the agentic Harness. The Trace format is ours and OpenTelemetry is an export (ADR-0001), so the tracing tool stays swappable.",
    code: ["batches/<batch-id>/traces/<case-id>--r<repeat>.jsonl", "src/clayzer/trace.py", "uv run clayzer trace <batch-id> <case-id>", "ADR-0001 (Trace format), ADR-0003 (fault attribution)"],
    docs: [{ href: "/docs/docs/caption-design.md#23-evaluation-loop-requirements", label: "Design §2.3: the loop's requirements (REQ-04)" }, { href: "/docs/docs/adr/0001-own-trace-format-otel-is-an-export.md", label: "ADR-0001: our own Trace format" }, { href: "/docs/docs/adr/0003-errors-are-attributed-to-harness-or-environment.md", label: "ADR-0003: fault attribution" }, { href: "/docs/docs/caption-plan.md#aws-service-tasks", label: "Plan §7: AWS service tasks (observability)" }],
  },
  {
    key: "summarize", phase: "observe", title: "Summarize", sub: "what the agent did, where it struggled", area: "Platform",
    what: "Each Trace becomes a short, readable account of the Run: what the Harness did, where it struggled and whose fault, and a one-line verdict. A model writes it from the Trace alone, once, and it's saved so replays never call a model; the code-written facts sit under it and stand in when there's no narrative. A narrative that names a fault the Trace doesn't have is rejected.",
    why: "Clay's explicit ask is to “summarize traces from agentic activity”. A summary is what a person reads before trusting a score, and what a Proposer would read to suggest the next change.",
    code: ["src/clayzer/summarize.py (facts, in code)", "src/clayzer/narrate.py (narrative, by a model)", "uv run clayzer summarize <batch-id> [--narrate]", "uv run clayzer trace <batch-id> <case-id>"],
    docs: [{ href: "/docs/docs/caption-design.md#23-evaluation-loop-requirements", label: "Design §2.3: the loop's requirements (REQ-05)" }, { href: "/docs/docs/adr/0001-own-trace-format-otel-is-an-export.md", label: "ADR-0001: our own Trace format" }],
  },
  {
    key: "workflow", phase: "score", title: "Workflow Score", sub: "how it worked, from the Trace", area: "Evaluation",
    what: `The first of the brief's two scores: how well the Harness worked, judged from its Trace alone and without a model call. Were the right tools called in a sensible order, were failed calls recovered, and how many Steps and how much cost did it take against the Case's budget? ${term("Environment Fault", "Environment Faults")} (network, access) don't count against it; ${term("Harness Fault", "Harness Faults")} do.`,
    why: "A Caption can come out right by luck or by a wasteful path. The Workflow Score tells them apart. Parts that don't apply are left out: until the Harness calls tools, a Run scores on finishing alone.",
    code: ["src/clayzer/workflow.py", "ADR-0003 (fault attribution)", "the Sandbox's scoring/workflow.py (same parts and weights)"],
    docs: [{ href: "/docs/docs/caption-design.md#23-evaluation-loop-requirements", label: "Design §2.3: the loop's requirements (REQ-06)" }, { href: "/docs/docs/adr/0003-errors-are-attributed-to-harness-or-environment.md", label: "ADR-0003: fault attribution" }],
  },
  {
    key: "output", phase: "score", title: "Output Score", sub: "what it produced, on five criteria", area: "Evaluation",
    what: "The second score: the final Caption against references, on Clay's five criteria, each reported on its own. Grounding is two numbers against the Answer Keys: correctness (of what was claimed, how much is right) and coverage (how much of the Answer Key was mentioned). Fidelity: Opus 5.5 looks at the image and the Caption. Retrieval: can a text query find the right Caption, with Titan embeddings. Plus label preparation time and cost. Clay's example captions and retrieval set slot in when they arrive; RSICD and VRSBench add outside benchmarks.",
    why: "Grounding is the criterion Clay ranked most important. It's split in two so a terse-but-right Caption and a detailed-but-sloppy one look different instead of averaging to the same number.",
    code: ["src/clayzer/grounding.py", "src/clayzer/judge.py", "src/clayzer/retrieval.py"],
    docs: [{ href: "/docs/docs/caption-plan.md#14-how-a-caption-is-scored", label: "Plan §1.4: how a Caption is scored" }, { href: "/docs/docs/caption-design.md#the-five-rubric-criteria", label: "Design §2: Clay's five rubric criteria" }, { href: "/docs/docs/caption-design.md#33-scoring-the-five-criteria", label: "Design §3.3: scoring the five criteria" }, { href: "/docs/docs/caption-plan.md#8-risks", label: "Plan §8: scoring risks and decisions" }, { href: "/docs/docs/adr/0007-claims-use-a-grid-and-a-fixed-relation-vocabulary.md", label: "ADR-0007: Claims use a 3×3 grid" }],
  },
  {
    key: "report", phase: "report", title: "Report", sub: "summary and both scores, per Run", area: "Platform",
    what: "One evaluation report per Run, in HTML for people and JSON for machines, that puts its Trace summary, scores with their reasons, Steps, and Caption together; Batch reports roll the Runs up and link to each one. The Workflow Score joins it once it exists. If the live Harness misbehaves, recorded Traces and Captions are replayed through scoring, so a report, and the demo, never depend on a live run.",
    why: "The report is what a practitioner or partner reads. The replay fallback is a brief Must: it keeps the demo safe.",
    code: ["src/clayzer/report_html.py", "uv run clayzer rescore <batch-id> (replays stored Captions through scoring)", "uv run clayzer ui"],
    docs: [{ href: "/docs/docs/caption-design.md#23-evaluation-loop-requirements", label: "Design §2.3: the loop's requirements (REQ-08, REQ-09)" }, { href: "/docs/docs/caption-plan.md#day-2-build", label: "Plan §7: Day 2 and the demo freeze" }],
  },
  {
    key: "batch", phase: "improve", title: "Batch & Compare", sub: "every Case × Repeats, side by side", area: "Evaluation",
    what: `A ${term("Batch")} runs every Case several times (${term("Repeat", "Repeats")}) under one fixed configuration and reports each Case's mean and ${term("Spread")}. Compare puts two Batches side by side: which settings differ (prompt, model, tools), and how every criterion moved, overall and per Case.`,
    why: "Captions differ from Run to Run: Pine Tree Solar scored 0.70, 0.43, and 0.88 in three identical Runs. One Run can't tell a better prompt from luck.",
    code: ["uv run clayzer batch --repeats 3 --label <change>", "uv run clayzer compare <a> <b>", "src/clayzer/batch.py"],
    docs: [{ href: "/docs/docs/caption-plan.md#6-approach", label: "Plan §6: approach and order of work" }, { href: "/docs/docs/caption-plan.md#10-decisions-behind-this-plan", label: "Plan §10: decisions behind the plan" }],
  },
  {
    key: "gate", phase: "improve", title: "Regression gate", sub: "keep or reject the change", area: "Evaluation",
    what: `The candidate Batch against the accepted ${term("Baseline")}. A Case regresses when its correctness, coverage, or fidelity drops more than max(0.05, the Baseline's Spread). Exit 0 pass, 1 fail, 2 inconclusive. Next, saved for later: a Proposer that reads a failure digest, proposes one change to the prompt, model, or tools, and lets the gate decide.`,
    why: "This is the improvement loop the pitch rests on: every change to the captioner is measured and kept only if nothing got worse.",
    code: ["uv run clayzer baseline accept <id>", "uv run clayzer gate <id>", "src/clayzer/gate.py"],
    docs: [{ href: "/docs/docs/caption-plan.md#6-approach", label: "Plan §6: the improvement loop" }, { href: "/docs/docs/caption-plan.md#8-risks", label: "Plan §8: the gate's rules and their risks" }, { href: "/docs/docs/caption-plan.md#10-decisions-behind-this-plan", label: "Plan §10: decisions" }],
  },
  {
    key: "ship", phase: "ship", title: "Ship", sub: "AWS, demo, readiness", area: "Demo and delivery",
    what: "Put it where Clay can use it: least-privilege IAM, a CDK stack any teammate can deploy, the app at a live URL, a GPU quota for open VLMs, the demo Stories, the questions for Clay, and a readiness check (no disallowed services, licenses respected, nothing secret committed).",
    why: "The judges score technical execution and AWS integration, and Clay needs to run this after the event.",
    code: ["caption-plan.md §7 (AWS service tasks)", "README.md"],
    docs: [{ href: "/docs/docs/caption-plan.md#7-timeline", label: "Plan §7: timeline and AWS service tasks" }, { href: "/docs/docs/caption-design.md#34-aws-services", label: "Design §3.4: AWS services" }, { href: "/docs/docs/caption-design.md#22-aws-integration-requirements", label: "Design §2.2: AWS requirements" }],
  },
];

function stepState(step, tasks) {
  const mine = tasks.filter((t) => t.step === step.key);
  if (mine.length && mine.every((t) => t.status === "done")) return ["built", "#2f6b3a"];
  if (mine.some((t) => ["done", "doing"].includes(t.status))) return ["partly built", "#8a5b0e"];
  return ["not built", "#b9b0ab"];
}

// ── Pages ────────────────────────────────────────────────────────────────────────────────

// ── Home page pieces ─────────────────────────────────────────────────────────────────────

const pct = (x) => (x === null || x === undefined ? "—" : `${Math.round(100 * x)}%`);
const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;

// The home page's scorecard follows Clay's rubric: five criteria, in the brief's order, each
// reported on its own because weights aren't set (CAP-15).
function meter(label, value, note) {
  const w = value === null || value === undefined ? 0 : Math.max(2, Math.round(100 * value));
  return `<div class="meter">
    ${label ? `<div class="meter-q">${esc(label)}</div>` : ""}
    <div class="meter-row"><div class="meter-bar" role="img" aria-label="${pct(value)}"><span style="width:${w}%"></span></div>
      <b>${pct(value)}</b></div>
    <div class="meter-a">${note}</div></div>`;
}

function criterion(n, name, question, body, tag = "") {
  return `<div class="crit">
    <div class="crit-head"><span class="crit-n">${n}</span><span class="crit-name">${esc(name)}</span>${tag}</div>
    <div class="crit-q">${esc(question)}</div>${body}</div>`;
}

function scorecard(B) {
  const secs = (x) => (x === null || x === undefined ? "—" : `${x.toFixed(1)} s`);
  const grounding = criterion(1, "Grounding", "Does the caption match what's on the ground?",
    meter("Right", B.correctness, "of what the captions claim checks out against the map (USGS, OSM)") +
    meter("Enough", B.coverage, "of what the map shows gets mentioned") +
    (B.unscored_share ? `<p class="crit-note">${pct(B.unscored_share)} of claims are about things no map covers yet (like vegetation), so they aren't scored.</p>` : ""),
    '<span class="badge b-warn">most important</span>');
  const fidelity = criterion(2, "Fidelity", "Would a reviewer agree with the caption?",
    meter("", B.fidelity, "the Judge's rating of each caption against its image"));
  const retrieval = criterion(3, "Retrieval quality", "Can you find the right caption by searching for it?",
    meter("", B.retrieval_top1, `of searches put the right caption first <span class="sub">· ranking score (MRR) ${pct(B.retrieval?.mean)}</span>`));
  const cost = criterion(4, "Cost", "How fast is captioning, and on what hardware?",
    `<div class="figure"><b>${secs(B.seconds_per_caption)}</b> per caption</div>
     <p class="crit-note">Partial: Clay measures cost in GPU time and GPU count and size, which Bedrock
     doesn't report. It comes with the open-VLM endpoint. (${B.tokens_per_caption ? Math.round(B.tokens_per_caption).toLocaleString() : "—"} tokens per caption, not the rubric's measure.)</p>`,
    '<span class="badge b-na">partial</span>');
  const prep = criterion(5, "Label preparation time", "How long does it take to prepare the labels?",
    `<div class="figure"><b>≈ ${secs(B.label_prep_seconds_per_case)}</b> per Case
       <span class="sub">(${secs(B.label_prep_seconds)} for ${plural(B.cases, "Case")})</span></div>
     <p class="crit-note">Time to build each Case's Reference Labels. Whether Clay means this or the time to
     write the Captions is a question for Clay.</p>`);
  const how = `<div class="crit how-worked">
    <div class="crit-head"><span class="crit-n">+</span><span class="crit-name">And how it worked</span></div>
    <div class="crit-q">Did the Harness work well, judged from its Trace?</div>
    ${B.workflow === null || B.workflow === undefined
      ? `<p class="crit-note">No Workflow Score yet: the Baseline was run before Traces were recorded.</p>`
      : meter("", B.workflow, `Workflow Score: finished, tool calls right and recovered, within budget${(B.tools || []).length ? "" : ". With no tools, only completion counts"}`)}
    <p class="crit-note">The brief's second score dimension, beside Clay's five criteria (REQ-06).</p></div>`;
  return grounding + fidelity + retrieval + cost + prep + how;
}

// A Chip with its Claims drawn on the 3×3 grid, like the Batch report.
const CELLS = ["north_west", "north", "north_east", "west", "centre", "east", "south_west", "south", "south_east"];
function chipFigure(sc) {
  const C = 512 / 3;
  const per = {};
  const pills = sc.claims.map((c) => {
    const i = CELLS.indexOf(c.position);
    if (i < 0) return "";
    const n = (per[c.position] = (per[c.position] || 0) + 1) - 1;
    const x = (i % 3) * C + 8, y = Math.floor(i / 3) * C + 10 + n * 26;
    const cls = c.verdict !== "matched" ? "bad" : c.position_score === 1 ? "good" : "near";
    const label = `${c.count} × ${c.object.replace(/_/g, " ")}`;
    return `<g class="pill ${cls}"><rect x="${x}" y="${y}" width="${C - 16}" height="22" rx="11"/>
      <text x="${x + (C - 16) / 2}" y="${y + 15}" text-anchor="middle">${esc(label)}</text></g>`;
  }).join("");
  const covered = new Set(sc.labels.flatMap((l) => l.cells));
  const refs = [...covered].map((cell) => {
    const i = CELLS.indexOf(cell);
    return `<rect class="ref" x="${(i % 3) * C + 3}" y="${Math.floor(i / 3) * C + 3}" width="${C - 6}" height="${C - 6}" rx="4"/>`;
  }).join("");
  const grid = [1, 2].map((k) => `<line x1="${k * C}" y1="0" x2="${k * C}" y2="512"/><line x1="0" y1="${k * C}" x2="512" y2="${k * C}"/>`).join("");
  return `<div class="chip-fig">
    <img src="/api/chips/${encodeURIComponent(sc.chip.id)}.png" alt="Aerial image ${esc(sc.chip.id)}">
    <svg viewBox="0 0 512 512" aria-hidden="true"><g class="grid">${grid}</g><g>${refs}</g>${pills}</svg></div>`;
}

function showcaseCard(list, i, batchId = "") {
  if (!list.length) {
    return `<div class="showcase empty">Run a Batch and accept it as the Baseline to see a featured Caption here.</div>`;
  }
  const sc = list[i % list.length];
  const missed = sc.missed.map((m) => m.replace(/_/g, " "));
  return `<div class="showcase">
    <div class="showcase-head"><span class="kicker">A caption from the Baseline</span>
      <span class="showcase-nav">${i % list.length + 1} of ${list.length}
        <button type="button" class="btn secondary" id="sc-next" aria-label="Show another caption">Show another →</button></span></div>
    ${chipFigure(sc)}
    <blockquote>${esc(sc.text)}</blockquote>
    <p class="showcase-score"><b>${sc.right} of ${sc.gradable}</b> Claims check out exactly
      ${missed.length ? `· missed: ${esc(missed.join(", "))}` : "· nothing missed"}</p>
    <p class="legend-row"><span><i class="dot good"></i>right, right place</span>
      <span><i class="dot near"></i>right, wrong cell</span> <span><i class="dot bad"></i>not there</span>
      <span><i class="sq"></i>where the map says things are</span></p>
    <p class="sub">${esc(sc.chip.id)} · NAIP ${esc(sc.chip.date)} ·
      <a href="#/runs/${esc(batchId)}/${esc(sc.case_id)}/${esc(sc.run_id.split("#")[1])}">open this Run</a></p></div>`;
}

const VERDICT = {
  baseline: ["★", "Baseline", "v-base"],
  pass: ["✓", "passed the gate", "v-pass"],
  fail: ["✗", "failed the gate", "v-fail"],
  inconclusive: ["?", "inconclusive", "v-na"],
  partial: ["·", "test run on some Cases", "v-na"],
  "different Cases": ["·", "different Cases: not comparable", "v-na"],
  "no Baseline": ["·", "no Baseline yet", "v-na"],
};

function experimentLog(rows) {
  if (!rows.length) return '<p class="sub">No Batches yet.</p>';
  return `<ol class="xlog">${rows.map((r) => {
    const [icon, text, cls] = VERDICT[r.verdict] || ["·", r.verdict, "v-na"];
    const when = (r.created || "").replace("T", " ").slice(5, 16);
    const moves = r.moves.filter((m) => Math.abs(m.points) >= 3).slice(0, 2).map((m) =>
      `<span class="move ${m.points > 0 ? "up" : "down"}">${esc(m.name)} ${m.points > 0 ? "▲" : "▼"}${Math.abs(m.points)} pts</span>`).join("");
    return `<li class="${cls}"><span class="xicon" aria-hidden="true">${icon}</span>
      <a href="#/batches/${esc(r.batch_id)}"><b>${esc(r.label)}</b></a>
      <span class="xmeta">${esc(when)} · ${plural(r.cases, "Case")} × ${plural(r.repeats, "Repeat")}</span>
      <span class="xverdict">${esc(text)}</span>${moves}</li>`;
  }).join("")}</ol>`;
}

function loopMission(core, tasks) {
  const segs = core.map((s) => {
    const [state] = stepState(s, tasks);
    const cls = state === "built" ? "built" : state === "partly built" ? "partly" : "not";
    return `<a class="seg ${cls}" href="#/how/${esc(s.key)}" title="${esc(s.title)}: ${esc(state)}"><span>${esc(s.title)}</span></a>`;
  }).join("");
  const built = core.filter((s) => stepState(s, tasks)[0] === "built").length;
  const going = core.filter((s) => stepState(s, tasks)[0] === "partly built").length;
  return `<div class="mission"><div class="mission-top"><span>Core loop</span>
    <b>${built} built · ${going} under way</b></div><div class="segs">${segs}</div>
    <small>capture, summarize, score, report: the brief's heart of the build</small></div>`;
}

function mission(title, done, total, note) {
  const w = total ? Math.round((100 * done) / total) : 0;
  return `<div class="mission"><div class="mission-top"><span>${esc(title)}</span><b>${done} / ${total}</b></div>
    <div class="meter-bar"><span style="width:${Math.max(w, 2)}%"></span></div><small>${esc(note)}</small></div>`;
}

async function overview() {
  const me = SEQ;
  const o = await api("/api/overview");
  if (stale(me)) return;
  const tasks = o.tasks, B = o.baseline;
  const must = tasks.filter((t) => t.tier === "Must");
  const mustDone = must.filter((t) => t.status === "done").length;
  const core = FLOW.filter((s) => PHASES.find((p) => p.key === s.phase).core);

  $view.innerHTML = `
    <section class="hero" aria-labelledby="hero-title">
      <div class="hero-body">
        <p class="hero-kicker">Clay Earth Dataset Foundry · caption track</p>
        <h1 id="hero-title">Captions that teach Clay to read the Earth</h1>
        <p class="hero-lede">Clay v2 learns from text as well as imagery. We write those captions for
        aerial imagery, and prove each change makes them better: every change is a ${term("Batch")},
        scored on Clay's five criteria, and kept only if the regression gate passes.</p>
        <div class="hero-cta">
          <a class="hero-btn primary" href="#/how">How it works</a>
          <a class="hero-btn" href="#/tasks">Pick a task</a>
        </div>
      </div>
    </section>

    <section class="home-score" aria-labelledby="score-title">
      <div>
        <h2 id="score-title">How good are the captions?</h2>
        <p class="sub">${B ? `Scored on Clay's five criteria, from the accepted ${term("Baseline")}: ${plural(B.cases, "Case")} × ${plural(B.repeats, "Repeat")}, captioned by ${esc(B.caption_model.replace(/^us\./, ""))}. Weights aren't set yet, so each criterion stands on its own.` : "No Baseline accepted yet."}</p>
        ${B ? scorecard(B) : ""}
      </div>
      <div id="showcase">${showcaseCard(o.showcase, 0, B ? B.batch_id : "")}</div>
    </section>

    <div class="home-row">
      <section aria-labelledby="xlog-title">
        <h2 id="xlog-title">Experiments</h2>
        <p class="sub">Every change is a Batch. The regression gate compares it with the Baseline and keeps it only if nothing got worse.</p>
        ${experimentLog(o.experiments)}
      </section>
      <section aria-labelledby="missions-title">
        <h2 id="missions-title">Missions</h2>
        <div class="missions">
          ${mission("Cases built", o.cases, 60, "the plan needs about 60 development Cases")}
          ${mission("Must tasks done", mustDone, must.length, "what the hackathon has to deliver")}
          ${loopMission(core, tasks)}
        </div>
      </section>
    </div>`;

  let shown = 0;
  const wire = () => {
    const next = document.getElementById("sc-next");
    if (next) next.addEventListener("click", () => {
      shown += 1;
      document.getElementById("showcase").innerHTML = showcaseCard(o.showcase, shown, B ? B.batch_id : "");
      wire();
    });
  };
  wire();
}

const STEP_STATE = {
  built: { label: "Built", cls: "st-built" },
  partly: { label: "Partly built", cls: "st-partly" },
  not: { label: "Not built yet", cls: "st-not" },
};
const stateOf = (step, tasks) => {
  const [label] = stepState(step, tasks);
  return label === "built" ? STEP_STATE.built : label === "partly built" ? STEP_STATE.partly : STEP_STATE.not;
};

async function howPage(stepKey) {
  const me = SEQ;
  const tasks = await api("/api/tasks");
  if (stale(me)) return;
  const first = Math.max(0, FLOW.findIndex((s) => s.key === stepKey));

  $view.innerHTML = `
    <header class="how-head">
      <h1>How it works</h1>
      <p class="how-lede">Ten steps take a place on the map to a kept or rejected change to the
      captioner. The middle of it, <b>observe, summarize, score, report</b>, is the loop the brief
      calls the heart of the build. Pick a step to see what it is, why it's there, where it lives
      in the code, and every task that's left for it. For the whole picture, read
      <a href="/docs/docs/caption-plan.md" target="_blank" rel="noopener">the plan</a> and
      <a href="/docs/docs/caption-design.md" target="_blank" rel="noopener">the design</a>.</p>
      <ul class="how-key" aria-label="Status key">
        <li><span class="how-num st-built" aria-hidden="true"></span>Built</li>
        <li><span class="how-num st-partly" aria-hidden="true"></span>Partly built</li>
        <li><span class="how-num st-not" aria-hidden="true"></span>Not built yet</li>
      </ul>
    </header>
    <div class="how-track" style="--steps:${FLOW.length}">
    <ol class="how-phases" aria-label="Phases">${PHASES.map((p) => {
      const n = FLOW.filter((s) => s.phase === p.key).length;
      return `<li class="${p.core ? "core" : ""}" style="grid-column: span ${n}">${esc(p.label)}</li>`;
    }).join("")}</ol>
    <ol class="how-steps" id="flow">${FLOW.map((s, i) => {
      const st = stateOf(s, tasks);
      return `<li><button type="button" data-i="${i}" aria-pressed="${i === first}"
          aria-label="Step ${i + 1}: ${esc(s.title)} (${st.label})">
        <span class="how-num ${st.cls}">${i + 1}</span>
        <span class="how-text"><span class="how-title">${esc(s.title)}</span>
          <span class="how-sub">${esc(s.sub)}</span></span>
      </button></li>`;
    }).join("")}</ol>
    </div>
    <p class="how-core-note"><span></span>The core loop: the brief's “observe, summarize, score” plus the report.</p>
    <section class="how-panel" id="step" aria-live="polite"></section>`;

  const show = (i) => {
    const s = FLOW[i];
    const st = stateOf(s, tasks);
    const order = { doing: 0, decide: 1, blocked: 2, todo: 3, done: 4 };
    const tier = { Must: 0, Should: 1, Could: 2 };
    const mine = tasks.filter((t) => t.step === s.key)
      .sort((x, y) => (order[x.status] - order[y.status]) || (tier[x.tier] - tier[y.tier]));
    const prev = FLOW[i - 1], next = FLOW[i + 1];
    document.querySelectorAll("#flow button").forEach((b) => b.setAttribute("aria-pressed", String(+b.dataset.i === i)));
    document.getElementById("step").innerHTML = `
      <div class="how-panel-head">
        <p class="how-kicker">Step ${i + 1} of ${FLOW.length} · ${esc(PHASES.find((p) => p.key === s.phase).label)}</p>
        <h2>${esc(s.title)}</h2>
        <p class="how-tags"><span class="how-area ${AREA_CLASS[s.area]}">${esc(s.area)}</span>
          <span class="how-state ${st.cls}">${esc(st.label)}</span></p>
      </div>
      <div class="how-panel-body">
        <div class="how-prose">
          <h3>What it is</h3><p>${s.what}</p>
          <h3>Why it's there</h3><p>${s.why}</p>
          <h3>Where it lives</h3>
          <ul class="how-code">${s.code.map((c) => `<li><code>${esc(c)}</code></li>`).join("")}</ul>
          ${(s.docs || []).length ? `<h3>Read more in the plan and design</h3>
          <ul class="how-docs">${s.docs.map((d) => `<li><a href="${esc(d.href)}" target="_blank" rel="noopener">${esc(d.label)}</a></li>`).join("")}</ul>` : ""}
        </div>
        <aside class="how-tasks" aria-label="Tasks for this step">
          <h3>Tasks for this step <small>(${mine.filter((t) => t.status === "done").length} of ${mine.length} done)</small></h3>
          ${mine.map((t) => `<div class="how-task">
              <div>${statusBadge(t.status)} <span class="badge b-na">${esc(t.tier)}</span></div>
              <p><a href="#/tasks/${esc(t.id)}">${esc(t.title)}</a></p></div>`).join("") || '<p class="sub">None listed.</p>'}
          <a class="how-all" href="#/tasks">All tasks →</a>
        </aside>
      </div>
      <nav class="how-pager" aria-label="Steps">
        ${prev ? `<button type="button" class="btn secondary" data-go="${i - 1}">← ${i}. ${esc(prev.title)}</button>` : "<span></span>"}
        ${next ? `<button type="button" class="btn" data-go="${i + 1}">${i + 2}. ${esc(next.title)} →</button>` : ""}
      </nav>`;
    document.querySelectorAll("#step [data-go]").forEach((b) => b.addEventListener("click", () => go(+b.dataset.go)));
  };
  const go = (i) => {
    show(i);
    // Give each step a linkable address without re-rendering the page.
    history.replaceState(null, "", `#/how/${FLOW[i].key}`);
  };
  document.querySelectorAll("#flow button").forEach((b) => b.addEventListener("click", () => go(+b.dataset.i)));
  show(first);
}

// A task as a self-contained brief a teammate can paste into their coding agent.
// Escaped text with `backticks` shown as code.
const inlineCode = (s) => esc(s).replace(/`([^`]+)`/g, "<code>$1</code>");

function taskBrief(t, byId, reqs) {
  const lines = [`# ${t.title}`, "",
    `Task \`${t.id}\` · ${t.tier} · ${STATUS[t.status]?.[1] || t.status} · area: ${t.area} · How it works step: ${t.step}`, ""];
  if (t.context) lines.push("## Context", "", t.context, "");
  if ((t.closes || []).length) {
    lines.push("## Requirements it closes", "");
    for (const id of t.closes) lines.push(`- **${id}**: ${reqs[id] || "(see docs/caption-design.md §2)"}`);
    lines.push("");
  }
  if ((t.done_when || []).length) lines.push("## Done when", "", ...t.done_when.map((d) => `- ${d}`), "");
  if ((t.refs || []).length) lines.push("## Read first", "", ...t.refs.map((r) => `- ${r}`), "");
  if (t.start) lines.push("## Where to start", "", t.start, "");
  const after = (t.after || []).filter((id) => byId[id]);
  if (after.length) {
    lines.push("## Waits on", "", ...after.map((id) => `- ${byId[id].title} (\`${id}\`, ${STATUS[byId[id].status]?.[1] || byId[id].status})`), "");
  }
  if (t.notes) lines.push("## Notes", "", t.notes, "");
  if (t.see_it) lines.push("## Where to see it", "", t.see_it, "");
  if ((t.changes || []).length) lines.push("## What changed", "", ...t.changes.map((c) => `- ${c}`), "");
  lines.push("## Repo rules", "",
    "- Capitalized terms (Case, Chip, Claim, Run, Trace, Batch, ...) mean exactly what GLOSSARY.md says.",
    "- The plan is docs/caption-plan.md; requirements are docs/caption-design.md §2; decisions are docs/adr/.",
    "- ADR-0006: the caption Harness never reads an Answer Key (USGS, GRW, OSM) or a Case's Reference Labels.",
    "- Before a PR: `uv run ruff check src tests` and `uv run pytest`. Never commit .env, data/, batches/, or benchmark images.",
    "- In the same PR, update this task in docs/tasks.toml (status, owner, notes).");
  return lines.join("\n");
}

async function tasksPage(focusId) {
  const me = SEQ;
  const [tasks, reqs] = await Promise.all([api("/api/tasks"), api("/api/requirements")]);
  if (stale(me)) return;
  const byId = Object.fromEntries(tasks.map((t) => [t.id, t]));
  const state = { tier: "", status: focusId ? "all" : "open" };
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
          return `<div class="task ${t.status === "done" ? "done" : ""}" id="task-${esc(t.id)}">
            <div class="t">${esc(t.title)}</div>
            <div class="meta">${statusBadge(t.status)} <span class="badge b-na">${esc(t.tier)}</span>
              <span class="ids">${(t.closes || []).map((c) => `<code title="${esc(reqs[c] || "")}">${esc(c)}</code>`).join("")}</span></div>
            ${t.notes ? `<div class="sub">${esc(t.notes)}</div>` : ""}
            ${wait.length ? `<div class="sub">After: ${wait.map((id) => esc(byId[id].title)).join("; ")}</div>` : ""}
            <details class="brief" ${t.id === focusId ? "open" : ""}><summary>Brief</summary>
              ${t.context ? `<p>${esc(t.context)}</p>` : ""}
              ${t.see_it ? `<h4>Where to see it</h4><p>${inlineCode(t.see_it)}</p>` : ""}
              ${(t.changes || []).length ? `<h4>What changed</h4><ul class="refs">${t.changes.map((c) => {
                const [path, ...rest] = c.split(": ");
                return `<li><code>${esc(path)}</code>${rest.length ? `: ${inlineCode(rest.join(": "))}` : ""}</li>`;
              }).join("")}</ul>` : ""}
              ${(t.done_when || []).length ? `<h4>Done when</h4><ul>${t.done_when.map((d) => `<li>${esc(d)}</li>`).join("")}</ul>` : ""}
              ${(t.refs || []).length ? `<h4>Read first</h4><ul class="refs">${t.refs.map((r) => `<li><code>${esc(r)}</code></li>`).join("")}</ul>` : ""}
              <button type="button" class="btn copy" data-id="${esc(t.id)}">Copy brief for your agent</button>
              <span class="copied sub" aria-live="polite"></span>
            </details>
            <div class="start">Start: <span class="mono">${esc(t.start || "")}</span>
              · Owner: ${esc(t.owner || "open")}</div></div>`;
        }).join("") || '<div class="task sub">Nothing matches the filter.</div>'}</section>`;
    }).join("");
    document.querySelectorAll("button.copy").forEach((b) => b.addEventListener("click", async () => {
      const text = taskBrief(byId[b.dataset.id], byId, reqs);
      const note = b.nextElementSibling;
      try {
        await navigator.clipboard.writeText(text);
        note.textContent = "Copied. Paste it into your agent.";
      } catch {
        // No clipboard access: show the brief so it can be copied by hand.
        const area = document.createElement("textarea");
        area.className = "brief-text"; area.value = text; area.rows = 14;
        b.replaceWith(area); area.select();
        note.textContent = "Select all and copy.";
      }
    }));
  };
  $view.innerHTML = `<h1>Tasks</h1>
    <p>Everything left to finish the hackathon project, by functional area. Pick one that isn't
    waiting on another, open its <b>Brief</b>, and copy it into your coding agent: it has the context,
    the requirements it closes, what done means, and what to read first. Put your name in
    <code>docs/tasks.toml</code> and open a PR.</p>
    <div class="filters">
      <label>Tier <select id="tier"><option value="">all</option><option>Must</option><option>Should</option><option>Could</option></select></label>
      <label>Status <select id="status"><option value="open">not done</option><option value="all">all</option>
        <option value="decide">needs a decision</option><option value="doing">in progress</option>
        <option value="todo">to do</option><option value="blocked">blocked</option><option value="done">done</option></select></label>
    </div><div class="areas" id="areas"></div>`;
  document.getElementById("status").value = state.status;
  document.getElementById("tier").addEventListener("change", (e) => { state.tier = e.target.value; render(); });
  document.getElementById("status").addEventListener("change", (e) => { state.status = e.target.value; render(); });
  render();
  if (focusId) {
    const el = document.getElementById(`task-${focusId}`);
    if (el) { el.classList.add("focus"); el.scrollIntoView({ block: "center" }); }
  }
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

// ── Provenance: what a Batch ran and was judged with, and where its files are ──────────

function provValue(key, v) {
  if (v === null || v === undefined) return key === "judge_model" || key === "judge_prompt_sha" ? "off" : "—";
  if (typeof v === "boolean") return v ? "yes" : "no";
  if (Array.isArray(v)) return v.length ? v.join(", ") : key === "tools" ? "none (single-call Harness)" : "—";
  const text = String(v);
  if (/^[0-9a-f]{40}$/.test(text)) return `<code title="${esc(text)}">${esc(text.slice(0, 12))}</code>`;
  if (/^[0-9a-f]{12}$/.test(text)) return `<code>${esc(text)}</code>`;
  return esc(text);
}

function provFiles(files) {
  return `<table class="prov-files"><tr><th>File</th><th>What it is</th><th>In the store</th></tr>
    ${files.map((f) => `<tr class="${f.exists ? "" : "missing"}">
      <td class="mono">${f.exists ? `<a href="${esc(f.href)}" target="_blank" rel="noopener">${esc(f.name)}</a>` : esc(f.name)}</td>
      <td>${esc(f.what)}${f.exists ? "" : ' <span class="badge b-na">not stored</span>'}</td>
      <td>${f.exists ? `<button type="button" class="btn-link copy-uri" data-uri="${esc(f.store_url)}" title="${esc(f.store_url)}">copy address</button>
        ${f.console_url ? ` · <a href="${esc(f.console_url)}" target="_blank" rel="noopener">AWS console</a>` : ""}` : ""}</td></tr>`).join("")}</table>`;
}

function wireCopy() {
  document.querySelectorAll("button.copy-uri").forEach((b) => b.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(b.dataset.uri);
      b.textContent = "copied";
    } catch {
      // No clipboard access: show the address so it can be copied by hand.
      b.replaceWith(Object.assign(document.createElement("code"), { textContent: b.dataset.uri }));
    }
  }));
}

function provenancePanel(p) {
  const groups = [...new Set(p.settings.map((s) => s.group))];
  const base = p.baseline_id;
  const unrecorded = p.settings.filter((s) => !s.recorded).length;
  return `<h2 id="provenance">Provenance</h2>
    <p class="sub">Everything this Batch was run and judged with, so any score can be traced back to its
      inputs.${base ? ` Compared with the Baseline, <code>${esc(base)}</code>.` : ""}
      ${unrecorded ? ` ${unrecorded} items weren't recorded: this Batch predates provenance recording.` : ""}</p>
    <div class="prov">
      <table class="prov-settings"><tr><th>Setting</th><th>This Batch</th>${base ? "<th>Baseline</th>" : ""}</tr>
      ${groups.map((g) => `<tr class="prov-group"><th colspan="${base ? 3 : 2}">${esc(g)}</th></tr>
        ${p.settings.filter((s) => s.group === g).map((s) => `<tr${s.differs ? ' class="differs"' : ""}>
          <td>${esc(s.label)}</td>
          <td>${s.recorded ? provValue(s.key, s.value) : '<span class="badge b-na">not recorded</span>'}</td>
          ${base ? `<td>${!("baseline" in s) ? "" : s.baseline_recorded ? provValue(s.key, s.baseline) : '<span class="badge b-na">not recorded</span>'}${s.differs ? ' <span class="badge b-warn">differs</span>' : ""}</td>` : ""}
        </tr>`).join("")}`).join("")}
      </table>
      <div><h3>Stored files</h3>${provFiles(p.files)}</div>
    </div>`;
}

async function batchPage(id, section) {
  const me = SEQ;
  const [b, prov] = await Promise.all([api(`/api/batches/${encodeURIComponent(id)}`),
    api(`/api/batches/${encodeURIComponent(id)}/provenance`)]);
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
    <code>${esc(c.cases_sha)}</code> · <a href="#/batches/${esc(id)}/provenance">full provenance</a></p>
    ${gateHtml}
    ${provenancePanel(prov)}
    <h2>Report</h2>
    <p class="sub">The same self-contained report the CLI writes; <a href="/api/batches/${encodeURIComponent(id)}/report.html" target="_blank">open it on its own</a>.</p>
    <iframe class="report" sandbox="allow-scripts allow-popups allow-popups-to-escape-sandbox" src="/api/batches/${encodeURIComponent(id)}/report.html" title="Batch report"></iframe>`;
  wireCopy();
  if (section) document.getElementById(section)?.scrollIntoView();
}

async function runPage(batchId, caseId, repeat) {
  const me = SEQ;
  const name = `${caseId}--r${repeat}`;
  const src = `/api/batches/${encodeURIComponent(batchId)}/runs/${encodeURIComponent(name)}`;
  const [r, p] = await Promise.all([api(`${src}.json`), api(`${src}/provenance`)]);
  if (stale(me)) return;
  const k = p.case;
  $view.innerHTML = `<p><a href="#/batches/${esc(batchId)}">← Batch ${esc(batchId)}</a></p>
    <h1>Run ${esc(r.run_id)}</h1>
    <p class="sub">${esc((r.summary || {}).verdict || r.status)} ·
      <a href="${src}.html" target="_blank" rel="noopener">open on its own</a> ·
      <a href="${src}.json" target="_blank" rel="noopener">as JSON</a></p>
    <details class="prov-run"><summary>Provenance: what this Run was scored on, and its stored files</summary>
      <table class="prov-settings">
        <tr><td>Case</td><td><code>${esc(k.id)}</code>, frozen in the Batch as <code>${esc(k.sha)}</code>
          with ${k.reference_labels} Reference Labels</td></tr>
        <tr><td>Chip</td><td><code>${esc(k.chip_uri)}</code>
          ${k.chip_sha256 ? `· SHA-256 <code title="${esc(k.chip_sha256)}">${esc(k.chip_sha256.slice(0, 12))}</code>, checked before the Run`
            : '<span class="badge b-na">hash not recorded</span>'}</td></tr>
        <tr><td>Settings</td><td>the Batch's: <a href="#/batches/${esc(batchId)}/provenance">models, prompts, Judge rubric, ontology, commit</a></td></tr>
      </table>
      ${provFiles(p.files)}
    </details>
    <iframe class="report" sandbox="allow-scripts" src="${src}.html" title="Run report"></iframe>`;
  wireCopy();
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
        <td>${{ measurement: '<span class="badge b-warn">measurement: scores may not be comparable</span>',
          code: '<span class="badge b-na">code</span>',
          "not recorded": '<span class="badge b-na">not recorded on one side</span>' }[s.kind]
          || '<span class="badge b-na">captioner</span>'}</td></tr>`).join("")}</table>`
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

// ── Ontology explainer (interactive) ───────────────────────────────────────────────────────
// A plain-English, no-API walk-through of the data-driven ontology and how the captioning agent
// uses it. Docs: docs/ontology-data-driven.md, docs/ontology-induction.md (ADR-0008/0010/0011).

const ONTO_CHIPS = {
  solar: { label: "Solar-farm tile", truth: "a real solar array site",
    scores: [["Solar farm", 0.80], ["Water", 0.47], ["Parking lot", 0.44]] },
  wind: { label: "Wind-farm tile", truth: "a real wind-turbine site", close: true,
    scores: [["Wind turbine", 0.96], ["Water", 0.91], ["Farm field", 0.89]] },
  empty: { label: "Empty-land tile", truth: "a tile with no solar or wind",
    scores: [["Parking lot", 0.92], ["Water", 0.86], ["Farm field", 0.80]] },
};

const ONTO_LAYERS = [
  { id: "A", cls: "onto-a", name: "Layer A — look-alikes", tag: "words",
    one: "Which things are easily mixed up, so the writer is warned.",
    more: "For each category the guide lists what it is easily confused with in an aerial view — e.g. a solar farm vs. a greenhouse vs. a parking lot. These warnings go into the writer's instructions so it doesn't call a greenhouse a solar farm.",
    from: "Built by an AI reading lots of example captions (and double-checked by the fingerprints)." },
  { id: "C", cls: "onto-c", name: "Layer C — example phrasings", tag: "words",
    one: "A couple of house-style sentences showing how to describe each thing.",
    more: "Short example sentences per category (\"Rows of dark blue-grey panels fill the centre…\"). They teach the writer the house style and help the search feature find captions later. They are generic examples — never a description of the actual image being captioned.",
    from: "Built by an AI reading example captions." },
  { id: "B", cls: "onto-b", name: "Layer B — visual fingerprints", tag: "pictures",
    one: "A numeric 'fingerprint' of what each category looks like.",
    more: "The Clay model turns example images into a fingerprint (a long list of numbers) for each category. A new image gets its own fingerprint, and we measure which category it most resembles — a fast, cheap hint with no AI 'thinking' at that step.",
    from: "Built by the Clay model looking at example images. Optional: the words still work without it." },
];

const ONTO_STEPS = [
  { key: "image", icon: "🛰️", title: "A new image arrives",
    body: "The captioning agent is handed one aerial tile and asked to describe what is on the ground — the objects, how many, where, and how they sit relative to each other." },
  { key: "fingerprint", icon: "🔎", title: "Fingerprint check (Layer B)", layer: "B",
    body: "The tile's fingerprint is compared with each category's fingerprint. The closest matches become a hint: “this looks most like a solar farm (0.80).” Pure arithmetic — instant and almost free.",
    skipNote: "Skipped: without the fingerprints there is no 'looks most like' hint." },
  { key: "notes", icon: "📋", title: "The guide prepares notes (Layers A + C)", layer: "AC",
    body: "The ontology gathers the relevant notes: the look-alikes to tell apart, a couple of house-style example sentences, and (if available) the fingerprint hint. All general knowledge — never the answer for this tile.",
    skipNote: "Skipped: without the ontology the writer gets no look-alike warnings or examples." },
  { key: "write", icon: "✍️", title: "The captioning AI writes", layer: "captions",
    body: "The vision model (e.g. Nova Pro) receives the image plus the notes, and writes a caption together with structured claims (object, count, position, relations)." },
  { key: "verify", icon: "✅", title: "Double-check (verify, then write)",
    body: "Each claim is checked against imagery with LGND Geo. Claims that can't be confirmed are marked uncertain, and the caption is rewritten from only the confirmed ones." },
  { key: "final", icon: "📝", title: "Final caption",
    body: "The finished caption and its confirmed claims are saved — then scored on grounding, retrieval and fidelity like any other caption, so we can measure whether the ontology helped." },
];

function ontologyReceives(withOnto) {
  const base = ["The aerial image", "Base instructions: describe objects, counts, positions, relations"];
  const extra = [
    "⚠️ Look-alikes to tell apart (Layer A): Solar farm vs Greenhouse; Solar farm vs Parking lot",
    "💬 Example phrasing (Layer C): “Rows of dark blue-grey panels fill the centre of the tile.”",
    "🔎 Fingerprint hint (Layer B): closest to Solar farm (0.80)",
  ];
  const items = withOnto ? base.concat(extra) : base;
  return `<ul class="onto-receives">${items.map((t, k) =>
    `<li class="${withOnto && k >= 2 ? "onto-extra" : ""}">${esc(t)}</li>`).join("")}</ul>`;
}

const ONTO_ROOTCOLOR = {
  energy_infrastructure: "#b06a4f", transportation: "#4a7a86",
  built_structure: "#8a7a63", hydrography: "#4a6a86", land_cover: "#5a7a4a",
};

async function ontologyPage(focus) {
  const me = SEQ;
  const ont = await api("/api/ontology").catch(() => null);
  if (stale(me)) return;
  const state = { chip: "solar", withOnto: true, node: null };

  // ── Step: what it is ───────────────────────────────────────────────────────
  const renderWhat = (host) => {
    host.innerHTML = `
      <p class="onto-lead">Before the AI describes an aerial image, we hand it a <b>field guide</b>
        to what shows up in these images — like a bird-watching guide: written entries plus
        reference photos, matched up by name. It has two halves. Click a layer to learn more.</p>
      <div class="onto-halves">
        <div class="onto-half">
          <h3>📖 The written guide <span class="onto-pill">words</span></h3>
          <p class="sub">Built by an AI reading example captions.</p>
          <div class="onto-layers" data-tags="words"></div>
        </div>
        <div class="onto-half">
          <h3>🖼️ The reference fingerprints <span class="onto-pill">pictures</span></h3>
          <p class="sub">Built by the Clay model looking at example images.</p>
          <div class="onto-layers" data-tags="pictures"></div>
        </div>
      </div>
      <p class="onto-join">The two halves are linked by <b>category name</b> — the words and the
        fingerprint for “solar farm” sit side by side. The written guide works on its own; the
        fingerprints are an optional add-on that sharpens the hints.</p>`;
    for (const h of host.querySelectorAll(".onto-layers")) {
      h.innerHTML = ONTO_LAYERS.filter((l) => l.tag === h.dataset.tags).map((l) => `
        <button type="button" class="onto-layer ${l.cls}">
          <span class="onto-badge">${l.id}</span>
          <span class="onto-layer-name">${esc(l.name)}</span>
          <span class="onto-layer-one">${esc(l.one)}</span>
          <span class="onto-layer-more">${esc(l.more)}<br><em>${esc(l.from)}</em></span>
        </button>`).join("");
    }
    host.querySelectorAll(".onto-layer").forEach((b) =>
      b.addEventListener("click", () => b.classList.toggle("open")));
  };

  // ── Step: how it's built ───────────────────────────────────────────────────
  const BUILD = {
    words: { cls: "build-words", icon: "📖", head: "The written guide (Layers A + C)",
      steps: [
        ["A pile of example captions", "e.g. a human-captioned image set (RSICD), or Clay's own example captions."],
        ["An AI reads them", "and pulls out the categories people mention, other names for the same thing (synonyms), which things get confused, and example sentences."],
        ["It organises them into a hierarchy", "grouping specific things under general ones, following a classic ontology recipe (Noy & McGuinness)."],
        ["A person reviews it", "and the scored categories stay matched to the answer keys, so grounding keeps working."],
        ["→ Layers A + C of the guide", "classes, synonyms, look-alikes, and house-style examples."],
      ] },
    pics: { cls: "build-pics", icon: "🖼️", head: "The fingerprints (Layer B)",
      steps: [
        ["Example images per category", "confirmed solar sites, wind sites, water, and so on."],
        ["The Clay model reads each image", "turning it into a fingerprint — a long list of numbers summarising what it looks like."],
        ["Average them per category", "all the solar examples become one “typical solar” fingerprint."],
        ["→ Layer B of the guide", "one fingerprint per category, stored beside the words."],
      ] },
  };
  const buildCol = (b) => `
    <div class="onto-build-col ${b.cls}">
      <h3>${b.icon} ${esc(b.head)}</h3>
      <ol class="onto-build-steps">
        ${b.steps.map(([t, d]) => `<li><b>${esc(t)}</b><span>${esc(d)}</span></li>`).join("")}
      </ol>
    </div>`;
  const renderBuild = (host) => {
    host.innerHTML = `
      <p class="onto-lead">The two halves are built separately — and <b>neither needs the other</b>.
        The words come from reading captions; the fingerprints come from looking at images.</p>
      <div class="onto-build">${buildCol(BUILD.words)}${buildCol(BUILD.pics)}</div>
      <details class="onto-rules">
        <summary>The rules the AI follows when building the guide (Noy &amp; McGuinness)</summary>
        <ul>
          <li><b>Group specific under general.</b> A greenhouse is a <i>kind of</i> building, which is a kind of built structure.</li>
          <li><b>Synonyms are alternate names, not new categories.</b> “PV plant”, “photovoltaic array”, “solar farm” all point to one <i>solar farm</i> entry.</li>
          <li><b>Only make a new category when it truly behaves differently.</b> “Large” is a <i>size</i> of solar farm, not its own category.</li>
          <li><b>Keep it tidy.</b> 2–12 things under each group; consistent, simple names; no loops.</li>
        </ul>
      </details>`;
  };

  // ── Step: example ontology graph ───────────────────────────────────────────
  const rootOf = (id, byId) => { let c = byId[id]; while (c && c.parent) c = byId[c.parent]; return c ? c.id : id; };
  const layoutOnt = (classes) => {
    const byId = {}; classes.forEach((c) => (byId[c.id] = c));
    const kids = {}; classes.forEach((c) => { const p = c.parent || ""; (kids[p] = kids[p] || []).push(c.id); });
    const depth = (id) => { let d = 0, p = byId[id].parent; while (p) { d++; p = byId[p].parent; } return d; };
    const rowH = 42, colW = 215, padX = 14, padY = 14, nodeH = 30, nodeW = 160;
    let leaf = 0; const y = {};
    const assign = (id) => {
      const ks = kids[id] || [];
      if (!ks.length) { y[id] = padY + leaf * rowH + nodeH / 2; leaf++; }
      else { ks.forEach(assign); y[id] = (y[ks[0]] + y[ks[ks.length - 1]]) / 2; }
    };
    (kids[""] || []).sort().forEach(assign);
    const maxDepth = Math.max(0, ...classes.map((c) => depth(c.id)));
    const nodes = classes.map((c) => ({ ...c, x: padX + depth(c.id) * colW, y: y[c.id] }));
    const edges = classes.filter((c) => c.parent).map((c) => ({ from: c.parent, to: c.id }));
    return { nodes, edges, byId, nodeW, nodeH, width: padX * 2 + maxDepth * colW + nodeW, height: padY * 2 + leaf * rowH };
  };
  const renderGraph = (host) => {
    if (!ont) { host.innerHTML = `<p class="empty">Couldn't load the ontology.</p>`; return; }
    const lay = layoutOnt(ont.classes);
    const byId = lay.byId;
    const edgeEls = lay.edges.map((e) => {
      const a = byId[e.from], b = byId[e.to];
      // Stop a few px short of the child so the arrowhead sits just before the box, not under it.
      const x1 = a.x + lay.nodeW, y1 = a.y, x2 = b.x - 4, y2 = b.y, mx = (x1 + x2) / 2;
      return `<path class="onto-edge" marker-end="url(#onto-arrow)" d="M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}"/>`;
    }).join("");
    const nodeEls = lay.nodes.map((n) => {
      const col = ONTO_ROOTCOLOR[rootOf(n.id, byId)] || "#999";
      return `<g class="onto-node" data-id="${esc(n.id)}" tabindex="0" role="button"
        aria-label="${esc(n.name)}" transform="translate(${n.x},${n.y - lay.nodeH / 2})">
        <rect width="${lay.nodeW}" height="${lay.nodeH}" rx="8" style="stroke:${col}"/>
        <text x="11" y="${lay.nodeH / 2 + 4}">${esc(n.name)}${n.keyed ? " ★" : ""}</text>
      </g>`;
    }).join("");
    host.innerHTML = `
      <p class="onto-lead">A real slice of the guide (Layer A), straight from the project's
        ontology file — classes and their sub-classes. <b>Click any box</b> to see its other names
        (synonyms) and what it's confused with.</p>
      <div class="onto-graph-wrap">
        <div class="onto-graph-scroll">
          <svg viewBox="0 0 ${lay.width} ${lay.height}" width="${lay.width}" height="${lay.height}"
            class="onto-graph-svg" role="group" aria-label="Ontology class hierarchy">
            <defs>
              <marker id="onto-arrow" viewBox="0 0 10 10" refX="9" refY="5"
                markerWidth="12" markerHeight="12" markerUnits="userSpaceOnUse" orient="auto">
                <path d="M0,0 L10,5 L0,10 z" fill="#6b6461"/>
              </marker>
            </defs>
            ${edgeEls}${nodeEls}
          </svg>
        </div>
        <aside id="onto-node-detail" class="onto-node-detail"><p class="sub">Pick a box to see its details.</p></aside>
      </div>
      <p class="sub onto-legend">★ = scored against an answer key · colour = top-level group ·
        ontology v${esc(ont.version)}.</p>`;
    const showNode = (id) => {
      const c = byId[id]; if (!c) return;
      const chain = []; let p = c.parent; while (p) { chain.unshift(byId[p].name); p = byId[p].parent; }
      const chips = (arr, kind) => arr.length
        ? `<div class="onto-chips">${arr.map((x) => `<span class="onto-chip ${kind}">${esc(byId[x] ? byId[x].name : x)}</span>`).join("")}</div>`
        : `<p class="sub">—</p>`;
      document.getElementById("onto-node-detail").innerHTML = `
        <h3>${esc(c.name)} ${c.keyed ? '<span class="onto-star">★ scored</span>' : '<span class="onto-star muted">not scored</span>'}</h3>
        <p class="sub onto-chain">${chain.length ? esc(chain.join(" › ")) + " › " : ""}<b>${esc(c.name)}</b></p>
        <p class="onto-dl-label">Other names (synonyms)</p>
        ${c.synonyms.length ? `<div class="onto-chips">${c.synonyms.map((s) => `<span class="onto-chip syn">${esc(s)}</span>`).join("")}</div>` : '<p class="sub">none listed</p>'}
        <p class="onto-dl-label">Easily confused with</p>
        ${chips(c.confusers, "conf")}`;
    };
    host.querySelectorAll(".onto-node").forEach((g) => {
      const sel = () => {
        host.querySelectorAll(".onto-node").forEach((x) => x.classList.toggle("selected", x === g));
        state.node = g.dataset.id; showNode(g.dataset.id);
      };
      g.addEventListener("click", sel);
      g.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); sel(); } });
    });
    if (state.node && byId[state.node]) {
      host.querySelector(`.onto-node[data-id="${state.node}"]`)?.classList.add("selected");
      showNode(state.node);
    }
  };

  // ── Step: measuring similarity ─────────────────────────────────────────────
  const renderMeasure = (host) => {
    host.innerHTML = `
      <p class="onto-lead">Each image becomes a fingerprint. We measure how closely a new tile's
        fingerprint lines up with each category's — a score from 0 (unrelated) to 1 (near-identical).
        Pick a tile:</p>
      <div class="onto-chipbtns">
        ${Object.entries(ONTO_CHIPS).map(([k, c]) =>
          `<button type="button" class="btn secondary onto-chipbtn" data-chip="${k}">${esc(c.label)}</button>`).join("")}
      </div>
      <div id="onto-compare" class="onto-compare"></div>`;
    const draw = () => {
      const c = ONTO_CHIPS[state.chip];
      document.getElementById("onto-compare").innerHTML = `
        <p class="onto-truth">This tile is ${esc(c.truth)}. Its fingerprint scores against each category:</p>
        <div class="onto-bars">
          ${c.scores.map(([name, s], k) => `
            <div class="onto-bar-row">
              <span class="onto-bar-name">${esc(name)}</span>
              <span class="onto-bar-track"><span class="onto-bar-fill ${k === 0 ? "top" : ""}" style="width:${Math.round(s * 100)}%"></span></span>
              <span class="onto-bar-score">${s.toFixed(2)}</span>
            </div>`).join("")}
        </div>
        <p class="sub onto-verdict">${c.close
          ? `Closest is <b>${esc(c.scores[0][0])}</b> — but the runner-up is close, so the hint tells the writer “these look alike here, check the image.”`
          : `Closest is <b>${esc(c.scores[0][0])}</b>, clearly ahead — a confident hint.`}</p>`;
    };
    host.querySelectorAll(".onto-chipbtn").forEach((b) => b.addEventListener("click", () => {
      state.chip = b.dataset.chip;
      host.querySelectorAll(".onto-chipbtn").forEach((x) => x.classList.toggle("active", x === b));
      draw();
    }));
    host.querySelector(`.onto-chipbtn[data-chip="${state.chip}"]`)?.classList.add("active");
    draw();
  };

  // ── Step: how the agent uses it ────────────────────────────────────────────
  const renderUse = (host) => {
    const skipped = (st) => !state.withOnto && (st.key === "fingerprint" || st.key === "notes");
    host.innerHTML = `
      <p class="onto-lead">A tile flows through the pipeline below. Toggle the ontology off to see
        what the writer would get without it.</p>
      <div class="onto-toggle" role="group" aria-label="Ontology on or off">
        <button type="button" class="seg2" data-mode="on">With ontology</button>
        <button type="button" class="seg2" data-mode="off">Without ontology</button>
      </div>
      <div id="onto-uselist" class="onto-uselist"></div>`;
    const draw = () => {
      document.getElementById("onto-uselist").innerHTML = ONTO_STEPS.map((st) => {
        const sk = skipped(st);
        let extra = "";
        if (sk) extra = `<p class="onto-skip">${esc(st.skipNote)}</p>`;
        else if (st.key === "write") extra = `<p class="onto-receives-label">What the writer receives:</p>${ontologyReceives(state.withOnto)}`;
        return `<div class="onto-use-step ${sk ? "skipped" : ""} ${st.layer ? "layer-" + st.layer : ""}">
          <div class="onto-use-head"><span class="onto-step-icon">${sk ? "⤼" : st.icon}</span>
            <h3>${esc(st.title)}</h3></div>
          <p>${esc(st.body)}</p>${extra}</div>`;
      }).join("");
    };
    host.querySelector(`.seg2[data-mode="${state.withOnto ? "on" : "off"}"]`).classList.add("active");
    host.querySelectorAll(".seg2").forEach((b) => b.addEventListener("click", () => {
      state.withOnto = b.dataset.mode === "on";
      host.querySelectorAll(".seg2").forEach((x) => x.classList.toggle("active", x === b));
      draw();
    }));
    draw();
  };

  // ── Wizard shell + navigation ──────────────────────────────────────────────
  const STEPS = [
    { key: "what", title: "What it is", render: renderWhat },
    { key: "build", title: "How it's built", render: renderBuild },
    { key: "graph", title: "Example ontology", render: renderGraph },
    { key: "measure", title: "Measuring “looks like”", render: renderMeasure },
    { key: "use", title: "How the agent uses it", render: renderUse },
  ];
  let cur = STEPS.findIndex((s) => s.key === focus);
  if (cur < 0) cur = 0;

  $view.innerHTML = `
    <section class="hero onto-hero">
      <div class="hero-body">
        <p class="hero-kicker">The data-driven ontology</p>
        <h1>How the ontology works</h1>
        <p class="hero-lede">A guided tour: what the ontology is, how its three layers are built,
          a real example you can explore, and how the caption-writer uses it.</p>
      </div>
    </section>
    <ol class="onto-wz-steps" role="tablist">
      ${STEPS.map((s, i) => `<li><button type="button" class="onto-wz-dot" data-i="${i}">
        <span class="onto-wz-num">${i + 1}</span><span class="onto-wz-label">${esc(s.title)}</span>
      </button></li>`).join("")}
    </ol>
    <div id="onto-panel" class="onto-panel" aria-live="polite"></div>
    <nav class="onto-wz-pager">
      <button type="button" class="btn secondary" id="onto-prev">←</button>
      <span id="onto-wz-at" class="sub"></span>
      <button type="button" class="btn" id="onto-next">Next →</button>
    </nav>
    <p class="onto-foot sub">Deeper reading for the team:
      <a href="/docs/docs/ontology-data-driven.md">ontology-data-driven.md</a> ·
      <a href="/docs/docs/ontology-induction.md">ontology-induction.md</a> ·
      ADR-<a href="/docs/docs/adr/0008-object-classes-live-in-one-ontology-file.md">0008</a>/<a href="/docs/docs/adr/0010-the-ontology-is-data-driven-and-feeds-the-captioner.md">0010</a>/<a href="/docs/docs/adr/0011-the-ontology-is-induced-from-a-caption-corpus.md">0011</a>.</p>`;

  const dots = [...$view.querySelectorAll(".onto-wz-dot")];
  const prev = document.getElementById("onto-prev");
  const next = document.getElementById("onto-next");
  const show = (i) => {
    cur = Math.max(0, Math.min(STEPS.length - 1, i));
    dots.forEach((d, k) => { d.classList.toggle("active", k === cur); d.classList.toggle("done", k < cur); });
    prev.disabled = cur === 0;
    next.textContent = cur === STEPS.length - 1 ? "Done ✓" : `Next: ${STEPS[cur + 1].title} →`;
    document.getElementById("onto-wz-at").textContent = `Step ${cur + 1} of ${STEPS.length}`;
    history.replaceState(null, "", `#/ontology/${STEPS[cur].key}`);
    const panel = document.getElementById("onto-panel");
    panel.innerHTML = "";
    STEPS[cur].render(panel);
    panel.scrollIntoView({ block: "nearest" });
  };
  dots.forEach((d) => d.addEventListener("click", () => show(+d.dataset.i)));
  prev.addEventListener("click", () => show(cur - 1));
  next.addEventListener("click", () => { if (cur < STEPS.length - 1) show(cur + 1); });
  show(cur);
}

async function route() {
  const me = ++SEQ;
  const parts = (location.hash.replace(/^#\/?/, "") || "").split("/").map(decodeURIComponent);
  const page = parts[0] || "";
  document.querySelectorAll("#nav a").forEach((a) => {
    const target = a.getAttribute("href").replace(/^#\/?/, "");
    a.toggleAttribute("aria-current", target === page || (page === "compare" && target === "batches"));
    if (a.hasAttribute("aria-current")) a.setAttribute("aria-current", "page");
  });
  const devMenu = document.getElementById("dev-menu");
  if (devMenu) {
    devMenu.classList.toggle("has-current", !!devMenu.querySelector('a[aria-current="page"]'));
    devMenu.removeAttribute("open");
  }
  $view.innerHTML = '<p class="sub">Loading…</p>';
  try {
    if (page === "") await overview();
    else if (page === "how") await howPage(parts[1]);
    else if (page === "ontology") await ontologyPage(parts[1]);
    else if (page === "tasks") await tasksPage(parts[1]);
    else if (page === "cases") await casesPage();
    else if (page === "batches" && parts[1]) await batchPage(parts[1], parts[2]);
    else if (page === "batches") await batchesPage();
    else if (page === "compare") await comparePage(parts[1], parts[2]);
    else if (page === "runs") await runPage(parts[1], parts[2], parts[3] || "1");
    else if (page === "sources") await sourcesPage();
    else if (page === "concepts") await conceptsPage();
    else $view.innerHTML = '<p class="empty">No such page.</p>';
  } catch (e) {
    if (!stale(me)) $view.innerHTML = `<p class="empty">Couldn't load this page: ${esc(e.message)}</p>`;
  }
}

// The For Dev Team menu closes on a click elsewhere or on Escape.
document.addEventListener("click", (e) => {
  const menu = document.getElementById("dev-menu");
  if (menu && menu.open && !menu.contains(e.target)) menu.removeAttribute("open");
});
document.addEventListener("keydown", (e) => {
  const menu = document.getElementById("dev-menu");
  if (e.key === "Escape" && menu && menu.open) {
    menu.removeAttribute("open");
    menu.querySelector("summary").focus();
  }
});

(async () => {
  CONFIG = await api("/api/config");
  document.getElementById("store").textContent = `store: ${CONFIG.store}`;
  GLOSSARY = Object.fromEntries((await api("/api/glossary")).map((t) => [t.term, t]));
  window.addEventListener("hashchange", route);
  route();
})();
