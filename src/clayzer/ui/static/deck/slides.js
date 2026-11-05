// The 4-minute pitch. One entry per slide: a title, a time budget in seconds (they add up to
// 4:00; the notes panel warns when a slide runs long), presenter notes, a plain-language `spoken`
// script read aloud by the A key (accessibility), and the component.
//
// Scores aren't quoted on a slide: the demo opens the live Overview, which reads the committed
// Baseline. The problem slide's caption is a real Run (see caption-chip.js). Scale figures (15.2B
// embeddings) are from the hackathon brief.

import { html } from "./html.js";
import { ArchitectureDiagram, StoryArchitecture } from "./diagram.js";
import { CaptionChip, WrongRecordChip } from "./caption-chip.js";
import { ValueFlow } from "./value-flow.js";

const Kicker = ({ children }) => html`<p class="kicker">${children}</p>`;

function Title() {
  return html`<div class="title-slide">
    <${Kicker}>Clay Earth Dataset Foundry · Caption track<//>
    <h1>Clayzer</h1>
    <p class="pron"><span>/ˈkleɪ.zər/</span> KLAY-zer, rhymes with laser · <i>noun</i></p>
    <p class="lede">A solution for producing captions you can trust, at scale.</p>
    <p class="team">Team Clayzer · Clay Earth Dataset Foundry hackathon · November 4th, 2026</p>
  </div>`;
}

// The problem only, in three presses: the Caption is wrong (the records' turbines appear), the
// records can be wrong too (OSM's "reservoir" over a dry basin), and so we cross-check sources and
// only bring in a person when they conflict or are too uncertain.
function Problem({ step = 0 }) {
  const shown = step >= 1;
  return html`<div class="problem">
    <${Kicker}>New caption, who dis?<//>
    <h2>Today, every caption is a black box</h2>
    <div class="problem-grid">
      <div class="hook">
        <${CaptionChip} records=${shown} />
        <div class="hook-side">
          <span class="hook-stamp">✗ Unchecked</span>
          <p class="hook-label">A real caption</p>
          <blockquote>“18 wind turbines, primarily in the center and eastern parts of the
            image.”</blockquote>
          <p class="hook-note">${shown
            ? "Count right, place wrong: the records put every turbine around the centre."
            : "Nova Pro saw only the photo. We ask it to name each object's place as one of our 9 grid cells, so \u201cwhere\u201d can be checked."}</p>
        </div>
      </div>
      <div class="stakes">
        <div class=${`wrong-card build ${step >= 2 ? "in" : ""}`}>
          <${WrongRecordChip} />
          <div>
            <p class="wrong-head">The records can be wrong too</p>
            <p>OpenStreetMap maps the blue outline as a reservoir. The photo shows a dry basin.</p>
          </div>
        </div>
        <div class=${`triage build ${step >= 3 ? "in" : ""}`}>
          <p class="triage-head">So we cross-check the sources</p>
          <p class="triage-row ok"><b>Sources agree</b><span>labelled automatically</span></p>
          <p class="triage-row ask"><b>Conflict, or too uncertain</b><span>only then, a person looks</span></p>
        </div>
      </div>
    </div>
  </div>`;
}

// Our solution: how Clayzer earns trust, one technique per press (`steps` in SLIDES), with the
// same Chip as the problem slide. The last press turns its Caption into one that matches the
// records. Each point says what the code does today; the verify-then-write figures are from the
// 4-Case test (verify-2 against base-v2, rescored with the same scorer).
const TRUST = [
  { icon: "check", title: "Verify, then write",
    text: "Each fact is checked against imagery at its grid cell before the caption is written. In testing, every object it named was really there." },
  { icon: "layers", title: "Hidden answer keys",
    text: "Public records (USGS, OpenStreetMap), cross-checked by code, grade every fact. The captioner never sees them, so a good score is earned." },
  { icon: "tag", title: "One shared vocabulary",
    text: "About 20 object classes with their look-alikes and minimum sizes, so “building” for a greenhouse earns partial credit, not zero." },
  { icon: "split", title: "Tune on one region, test on another",
    text: "74 Mojave images to tune, 61 Texas images it never saw, plus look-alikes: greenhouses fooled it 9 of 12 times." },
  { icon: "loop", title: "A self-improvement loop",
    text: "Every change runs 3× per image and is kept only if it beats the baseline. It kept verify-then-write out: more accurate, but less complete." },
];

