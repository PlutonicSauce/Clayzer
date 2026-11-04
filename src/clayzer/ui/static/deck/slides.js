// The 4-minute pitch. One entry per slide: a title, a time budget in seconds (they add up to
// 4:00; the notes panel warns when a slide runs long), presenter notes, a plain-language `spoken`
// script read aloud by the A key (accessibility), and the component.
//
// Scores aren't quoted on a slide: the demo opens the live Overview, which reads the committed
// Baseline. The caption example is a real Run (see caption-example.js). Scale figures (15.2B
// embeddings) are from the hackathon brief.

import { html } from "./html.js";
import { StoryArchitecture } from "./diagram.js";
import { CaptionExample } from "./caption-example.js";

const Kicker = ({ children }) => html`<p class="kicker">${children}</p>`;

function Title() {
  return html`<div class="title-slide">
    <${Kicker}>Clay Earth Dataset Foundry · Caption track<//>
    <h1>Clayzer</h1>
    <p class="lede">Give us your caption set, and we tell you how much of it you can trust, where
      it fails, and what it costs to make better.</p>
    <p class="team">Team Clayzer · Clay Earth Dataset Foundry hackathon · November 4th, 2026</p>
  </div>`;
}

function Problem() {
  return html`<div class="two-col">
    <div>
      <${Kicker}>The problem<//>
      <h2>Clay v2 learns from captions nobody has checked</h2>
      <p class="big">Clay v2 is text-native. It is trained on written descriptions of satellite
        and aerial images — and no one has the time to check whether those descriptions are true.</p>
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

// The architecture, told as a journey: one image goes in on the left, a trustworthy verdict comes
// out on the right. Each stop is numbered so a non-technical listener can follow the story.
function Architecture() {
  return html`<div class="arch-slide">
    <${Kicker}>How it works · follow one image through<//>
    <h2>From a raw aerial tile to a verdict you can trust</h2>
    <${StoryArchitecture} />
    <p class="source">Same path for one image or a million: each stop is a managed AWS service, so
      the story scales without changing. A role per service, every bucket private.</p>
  </div>`;
}

// One "approach" slide that carries the three novel ideas (originality) as it explains how a
// caption is written and scored. Merged from the old Generation, Evaluation, and What's-new
// slides to keep the deck to 8.
function Approach() {
  return html`<div>
    <${Kicker}>Our approach · what's new<//>
    <h2>Three things you won't find in a plain VLM prompt</h2>
    <div class="criteria">
      <div class="criterion"><b>Verify-then-write</b><p>Each Claim is checked against imagery at
        its own 3 × 3 grid cell <i>as the caption is written</i> — wrong Claims are dropped or
        moved, not graded after.</p></div>
      <div class="criterion"><b>Hidden answer keys</b><p>The captioner never sees the ground truth
        (USGS, OpenStreetMap), so a high score is earned. Grounding is two numbers, so a terse
        caption can't win by saying less.</p></div>
      <div class="criterion"><b>An ontology that feeds the model</b><p>The object vocabulary — its
        look-alikes and house phrasings — is <i>learned from captions</i> and fed back into the
        prompt, so the model confuses a greenhouse for a solar array less often.</p></div>
    </div>
    <p class="big">The brief asked for an evaluation sandbox. We built one that also makes the
      captions better — and closes the loop: the ontology scores captions <i>and</i> teaches the
      next ones, proven by the regression gate, not asserted.</p>
    <p class="source">Captions on Bedrock (Nova Pro); fidelity judged by Opus 5.5; retrieval by
      Titan embeddings. The ontology is data-driven (ADR-0010), induced from a caption corpus
      (ADR-0011).</p>
  </div>`;
}

function Demo() {
  return html`<div>
    <${Kicker}>Live demo · the proof<//>
    <h2>The site, in four stops</h2>
    <ol class="demo-script">
      <li><b>Overview.</b> The current Baseline: every Case, every Repeat, scored.</li>
      <li><b>A Caption.</b> Each Claim marked supported or not, on the 3 × 3 grid — see it, don't
        read it.</li>
      <li><b>The report.</b> Five criteria side by side, and a Listen button that reads it aloud.</li>
      <li><b>Compare to Baseline.</b> The gate says better, worse, or inconclusive.</li>
    </ol>
    <p class="source">Live here: <a href="./">Overview</a> · <a href="./#/batches">Batches</a> ·
      fallback is the recorded Batch, replayed offline with no model or network.</p>
  </div>`;
}

function Next() {
  return html`<div class="title-slide closing">
    <${Kicker}>What it means for Clay<//>
    <h2>Trust your captions before you train on them</h2>
    <p class="lede">Hand Clayzer a caption set, get a verdict: how much to trust, where it fails,
      what it costs to fix. It's serverless, with cheap checks on every caption and the costly
      judge on a sample, so it grows toward the 15.2 billion embeddings Clay has published.</p>
    <p class="team">The ask: Clay's real caption set and its rubric weights, so the verdict is
      Clay's, not our stand-in's.</p>
    <p class="access-note">Any slide reads itself aloud — press <b>A</b> or the Listen button.</p>
  </div>`;
}

// Seven slides, exactly 4:00: problem, one real caption and its answer key, the architecture as
// a story, the novel ideas, the site, and the close. Results and scale ride on the demo's live
// Overview and the closing slide.
export const SLIDES = [
  { title: "Clayzer", seconds: 10, theme: "dark", component: Title,
    spoken: "Clayzer. Give us your caption set, and we tell you how much of it you can trust.",
    notes: ["One line, then move on.", "4:00 total. T starts the timer, A reads a slide aloud."] },
  { title: "The problem", seconds: 25, component: Problem,
    spoken: "Clay's new model learns from written descriptions of satellite images that nobody has checked. In a real run, a caption put a wind farm's turbines to the north. The official database says sixteen turbines, to the south. Plausible, and wrong.",
    notes: ["Read the wrong caption, then the answer key: 16 turbines, south.", "Keep it short: the next slide shows a full example."] },
  { title: "What a caption looks like", seconds: 40, component: CaptionExample,
    spoken: "Here is one real caption. The model saw only this photo and wrote that there are eighteen wind turbines, then listed its facts. We grade those facts against public records. But the records disagree. The government turbine database counts seventeen in the photo; OpenStreetMap counts eighteen, because it places one turbine two metres further in, right at the top edge. So no single source is the truth, and we never hand-label: the code builds every answer key from public records and cross-checks the sources, and a person only looks where they disagree, like here. This caption got the count right and the position wrong: it put every turbine in the centre, and the dots show they are all around it.",
    notes: ["Dots are the records, drawn on the real turbines. The amber box is the caption's claim: Claims name a cell, not an object.", "USGS and OpenStreetMap place the top-edge turbine 2 m apart: one says inside the photo, one outside.", "Scale: labels are automatic (about a minute per image); the code cross-checks sources and flags disagreements for a person. Don't say we checked every image by eye: that was a one-time audit of the test set.", "Say both: count right, position wrong."] },
  { title: "How it works", seconds: 45, component: Architecture,
    spoken: "Here is the whole journey. One aerial image comes in on the left. A model on AWS writes a caption. Before each statement is kept, we check it against the imagery. We score it against open map data the model never saw. A gate decides whether it is good enough. What comes out is a verdict you can trust, and the same path works for one image or a million.",
    notes: ["One image in on the left, a verdict out on the right.", "Point at each numbered stop. End on: same path scales to millions."] },
  { title: "Our approach · what's new", seconds: 40, component: Approach,
    spoken: "Three things set this apart. Verify-then-write: each claim is checked against imagery as the caption is written. Hidden answer keys: the captioner never sees the ground truth, so a good score is earned. And an ontology learned from captions and fed back into the model, so it confuses a greenhouse for a solar array less often. It scores captions and teaches the next ones.",
    notes: ["Verify-then-write, hidden keys, the ontology that feeds the model.", "The loop: the ontology scores AND teaches, proven by the gate."] },
  { title: "Live demo", seconds: 50, component: Demo,
    spoken: "Now the site. The overview shows the current baseline. A caption, with each claim marked supported or not, right on the image. The report, five criteria side by side, which can read itself aloud. And compare to baseline: the gate says better, worse, or inconclusive.",
    notes: ["Overview → a Caption on its grid → report and Listen → Compare.", "Keep the recorded Batch open as the offline fallback."] },
  { title: "What it means for Clay", seconds: 30, theme: "dark", component: Next,
    spoken: "Hand Clayzer a caption set and get a verdict: how much to trust, where it fails, what it costs to fix. It is serverless, so it grows to Clay's scale. Our ask is Clay's real caption set and its rubric weights. And any slide here reads itself aloud.",
    notes: ["Close on the ask: Clay's real caption set and its rubric weights.", "Mention Listen (A) as the accessibility point."] },
];
