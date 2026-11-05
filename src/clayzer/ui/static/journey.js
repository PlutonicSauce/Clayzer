// Continuous, read-only storytelling. Scores and classifications are never computed here.
const STORY_SCENES = [
  "discover",
  "explore",
  "describe",
  "verify",
  "understand",
];
const STORY_NAMES = ["Discover", "Explore", "Describe", "Verify", "Understand"];
let ACTIVE_STORY = null;
const GALLERY_MEMORY = { search: "", category: "", y: 0 };
const motionPreference = matchMedia("(prefers-reduced-motion: reduce)");
let quietMotion = false;
const storyMotion = () => !motionPreference.matches && !quietMotion;

async function verifiedStoryRecord(batchId, caseId, repeat = 1) {
  const base = `/api/batches/${encodeURIComponent(batchId)}`;
  const name = `${encodeURIComponent(caseId)}--r${encodeURIComponent(repeat)}`;
  const [run, provenance, response] = await Promise.all([
    api(`${base}/runs/${name}.json`),
    api(`${base}/runs/${name}/provenance`),
    fetch(`${base}/files/cases.jsonl`),
  ]);
  if (!response.ok) throw new Error("Frozen references are unavailable.");
  const frozen = (await response.text())
    .split(/\r?\n/)
    .filter(Boolean)
    .map((line) => JSON.parse(line))
    .find((c) => c.id === caseId);
  if (
    !frozen ||
    run.case_id !== caseId ||
    !run.chip ||
    frozen.chips.at(-1)?.id !== run.chip.id
  )
    throw new Error(
      "This recording cannot be represented by one verified later image. Use its full report.",
    );
  const recorded = provenance.case?.chips?.find((c) => c.uri === run.chip.uri);
  const expected =
    recorded?.sha256 ||
    (provenance.case?.chip_uri === run.chip.uri
      ? provenance.case.chip_sha256
      : null);
  if (!expected || !window.crypto?.subtle)
    throw new Error(
      "The recorded image hash is unavailable; an image/record pairing cannot be verified.",
    );
  const image = await fetch(
    `/api/chips/${encodeURIComponent(run.chip.id)}.png`,
  );
  if (!image.ok) throw new Error("The recorded input image is unavailable.");
  const imageBytes = await image.arrayBuffer();
  const digest = await crypto.subtle.digest("SHA-256", imageBytes);
  const actual = [...new Uint8Array(digest)]
    .map((v) => v.toString(16).padStart(2, "0"))
    .join("");
  if (actual !== expected)
    throw new Error(
      "Current image bytes differ from this recording. Open the original report instead.",
    );
  return {
    imageUrl: URL.createObjectURL(
      new Blob([imageBytes], { type: "image/png" }),
    ),
    run,
    batchId,
    repeat,
    example: {
      id: caseId,
      kind: frozen.kind,
      chip: run.chip,
      chips: frozen.chips,
      labels: frozen.reference_labels || [],
    },
    synthetic: String(run.chip.source).startsWith("synthetic"),
    scripted: String(run.config?.caption_model || "").startsWith("scripted-"),
  };
}

function disposeStory() {
  ACTIVE_STORY?.dispose();
  ACTIVE_STORY = null;
  document.body.classList.remove("in-story");
}

