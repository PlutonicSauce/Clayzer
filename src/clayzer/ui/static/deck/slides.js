// The 4-minute pitch. One entry per slide: a title, a time budget in seconds (they add up to
// 4:00; the notes panel warns when a slide runs long), presenter notes, a plain-language `spoken`
// script read aloud by the A key (accessibility), and the component.
//
// Scores aren't quoted on a slide: the demo opens the live Overview, which reads the committed
// Baseline. The problem slide's caption is a real Run (see caption-chip.js). Scale figures (15.2B
// embeddings) are from the hackathon brief.

import { html } from "./html.js";
import { ArchitectureDiagram } from "./diagram.js";
import { ChipJourney } from "./chip-journey.js";
import { OntologyViz } from "./ontology-slide.js";
import { ChipStats, LeverList, PotteryScale } from "./scale-pottery.js";
import { ProblemViz } from "./problem-slide.js";

const Kicker = ({ children }) => html`<p class="kicker">${children}</p>`;

function Title() {
  return html`<div class="title-slide">
    <${Kicker}>Clay Earth Dataset Foundry · Caption track · 2026 NOV 5<//>
    <h1>Clayzer</h1>
    <p class="pron"><span>/ˈkleɪ.zər/</span> <i>noun</i> · from glaze, the finish a potter fires
      onto clay</p>
    <p class="lede">A solution for producing captions you can trust, at scale.</p>
  </div>`;
}

// The problem only, in three presses on one photo: the Caption is wrong (the 17 turbines both
// records agree on appear), the records disagree too (the 18th, either side of the top edge), and
// so we cross-check sources and only bring in a person when they conflict or are too uncertain.
function Problem({ step = 0 }) {
  return html`<div class="problem-statement">
    <${Kicker}>New caption, who dis?<//>
    <h2>Trusted, never verified</h2>
    <${ProblemViz} step=${step} />
  </div>`;
}

// How it works, on one real Chip: each press is one of the four steps (chip-journey.js). It
// also carries what the old solution slide said: the ontology, the records' cross-check, and the
// region split.
function Architecture({ step = 0 }) {
  return html`<div class="arch-slide">
    <${Kicker}>How it works · one image, start to finish<//>
    <h2>Follow one aerial image through Clayzer</h2>
    <${ChipJourney} step=${step} />
  </div>`;
}

// The ontology the caption harness reads (ontology/objects.toml), shown on one photo: its objects
// and their "near" links, the photo pixelating into the ontology graph, then the guidance the
// captioner is given and why it helps (ontology-slide.js). The guidance quoted is
// ontology.prompt_context's real output for the photo's classes; 9 of 12 is the Baseline's
// look-alike count (summary.json `lookalikes`), captioned without the guidance.
function Ontology({ step = 0 }) {
  return html`<div class="onto-slide">
    <${Kicker}>Our solution · the ontology<//>
    <h2>From pixels to what the harness understands</h2>
    <div class="onto-grid">
      <${OntologyViz} step=${step} />
      <div class="onto-side">
        <div class=${`onto-card ${step >= 2 ? "gone" : ""}`}>
          <b>1 · The photo</b>
          <p>A greenhouse beside buildings and a road, with farm fields and two ponds.</p>
        </div>
        <div class=${`onto-card after-graph build ${step >= 1 ? "in" : ""}`}>
          <b>2 · The ontology</b>
          <p class=${step >= 2 ? "folded" : ""}>17 classes in 5 families, in one file the harness
            reads.</p>
          <ul class="onto-key">
            <li><i class="isa"></i>is a kind of</li>
            <li><i class="near"></i>is typically found near</li>
            <li><i class="alike"></i>is easily mistaken for</li>
          </ul>
        </div>
        <div class=${`onto-card told build ${step >= 2 ? "in" : ""}`}>
          <b>3 · Why it helps the caption</b>
          <p class="onto-problem">Without it: greenhouses called solar farms in <b>9 of 12</b> runs.</p>
          <p>Before it writes, the harness is told to:</p>
          <ol class="onto-benefits">
            <li><span>1</span><p><b>Tell look-alikes apart:</b> greenhouse vs solar array.</p></li>
            <li><span>2</span><p><b>Look for what sits together:</b> greenhouse near road, said only
              if seen.</p></li>
            <li><span>3</span><p><b>Use words we can check:</b> 11 classes, each mapped to public
              records.</p></li>
          </ol>
          <p class="onto-why">A semantic layer: knowledge the pixels can't give, never this photo's
            answer.</p>
        </div>
      </div>
    </div>
  </div>`;
}

