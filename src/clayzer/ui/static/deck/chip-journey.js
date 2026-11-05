// How it works, on one real Chip: Case fixed-dev-neg-1, Repeat 1 of Batch 20261104T124711Z-verify-2
// (the verify-drops-invented-solar Story in demo/stories.toml). Each press is one of Clayzer's four
// steps, and carries the points the old solution slide made: the ontology's vocabulary (step 1),
// the records' cross-check (step 3), and the region split (step 4). 1: Nova Pro drafts five Claims
// from the image alone. 2: LGND Geo's imagery check rejects
// three of them at their cells (its reasons are quoted from the Trace), and the Caption is written
// from the rest. 3: the Caption is scored against the Answer Key it never saw, the Case's current
// Reference Labels (fixtures/caption/cases/caption-dev.jsonl), with today's scorer: correctness 1.0,
// coverage 0.25. 4: the regression gate, shown on the vague-prompt change it rejected
// (20261104T052042Z-base -> 20261104T052747Z-vague, the gate-rejects-vague-prompt Story).

import { html } from "./html.js";

const CHIP = "/api/chips/ca-neg-1-20220607.png";
const C = 512 / 3;
const CELLS = ["north_west", "north", "north_east", "west", "centre", "east", "south_west", "south",
  "south_east"];
const STEPS = ["Write", "Verify", "Score", "Gate"];

// The draft, in order, with LGND's verdict at each Claim's cell.
const DRAFT = [
  { object: "building", cell: "north", kept: true },
  { object: "parking lot", cell: "north", kept: false, why: "a white rooftop" },
  { object: "bare ground", cell: "centre", kept: true },
  { object: "vegetation", cell: "centre", kept: false, why: "bare ground and paving" },
  { object: "solar array", cell: "south_west", kept: false, why: "a storage yard" },
];
// The Answer Key's cells: OpenStreetMap's building and road (the north row) and railroad (south).
const KEY = ["north_west", "north", "north_east", "south"];

const Arrow = () => html`<svg viewBox="0 0 40 16" width="40" height="16">
  <line x1="2" y1="8" x2="30" y2="8" /><path d="M28 2 38 8 28 14z" /></svg>`;

function Pill({ claim, k, step }) {
  const i = CELLS.indexOf(claim.cell);
  const n = DRAFT.filter((d, j) => j < k && d.cell === claim.cell).length;
  const x = (i % 3) * C + 8, y = Math.floor(i / 3) * C + 10 + n * 46;
  const struck = step >= 2 && !claim.kept;
  return html`<g class=${`jpill ${struck ? "struck" : step >= 2 ? "kept" : ""}`}>
    <rect x=${x} y=${y} width=${C - 16} height="38" rx="19" />
    <text x=${x + (C - 16) / 2} y=${y + 26} text-anchor="middle">${claim.object}</text>
    ${struck && html`<line x1=${x + 12} y1=${y + 19} x2=${x + C - 28} y2=${y + 19} />`}
  </g>`;
}

export function ChipJourney({ step = 0 }) {
  const box = (cell) => { const i = CELLS.indexOf(cell); return [(i % 3) * C, Math.floor(i / 3) * C]; };
  return html`<div class="journey">
    <ol class="journey-strip" aria-label="An aerial image goes in, through Clayzer's four steps, and
        checked image and caption pairs go out to Clay, LGND, or downstream applications">
      <li class="io">Aerial image</li>
      <li class="arrow in" aria-hidden="true"><${Arrow} /></li>
      ${STEPS.map((s, k) => html`<li class=${step === k + 1 ? "now" : step > k + 1 ? "done" : ""}>
        <span>${k + 1}</span>${s}</li>
        <li class=${`arrow ${k === STEPS.length - 1 ? `out ${step >= 4 ? "lit" : ""}` : ""}`}
          aria-hidden="true"><${Arrow} /></li>`)}
      <li class=${`io out ${step >= 4 ? "lit" : ""}`}>Clay · LGND · downstream apps</li>
    </ol>
    <div class="journey-grid">
      <figure class="ex-chip">
        <div class="ex-frame journey-frame">
          <img src=${CHIP} alt="Aerial photo: a large white warehouse roof and a parking lot in the
            north, bare ground in the centre, and a storage yard of long equipment rows in the
            south-west that looks like solar panels" />
          <svg viewBox="0 0 512 512" aria-hidden="true">
            <g class="grid">${[1, 2].map((k) => html`<line x1=${k * C} y1="0" x2=${k * C} y2="512" />
              <line x1="0" y1=${k * C} x2="512" y2=${k * C} />`)}</g>
            <g class=${`key ${step >= 3 ? "in" : ""}`}>
              ${KEY.map((cell) => { const [x, y] = box(cell);
                return html`<rect x=${x + 4} y=${y + 4} width=${C - 8} height=${C - 8} rx="6" />`; })}
            </g>
            <g class=${`draft ${step >= 1 ? "in" : ""}`}>
              ${DRAFT.map((d, k) => html`<${Pill} claim=${d} k=${k} step=${step} />`)}
            </g>
          </svg>
        </div>
        <figcaption class="journey-caption">${step >= 2
          ? html`<b>Caption:</b> “A large building in the north and a large, mostly bare ground area
              in the centre.”`
          : html`NAIP, 0.6 m, about 300 m across. The captioner sees only this.`}
          ${step >= 3 && html`<span class="journey-key"><i></i>the records' building, road and
            railroad</span>`}</figcaption>
      </figure>
      <div class="journey-steps">
        <div class=${`jstep build ${step >= 1 ? "in" : ""}`}>
          <b>1 · Write</b>
          <p>Nova Pro drafts five Claims from the image alone: an object and its cell, in the words of
            our ontology (next slide).</p>
        </div>
        <div class=${`jstep build ${step >= 2 ? "in" : ""}`}>
          <b>2 · Verify</b>
          <p>MCP tools check each Claim against imagery at its cell and reject three. The solar
            array?${" "}
            <q>A storage yard … instead of a solar array.</q> The Caption is written from the rest.</p>
        </div>
        <div class=${`jstep build ${step >= 3 ? "in" : ""}`}>
          <b>3 · Score</b>
          <p>Against public records it never saw, cross-checked by code: where they agree, labels
            are automatic; where they conflict, a person looks. The building is right, but the road
            and railroad are missing. <span class="jnum">correct 1.0 · coverage 0.25</span></p>
        </div>
        <div class=${`jstep build ${step >= 4 ? "in" : ""}`}>
          <b>4 · Gate</b>
          <p>Every change must beat the Baseline, tuned on one region and tested on another it
            never saw. A vaguer prompt: correct 0.59 → 0.96, coverage 0.60 → 0.35.
            <span class="jfail">FAIL</span></p>
        </div>
        <p class=${`journey-out build ${step >= 4 ? "in" : ""}`}>Only image + caption pairs that pass
          go out to Clay, LGND, or downstream apps.</p>
      </div>
    </div>
  </div>`;
}
