// Visitor views use the existing read-only API. All data is escaped before HTML insertion.
const readable = (s) => String(s ?? "Not recorded").replace(/_/g, " ");
const imageCategory = (c) =>
  c.kind === "change"
    ? "Change over time"
    : c.labels.some((l) => /solar/.test(l.object) && l.count !== 0)
      ? "Solar"
      : c.labels.some((l) => /wind/.test(l.object) && l.count !== 0)
        ? "Wind"
        : "Other landscapes";
const imageAlt = (c) =>
  `NAIP aerial image, ${c.chip.date}. ${imageCategory(c)} example ${c.id}. Independent reference information follows; this is not an AI detection.`;
const pageHead = (k, h, p) =>
  `<header class="page-head" data-listen><p class="eyebrow">${k}</p><h1>${h}</h1><p class="lede">${p}</p></header>`;
const threeSteps = () =>
  `<nav class="journey-ribbon" aria-label="From image to evidence"><a href="#/cases"><span>01</span> Find a place <b aria-hidden="true">↗</b></a><a href="#/batches"><span>02</span> Read a description <b aria-hidden="true">↗</b></a><a href="#/how"><span>03</span> Follow the evidence <b aria-hidden="true">↗</b></a></nav>`;
const chipUrl = (c) => `/api/chips/${encodeURIComponent(c.chip.id)}.png`;
const photoCard = (c, extra = "") =>
  `<figure class="field-photo ${extra}"><a href="#/cases/${encodeURIComponent(c.id)}"><img src="${chipUrl(c)}" alt="${esc(imageAlt(c))}" width="512" height="512"><span class="photo-arrow" aria-hidden="true">↗</span></a><figcaption><span>${esc(imageCategory(c))} · NAIP ${esc(c.chip.date)}</span><a href="#/cases/${encodeURIComponent(c.id)}">Explore this place <span aria-hidden="true">→</span></a></figcaption></figure>`;
const evidenceNote = () =>
  `<aside class="evidence-note" data-listen><strong>Evidence has limits.</strong> A missing map record does not prove absence. Correctness checks evaluated claims; coverage checks which reference types were mentioned. Neither alone measures complete caption quality.</aside>`;

async function publicHome() {
  const me = SEQ;
  const cases = await api("/api/cases");
  if (stale(me)) return;
  const example = cases.find((c) => imageCategory(c) === "Solar") || cases[0];
  const second = cases.find(
    (c) => imageCategory(c) === "Wind" && c.id !== example?.id,
  );
  $view.innerHTML = `<section class="earth-hero"><div data-listen><p class="eyebrow"><span class="live-dot" aria-hidden="true"></span> Earth, with a little more understanding</p><h1>Explore the Earth.<br><em>Question the AI.</em></h1><p class="lede">A closer look at our changing planet. Explore aerial imagery, read AI descriptions and discover what the evidence really says.</p><div class="actions"><a class="btn" href="#/journey">Explore how Clayzer works <span aria-hidden="true">↗</span></a><a class="btn secondary" href="#/cases">Browse the imagery</a></div><p class="hero-footnote">A research prototype · Curiosity welcome. Evidence essential.</p></div><div class="earth-collage">${example ? photoCard(example, "photo-main") : '<p class="empty">No imagery in this store yet.</p>'}${second ? photoCard(second, "photo-small") : ""}<span class="field-stamp" aria-hidden="true">EARTH<br>FIELD NOTES<br>↙  CLAYZER</span></div></section>${threeSteps()}

  <section class="section-intro" data-listen><p class="eyebrow">From image to evidence</p><h2>A description is a starting point.<br>Understanding takes evidence.</h2><p>We make the evaluation visible, so you can inspect the image, the description and the reasons behind each score.</p></section>
  <section class="evidence-section" data-listen><div><p class="eyebrow">A more honest picture</p><h2>What do we actually know?</h2><p>Independent reference information comes from sources such as USGS and OpenStreetMap. It is kept separate from the AI's input.</p><a class="text-link" href="#/about">Read about the method →</a></div><ul class="evidence-list"><li><b>✓ Supported</b><span>Available reference evidence agrees with a claim.</span></li><li><b>× Contradicted</b><span>Available reference evidence disagrees with a claim.</span></li><li><b>? Not verifiable</b><span>The evidence is missing, incomplete or cannot answer the question.</span></li></ul></section>${evidenceNote()}
  <section class="collection-banner" data-listen><div><p class="eyebrow">Make up your own mind</p><h2>See the places. Inspect the process.</h2><p>${cases.length} development examples currently in this store. Reference imagery is not evidence of AI caption accuracy. Scripted demonstrations, when present, are labelled synthetic.</p></div><a class="btn" href="#/batches">Explore results →</a></section>`;
}