// The AWS deployment, from diagram.js (infra/app.py and infra/agentcore_app.py, the MCP servers in
// src/clayzer/tools.py, plus what caption-design.md §3.4 plans next).
function Aws() {
  return html`<div class="arch-slide">
    <${Kicker}>On AWS · the services we use<//>
    <h2>All managed services, deployed with CDK</h2>
    <${ArchitectureDiagram} />
    <div class="legend">
      <span><i class="live"></i> Deployed: this deck is served by it</span>
      <span><i class="planned"></i> Planned next, or opt-in</span>
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

// The example search, animated (HyperFrames project in ../Clayzer-videos/flood-search-motion).
// It plays once, muted, and freezes on its end card; the deck mounts one slide at a time, so it
// starts from the top on arrival.
function ExampleSearch() {
  return html`<div class="video-slide">
    <${Kicker}>What trusted captions unlock<//>
    <h2>Search the Earth in plain words</h2>
    <video class="slide-video" src="static/deck/media/paddy-search.mp4" poster="static/deck/media/paddy-search-poster.jpg" autoplay muted playsInline
      aria-label="A text search for rice fields near Bangkok that became buildings since 2011 returns three before-and-after pairs. Two captions are checked: rice fields replaced by a housing estate, and paddies built over by a warehouse park. The third pair shows rice fields that became fish ponds, but its caption says new buildings: the check circles and strikes the caption, writes the right one underneath, fish ponds on former rice fields, and removes it as not a match. Then: anyone can ask the Earth a question, about homes, harvests and jobs; Clayzer makes the answers trustworthy."></video>
    <p class="source">Search results are only as good as the captions behind them. Illustrative:
      not real search results.</p>
  </div>`;
}

// Same pot, less clay (scale-pottery.js): each press applies one cost lever, and the bricks of
// clay it saves fall away while the pot, the job at the same quality bar, stays full.
function Scale({ step = 0 }) {
  return html`<div class="scale-slide">
    <${Kicker}>At Clay's scale<//>
    <h2>How it scales</h2>
    <div class="scale-grid">
      <${PotteryScale} step=${step} />
      <div class="scale-side">
        <${ChipStats} />
        <${LeverList} step=${step} />
        <ul class="scale-notes">
          <li>Measured: 2,559 tokens and 2.9 s per Caption (dev63, 189 Captions), at AWS list
            prices, us-east-1.</li>
          <li>Cost is from tokens, not the GPU time and GPU count and size the Vision document asks
            for: hosted Bedrock doesn't report them. A SageMaker GPU run is next.</li>
          <li>"Assumed" rows are the next Batches to run, each kept only if the gate says quality
            holds.</li>
          <li>Scoring: an Opus judge on every Caption would cost $1.1M; grounding needs no model,
            so ours is $5.5K with Opus on a 1% sample.</li>
        </ul>
      </div>
    </div>
  </div>`;
}

// The close: where to see it and read it. No hero background; two big links the audience can
// note down, and the ask. The site link is the app's CLAYZER_PUBLIC_URL, so a deck presented
// from a laptop still shows the deployed site, else wherever this deck is being served from.
// Either way no deployment hostname is committed (tests/test_repo_readiness.py).
const here = typeof location !== "undefined" ? location.origin : "";
const SITE = await fetch("/api/config")
  .then((r) => (r.ok ? r.json() : {}))
  .then((c) => c.public_url || here)
  .catch(() => here);
const REPO = "https://github.com/PlutonicSauce/Clayzer";

function Next() {
  return html`<div class="closing-links">
    <${Kicker}>Thank you · try it yourself<//>
    <h2>See it live, and read the code</h2>
    <div class="link-cards">
      <a class="link-card" href=${SITE} target="_blank" rel="noopener">
        <span class="link-kind">The live site</span>
        <b>${SITE.replace(/^https?:\/\//, "") || "this site"}</b>
        <span>Every Case, Batch and report, and this deck at /deck</span>
      </a>
      <a class="link-card" href=${REPO} target="_blank" rel="noopener">
        <span class="link-kind">The code · Apache-2.0</span>
        <b>${REPO.replace("https://", "")}</b>
        <span>Open source: the pipeline, the scoring, and this deck</span>
      </a>
    </div>
    <p class="source">Any slide reads itself aloud: press <b>A</b> or the Listen button.</p>
  </div>`;
}

// Nine slides, exactly 4:00, in four sections: the problem; the value it unlocks (search in words,
// animated); our solution (how it works on one image, the ontology, the AWS services, the live
// demo); the cost at Clay's scale; then the close.
// The deck's sections, in order, for the breadcrumb at the top of each slide (deck.js). A slide's
// `section` names one; the title and closing slides have none.
export const SECTIONS = ["Problem Statement", "Value Unlock", "Our Solution", "Scale"];

export const SLIDES = [
  { title: "Clayzer", seconds: 10, theme: "dark", component: Title,
    spoken: "Glaze is what makes a pot safe to use. We do that for Clay's captions. We're Clayzer, said KLAY-zer. Captions you can trust, at scale.",
    notes: ["Open cold on the glaze line, then pause after \"safe to use\" so the second sentence lands as the reveal.", "Say the name once, clearly: KLAY-zer. If you add names, keep it to one breath: \"I'm ___, with ___ and ___.\"", "4:00 total. T starts the timer, A reads a slide aloud."] },
  { title: "The problem", section: "Problem Statement", seconds: 40, component: Problem, steps: 2,
    spoken: "New caption, who dis? Here's a real one. We showed a vision model this photo with a simple prompt. Its answer: a large solar array. Three times out of three. Sounds confident. These are white roofs. No panels. So check it against the public records? Here's the twist: they disagree too. On this wind farm, the government counts seventeen turbines and OpenStreetMap eighteen. One turbine, two metres apart, either side of the edge. So what do you trust?",
    notes: ["Tell it as a story: a confident answer, the reveal, then the twist. \"New caption, who dis?\" is the joke: a caption shows up and nobody knows if it's legit.", "Case lookalike-neg-110: rows of white roofs. Nova Pro said a large solar array in the north-east, in all 3 Repeats of the Baseline. USPVDB has no solar there, checked by eye.", "Press 1 on \"These are white roofs\": the claim crossed out, the same answer 3 times in 3. Pause before it.", "Press 2 on \"Here's the twist\": a different Case, the wind farm uswtdb-3073564. USGS puts one turbine just outside the photo, OpenStreetMap just inside, 2 m apart, so 17 or 18. Checked live against both. Gesture to each side of the top edge.", "End on \"So what do you trust?\" and move on: How it works answers it. The cross-check (agree: automatic; conflict: a person) is step 3 there.", "The 3 × 3 grid is ours: the prompt makes the model name each object's place as one of 9 cells."] },
  { title: "Example search", section: "Value Unlock", seconds: 22, component: ExampleSearch,
    spoken: "Why does this matter? Picture asking the planet a question, in plain words: which rice fields near Bangkok became buildings since 2011? Three matches. But this one says new buildings. We check it against the image. Fish ponds. Struck out. Anyone can ask the Earth a question, and trust the answer.",
    notes: ["Start the moment the slide appears: the video plays once, 22 s, and doesn't wait. To replay it, leave the slide and come back.", "Cues: read the query as it types (0-4 s); \"Three matches\" as the results appear (6 s); \"But this one…\" as it zooms on the third (8 s); \"Fish ponds. Struck out.\" on the strike-through (about 12 s); the last line on the end card (18 s). Behind? Cut \"Three matches\".", "Why text search and not just the latest image: you don't know where to look, no layer exists for it, and the change is slow, a few fields a year, so it only shows across dates.", "Look-alikes: fish ponds and flooded paddies look the same from above; that is what our look-alike vocabulary is for.", "Illustrative, not real results: our Cases today are US solar, wind and land cover. Don't imply we have run this search."] },
  { title: "How it works", section: "Our Solution", seconds: 42, component: Architecture, steps: 4,
    spoken: "Let's follow one real image. One: the model writes five claims from the image alone, in the words of our ontology; more on that next. Two: each claim is checked against the imagery. That solar array is a storage yard, so it's gone before the caption is written. Three: we score it against public records it never saw, cross-checked, so a person only looks where they disagree: right, but it missed the road. Four: a self-improvement loop. Every change runs three times per image and faces a gate, tuned on one region and tested on another. A vaguer prompt looked more correct, and failed. Only pairs that pass go out, to Clay, LGND, or other apps.",
    notes: ["One press per step; the strip at the top lights the step you're on.", "Press 1: name the ontology and move on: the next slide covers it.", "Press 2 is the moment: point at the south-west cell, the storage yard that looks like panels.", "Verify-then-write isn't in the Baseline: in the 4-image test every object it named was really there and correctness rose 0.53 → 0.65, but the gate kept it out because coverage dropped.", "Press 3, if asked: wind records agreed on 25 of 26 Cases, so a person rarely looks. The cross-check is built for solar and wind.", "Press 4: the self-improvement loop. Today we propose each change and the gate decides; an agent that proposes changes from the failures is planned, not built.", "Press 4, if asked: tuned on 74 Mojave images, tested once on 61 Texas images it never saw; correctness held, 0.76 against 0.75 on dev. Say 'tune', not 'train': we tune the prompt and checks.", "Real Runs: verify-2 neg-1 Repeat 1, and the vague-prompt gate (demo/stories.toml)."] },
  { title: "The ontology", section: "Our Solution", seconds: 22, component: Ontology, steps: 2,
    spoken: "Our caption harness also reads an ontology: a semantic layer of what things are, what they sit near, and what they are mistaken for. Without it, the captioner called greenhouses solar farms nine times in twelve. With it, it is warned before it writes, and every claim uses words we can check.",
    notes: ["Press 1: the photo pixelates into the ontology graph; each tag lands on its class.", "Press 2: why it helps. The badges 1, 2, 3 on the graph match the three benefits. The quoted lines are the real output of ontology.prompt_context for these classes.", "9 of 12 is measured: the Baseline, captioned without the guidance. The effect with it isn't measured yet: it's the next Batch the gate tests. Don't claim it fixed the greenhouses.", "Don't claim it's in the baseline: the guidance is a Batch option (ontology_context), off in the Baseline. Always on: the captioner may only name the ontology's 11 classes."] },
  { title: "On AWS", section: "Our Solution", seconds: 27, component: Aws,
    spoken: "All of it runs on AWS, deployed with CDK. Bedrock writes, judges and searches the captions. The agentic captioner runs on AgentCore, which holds its LGND sign-in and reaches two MCP servers: LGND Geo to check imagery, and RODA for AWS open data. Results live in S3, and the site runs on Fargate behind CloudFront. Next: Step Functions to fan out, and SageMaker for GPU cost.",
    notes: ["Solid boxes are running now: this deck comes from that Fargate task.", "AgentCore is live: validated in us-west-2 on 2026-11-04, a verified Batch on 3 dev Cases with the LGND token from Identity. The Baseline ran locally with no tools, so don't tie its numbers to AgentCore.", "MCP servers are allowlisted: none may read an answer key (ADR-0006). RODA is pinned to 0.1.7; LGND is remote, so each Batch records the version it reports.", "Two CDK stacks per account, the web app and AgentCore; nothing crosses accounts. X-Ray spans are built but opt-in, because Transaction Search is account-wide: don't say they're on.", "Dashed boxes are next; lead into the scale slide: what it costs."] },
  { title: "Live demo", section: "Our Solution", seconds: 26, component: Demo,
    spoken: "Now the site. The overview shows the current baseline. A caption, with each claim marked supported or not, right on the image. The report, five criteria side by side, which can read itself aloud. And compare to baseline: the gate says better, worse, or inconclusive.",
    notes: ["Overview → a Caption on its grid → report and Listen → Compare.", "Keep the recorded Batch open as the offline fallback."] },
  { title: "At Clay's scale", section: "Scale", seconds: 35, component: Scale, steps: 4,
    spoken: "What does this cost at Clay's scale? Clay's own training set is seventy million chips, and that is only a five percent sample of the world. Captioning all of it with our current model would cost about one hundred and eighty thousand dollars. Batch pricing halves that. A cheap model first, with only the hard images sent to the strong one, smaller images where objects are still visible, and reusing captions for look-alike chips bring it to about four thousand dollars, forty-six times cheaper. Time scales too: one at a time it would take six years, but captions run in parallel, so it's days.",
    notes: ["Press → once per technique as you name it (4 presses). The bricks it saves fall away; one brick is $10K. On each press the clay drops onto the quality bar and the gate catches it: every cut is tested, and the gate stops quality going lower.",
      "If \"chip\" needs a word: one small square tile of a big aerial or satellite image, like the three on screen. It's Clay's own term (the v1.5 spec: \"70 million … chips\").",
      "Clay itself is a ~5% sample; the archives are 100× bigger, so cost per caption decides what gets captioned.",
      "The $181K is our measured $0.0026 per caption (2,559 tokens, Nova Pro, AWS list price) × Clay's ~70M chips. Ours are 512 px NAIP chips; Clay's are 256 px and from several sensors, so it's likely on the high side, and radar chips may not caption well. Neither is measured.",
      "Quality, if asked: batch changes only billing and turnaround, so the output is the same. The three green 'assumed' rows are hypotheses: each becomes a gated run, kept only if no score drops beyond the Baseline's run-to-run spread. Say \"$3.9K is the best case if all three pass\".",
      "Cost is from tokens, not the GPU time and GPU size the Vision document asks for (footnote): hosted Bedrock doesn't report them, so a SageMaker GPU run is next.",
      "Time: 2.9 s per caption is measured; 6.4 years one at a time. 'Days' assumes about 1,000 in parallel (about 2.3 days), which we haven't been granted or tested: the Bedrock quota sets it.",
      "If asked about scoring: an Opus judge on every caption would cost $1.1M; our grounding needs no model (footnote).",
      "The script runs about 43 s against a 35 s budget: keep it brisk, or give only the first and last price."] },
  { title: "Thank you", seconds: 16, component: Next,
    spoken: "Thank you. You can see it live on our site, and read every line of the code on GitHub. And any slide here reads itself aloud.",
    notes: ["Point at the two links; leave this slide up for questions.", "Mention Listen (A) as the accessibility point."] },
];
