// The 7-minute pitch. One entry per slide: a title, a time budget in seconds (they add up to
// 7:00; the notes panel warns when a slide runs long), presenter notes, and the component.
//
// <Placeholder> marks content the team still has to write: the novel parts of caption generation
// and evaluation, the demo, and results. Replace each one with the real slide content; the dashed
// box keeps an unfinished slide obvious in rehearsal.

import { html } from "./html.js";
import { ArchitectureDiagram } from "./diagram.js";

function Placeholder({ label, children }) {
  return html`<div class="placeholder" role="note">
    <span class="placeholder-tag">To write · ${label}</span>
    <div class="placeholder-body">${children}</div>
  </div>`;
}

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
    <${Placeholder} label="the hook">
      <p>One real Chip with a confident, wrong caption next to what is actually on the ground.
        Pick it from our dev Cases: the caption, the Claim it gets wrong, and the Answer Key that
        catches it.</p>
    <//>
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
      <div class="step"><b>Caption</b><span>objects, counts, 3 × 3 positions, relations</span></div>
    </div>
    <${Placeholder} label="what is novel in generation">
      <p>The one idea that makes our captions better than a plain VLM prompt, in a sentence a judge
        will repeat. Candidates from the design: verify-then-write against LGND Geo's imagery
        check; the Object Ontology's look-alikes in the prompt; the 3 × 3 grid and relation
        vocabulary (ADR-0007).</p>
      <p>Show it as a before / after on the same Chip.</p>
    <//>
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
    <p class="source">Clay's five criteria. Answer Keys: USGS solar and wind databases,
      OpenStreetMap. The captioner never sees them (ADR-0006).</p>
    <${Placeholder} label="what is novel in evaluation">
      <p>What we do that a rubric alone doesn't. Candidates: Claim-level grounding with
        Answer Keys hidden from the captioner; scoring any caption set, not only ours (CAP-20);
        a dataset verdict with confidence intervals (CAP-21); the regression gate that proves a
        change made captions better.</p>
    <//>
  </div>`;
}

function Demo() {
  return html`<div>
    <${Kicker}>Live demo<//>
    <h2>One Batch, from Chip to report</h2>
    <${Placeholder} label="the demo script">
      <ol>
        <li>Open a Case: the Chip and its Reference Labels.</li>
        <li>Its Caption, with each Claim marked supported or unsupported.</li>
        <li>The Batch report: five criteria side by side.</li>
        <li>Compare against the Baseline: the gate says better, worse, or inconclusive.</li>
      </ol>
      <p>Fallback if the network fails: the recorded demo pack.</p>
    <//>
    <p class="source">Live at this site: <a href="./">Overview</a> · <a href="./#/batches">Batches</a></p>
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
      <span>Least-privilege roles: the web app can only read its own prefix of the store</span>
    </div>
  </div>`;
}

function Results() {
  return html`<div>
    <${Kicker}>Results<//>
    <h2>What we measured</h2>
    <${Placeholder} label="the numbers">
      <p>The headline result, per criterion, with Repeats and spread. Include at least one
        before / after where our novel step moved grounding, and what it cost in tokens or GPU
        time.</p>
      <p>Only quote numbers from a committed Baseline (baselines/), never a one-off Run.</p>
    <//>
  </div>`;
}

function Next() {
  return html`<div class="title-slide closing">
    <${Kicker}>What it means for Clay<//>
    <h2>Trust your captions before you train on them</h2>
    <${Placeholder} label="impact and the ask">
      <p>What Clay can do on Monday: hand us a caption set, get a verdict. Then the one thing we
        want from Clay or the judges.</p>
    <//>
  </div>`;
}

export const SLIDES = [
  { title: "Clayzer", seconds: 20, theme: "dark", component: Title,
    notes: ["Say the one-line pitch, then move on."] },
  { title: "The problem", seconds: 45, component: Problem,
    notes: ["Clay v2 is trained on untested synthetic captions.", "Show the wrong caption: make it concrete."] },
  { title: "Generating captions", seconds: 60, component: Generation,
    notes: ["Placeholder: the novel generation idea."] },
  { title: "Evaluating captions", seconds: 60, component: Evaluation,
    notes: ["Grounding matters most.", "Placeholder: the novel evaluation idea."] },
  { title: "Live demo", seconds: 90, component: Demo,
    notes: ["Keep the fallback demo pack open in another tab."] },
  { title: "On AWS", seconds: 60, component: Architecture,
    notes: ["Solid boxes are running now: this deck comes from that Fargate task.", "One cdk deploy per account; nothing crosses accounts.", "Dashed boxes are next: SageMaker gives the GPU-time cost criterion."] },
  { title: "Results", seconds: 45, component: Results,
    notes: ["Placeholder: numbers from a committed Baseline."] },
  { title: "What it means for Clay", seconds: 40, theme: "dark", component: Next,
    notes: ["Close on the ask."] },
];