async function publicHow() {
  const me = SEQ;
  const cases = await api("/api/cases");
  if (stale(me)) return;
  const example = cases.find((c) => imageCategory(c) === "Solar") || cases[0];
  const steps = [
    [
      "Start with a place",
      "Every story starts on the ground.",
      "This is genuine aerial imagery. Its date and source matter: a place can change, and a map can be incomplete.",
    ],
    [
      "Read the description",
      "Words are claims. Let's be curious.",
      "Saved experiments contain the actual recorded descriptions. This image preview has no caption attached to it. We never invent one to fill the space.",
    ],
    [
      "Look closer",
      "An answer is only as good as its evidence.",
      "Independent references are kept separate from the captioner's input. They help check claims, but they cannot answer every question.",
    ],
  ];
  $view.innerHTML = `${pageHead("A field guide to Clayzer", "A place. A description.<br><em>A closer look.</em>", "You don't need to be an AI researcher. Bring your curiosity; we'll make the evidence visible.")}<section class="method-lab" aria-label="Explore the three steps"><div class="method-visual">${example ? `<div class="method-image"><img src="${chipUrl(example)}" alt="${esc(imageAlt(example))}" width="512" height="512"><div class="method-grid" aria-hidden="true">${Array.from({ length: 9 }, (_, i) => `<span>${["NW", "N", "NE", "W", "C", "E", "SW", "S", "SE"][i]}</span>`).join("")}</div><span class="image-tag">Real imagery · independent references</span></div><p class="image-source">NAIP · ${esc(example.chip.date)} · <a href="#/cases/${encodeURIComponent(example.id)}">Inspect full image and references →</a></p>` : '<p class="empty">No example imagery in this store. The method still applies to saved evaluations.</p>'}<p class="method-caveat">A reference preview, not an AI prediction. These images alone do not measure model accuracy.</p></div><div class="method-story"><p class="eyebrow">Follow the evidence</p><div class="method-steps" role="group" aria-label="Choose a step">${steps.map((x, i) => `<button class="method-step" aria-pressed="${i === 0}" aria-controls="method-detail" data-method="${i}"><span>0${i + 1}</span>${x[0]}<b aria-hidden="true">↗</b></button>`).join("")}</div><div id="method-detail" class="method-detail" aria-live="polite" aria-atomic="true"></div></div></section>${evidenceNote()}<section class="measurement-story" data-listen><header><p class="eyebrow">Two questions. Different answers.</p><h2>Getting it right.<br>Leaving things out.</h2><p>There is no single number that tells the whole story.</p></header><div><article><span class="measure-symbol" aria-hidden="true">✓</span><h3>Correctness</h3><p>How much of the description's evaluated claims agrees with independent evidence?</p></article><article><span class="measure-symbol" aria-hidden="true">⊞</span><h3>Coverage</h3><p>Which reference object types were mentioned? A brief caption can be correct and still leave things out.</p></article><details><summary>What about the other measurements?</summary><p>Fidelity is an AI judge's opinion. Retrieval checks whether text search finds relevant descriptions. Workflow checks task completion. Time and hardware observations appear only when measured. Missing measurements stay unavailable.</p></details></div></section><div class="actions"><a class="btn" href="#/journey">Enter the guided story ↗</a><a class="btn secondary" href="#/batches">Read a recorded report ↗</a><a class="btn secondary" href="#/how/case">Technical walkthrough</a></div>`;
  const show = (i) => {
    document
      .querySelectorAll("[data-method]")
      .forEach((b) =>
        b.setAttribute("aria-pressed", String(Number(b.dataset.method) === i)),
      );
    document.querySelector(".method-lab").dataset.step = i;
    const refs = example?.labels.filter((l) => l.count !== 0) || [];
    document.getElementById("method-detail").innerHTML =
      `<p class="eyebrow">Step 0${i + 1} / 03</p><h2>${steps[i][1]}</h2><p data-listen>${steps[i][2]}</p>${i === 2 ? `<h3>Recorded reference entries</h3><ul>${refs.map((l) => `<li>${esc(readable(l.object))} · ${esc(readable(l.position))} · ${esc(l.source)}</li>`).join("") || "<li>No positive reference entries recorded. This does not establish absence.</li>"}</ul><p class="sub">References are not claim outcomes. Outcomes require a recorded caption and evaluation.</p>` : i === 1 ? '<a class="text-link" href="#/batches">Find actual recorded descriptions →</a>' : '<p class="sub">The optional nine-cell grid gives us a shared way to talk about position. It is not a detection overlay.</p>'}`;
  };
  document
    .querySelectorAll("[data-method]")
    .forEach((b) =>
      b.addEventListener("click", () => show(Number(b.dataset.method))),
    );
  show(0);
}

