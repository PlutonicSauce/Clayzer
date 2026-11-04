// The 8-minute pitch. One entry per slide: a title, a time budget in seconds (they add up to
// 8:00; the notes panel warns when a slide runs long), presenter notes, and the component.
//
// Numbers come from the committed Baseline (baselines/default/summary.json): base-v2, Nova Pro
// captions judged by Opus 5.5, 4 dev Cases × 3 Repeats, all 12 Runs ok. Re-quote from a committed
// Baseline if they change, never from a one-off Run.

import { html } from "./html.js";
import { ArchitectureDiagram } from "./diagram.js";

const Kicker = ({ children }) => html`<p class="kicker">${children}</p>`;

function Title() {
  return html`<div class="title-slide">
    <${Kicker}>Clay Earth Dataset Foundry · Caption track<//>
    <h1>Clayzer</h1>
    <p class="lede">Give us your caption set, and we tell you how much of it you can trust, where
      it fails, and what it costs to make better.</p>
    <p class="team">Team names · date</p>
  </div>`;
}

function Problem() {
  return html`<div class="two-col">
    <div>
      <${Kicker}>The problem<//>
      <h2>Clay v2 learns from captions nobody has checked</h2>
      <p class="big">Clay v2 is text-native. It is trained on synthetic captions of satellite and
        aerial imagery, and Clay has no bandwidth to test them.</p>
      <p class="big">A caption that miscounts turbines or invents a road teaches the model the
        wrong thing, at continental scale.</p>
    </div>
    <div class="hook">
      <p class="hook-label">Seen in a real Run</p>
      <blockquote>"An aerial image of a wind farm … turbines in the north-west, north, and
        north-east …"</blockquote>
      <p class="hook-truth">The USGS turbine database says <b>16 turbines, to the south</b>.
        Wrong count, wrong place. A plausible caption, and wrong — the kind that quietly poisons
        training.</p>
    </div>
  </div>`;
}

function Generation() {
  return html`<div>
    <${Kicker}>Our approach · generating captions<//>
    <h2>Captions that know where things are</h2>
    <div class="flow">
      <div class="step"><b>Chip</b><span>512 × 512 px NAIP, 0.6 m</span></div>
      <div class="arrow">→</div>
      <div class="step"><b>Caption Harness</b><span>Nova Pro on Bedrock</span></div>
      <div class="arrow">→</div>
      <div class="step"><b>Verify-then-write</b><span>each Claim checked at its cell</span></div>
      <div class="arrow">→</div>
      <div class="step"><b>Caption</b><span>objects, counts, 3 × 3 positions, relations</span></div>
    </div>
    <p class="big">The novel step: before a Claim is written, the Harness checks it against
      LGND Geo's imagery search at the Claim's own grid cell (verify-then-write). A Claim the
      imagery can't support is dropped or moved, so the caption is grounded as it is written, not
      only scored afterwards.</p>
    <p class="source">Positions use a 3 × 3 grid and a fixed relation vocabulary (ADR-0007), so
      "solar array, centre" and "road along the north edge" are checkable, not prose.</p>
  </div>`;
}

const CRITERIA = [
  ["Grounding", "Does it match what is on the ground: objects, attributes, counts?", "most important"],
  ["Fidelity", "Does an LLM judge rate it an accurate account of the image?", ""],
  ["Retrieval", "Can the caption be found from a text query alone?", ""],
  ["Cost", "Throughput and time to output, in GPU time", ""],
  ["Label prep time", "How long it takes to prepare the labels", ""],
];

function Evaluation() {
  return html`<div>
    <${Kicker}>Our approach · evaluating captions<//>
    <h2>Every Claim checked against open data</h2>
    <div class="criteria">
      ${CRITERIA.map(([name, q, tag]) => html`<div class="criterion">
        <b>${name}</b>${tag && html`<span class="tag">${tag}</span>`}<p>${q}</p>
      </div>`)}
    </div>
    <p class="big">We score Clay's five criteria, and the captioner never sees the Answer Keys
      (ADR-0006), so grounding can't be gamed. Grounding is two numbers — correctness and
      coverage — so a terse caption can't win by saying less.</p>
    <p class="source">Answer Keys: USGS solar and wind databases, OpenStreetMap. It scores any
      caption set, not only ours (CAP-20), and a regression gate decides if a change actually
      helped.</p>
  </div>`;
}

function Demo() {
  return html`<div>
    <${Kicker}>Live demo<//>
    <h2>One Batch, from Chip to report</h2>
    <ol class="demo-script">
      <li><b>A Case.</b> The Chip and its Reference Labels from USGS and OSM.</li>
      <li><b>Its Caption.</b> Each Claim marked supported or unsupported, on the 3 × 3 grid.</li>
      <li><b>The Batch report.</b> Five criteria side by side, mean ± spread over 3 Repeats.</li>
      <li><b>The dataset card.</b> Duplication, coverage, and per-class error patterns —
        where a greenhouse gets called a solar array.</li>
      <li><b>Compare to Baseline.</b> The gate says better, worse, or inconclusive.</li>
    </ol>
    <p class="source">Live here: <a href="./">Overview</a> · <a href="./#/batches">Batches</a> ·
      fallback is the recorded Batch, replayed offline with no model or network.</p>
  </div>`;
}