async function publicJourney(parts) {
  const me = SEQ;
  const recording = parts[0] === "journey-run";
  let record = null,
    example,
    batches = [],
    notice = "",
    cases = [];
  let demoCandidate = null;
  const requestedScene = parts[recording ? 4 : 2] || "discover";
  if (!STORY_SCENES.includes(requestedScene)) {
    $view.innerHTML =
      '<h1>Scene not found</h1><p><a href="#/journey">Start the guided story</a>.</p>';
    return;
  }
  if (recording) {
    try {
      record = await verifiedStoryRecord(parts[1], parts[2], parts[3]);
      example = record.example;
    } catch (e) {
      if (stale(me)) return;
      $view.innerHTML = `<h1>The recording needs a closer look.</h1><p role="alert">${esc(e.message)}</p><p>No unverified image or claim outcomes have been attached to this story.</p><div class="actions"><a class="btn" href="#/runs/${encodeURIComponent(parts[1] || "")}/${encodeURIComponent(parts[2] || "")}/${encodeURIComponent(parts[3] || "1")}">Open the full recorded report</a><a class="btn secondary" href="#/journey">Explore reference imagery</a></div>`;
      return;
    }
  } else {
    cases = await api("/api/cases");
    example = parts[1]
      ? cases.find((c) => c.id === parts[1])
      : cases.find((c) => imageCategory(c) === "Solar") || cases[0];
    if (!example) {
      if (!stale(me))
        $view.innerHTML =
          '<h1>No imagery for this story yet.</h1><p>There is no matching Case in this store. No example or result has been invented.</p><a class="btn" href="#/cases">Explore available imagery</a>';
      return;
    }
    // Bounded discovery, not an assertion that the whole store has been searched.
    try {
      batches = await api("/api/batches");
      for (const b of batches.filter((b) => b.complete).slice(0, 8)) {
        if (stale(me)) return;
        const meta = await api(
          `/api/batches/${encodeURIComponent(b.batch_id)}`,
        );
        if (
          !demoCandidate &&
          /synthetic/i.test(b.label || b.batch_id) &&
          meta.config?.case_ids?.length
        ) {
          demoCandidate = {
            batchId: b.batch_id,
            caseId: meta.config.case_ids[0],
          };
        }
        if (!meta.config?.case_ids?.includes(example.id)) continue;
        try {
          record = await verifiedStoryRecord(b.batch_id, example.id);
        } catch {
          notice =
            "A candidate recording could not be paired with verified image bytes; inspect saved reports separately.";
        }
        if (record) {
          example = record.example;
          break;
        }
      }
    } catch {
      notice =
        "Saved-record discovery is unavailable. The image and references remain a reference-only preview.";
    }
  }
  if (stale(me)) {
    if (record?.imageUrl) URL.revokeObjectURL(record.imageUrl);
    return;
  }
  const displayImage = record?.imageUrl || chipUrl(example);
  const synthetic = record?.synthetic || false;
  const scripted = record?.scripted || false;
  const mode = record
    ? scripted
      ? "Recorded scripted illustration · not model accuracy"
      : synthetic
        ? "Synthetic input · recorded evaluation; not real-world accuracy"
        : "Verified recorded input · inspect evaluation limits"
    : "Reference imagery · no evaluated caption attached";
  const root = recording
    ? `#/journey-run/${encodeURIComponent(parts[1])}/${encodeURIComponent(parts[2])}/${encodeURIComponent(parts[3])}`
    : `#/journey/${encodeURIComponent(example.id)}`;
  const href = (scene) => `${root}/${scene}`;
  const report = record
    ? `#/runs/${encodeURIComponent(record.batchId)}/${encodeURIComponent(example.id)}/${encodeURIComponent(record.repeat)}`
    : "#/batches";
  const demoHref = demoCandidate
    ? `#/journey-run/${encodeURIComponent(demoCandidate.batchId)}/${encodeURIComponent(demoCandidate.caseId)}/1/describe`
    : null;
  const refs = example.labels;
  const rows = record?.run.scores?.grounding_detail?.rows || [];
  const outcomesRecorded = rows.some((r) => r.outcome);
  const g = record?.run.scores?.grounding || {};
  const cells = [
    "north_west",
    "north",
    "north_east",
    "west",
    "centre",
    "east",
    "south_west",
    "south",
    "south_east",
  ];
  const refWords = (r) =>
    `${r.count == null ? "Count unrecorded" : r.count + " recorded"} · ${readable(r.object)} · ${readable(r.position)} · ${r.source || "source unrecorded"}${r.count === 0 ? "; zero in this reference is not proof of absence" : ""}`;
  const next = (scene, label) =>
    `<a class="scene-next" href="${href(scene)}">${label} <span aria-hidden="true">↓</span></a>`;
  const outcomeList = outcomesRecorded
    ? `<div class="story-verdicts">${[
        ["supported", "Supported"],
        ["contradicted", "Contradicted"],
        ["not_verifiable", "Not verifiable"],
      ]
        .map(([key, label]) => {
          const found = rows.filter((r) => r.outcome === key);
          return `<section><h3>${label} <span>${found.length}</span></h3>${found.length ? `<ul>${found.map((r) => `<li>${esc(readable(r.claim?.object))}${r.claim?.count == null ? "" : ` · ${esc(r.claim.count)}`}${r.claim?.position ? ` · ${esc(readable(r.claim.position))}` : ""}</li>`).join("")}</ul>` : "<p>No claims recorded in this category.</p>"}</section>`;
        })
        .join("")}</div>`
    : `<p class="story-note">${record ? "This older recording has no claim-outcome classifications. Missing classifications are not evidence that all claims are supported." : "These are reference entries, not claim outcomes. A recorded caption must be evaluated before we can classify its statements."}</p>`;
  $view.innerHTML = `<article class="journey-frame" data-scene="discover"><div class="story-topline"><a href="#/cases">← All imagery</a><span>${esc(mode)}</span></div><nav class="story-nav" aria-label="Guided story scenes"><ol>${STORY_SCENES.map((s, i) => `<li><a href="${href(s)}" data-scene-link="${s}"><span aria-hidden="true">0${i + 1}</span> ${STORY_NAMES[i]}</a></li>`).join("")}</ol><button class="story-motion" type="button" aria-pressed="false">Reduce motion</button><details class="story-audio"><summary>Audio</summary><div class="story-audio-panel"><p>Listen to the current scene. Audio stops when the scene changes.</p><div><button id="story-listen" type="button">Play scene</button><button id="story-pause" type="button" disabled>Pause</button><button id="story-stop" type="button" disabled>Stop</button><label>Voice<select id="story-voice" aria-describedby="listen-voice-help"></select></label><label>Reading speed<select id="story-speed"><option value="0.75">0.75×</option><option value="1">1×</option><option value="1.25">1.25×</option><option value="1.5">1.5×</option></select></label></div><p id="story-audio-status"></p><progress id="story-audio-progress" max="1" value="0" aria-label="Scene reading progress"></progress></div></details></nav><div class="journey-body"><figure class="journey-stage" aria-label="The same input image throughout the story"><div class="journey-map"><img id="story-image" src="${displayImage}" alt="${esc(synthetic ? "Synthetic fixture input: generated imagery, not a photograph of a real place." : imageAlt(example))}" width="512" height="512" fetchpriority="high"><svg class="story-overlay" viewBox="0 0 512 512" aria-hidden="true"><g class="story-grid">${[1, 2].map((v) => `<path d="M${(v * 512) / 3} 0V512M0 ${(v * 512) / 3}H512"/>`).join("")}</g><g id="story-ref-cells"></g></svg></div><figcaption class="story-image-controls"><p><strong>${esc(synthetic ? "Synthetic fixture" : "NAIP aerial imagery")}</strong> · ${esc(example.chip.date)}</p><div><button type="button" id="story-expand">Expand full image ↗</button><label><input id="story-refs" type="checkbox"> Reference areas</label></div><p class="story-overlay-note">${record ? "Image bytes verified against recorded SHA256. References are frozen with this Run." : "Current Case references. Coarse grid areas, not detected object boundaries."}</p></figcaption></figure><div class="journey-scenes">
<section class="journey-scene" id="scene-discover" data-scene="discover" aria-labelledby="discover-title"><div class="scene-copy" data-listen><p class="scene-kicker">A Clayzer field story</p><h1 id="discover-title">How much can AI<br><em>really see?</em></h1><p>${scripted ? "This story uses an actual saved scripted recording. It demonstrates the software, not a vision model's accuracy." : "From above, a place becomes patterns. A description gives those patterns words. But what can we actually check?"}</p>${next("explore", "Explore how Clayzer works")}</div></section>
<section class="journey-scene" id="scene-explore" data-scene="explore" aria-labelledby="explore-title"><div class="scene-copy" data-listen><p class="scene-kicker">Explore · the image comes first</p><h2 id="explore-title">Look at the place.<br>Before the words.</h2><p>${synthetic ? "This is the actual synthetic input from a saved recording. It is a generated fixture, not a photograph of a real place." : "Look for repeated shapes, access roads and the land around them. The image is evidence you can inspect for yourself."}</p><p>A nine-cell grid gives us shared words for position: north, centre, south. It does not detect anything.</p><p class="story-note">${esc(example.chip.source)} · ${esc(example.id)}${example.kind === "change" ? ". This story uses the later image; open the Case to compare both dates." : ""}</p>${next("describe", "Now read the description")}</div></section>
<section class="journey-scene" id="scene-describe" data-scene="describe" aria-labelledby="describe-title"><div class="scene-copy" data-listen><p class="scene-kicker">Describe · words become claims</p><h2 id="describe-title">A description.<br>Not the final word.</h2>${record?.run.caption?.text ? `<p class="caption-kind">${scripted ? "RECORDED SCRIPTED CAPTION · NO VISION MODEL INVOKED" : "RECORDED CAPTION · VERIFIED INPUT IMAGE"}</p><blockquote>${esc(record.run.caption.text)}</blockquote><p>Keep the image in view. Which parts of those words can independent evidence answer?</p>` : `<p class="no-caption">No evaluated caption is attached to this image.</p><p>We checked the first repeat of up to eight recent complete experiments. This is not an exhaustive search. We will not make up a description or a score.</p>${demoHref ? `<a class="story-text-link" href="${demoHref}">Explore a saved recording →</a>` : '<a class="story-text-link" href="#/batches">Inspect saved experiments →</a>'}`}${notice ? `<p class="story-note">${esc(notice)}</p>` : ""}${next("verify", "Discover the evidence")}</div></section>
<section class="journey-scene" id="scene-verify" data-scene="verify" aria-labelledby="verify-title"><div class="scene-copy"><div data-listen><p class="scene-kicker">Verify · a separate source of evidence</p><h2 id="verify-title">What stands up<br>to a closer look?</h2><p>${record ? "These outcomes were recorded against the frozen references for this input. They have not been recomputed by the website." : "The reference information comes from a separate source. It is not an AI prediction, and it may be incomplete."}</p></div>${outcomeList}<div class="story-reference-list"><h3>Explore the reference areas</h3><p>Choose an entry to highlight its coarse grid cells. Zero-count entries do not highlight an object.</p>${refs.map((r, i) => `<button type="button" data-story-ref="${i}" aria-pressed="false">${esc(refWords(r))}</button>`).join("") || "<p>No reference entries recorded. That does not establish absence.</p>"}<p id="story-ref-status" role="status"></p></div><details class="story-definitions"><summary>Read the reference areas as text</summary><ul>${refs.map((r) => `<li>${esc(readable(r.object))}: ${r.count === 0 ? "zero-count entry; no object area highlighted" : esc((r.cells?.length ? r.cells : [r.position]).map(readable).join(", "))}</li>`).join("") || "<li>No reference areas recorded.</li>"}</ul><p>These are coarse named grid cells, not precise object boundaries.</p></details><details class="story-definitions"><summary>Supported, contradicted, or not verifiable?</summary><p>Supported: available evidence agrees with the evaluated claim. Contradicted: available evidence disagrees. Not verifiable: the evidence cannot answer the question. Missing map records do not prove absence.</p></details>${next("understand", "Put it in perspective")}</div></section>
<section class="journey-scene" id="scene-understand" data-scene="understand" aria-labelledby="understand-title"><div class="scene-copy" data-listen><p class="scene-kicker">Understand · the evidence has limits</p><h2 id="understand-title">A clearer view.<br>Better questions.</h2><p>A useful description helps you see. A trustworthy evaluation also shows what it cannot know.</p><dl class="story-measures"><div><dt>Correctness${g.correctness == null ? "" : ` · ${pct(g.correctness)}`}</dt><dd>${g.correctness == null ? "Not measured for this story. " : "Recorded agreement of evaluated claims. "}Are the evaluated claims supported?</dd></div><div><dt>Coverage${g.coverage == null ? "" : ` · ${pct(g.coverage)}`}</dt><dd>${g.coverage == null ? "Not measured for this story. " : "Recorded reference-type coverage. "}Which reference types were mentioned? This is not an object census.</dd></div></dl><p class="story-note">${scripted ? "These scripted measurements do not establish real model accuracy. " : synthetic ? "Synthetic-input measurements do not establish real-world accuracy. " : ""}${g.denominators ? `${esc(g.denominators.presence_evaluated)} of ${esc(g.denominators.claims)} presence claims evaluated. ${esc(g.denominators.unknown_claims)} unknown. ${esc(g.denominators.counts_evaluated)} counts and ${esc(g.denominators.positions_evaluated)} positions evaluated. ` : ""}Scorer versions, reference dates and denominators matter. No single score measures complete caption quality.</p><a class="story-report-link" href="${report}">${record ? "Open the full recorded report" : "Explore saved reports"} <span aria-hidden="true">↗</span></a><p><a class="story-text-link" href="${recording ? "#/cases" : `#/cases/${encodeURIComponent(example.id)}`}">${recording ? "Explore real aerial imagery" : "Inspect this Case in full"} →</a></p><p><a class="story-text-link" href="#/cases">Find another place →</a></p></div></section>
</div></div><p class="story-endnote">${esc(mode)}. ${record ? "See the report for frozen evidence, scorer provenance and trace links." : "No AI accuracy claim is made for this reference preview."}</p></article><dialog id="story-image-dialog" aria-labelledby="story-dialog-title"><div class="story-dialog-head"><h2 id="story-dialog-title">The complete input image</h2><button type="button" id="story-close">Close ×</button></div><img src="${displayImage}" alt="${esc(synthetic ? "Complete synthetic fixture input" : imageAlt(example))}" width="512" height="512" loading="lazy"><p>${esc(mode)} · ${esc(example.chip.date)}. No reference areas or cropped framing on this expanded image.</p></dialog>`;
  document.body.classList.add("in-story");
  const frame = document.querySelector(".journey-frame");
  const abort = new AbortController();
  const signal = abort.signal;
  let active = "",
    selectedRef = -1,
    manualOverlay = null;
  const checkbox = document.getElementById("story-refs");
  const dialog = document.getElementById("story-image-dialog");
  const sceneNodes = [...document.querySelectorAll(".journey-scene")];
  const drawRefs = () => {
    const chosen = selectedRef < 0 ? refs : [refs[selectedRef]];
    const covered = new Set(
      chosen
        .filter((r) => r.count !== 0)
        .flatMap((r) => (r.cells?.length ? r.cells : [r.position])),
    );
    document.getElementById("story-ref-cells").innerHTML = cells
      .map((c, i) =>
        covered.has(c)
          ? `<rect x="${((i % 3) * 512) / 3 + 2}" y="${(Math.floor(i / 3) * 512) / 3 + 2}" width="${512 / 3 - 4}" height="${512 / 3 - 4}"/>`
          : "",
      )
      .join("");
    frame.classList.toggle("show-references", checkbox.checked);
  };
  const setScene = (scene, scroll = false, updateUrl = false) => {
    const changed = active !== scene;
    active = scene;
    frame.dataset.scene = scene;
    document
      .querySelectorAll("[data-scene-link]")
      .forEach((a) =>
        a.dataset.sceneLink === scene
          ? a.setAttribute("aria-current", "step")
          : a.removeAttribute("aria-current"),
      );
    if (manualOverlay === null)
      checkbox.checked = scene === "verify" || scene === "understand";
    drawRefs();
    if (changed) window.cancelPageSpeech?.({ silentIfIdle: true });
    document.title = `${STORY_NAMES[STORY_SCENES.indexOf(scene)]} · Clayzer field story`;
    if (updateUrl && location.hash !== href(scene))
      history.replaceState(null, "", href(scene));
    if (scroll) {
      const destination = document.getElementById(`scene-${scene}`);
      destination.scrollIntoView({ block: "start", behavior: "auto" });
      const heading = destination.querySelector("h1, h2");
      heading.setAttribute("tabindex", "-1");
      heading.focus({ preventScroll: true });
    }
    // Audio reads this scene, not five scenes or controls in one long burst.
    document
      .querySelectorAll(".journey-scene")
      .forEach((n) =>
        n.toggleAttribute("data-listen-skip", n.dataset.scene !== scene),
      );
  };
  checkbox.addEventListener(
    "change",
    () => {
      manualOverlay = checkbox.checked;
      drawRefs();
    },
    { signal },
  );
  document.querySelectorAll("[data-story-ref]").forEach((b) =>
    b.addEventListener(
      "click",
      () => {
        selectedRef = Number(b.dataset.storyRef);
        manualOverlay = true;
        checkbox.checked = true;
        document
          .querySelectorAll("[data-story-ref]")
          .forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
        document.getElementById("story-ref-status").textContent =
          refs[selectedRef].count === 0
            ? "Zero-count reference: no object area highlighted. This does not establish absence."
            : `Showing reference areas for ${readable(refs[selectedRef].object)}: ${(refs[selectedRef].cells?.length ? refs[selectedRef].cells : [refs[selectedRef].position]).map(readable).join(", ")}. Coarse grid cells, not precise object outlines.`;
        drawRefs();
      },
      { signal },
    ),
  );
  document.getElementById("story-expand").addEventListener(
    "click",
    () => {
      window.cancelPageSpeech?.();
      dialog.showModal();
    },
    { signal },
  );
  document
    .getElementById("story-close")
    .addEventListener("click", () => dialog.close(), { signal });
  const motionButton = document.querySelector(".story-motion");
  const updateMotion = () => {
    document.documentElement.dataset.motion = storyMotion() ? "on" : "off";
    motionButton.setAttribute("aria-pressed", String(!storyMotion()));
    motionButton.textContent = motionPreference.matches
      ? "Reduced motion · device setting"
      : quietMotion
        ? "Reduced motion on"
        : "Reduce motion";
    motionButton.disabled = motionPreference.matches;
  };
  motionButton.addEventListener(
    "click",
    () => {
      quietMotion = !quietMotion;
      updateMotion();
    },
    { signal },
  );
  motionPreference.addEventListener("change", updateMotion, { signal });
  updateMotion();
  const audioMap = [
    ["story-listen", "listen-play"],
    ["story-pause", "listen-pause"],
    ["story-stop", "listen-stop"],
  ];
  const syncAudio = () => {
    for (const [local, original] of audioMap) {
      const control = document.getElementById(original);
      document.getElementById(local).disabled = control.disabled;
      document.getElementById(local).textContent =
        local === "story-listen"
          ? control.textContent.startsWith("Restart")
            ? "Restart scene"
            : "Play scene"
          : control.textContent;
    }
    const storyVoice = document.getElementById("story-voice");
    const pageVoice = document.getElementById("listen-voice");
    const optionsDiffer =
      storyVoice.options.length !== pageVoice.options.length ||
      [...pageVoice.options].some(
        (option, i) =>
          storyVoice.options[i]?.value !== option.value ||
          storyVoice.options[i]?.textContent !== option.textContent,
      );
    if (optionsDiffer)
      storyVoice.replaceChildren(
        ...[...pageVoice.options].map((option) => option.cloneNode(true)),
      );
    storyVoice.value = pageVoice.value;
    storyVoice.disabled = pageVoice.disabled;
    document.getElementById("story-speed").value =
      document.getElementById("listen-speed").value;
    document.getElementById("story-speed").disabled =
      document.getElementById("listen-speed").disabled;
    document.getElementById("story-audio-status").textContent =
      document.getElementById("listen-status").textContent;
    const progress = document.getElementById("listen-progress");
    document.getElementById("story-audio-progress").max = progress.max;
    document.getElementById("story-audio-progress").value = progress.value;
  };
  for (const [local, original] of audioMap)
    document
      .getElementById(local)
      .addEventListener(
        "click",
        () => document.getElementById(original).click(),
        { signal },
      );
  document.getElementById("story-speed").addEventListener(
    "change",
    (e) => {
      const original = document.getElementById("listen-speed");
      original.value = e.target.value;
      original.dispatchEvent(new Event("change"));
      syncAudio();
    },
    { signal },
  );
  document.getElementById("story-voice").addEventListener(
    "change",
    (e) => {
      const original = document.getElementById("listen-voice");
      original.value = e.target.value;
      original.dispatchEvent(new Event("change"));
      syncAudio();
    },
    { signal },
  );
  const audioObserver = new MutationObserver(syncAudio);
  audioObserver.observe(document.querySelector(".listen-panel"), {
    subtree: true,
    childList: true,
    attributes: true,
    characterData: true,
  });
  syncAudio();
  let observer;
  if ("IntersectionObserver" in window) {
    observer = new IntersectionObserver(
      () => {
        if (signal.aborted || location.hash !== href(active)) return;
        const line = innerWidth <= 760 ? innerHeight * 0.72 : innerHeight * 0.5;
        const current = sceneNodes.find((n) => {
          const b = n.getBoundingClientRect();
          return b.top <= line && b.bottom > line;
        });
        if (current && current.dataset.scene !== active)
          setScene(current.dataset.scene, false, true);
      },
      { threshold: [0, 0.25, 0.5, 0.75, 1] },
    );
    sceneNodes.forEach((n) => observer.observe(n));
  }
  const identity = recording
    ? parts.slice(0, 4).join("/")
    : `journey/${example.id}`;
  ACTIVE_STORY = {
    identity,
    accepts: (p) =>
      recording
        ? p.slice(0, 4).join("/") === identity
        : p[0] === "journey" && (!p[1] || p[1] === example.id),
    navigate: (p) => {
      const s = p[recording ? 4 : 2] || "discover";
      if (!STORY_SCENES.includes(s)) return false;
      setScene(s, true);
      return true;
    },
    dispose: () => {
      observer?.disconnect();
      audioObserver.disconnect();
      if (record?.imageUrl) URL.revokeObjectURL(record.imageUrl);
      abort.abort();
      if (dialog.open) dialog.close();
    },
    start: () => {
      history.replaceState(null, "", href(requestedScene));
      setScene(requestedScene, true);
    },
  };
}

// Native view transitions are a small progressive enhancement, never a network wait.
async function presentCaseView(render) {
  const shared = document.querySelector(
    '.gallery-image img[data-story-shared="true"]',
  );
  if (shared && document.startViewTransition && storyMotion()) {
    shared.style.viewTransitionName = "clayzer-place";
    let image;
    const transition = document.startViewTransition(() => {
      render();
      image = document.querySelector("#case-fig img");
      if (image) image.style.viewTransitionName = "clayzer-place";
    });
    await transition.updateCallbackDone;
    transition.finished.then(
      () => {
        if (image) image.style.viewTransitionName = "";
      },
      () => {
        if (image) image.style.viewTransitionName = "";
      },
    );
  } else render();
}