async function publicGallery() {
  const me = SEQ;
  const cases = await api("/api/cases");
  if (stale(me)) return;
  $view.innerHTML = `${pageHead("The development collection", "Explore imagery", "Real places, independent references. Browse solar sites, wind projects and other landscapes. These images alone do not measure AI accuracy.")}<div class="gallery-controls"><label>Find an example<input type="search" id="image-search" placeholder="Search example ID or reference type"></label><label>Landscape<select id="image-category"><option value="">All landscapes</option>${["Solar", "Wind", "Other landscapes", "Change over time"].map((x) => `<option>${x}</option>`).join("")}</select></label><p id="image-count" role="status" aria-live="polite"></p></div><div class="case-grid" id="image-gallery"></div>`;
  const render = () => {
    const q = document.getElementById("image-search").value.toLowerCase();
    const category = document.getElementById("image-category").value;
    const filtered = cases.filter(
      (c) =>
        (!category || imageCategory(c) === category) &&
        `${c.id} ${c.labels.map((l) => l.object).join(" ")}`
          .toLowerCase()
          .includes(q),
    );
    document.getElementById("image-count").textContent =
      `${filtered.length} of ${cases.length} examples`;
    document.getElementById("image-gallery").innerHTML =
      filtered
        .map(
          (c) =>
            `<article class="case-card"><a href="#/cases/${encodeURIComponent(c.id)}" class="gallery-image"><img src="/api/chips/${encodeURIComponent(c.chip.id)}.png" alt="${esc(imageAlt(c))}" loading="lazy" width="512" height="512"><span class="image-tag">${esc(imageCategory(c))}</span></a><div class="body"><p class="eyebrow">NAIP · ${esc(c.chip.date)}</p><h2><a href="#/cases/${encodeURIComponent(c.id)}">${esc(readable(c.id))}</a></h2><p>${c.labels.length} reference entries · ${c.kind === "change" ? "Two image dates" : "One image date"}</p><a class="text-link" href="#/cases/${encodeURIComponent(c.id)}">Inspect image and evidence →</a></div></article>`,
        )
        .join("") ||
      '<div class="empty"><h2>No matching examples</h2><p>Try another reference type, clear the search or select All landscapes.</p></div>';
  };
  document.getElementById("image-search").value = GALLERY_MEMORY.search;
  document.getElementById("image-category").value = GALLERY_MEMORY.category;
  document.getElementById("image-search").addEventListener("input", () => {
    GALLERY_MEMORY.search = document.getElementById("image-search").value;
    GALLERY_MEMORY.y = 0;
    render();
  });
  document.getElementById("image-category").addEventListener("change", () => {
    GALLERY_MEMORY.category = document.getElementById("image-category").value;
    GALLERY_MEMORY.y = 0;
    render();
  });
  render();
}