function Architecture() {
  return html`<div class="arch-slide">
    <${Kicker}>On AWS<//>
    <h2>Deployed in each teammate's account with one command</h2>
    <${ArchitectureDiagram} />
    <div class="legend">
      <span><i class="live"></i> Deployed: this deck is served by it</span>
      <span><i class="planned"></i> Planned next</span>
      <span>A role per service; the web app can only read its own prefix of the store</span>
    </div>
  </div>`;
}

function Results() {
  return html`<div>
    <${Kicker}>Results · committed Baseline base-v2<//>
    <h2>What we measured</h2>
    <div class="criteria">
      <div class="criterion"><b>0.58</b><p>Grounding correctness</p></div>
      <div class="criterion"><b>0.67</b><p>Grounding coverage</p></div>
      <div class="criterion"><b>0.54</b><p>Fidelity (Opus judge)</p></div>
      <div class="criterion"><b>0.89</b><p>Retrieval MRR, ±0.02</p></div>
      <div class="criterion"><b>3.9 s</b><p>per Caption on Bedrock</p></div>
    </div>
    <p class="big">4 dev Cases × 3 Repeats, 12 of 12 Runs clean. The gate caught a vague
      one-Claim prompt that looked good on correctness but collapsed on coverage (0.67 → 0.27) —
      exactly the "says less to score higher" failure, stopped before it became the Baseline.</p>
    <p class="source">Every rate is per criterion; weights are Clay's to set. Numbers from a
      committed Baseline, not a one-off Run.</p>
  </div>`;
}

function Shipped() {
  return html`<div>
    <${Kicker}>Reliability<//>
    <h2>Built so the eval, and the demo, hold up</h2>
    <div class="criteria">
      <div class="criterion"><b>Replay</b><p>Any Batch rescored and re-reported offline — no
        model, credentials, or network. The demo can't fail on a flaky link.</p></div>
      <div class="criterion"><b>Dataset card</b><p>Per caption set: duplication, coverage, and
        per-class error patterns, with look-alike confusions from the Object Ontology.</p></div>
      <div class="criterion"><b>Least privilege</b><p>A role per service on AWS, no long-lived
        keys, every bucket private — checked by <code>clayzer readiness</code>.</p></div>
    </div>
    <p class="source">Every scored Run keeps its Trace, inputs, and the rubric it was judged
      against, so a verdict is inspectable and reproducible.</p>
  </div>`;
}

function Next() {
  return html`<div class="title-slide closing">
    <${Kicker}>What it means for Clay<//>
    <h2>Trust your captions before you train on them</h2>
    <p class="lede">On Monday: hand Clayzer a caption set, get a verdict — how much to trust,
      where it fails, what it costs to fix. Point it at Clay's own pipeline next.</p>
    <p class="team">The ask: Clay's real caption set and its rubric weights, so the verdict is
      Clay's, not our stand-in's.</p>
  </div>`;
}

export const SLIDES = [
  { title: "Clayzer", seconds: 25, theme: "dark", component: Title,
    notes: ["Say the one-line pitch, then move on.", "8:00 total. T starts the timer."] },
  { title: "The problem", seconds: 55, component: Problem,
    notes: ["Clay v2 is trained on untested synthetic captions.", "Read the wrong caption, then the Answer Key: 16 turbines, south. Make it concrete."] },
  { title: "Generating captions", seconds: 70, component: Generation,
    notes: ["One idea: verify-then-write grounds each Claim as it's written.", "The 3×3 grid makes positions checkable, not prose."] },
  { title: "Evaluating captions", seconds: 70, component: Evaluation,
    notes: ["Grounding matters most, and the captioner never sees the Answer Keys.", "Two numbers stop a terse caption winning by saying less.", "We score any caption set, not only ours."] },
  { title: "Live demo", seconds: 110, component: Demo,
    notes: ["The core of the pitch. Case → Caption → report → dataset card → gate.", "Keep the recorded Batch open in another tab as the fallback."] },
  { title: "Results", seconds: 55, component: Results,
    notes: ["Numbers are from the committed Baseline base-v2.", "Lead with the gate catching the vague prompt: coverage 0.67 → 0.27."] },
  { title: "Reliability", seconds: 50, component: Shipped,
    notes: ["Replay keeps the demo safe; the card and readiness show breadth.", "Provenance: every verdict is inspectable and reproducible."] },
  { title: "What it means for Clay", seconds: 45, theme: "dark", component: Next,
    notes: ["Close on the ask: Clay's real caption set and its rubric weights."] },
];
