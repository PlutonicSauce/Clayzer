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

function Generation() {
  return html`<div>
    <${Kicker}>Step 1–2 · writing the caption<//>
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
    <p class="big">Before a Claim is written, the Harness checks it against LGND Geo's imagery
      search at the Claim's own grid cell. A Claim the imagery can't support is dropped or moved —
      so the caption is grounded as it is written, not only scored afterwards.</p>
    <p class="source">Positions use a 3 × 3 grid and a fixed relation vocabulary (ADR-0007), so
      "solar array, centre" is checkable, not prose.</p>
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
    <${Kicker}>Step 3 · scoring the caption<//>
    <h2>Every Claim checked against open data</h2>
    <div class="criteria">
      ${CRITERIA.map(([name, q, tag]) => html`<div class="criterion">
        <b>${name}</b>${tag && html`<span class="tag">${tag}</span>`}<p>${q}</p>
      </div>`)}
    </div>
    <p class="big">We score Clay's five criteria, and the captioner never sees the answer keys
      (ADR-0006), so grounding can't be gamed. Grounding is two numbers — correctness and
      coverage — so a terse caption can't win by saying less.</p>
    <p class="source">Answer keys: USGS solar and wind databases, OpenStreetMap. It scores any
      caption set, not only ours, and a gate decides if a change actually helped.</p>
  </div>`;
}

function Original() {
  return html`<div>
    <${Kicker}>What's new<//>
    <h2>Three things you won't find in a plain VLM prompt</h2>
    <div class="criteria">
      <div class="criterion"><b>Verify-then-write</b><p>The model's Claims are checked against
        imagery <i>as the caption is written</i>, not graded after. Wrong Claims never ship.</p></div>
      <div class="criterion"><b>Hidden answer keys</b><p>The captioner never sees the ground
        truth, so a high score is earned, not gamed. Correctness and coverage, kept apart.</p></div>
      <div class="criterion"><b>A verdict on any set</b><p>Point it at anyone's captions and get
        trust, failure modes, and cost — a dataset card, not just a number.</p></div>
    </div>
    <p class="big">The hackathon asked for an eval sandbox. We built one that also makes the
      captions better and proves it with a regression gate — the loop, not a one-off score.</p>
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
      <div class="criterion"><b>~99 MCP tools</b><p>the same Harness reaches Clay's whole catalog,
        so the eval widens as Clay does</p></div>
    </div>
    <p class="big">The impact: Clay can trust a caption set before training on it, instead of
      finding out after a continental-scale run. A bad caption caught here is a wrong lesson the
      model never learns.</p>
  </div>`;
}