async function publicAbout() {
  const me = SEQ;
  const cases = await api("/api/cases");
  if (stale(me)) return;
  const example = cases.find((c) => imageCategory(c) === "Wind") || cases[0];
  $view.innerHTML = `${pageHead("About Clayzer", "More transparent AI,\none place at a time.", "A research prototype for generating and evaluating descriptions of aerial imagery for Clay v2.")}${example ? `<section class="about-field"><div data-listen><p class="eyebrow">Curiosity, grounded.</p><h2>Our planet is complex.<br>Understanding it should feel inviting.</h2><p>Clayzer makes the distance between an AI description and its evidence easier to explore. Look at the place. Ask questions. Follow the record.</p></div>${photoCard(example)}</section>` : ""}<div class="reading-section" data-listen><h2>What this prototype demonstrates</h2><p>Clayzer connects imagery, descriptions, independent references and recorded AI activity. You can inspect individual examples and evaluation experiments, with separate measurements of output quality and workflow.</p><h2>What it does not establish</h2><p>The software demonstration is not a validated claim of model accuracy, training improvement or operational performance. Synthetic recordings test software behavior. Independent human calibration and external benchmark evaluation remain outstanding.</p><h2>Where the evidence comes from</h2><p>NAIP aerial imagery is public domain. Reference information includes public-domain USGS solar and wind data and © OpenStreetMap contributors, available under the Open Database License. Map records may be incomplete or from different dates.</p><p><a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap attribution and licence</a> · <a href="https://github.com/PlutonicSauce/Clayzer/blob/main/fixtures/caption/README.md" target="_blank" rel="noopener">Development collection documentation</a></p><h2>Accessibility and listening</h2><p>Use the Listen controls to read a curated page summary with your browser's speech support. Audio never starts automatically. Keyboard navigation, visible focus, resizable text and reduced-motion preferences are supported. Accessibility testing is ongoing; this prototype does not claim certified WCAG compliance.</p><div class="actions"><a class="btn" href="#/how">Understand the method</a><a class="btn secondary" href="#/developer">Developer tools</a></div></div>`;
}

function publicDeveloper() {
  $view.innerHTML = `${pageHead("For researchers and builders", "Developer tools", "Inspect methodology, raw reports and implementation details without losing the larger picture.")}<div class="tool-grid">${[
    [
      "how/case",
      "Technical walkthrough",
      "All ten steps, contracts and implementation links.",
    ],
    [
      "ontology",
      "Object field guide",
      "Explore the team’s ontology and captioning guidance.",
    ],
    [
      "tasks",
      "Project tasks",
      "Current scope, progress and known dependencies.",
    ],
    [
      "sources",
      "Data sources",
      "Source provenance, permitted uses and limitations.",
    ],
    [
      "concepts",
      "Concepts and glossary",
      "Cases, Batches, Claims and Traces explained.",
    ],
    [
      "datasets",
      "Dataset cards",
      "Descriptive diagnostics for imported caption sets.",
    ],
    [
      "batches",
      "Experiments and raw reports",
      "Saved measurements, provenance, JSON and trace links.",
    ],
  ]
    .map(
      ([route, title, body]) =>
        `<article><h2><a href="#/${route}">${title} →</a></h2><p>${body}</p></article>`,
    )
    .join(
      "",
    )}</div><p><a href="/deck">Pitch deck</a> · <a href="https://github.com/PlutonicSauce/Clayzer" target="_blank" rel="noopener">Source repository</a></p>`;
}

