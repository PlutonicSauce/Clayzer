// "Try the captioner": pick one of a few aerial images, feed it to the Harness, and watch the
// background steps (Bedrock, the Object Ontology, geospatial tools, the Judge) before the Caption
// appears. By default it replays a recorded Run step by step; when the app was started with
// --allow-launch it can also run the Harness live against the same image.
//
// Read-only and honest: the page never computes a score. It replays what was recorded, or asks
// the server to run a real Batch and then reads that Run's result. Globals ($view, esc, api,
// CELLS, CONFIG, SEQ, stale, pageHead) come from app.js and public.js (shared classic-script scope).

// The caption may only assert these classes: the Object Ontology's claimable classes, fed to the
// model on every Run (substituted into the prompt and enforced by the submit_caption schema).
const TRY_CLASSES = [
  "solar_array", "wind_turbine", "road", "railroad", "building", "water",
  "field", "parking_lot", "greenhouse", "vegetation", "bare_ground",
];
const TRY_CELLS = ["north_west", "north", "north_east", "west", "centre", "east", "south_west", "south", "south_east"];
const tryReduceMotion = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
const tryDelay = (ms) => new Promise((r) => setTimeout(r, ms));
let TRY_DATA = null;

async function tryPage() {
  const me = SEQ;
  try {
    TRY_DATA = await api("/api/try");
  } catch {
    TRY_DATA = { images: [], available: false, allow_launch: false };
  }
  if (stale(me)) return;

  const imgs = TRY_DATA.images || [];
  const live = TRY_DATA.allow_launch;
  const cards = imgs.map((im, i) => `
    <button type="button" class="try-card" data-pick="${i}" aria-describedby="try-stage">
      <img src="/api/chips/${encodeURIComponent(im.chip)}.png" alt="Aerial image: ${esc(im.title)}" width="512" height="512" loading="lazy">
      <span class="try-card-body"><b>${esc(im.title)}</b><span>${esc(im.blurb)}</span></span>
      <span class="try-card-go" aria-hidden="true">Caption this image →</span>
    </button>`).join("");

  $view.innerHTML = `${pageHead(
    "Try the captioner",
    "Hand the agent an image.<br>Watch it work.",
    "Pick an aerial image. The captioning agent reads it, is given the Object Ontology's vocabulary, calls Amazon Bedrock, and writes a caption grounded in what it sees — you'll see each background step as it happens."
  )}
    <p class="try-mode" role="note">${live
      ? "This app can run the Harness <b>live</b> on Amazon Bedrock. Picking an image replays a recorded Run; use <b>Run it live</b> to call the model for real."
      : "This is a <b>recorded</b> demonstration: picking an image replays a saved Run step by step. No model is called and no network is used. Synthetic recordings show software behaviour, not validated accuracy."}</p>
    ${imgs.length ? `<div class="try-cards">${cards}</div>` : `<div class="empty"><h2>No demo images recorded yet</h2><p>Record a Run and point <code>demo/try.toml</code> at it. See the file's header for the command.</p></div>`}
    <section id="try-stage" class="try-stage" aria-live="polite" aria-atomic="false">
      <p class="try-stage-idle">Choose an image above to caption it.</p>
    </section>`;

  document.querySelectorAll(".try-card").forEach((b) =>
    b.addEventListener("click", () => startDemo(imgs[+b.dataset.pick], false)));
}

// Build a readable list of background steps from a recorded or live Trace.
function tryStepsFromTrace(events) {
  const steps = [];
  for (const ev of events) {
    const d = ev.data || {};
    if (ev.event === "run_start") {
      const chip = (d.metadata || {}).chip_id || "aerial image";
      const tools = (d.tools || []).filter((t) => t !== "submit_caption");
      steps.push({ label: "Load the aerial image", detail: `${chip} · NAIP, 0.6 m per pixel, about 300 m across` });
      steps.push({ label: "Connect to Amazon Bedrock", detail: d.model_id || "" });
      steps.push({ label: "Feed the Object Ontology", detail: `${TRY_CLASSES.length} claimable classes the caption may assert`, classes: true });
      if (tools.length) steps.push({ label: "Attach geospatial tools", detail: `${tools.length} MCP tools available (roda)` });
    } else if (ev.event === "step") {
      const kind = d.kind, name = d.name;
      const ms = (d.attributes || {}).latency_ms;
      const content = ((d.output || {}).content) || [];
      if (kind === "judge") {
        steps.push({ label: "Score the caption's fidelity with the Judge", detail: (d.attributes || {}).model_id || "", ms });
      } else if (kind === "tool" || kind === "verify") {
        steps.push({ label: `Geospatial tool call: ${name}`, detail: (d.attributes || {}).role || "", ms });
      } else {
        // a model turn (caption draft or rewrite); surface any non-submit tool calls it made
        for (const c of content) {
          if (c.toolUse && c.toolUse.name !== "submit_caption") {
            steps.push({ label: `Model calls a tool: ${c.toolUse.name}`, detail: "looking data up before writing", ms });
          }
        }
        const submitted = content.some((c) => c.toolUse && c.toolUse.name === "submit_caption");
        steps.push({
          label: submitted ? "Model reads the image and drafts the caption" : `Model thinks (turn ${(d.input || {}).turn || "?"})`,
          detail: ms ? `${(ms / 1000).toFixed(1)} s on the model` : "", ms,
        });
      }
    }
  }
  steps.push({ label: "Caption checked and returned", detail: "", done: true });
  return steps;
}

async function startDemo(pick, forceLive) {
  const me = SEQ;
  const stage = document.getElementById("try-stage");
  const live = forceLive;
  stage.innerHTML = `
    <div class="try-run">
      <figure class="try-run-image">
        <img src="/api/chips/${encodeURIComponent(pick.chip)}.png" alt="Aerial image being captioned: ${esc(pick.title)}" width="512" height="512">
        <figcaption>${esc(pick.title)}</figcaption>
      </figure>
      <div class="try-run-body">
        <p class="eyebrow">${live ? "Running the Harness live" : "Replaying a recorded Run"}</p>
        <h2>${live ? "Captioning on Amazon Bedrock…" : "The agent is working…"}</h2>
        <ol class="try-steps" id="try-steps"></ol>
        <p class="try-live-log" id="try-live-log" hidden></p>
      </div>
    </div>
    <div id="try-result"></div>`;
  stage.scrollIntoView({ behavior: tryReduceMotion() ? "auto" : "smooth", block: "start" });

  try {
    if (live) {
      await runLive(pick, me);
    } else {
      const events = await fetchTrace(TRY_DATA.batch, pick.run);
      if (stale(me)) return;
      const ok = await animateSteps(tryStepsFromTrace(events), me);
      if (!ok || stale(me)) return;
      const run = await api(`/api/batches/${encodeURIComponent(TRY_DATA.batch)}/runs/${encodeURIComponent(pick.run)}.json`);
      if (stale(me)) return;
      renderResult(run, pick, false);
    }
  } catch (e) {
    if (!stale(me)) document.getElementById("try-result").innerHTML =
      `<p class="try-error" role="alert">Could not complete this run: ${esc(e.message)}</p>`;
  }
}

async function fetchTrace(batch, run) {
  const r = await fetch(`/api/batches/${encodeURIComponent(batch)}/traces/${encodeURIComponent(run)}.jsonl`);
  if (!r.ok) throw new Error("the recorded Trace is unavailable");
  const text = await r.text();
  return text.split("\n").filter((l) => l.trim()).map((l) => JSON.parse(l));
}

async function animateSteps(steps, me) {
  const list = document.getElementById("try-steps");
  if (!list) return false;
  const reduce = tryReduceMotion();
  for (const s of steps) {
    if (stale(me)) return false;
    const li = document.createElement("li");
    li.className = "try-step is-running";
    li.innerHTML = `<span class="try-step-mark" aria-hidden="true"></span>
      <span class="try-step-text"><b>${esc(s.label)}</b>${s.detail ? `<span>${esc(s.detail)}</span>` : ""}${
        s.classes ? `<span class="try-classes">${TRY_CLASSES.map((c) => `<code>${esc(c)}</code>`).join("")}</span>` : ""}</span>`;
    list.appendChild(li);
    const wait = reduce ? 0 : Math.max(360, Math.min(1100, s.ms ? s.ms / 4 : 620));
    await tryDelay(wait);
    if (stale(me)) return false;
    li.classList.remove("is-running");
    li.classList.add("is-done");
  }
  return true;
}

// Live: start a one-image, one-repeat Batch, show its progress, then read the fresh Run.
async function runLive(pick, me) {
  const log = document.getElementById("try-live-log");
  log.hidden = false;
  log.textContent = "Starting the Harness…";
  let job;
  try {
    job = await api("/api/batches", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ repeats: 1, label: "try-live", only: [pick.case] }),
    });
  } catch (e) {
    throw new Error(e.message.includes("already running") ? "a Batch is already running; try again in a moment" : e.message);
  }
  const batch = job.batch_id;
  // Poll until the job stops, streaming its progress lines into the log.
  for (;;) {
    if (stale(me)) return;
    await tryDelay(1200);
    if (stale(me)) return;
    const jobs = await api("/api/jobs");
    const j = jobs.find((x) => x.batch_id === batch) || job;
    if ((j.lines || []).length) log.textContent = j.lines[j.lines.length - 1];
    if (j.state !== "running") {
      if (j.state === "failed") throw new Error((j.lines || []).slice(-1)[0] || "the live run failed");
      break;
    }
  }
  // Replay the freshly recorded Trace, then show the real Caption.
  const run = `${pick.case}--r1`;
  const events = await fetchTrace(batch, run).catch(() => []);
  if (stale(me)) return;
  if (events.length) {
    const ok = await animateSteps(tryStepsFromTrace(events), me);
    if (!ok || stale(me)) return;
  }
  const result = await api(`/api/batches/${encodeURIComponent(batch)}/runs/${encodeURIComponent(run)}.json`);
  if (stale(me)) return;
  renderResult(result, pick, true);
}

// A 3x3 grid with the agent's Claims drawn where it placed them.
function tryClaimGrid(caption) {
  const C = 512 / 3;
  const per = {};
  const pills = (caption.objects || []).map((o) => {
    const i = TRY_CELLS.indexOf(o.position);
    if (i < 0) return "";
    const n = (per[o.position] = (per[o.position] || 0) + 1) - 1;
    const x = (i % 3) * C + 8, y = Math.floor(i / 3) * C + 10 + n * 26;
    const label = `${o.count ?? ""} ${String(o.object).replace(/_/g, " ")}`.trim();
    return `<g class="try-pill"><rect x="${x}" y="${y}" width="${C - 16}" height="22" rx="11"></rect>
      <text x="${x + (C - 16) / 2}" y="${y + 15}" text-anchor="middle">${esc(label)}</text></g>`;
  }).join("");
  const grid = [1, 2].map((k) =>
    `<line x1="${k * C}" y1="0" x2="${k * C}" y2="512"></line><line x1="0" y1="${k * C}" x2="512" y2="${k * C}"></line>`).join("");
  return `<svg viewBox="0 0 512 512" class="try-grid-svg" aria-hidden="true"><g class="try-grid-lines">${grid}</g>${pills}</svg>`;
}

const tryPct = (x) => (x === null || x === undefined ? "—" : `${Math.round(100 * x)}%`);

function renderResult(run, pick, wasLive) {
  const cap = run.caption || {};
  const g = (run.scores || {}).grounding || {};
  const fid = (run.scores || {}).fidelity || {};
  const ret = (run.scores || {}).retrieval || {};
  const wf = run.workflow || {};
  const objs = cap.objects || [];
  const el = document.getElementById("try-result");
  el.innerHTML = `
    <div class="try-done">
      <p class="eyebrow">${wasLive ? "Live result" : "Recorded result"} · ${esc(run.config?.caption_model || "")}</p>
      <h2>The caption</h2>
      <blockquote class="try-caption">${esc(cap.text || "(no caption)")}</blockquote>
      <div class="try-result-grid">
        <figure class="try-claim-figure">
          <div class="try-claim-stack">
            <img src="/api/chips/${encodeURIComponent(pick.chip)}.png" alt="Aerial image with the agent's claims drawn on a 3 by 3 grid" width="512" height="512">
            ${tryClaimGrid(cap)}
          </div>
          <figcaption>What the agent claimed, placed on the 3×3 grid it was given.</figcaption>
        </figure>
        <div class="try-claim-list">
          <h3>Claims (${objs.length})</h3>
          <ul>${objs.length ? objs.map((o) =>
            `<li><b>${esc(String(o.object).replace(/_/g, " "))}</b> · ${esc(o.count ?? "?")} · ${esc(String(o.position || "").replace(/_/g, " "))}${
              o.attributes && Object.keys(o.attributes).length ? ` · ${esc(Object.values(o.attributes).join(", "))}` : ""}</li>`).join("")
            : "<li>None asserted.</li>"}</ul>
          ${(cap.uncertain || []).length ? `<p class="try-uncertain">Unsure about: ${esc(cap.uncertain.map((u) => (u.object || u)).join(", "))}</p>` : ""}
        </div>
      </div>
      <h3>How it scored, against independent references</h3>
      <div class="try-scores">
        ${tryScore("Correct", g.correctness, "of what it claimed checks out")}
        ${tryScore("Complete", g.coverage, "of mapped features it mentioned")}
        ${tryScore("Fidelity", fid.score, "a Judge model's opinion vs the image")}
        ${tryScore("Retrieval", ret.mrr, "can a search find this caption first")}
        ${tryScore("Workflow", wf.score, "did the agent work sensibly")}
      </div>
      <p class="try-caveat">A high score does not prove a complete caption: counts and positions may be unstated or unevaluated. The agent never sees the reference answers (ADR-0006). <a href="#/runs/${encodeURIComponent(run.batch_id)}/${encodeURIComponent(run.case_id)}/${esc(String(run.repeat))}">Open the full Run report →</a></p>
      <div class="actions">
        <button type="button" class="btn secondary" id="try-again">← Pick another image</button>
        ${TRY_DATA.allow_launch && !wasLive ? `<button type="button" class="btn" id="try-live">Run it live on Bedrock ↗</button>` : ""}
      </div>
    </div>`;
  document.getElementById("try-again")?.addEventListener("click", () => {
    document.getElementById("try-stage").innerHTML = `<p class="try-stage-idle">Choose an image above to caption it.</p>`;
    document.querySelector(".try-cards")?.scrollIntoView({ behavior: tryReduceMotion() ? "auto" : "smooth", block: "start" });
  });
  document.getElementById("try-live")?.addEventListener("click", () => startDemo(pick, true));
}

function tryScore(label, value, note) {
  const w = value === null || value === undefined ? 0 : Math.max(3, Math.round(100 * value));
  return `<div class="try-score">
    <div class="try-score-top"><span>${esc(label)}</span><b>${tryPct(value)}</b></div>
    <div class="try-score-bar" role="img" aria-label="${esc(label)}: ${tryPct(value)}"><span style="width:${w}%"></span></div>
    <small>${esc(note)}</small></div>`;
}