function Access() {
  return html`<div>
    <${Kicker}>Made to be understood<//>
    <h2>Readable by anyone in the room</h2>
    <div class="criteria">
      <div class="criterion"><b>Listen</b><p>Press <b>A</b>, or the Listen button, and any slide
        reads itself aloud — for a non-technical listener or anyone who finds dense slides hard.</p></div>
      <div class="criterion"><b>See, don't read</b><p>Claims land on a 3 × 3 grid over the image;
        right cell green, wrong cell amber. The result is a picture, not a paragraph.</p></div>
      <div class="criterion"><b>High contrast</b><p>Large type, strong contrast, and motion
        dropped for anyone who asks for reduced motion.</p></div>
    </div>
    <p class="source">The whole deck is one self-contained page served from the app — no network,
      no slides to email around.</p>
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
  { title: "Clayzer", seconds: 20, theme: "dark", component: Title,
    spoken: "Clayzer. Give us your caption set, and we tell you how much of it you can trust, where it fails, and what it costs to make better.",
    notes: ["Say the one-line pitch, then move on.", "8:00 total. T starts the timer, A reads a slide aloud."] },
  { title: "The problem", seconds: 45, component: Problem,
    spoken: "Clay's new model learns from written descriptions of satellite images that nobody has checked. In a real run, a caption described a wind farm with turbines to the north. The official database says sixteen turbines, to the south. Wrong count, wrong place. That kind of plausible, wrong caption quietly poisons training.",
    notes: ["Read the wrong caption, then the answer key: 16 turbines, south.", "Make it concrete — this is the hook."] },
  { title: "How it works", seconds: 65, component: Architecture,
    spoken: "Here is the whole journey. One aerial image comes in on the left. Step one, a model on AWS writes a caption. Step two, before each statement is kept, we check it against the imagery. Step three, we score it against open map data the model never saw. Step four, a gate decides whether it is good enough. What comes out on the right is a verdict you can trust. The same path works for one image or a million.",
    notes: ["Walk it as a story: one image in on the left, a verdict out on the right.", "Point at each numbered stop. End on: same path scales to millions."] },
  { title: "Writing the caption", seconds: 50, component: Generation,
    spoken: "The novel step is verify-then-write. Before a claim is written into the caption, the system checks it against imagery at that exact spot on a three-by-three grid. A claim the imagery cannot support is dropped or moved. So the caption is grounded as it is written, not only scored afterwards.",
    notes: ["One idea: verify-then-write grounds each Claim as it's written.", "The 3×3 grid makes positions checkable, not prose."] },
  { title: "Scoring the caption", seconds: 45, component: Evaluation,
    spoken: "We score Clay's five criteria. The captioner never sees the answer keys, so a good grounding score is earned, not gamed. And grounding is two numbers, correctness and coverage, so a caption cannot win by just saying less.",
    notes: ["Grounding matters most, and the captioner never sees the answer keys.", "Two numbers stop a terse caption winning by saying less."] },
  { title: "What's new", seconds: 40, component: Original,
    spoken: "Three things set this apart. We verify claims as the caption is written. We hide the answer keys so scores are earned. And we give a full verdict on anyone's caption set, not just a number. The brief asked for an eval sandbox; we built one that also makes captions better and proves it.",
    notes: ["The originality slide: verify-then-write, hidden keys, verdict on any set.", "Land: we built the loop, not a one-off score."] },
  { title: "Live demo", seconds: 90, component: Demo,
    spoken: "Now the proof. A case: the image and what is really there. Its caption, with each claim marked supported or not, right on the image. The report, five criteria side by side. The dataset card, showing where captions go wrong. And compare to baseline: the gate says better, worse, or inconclusive.",
    notes: ["The core of the pitch. Case → Caption → report → dataset card → gate.", "Keep the recorded Batch open as the offline fallback."] },
  { title: "Results", seconds: 40, component: Results,
    spoken: "On our committed baseline: correctness zero point five eight, coverage zero point six seven, fidelity zero point five four, retrieval zero point eight nine. The headline: the gate caught a vague prompt whose coverage collapsed from zero point six seven to zero point two seven, and stopped it. That is the evaluation doing its job.",
    notes: ["Numbers from the committed Baseline base-v2.", "Lead with the gate catching the vague prompt: coverage 0.67 → 0.27."] },
  { title: "Scale & impact", seconds: 45, component: Scale,
    spoken: "Will it scale? Clay has already published fifteen point two billion embeddings — that is the scale its captions must reach. Everything here is serverless: Bedrock, S3, and Step Functions fan out over images with no server to outgrow. Cheap checks run on the whole set; the costly judge only on a sample. The impact: Clay can trust a caption set before training on it, instead of finding out after a continental-scale run.",
    notes: ["Answer the scale question head on: 15.2B embeddings is the target.", "Impact: a bad caption caught here is a wrong lesson the model never learns."] },
  { title: "Made to be understood", seconds: 20, component: Access,
    spoken: "This is built to be understood by anyone in the room. Press A and any slide reads itself aloud. Claims are shown on the image, not buried in text. Large type, strong contrast, and reduced motion for those who want it.",
    notes: ["Demo the A key here — let a slide read itself.", "See-don't-read: the grid is the accessibility win, not just the audio."] },
  { title: "What it means for Clay", seconds: 20, theme: "dark", component: Next,
    spoken: "What it means for Clay: hand Clayzer a caption set, get a verdict — how much to trust, where it fails, what it costs to fix. Then point it at Clay's own pipeline. Our ask is Clay's real caption set and its rubric weights.",
    notes: ["Close on the ask: Clay's real caption set and its rubric weights."] },
];