function runStory(r) {
  const scripted = String(r.config?.caption_model || "").startsWith(
    "scripted-",
  );
  const g = r.scores?.grounding || {};
  const rows = r.scores?.grounding_detail?.rows || [];
  const hasOutcomes = rows.some((x) => x.outcome);
  const groups = [
    ["supported", "Supported"],
    ["contradicted", "Contradicted"],
    ["not_verifiable", "Not verifiable"],
  ];
  const metric = (n, v, explanation) =>
    `<div class="metric-card"><h3>${n}</h3><strong>${v == null ? "Not measured" : pct(v)}</strong><p>${explanation}</p></div>`;
  return `<section class="run-story"><p class="evidence-note" data-listen><strong>Outcome: ${esc(readable(r.status))}.</strong> ${scripted ? "Scripted demonstration. These values do not measure real model accuracy." : r.chip?.source?.startsWith("synthetic") ? "Synthetic input. These recorded values do not establish real-world model accuracy." : "Recorded evaluation; read the evidence and measurement limits below."}</p><div class="run-intro"><img class="run-image" src="/api/chips/${encodeURIComponent(r.chip.id)}.png" alt="${esc(r.chip?.source?.startsWith("synthetic") ? "Synthetic fixture input" : "Recorded aerial input")} for ${esc(r.case_id)}; the caption and independent evidence follow."><div data-listen><p class="eyebrow">The evaluation, explained</p><h2>The recorded description</h2><blockquote>${esc(r.caption?.text || "No evaluated caption is available for this Run.")}</blockquote><p>${r.replay ? "Replayed recording: recomputed measurements and retained model opinions may use different scoring versions. Inspect provenance." : "A recorded description; inspect the evidence before drawing conclusions."}</p></div></div><div class="metric-grid">${metric("Correctness", g.correctness, "Agreement of evaluated claims with reference evidence.")}${metric("Coverage", g.coverage, "Reference object types mentioned; not an object census.")}${metric("Fidelity", r.scores?.fidelity?.score, "An AI judge's opinion; not independent ground truth.")}${metric("Workflow", r.workflow?.score, "Applicable task-completion and process checks.")}${metric("Search Recall@1", r.scores?.retrieval?.["recall@1"], `Repeat-level search measurement: ${esc(r.scores?.retrieval?.query_count ?? "unrecorded")} evaluated queries over ${esc(r.scores?.retrieval?.corpus_size ?? "unrecorded")} descriptions. Not a per-image score.`)}</div><section data-listen><p>${g.denominators ? `${esc(g.denominators.presence_evaluated)} of ${esc(g.denominators.claims)} claims have evaluated presence; ${esc(g.denominators.unknown_claims)} lack verifiable presence evidence. ${esc(g.denominators.counts_evaluated)} counts and ${esc(g.denominators.positions_evaluated)} positions evaluated.` : "Field denominators were not recorded for this historical result."}</p><h2>What does the evidence say?</h2><div class="evidence-columns">${groups
    .map(([key, title]) => {
      const found = rows.filter((x) => x.outcome === key);
      return `<section><h3>${title} (${hasOutcomes ? found.length : "not recorded"})</h3><ul>${found.map((x) => `<li>${esc(readable(x.claim?.object))}${x.claim?.position ? ` · ${esc(readable(x.claim.position))}` : ""}</li>`).join("") || "<li>No claims recorded in this category.</li>"}</ul></section>`;
    })
    .join(
      "",
    )}</div>${!hasOutcomes ? "<p>Claim-level outcome classifications were not recorded. This is not evidence that all claims are supported.</p>" : ""}</section>${evidenceNote()}<p>The detailed report uses the independent references frozen with this experiment; they may differ from the current gallery.</p><h2>How was it scored, and what did the AI do?</h2><p>The detailed report below contains the image, component scores, denominators and recorded steps. Technical records and JSON remain available.</p></section>`;
}

