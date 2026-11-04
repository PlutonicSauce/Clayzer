// The 8-minute pitch. One entry per slide: a title, a time budget in seconds (they add up to
// 8:00; the notes panel warns when a slide runs long), presenter notes, a plain-language `spoken`
// script read aloud by the A key (accessibility), and the component.
//
// Numbers come from the committed Baseline (baselines/default/summary.json): base-v2, Nova Pro
// captions judged by Opus 5.5, 4 dev Cases × 3 Repeats, all 12 Runs ok. Scale figures (15.2B
// embeddings, ~99 MCP servers) are from the hackathon brief. Re-quote from a committed Baseline
// if the scores change, never from a one-off Run.

import { html } from "./html.js";
import { StoryArchitecture } from "./diagram.js";

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
    <h2>One Batch, from image to verdict</h2>
    <ol class="demo-script">
      <li><b>A Case.</b> The image and what open data says is really there.</li>
      <li><b>Its Caption.</b> Each Claim marked supported or not, on the 3 × 3 grid — see it, don't
        read it.</li>
      <li><b>The report.</b> Five criteria side by side, averaged over repeats.</li>
      <li><b>The dataset card.</b> Where captions go wrong — a greenhouse called a solar array.</li>
      <li><b>Compare to Baseline.</b> The gate says better, worse, or inconclusive.</li>
    </ol>
    <p class="source">Live here: <a href="./">Overview</a> · <a href="./#/batches">Batches</a> ·
      fallback is the recorded Batch, replayed offline with no model or network.</p>
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
    <p class="big">The gate caught a vague one-Claim prompt that looked good on correctness but
      collapsed on coverage (0.67 → 0.27) — the "say less to score higher" trap, stopped before it
      became the Baseline. That is the eval doing its job.</p>
    <p class="source">4 dev Cases × 3 Repeats, 12 of 12 Runs clean. Each rate is on its own;
      weights are Clay's to set. From a committed Baseline, not a one-off Run.</p>
  </div>`;
}

function Scale() {
  return html`<div>
    <${Kicker}>Scale &amp; impact<//>
    <h2>Built to grow from 12 Runs to 15 billion</h2>
    <div class="criteria">
      <div class="criterion"><b>15.2B</b><p>embeddings Clay has already published — the scale its
        captions must reach</p></div>
      <div class="criterion"><b>Serverless</b><p>Bedrock, S3, and Step Functions fan out over
        Chips; no server to outgrow</p></div>
      <div class="criterion"><b>Cheap checks first</b><p>grounding and duplication run on the whole
        set; the costly LLM judge only on a sample</p></div>
      <div class="criterion"><b>Any caption set</b><p>point it at anyone's captions — ours, or
        Clay's own pipeline — for a verdict, failure modes, and cost, no retraining</p></div>
    </div>
    <p class="big">The impact: Clay can trust a caption set before training on it, instead of
      finding out after a continental-scale run. And the ontology learned on the way makes the
      next batch of captions better — a loop that compounds, not a one-off score.</p>
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
    <p class="access-note">Any slide reads itself aloud — press <b>A</b> or the Listen button.</p>
  </div>`;
}

// Eight slides, exactly 8:00. The story architecture, the three novel ideas, scale, and the
// demo each get their own slide; writing + scoring + originality are merged into Approach, and
// the accessibility note rides on the closing slide (the Listen feature is on every slide).
export const SLIDES = [
  { title: "Clayzer", seconds: 25, theme: "dark", component: Title,
    spoken: "Clayzer. Give us your caption set, and we tell you how much of it you can trust, where it fails, and what it costs to make better.",
    notes: ["Say the one-line pitch, then move on.", "8:00 total. T starts the timer, A reads a slide aloud."] },
  { title: "The problem", seconds: 55, component: Problem,
    spoken: "Clay's new model learns from written descriptions of satellite images that nobody has checked. In a real run, a caption described a wind farm with turbines to the north. The official database says sixteen turbines, to the south. Wrong count, wrong place. That kind of plausible, wrong caption quietly poisons training.",
    notes: ["Read the wrong caption, then the answer key: 16 turbines, south.", "Make it concrete — this is the hook."] },
  { title: "How it works", seconds: 75, component: Architecture,
    spoken: "Here is the whole journey. One aerial image comes in on the left. Step one, a model on AWS writes a caption. Step two, before each statement is kept, we check it against the imagery. Step three, we score it against open map data the model never saw. Step four, a gate decides whether it is good enough. What comes out on the right is a verdict you can trust. The same path works for one image or a million.",
    notes: ["Walk it as a story: one image in on the left, a verdict out on the right.", "Point at each numbered stop. End on: same path scales to millions."] },
  { title: "Our approach · what's new", seconds: 70, component: Approach,
    spoken: "Three things set this apart from a plain prompt. First, verify-then-write: each claim is checked against imagery as the caption is written, so wrong claims are dropped, not graded after. Second, the captioner never sees the answer keys, so a good score is earned. Third, and this is the differentiator: our object vocabulary is learned from a caption corpus and fed back into the model, so it confuses a greenhouse for a solar array less often. The ontology both scores captions and teaches the next ones — a loop, proven by the gate.",
    notes: ["Originality: verify-then-write, hidden keys, and the ontology that feeds the model.", "The loop is the story: the ontology scores AND teaches. Proven by the gate, not asserted.", "Honest: the A/B/C comparison number is pending real Clay embeddings."] },
  { title: "Live demo", seconds: 100, component: Demo,
    spoken: "Now the proof. A case: the image and what is really there. Its caption, with each claim marked supported or not, right on the image. The report, five criteria side by side. The dataset card, showing where captions go wrong. And compare to baseline: the gate says better, worse, or inconclusive.",
    notes: ["The core of the pitch. Case → Caption → report → dataset card → gate.", "Keep the recorded Batch open as the offline fallback."] },
  { title: "Results", seconds: 50, component: Results,
    spoken: "On our committed baseline: correctness zero point five eight, coverage zero point six seven, fidelity zero point five four, retrieval zero point eight nine. The headline: the gate caught a vague prompt whose coverage collapsed from zero point six seven to zero point two seven, and stopped it. That is the evaluation doing its job.",
    notes: ["Numbers from the committed Baseline base-v2.", "Lead with the gate catching the vague prompt: coverage 0.67 → 0.27."] },
  { title: "Scale & impact", seconds: 60, component: Scale,
    spoken: "Will it scale? Clay has already published fifteen point two billion embeddings — that is the scale its captions must reach. Everything here is serverless: Bedrock, S3, and Step Functions fan out over images with no server to outgrow. Cheap checks run on the whole set; the costly judge only on a sample. Point it at any caption set, including Clay's own pipeline. The impact: Clay can trust a set before training on it, and the ontology it learns makes the next batch better — a loop that compounds.",
    notes: ["Answer scale head on: 15.2B embeddings is the target; serverless fan-out.", "Impact + loop: a bad caption caught here is a lesson never learned; the ontology compounds."] },
  { title: "What it means for Clay", seconds: 45, theme: "dark", component: Next,
    spoken: "What it means for Clay: hand Clayzer a caption set, get a verdict — how much to trust, where it fails, what it costs to fix. Then point it at Clay's own pipeline. Our ask is Clay's real caption set and its rubric weights. And any slide here reads itself aloud — press A.",
    notes: ["Close on the ask: Clay's real caption set and its rubric weights.", "Mention the Listen feature (A) as the accessibility point."] },
];