function TrustIcon({ name }) {
  const s = { fill: "none", stroke: "currentColor", "stroke-width": 3, "stroke-linecap": "round", "stroke-linejoin": "round" };
  return html`<svg class="trust-icon" viewBox="0 0 48 48" aria-hidden="true">
    ${name === "check" && html`<g ...${s}><circle cx="24" cy="24" r="17" /><path d="M16 24l6 6 11-12" /></g>`}
    ${name === "layers" && html`<g ...${s}><path d="M24 8 42 17 24 26 6 17Z" /><path d="M6 24l18 9 18-9" /><path d="M6 31l18 9 18-9" /></g>`}
    ${name === "tag" && html`<g ...${s}><path d="M8 8h16l17 17-16 16L8 24Z" /><circle cx="16" cy="16" r="3" /></g>`}
    ${name === "split" && html`<g ...${s}><rect x="5" y="12" width="15" height="24" rx="3" /><rect x="28" y="12" width="15" height="24" rx="3" /><path d="M20 24h8" stroke-dasharray="2 4" /></g>`}
    ${name === "loop" && html`<g ...${s}><path d="M38 20a15 15 0 0 0-27-4" /><path d="M10 9v7h7" /><path d="M10 28a15 15 0 0 0 27 4" /><path d="M38 39v-7h-7" /></g>`}
  </svg>`;
}