function enhancePage() {
  document.querySelectorAll("#view table").forEach((t) => {
    t.querySelectorAll("th").forEach((th) => (th.scope = "col"));
    if (!t.querySelector("caption")) {
      const c = t.createCaption();
      c.className = "sr-only";
      c.textContent =
        document.querySelector("#view h1")?.textContent || "Recorded details";
    }
    const wrapper = document.createElement("div");
    wrapper.className = "table-scroll";
    wrapper.tabIndex = 0;
    wrapper.setAttribute("role", "region");
    wrapper.setAttribute("aria-label", "Scrollable recorded details");
    t.before(wrapper);
    wrapper.append(t);
  });
  document.querySelectorAll("#view pre").forEach((n) => {
    n.tabIndex = 0;
    n.setAttribute("aria-label", "Recorded code or source details");
  });
  document
    .querySelectorAll(".pick")
    .forEach((x) =>
      x.setAttribute(
        "aria-label",
        `Select experiment ${x.value} for comparison`,
      ),
    );
  document
    .querySelectorAll('a[target="_blank"]')
    .forEach((a) => (a.rel = "noopener noreferrer"));
}

document.querySelector(".skip-link").addEventListener("click", (e) => {
  e.preventDefault();
  document.getElementById("view").focus();
});

function experimentCards(list) {
  return `<div class="experiment-cards">${list.map((b) => `<article class="experiment-card"><p class="eyebrow">Saved evaluation experiment</p><h2><a href="#/batches/${encodeURIComponent(b.batch_id)}">${esc((b.label || b.batch_id).replace(/[-_]+/g, " "))}</a></h2><p>${esc(b.cases)} image examples · ${esc(b.repeats)} repeat${b.repeats === 1 ? "" : "s"}</p><dl><div><dt>Correctness</dt><dd>${badge(b.correctness)}</dd></div><div><dt>Coverage</dt><dd>${badge(b.coverage)}</dd></div><div><dt>AI judge opinion</dt><dd>${badge(b.fidelity)}${b.self_graded ? ' <span class="badge b-warn">self-graded</span>' : ""}</dd></div></dl><p class="sub">${b.complete ? "Recorded results available. Inspect the report for denominators, scorer version and limitations." : "No complete evaluation recorded. Missing measurements are not zero."}</p><a class="text-link" href="#/batches/${encodeURIComponent(b.batch_id)}">Open this report →</a></article>`).join("")}</div>`;
}

function mountChangeComparison(c) {
  const section = document.createElement("section");
  section.className = "change-comparison";
  section.innerHTML = `<header data-listen><p class="eyebrow">A place, across time</p><h2>What changed between these images?</h2><p>Move the divider to compare the same footprint. Reference overlays remain on the separate later-image viewer above.</p></header><div class="compare-image"><img src="/api/chips/${encodeURIComponent(c.chips[0].id)}.png" alt="Earlier NAIP image, ${esc(c.chips[0].date)}" width="512" height="512"><img class="compare-later" src="${chipUrl(c)}" alt="Later NAIP image, ${esc(c.chip.date)}" width="512" height="512"><span class="compare-divider" aria-hidden="true"></span><div class="compare-dates" aria-hidden="true"><span>${esc(c.chip.date)} · later</span><span>${esc(c.chips[0].date)} · earlier</span></div></div><label for="compare-position">Image divider position <output id="compare-value" for="compare-position">50% later image</output></label><input id="compare-position" type="range" min="0" max="100" value="50" aria-valuetext="50 percent later image"><p class="sub">Use the arrow keys when the slider is focused. Both unaltered images are also available in the viewer and image details above.</p>`;
  $view.append(section);
  const slider = section.querySelector("input");
  slider.addEventListener("input", () => {
    section.style.setProperty("--compare", `${slider.value}%`);
    slider.setAttribute(
      "aria-valuetext",
      `${slider.value} percent later image`,
    );
    section.querySelector("output").textContent =
      `${slider.value}% later image`;
  });
}