function Trust({ step = 0 }) {
  const trusted = step > TRUST.length;
  return html`<div class="problem trust-slide">
    <${Kicker}>Our solution<//>
    <h2>From black box to captions you can trust</h2>
    <div class="trust-grid">
      <div class=${`hook ${trusted ? "trusted" : ""}`}>
        <${CaptionChip} fixed=${trusted} />
        <span class="hook-stamp">${trusted ? "✓ Trusted" : "✗ Unchecked"}</span>
        <p class="hook-label">${trusted ? "The goal" : "The same caption"}</p>
        <blockquote>${trusted
          ? "“18 wind turbines spread across the image, none in the centre.”"
          : "“18 wind turbines, primarily in the center …”"}</blockquote>
      </div>
      <div class="trust">
        ${TRUST.map((t, k) => html`<div class=${`trust-item build ${step >= k + 1 ? "in" : ""}`}>
          <${TrustIcon} name=${t.icon} />
          <div><b>${t.title}</b><p>${t.text}</p></div>
        </div>`)}
      </div>
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

// The AWS deployment, from diagram.js (infra/app.py, plus what caption-design.md §3.4 plans next).
function Aws() {
  return html`<div class="arch-slide">
    <${Kicker}>On AWS · the services we use<//>
    <h2>One deploy command, all managed services</h2>
    <${ArchitectureDiagram} />
    <div class="legend">
      <span><i class="live"></i> Deployed: this deck is served by it</span>
      <span><i class="planned"></i> Planned next</span>
      <span>A role per service; the web app can only read its own part of the store</span>
    </div>
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

// Downstream value: how checked captions reach Clay v2 and what it can do with them.
function Downstream() {
  return html`<div class="arch-slide">
    <${Kicker}>Downstream value<//>
    <h2>Checked captions, searchable imagery</h2>
    <${ValueFlow} />
  </div>`;
}

// The example search, animated (HyperFrames project in ../Clayzer-videos/flood-search-motion).
// It loops muted; the deck mounts one slide at a time, so it starts from the top on arrival.
function ExampleSearch() {
  return html`<div class="video-slide">
    <${Kicker}>Example · searching in words<//>
    <video class="slide-video" src="static/deck/media/flood-search.mp4" poster="static/deck/media/flood-search-poster.jpg" autoplay muted loop playsInline
      aria-label="A text search for the economic impact of flooding in Bangkok and access to aid returns four images whose checked captions match: a flooded district, a market and road under water, a relief site on dry ground, and an open route from the relief site to the flooded district. Then: results are only as good as the captions; Clayzer checks them."></video>
    <p class="source">Illustrative: not real search results.</p>
  </div>`;
}

// Per 1,000 Captions and for Clay's ~70M training chips; docs/scale-napkin-math.md has the sums.
const LEVERS = [
  ["Nova Pro, on-demand", 2.59, "$181K", "measured"],
  ["+ Bedrock batch inference", 1.30, "$91K", "published"],
  ["+ Nova Lite first, 20% escalated to Pro", 0.36, "$25K", "assumed"],
  ["+ 256 px where the class is still visible", 0.28, "$20K", "assumed"],
  ["+ Caption 1 in 5, reuse via Clay embeddings", 0.056, "$3.9K", "assumed"],
];

function Scale() {
  return html`<div>
    <${Kicker}>At Clay's scale<//>
    <h2>46× cheaper to caption Clay's 70M chips</h2>
    <div class="scale">
      <div class="magnitude">
        <p><b>70M</b> chips in Clay v1.5, a stratified sample: ~5% of MGRS tiles, at most 6 dates
          per place</p>
        <p><b>86M</b> Chips in one NAIP pass over CONUS</p>
        <p><b>~13B</b> in the Sentinel-2 archive over land</p>
      </div>
      <div class="ladder">
        ${LEVERS.map(([name, per1k, total, basis]) => html`<div class="lever">
          <span class="name">${name}</span>
          <span class="bar"><i style=${`width: ${Math.max(1.5, (per1k / 2.59) * 100)}%`}></i></span>
          <span class="total">${total}</span>
          <span class=${`basis ${basis}`}>${basis}</span>
        </div>`)}
        <p class="judge">Scoring: an Opus judge on every Caption would cost <b>$1.1M</b>, 6× the
          captions. Grounding needs no model call, so ours is <b>$5.5K</b> with Opus on a 1%
          sample.</p>
      </div>
    </div>
    <p class="source">Measured: 2,559 tokens and 2.9 s per Caption (dev63, 189 Captions). Prices:
      AWS Price List, us-east-1. "Assumed" rows are the next Batches to run.</p>
  </div>`;
}

function Next() {
  return html`<div class="title-slide closing">
    <${Kicker}>What it means for Clay<//>
    <h2>Trust your captions before anyone searches them</h2>
    <p class="lede">Hand Clayzer a caption set, get a verdict: how much to trust, where it fails,
      what it costs to fix.</p>
    <p class="team">The ask: Clay's real caption set and its rubric weights, so the verdict is
      Clay's, not our stand-in's.</p>
    <p class="access-note">Any slide reads itself aloud — press <b>A</b> or the Listen button.</p>
  </div>`;
}

// Ten slides, exactly 4:00: the problem, the value it unlocks (downstream search and an example),
// then the solution (the story, how we earn trust, the AWS services, the cost at Clay's scale),
// the live demo, and the close.
export const SLIDES = [
  { title: "Clayzer", seconds: 10, theme: "dark", component: Title,
    spoken: "Clayzer, said KLAY-zer, rhymes with laser. A solution for producing captions you can trust, at scale.",
    notes: ["Say the name, KLAY-zer, then the one-line definition, and move on.", "4:00 total. T starts the timer, A reads a slide aloud."] },
  { title: "The problem", seconds: 35, component: Problem, steps: 3,
    spoken: "New caption, who dis? That is how captions on Clay's imagery work today. Here is a real one: the model saw only this photo and said eighteen wind turbines, mostly in the centre. The public records put every turbine around the centre, not in it. But the records can be wrong too: OpenStreetMap calls this basin a reservoir, and it is dry. So we never trust one source. We cross-check them: when they agree, the label is automatic, and only when they conflict, or are too uncertain, does a person look.",
    notes: ["Open with the label as a joke: \"New caption, who dis? That's how Clay's imagery works today: a caption shows up and nobody knows if it's legit.\"", "Press 1: the records' dots appear. The caption is wrong: count right, place wrong.", "Press 2: the records can be wrong too. OpenStreetMap maps this basin as a reservoir; the photo shows it dry.", "Press 3: we stay out of hand-labelling unless sources conflict or confidence is too low.", "If asked: cross-checking is built for solar and wind (USGS against OpenStreetMap). The basin was caught in our one-time audit by eye; a confidence threshold for labels is the plan, not built yet.", "The 3 × 3 grid is ours: the model sees the plain photo, and the prompt makes it name each object's place as one of 9 cells."] },
  { title: "Downstream value", seconds: 20, component: Downstream,
    spoken: "Now imagine those captions were checked. Imagery and public records go into Clayzer. We write each caption from the image alone and check every fact against the records. Only pairs that pass go on to Clay, which makes the imagery searchable in words.",
    notes: ["Left to right: public data, Clayzer (our part, the dashed box), Clay.", "The line to land: search results are only as good as the captions behind them.", "The Thailand flood search is an illustration: our Cases today are US solar, wind and land cover. Don't imply we have run it.", "The dashed loop back is planned, not built: say 'next'."] },
  { title: "Example search", seconds: 18, component: ExampleSearch,
    spoken: "Here is what that looks like. Ask in plain words, like the economic impact of flooding in Bangkok and access to aid, and you get the images whose checked captions match: flooded streets, a market under water, a relief site, and the route to reach it.",
    notes: ["Let the video play; it loops every 16 s.", "Illustrative, not real results: don't imply we have run this search."] },
  { title: "How it works", seconds: 20, component: Architecture,
    spoken: "Here is the whole journey. One aerial image comes in on the left. A model on AWS writes a caption. Before each statement is kept, we check it against the imagery. We score it against open map data the model never saw. A gate decides whether it is good enough. What comes out is a verdict you can trust, and the same path works for one image or a million.",
    notes: ["One image in on the left, a verdict out on the right.", "Point at each numbered stop. End on: same path scales to millions."] },
  { title: "Our solution", seconds: 40, component: Trust, steps: 6,
    spoken: "Here is how we make captions you can trust. We verify, then write: each fact is checked against the imagery before the caption is written. The answer keys are public records, cross-checked by code, that the captioner never sees. One shared vocabulary of objects and their look-alikes. We tune on one region and test on another it never saw. And a self-improvement loop keeps only the changes that beat the baseline. The result: a caption that matches what is really there.",
    notes: ["Press → for each point as you say it (5 presses); the 6th turns the caption green.", "Verify-then-write: in the 4-image test, every object it named was really there, and correctness rose 0.53 → 0.65. Don't claim it's in the baseline: the gate kept it out because coverage dropped.", "Say 'tune', not 'train': we tune the captioner's prompt and checks.", "Labels are automatic; a person only looks where the two records disagree."] },
  { title: "On AWS", seconds: 25, component: Aws,
    spoken: "All of it runs on AWS, from one deploy command. Bedrock writes, judges and searches the captions, with Nova Pro, Claude Opus and Titan embeddings. Results live in S3, and the site runs on Fargate behind CloudFront. The dashed boxes are next: Step Functions to fan out, SageMaker for GPU cost, and AgentCore for the agentic captioner.",
    notes: ["Solid boxes are running now: this deck comes from that Fargate task.", "One cdk deploy per account; nothing crosses accounts.", "Dashed boxes are next; lead into the scale slide: what it costs."] },
  { title: "At Clay's scale", seconds: 20, component: Scale,
    spoken: "What does this cost at Clay's scale? Clay's own training set is seventy million chips, and that is only a five percent sample of the world. Captioning all of it with our current model would cost about one hundred and eighty thousand dollars. Batch pricing halves that. A cheap model first, with only the hard images sent to the strong one, smaller images where objects are still visible, and reusing captions for look-alike chips bring it to about four thousand dollars, forty-six times cheaper. Checking matters too: a large model judging every caption would cost over a million dollars, but our checks against open data need no model at all.",
    notes: ["Clay itself is a ~5% sample; the archives are 100× bigger, so cost per Caption decides what gets captioned.",
      "Batch is a published 50%; the green 'assumed' rows are hypotheses our gate can test, which is the point.",
      "Land the judge line: scoring with a big model costs more than captioning, and our grounding is free."] },
  { title: "Live demo", seconds: 32, component: Demo,
    spoken: "Now the site. The overview shows the current baseline. A caption, with each claim marked supported or not, right on the image. The report, five criteria side by side, which can read itself aloud. And compare to baseline: the gate says better, worse, or inconclusive.",
    notes: ["Overview → a Caption on its grid → report and Listen → Compare.", "Keep the recorded Batch open as the offline fallback."] },
  { title: "What it means for Clay", seconds: 20, theme: "dark", component: Next,
    spoken: "Hand Clayzer a caption set and get a verdict: how much to trust, where it fails, what it costs to fix. Our ask is Clay's real caption set and its rubric weights. And any slide here reads itself aloud.",
    notes: ["Close on the ask: Clay's real caption set and its rubric weights.", "Mention Listen (A) as the accessibility point."] },
];
