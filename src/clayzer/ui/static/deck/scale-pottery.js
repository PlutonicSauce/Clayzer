// The scale slide's picture: same pot, less clay. The pot on the wheel is the job, Clay's 70M
// chips captioned to the same quality bar, and clay keeps dripping into it. The bricks beside it
// are what the job costs, one brick per $10K. Each press applies one cost lever (`steps: 4` in
// slides.js), and the bricks it saves fall away: 18 bricks on-demand, under half a brick at the
// end, which is the 46×.
//
// Costs are per 1,000 Captions and for Clay's ~70M training chips; docs/scale-napkin-math.md has
// the sums. "assumed" levers are the next Batches to run: each is kept only if the regression
// gate says quality holds, which is what the quality bar on the pot stands for.
//
// All motion is CSS, keyed off the step or looping (the drip, the wheel), with no hooks, so
// tests/deck_smoke.mjs can render it. Reduced motion: no transitions, no loops.

import { html } from "./html.js";

// [pottery name, the technique, $ per 1,000 Captions, total for 70M chips in $K, basis].
export const LEVERS = [
  ["By hand, one at a time", "Nova Pro, on-demand", 2.59, 181, "measured"],
  ["Fire a full kiln", "+ Bedrock batch inference", 1.30, 91, "published"],
  ["Rough out on a cheap wheel", "+ Nova Lite first, 20% escalated to Pro", 0.36, 25, "assumed"],
  ["Thinner walls where they hold", "+ 256 px where the class is still visible", 0.28, 20, "assumed"],
  ["Cast from a mould", "+ Caption 1 in 5, reuse via Clay embeddings", 0.056, 3.9, "assumed"],
];
const BASIS = { measured: "measured", published: "published price", assumed: "assumed" };

const BRICK = 10; // $K per brick
const SLOTS = 20, COLS = 5, BW = 62, BH = 30, GAP = 6, BX = 30, BY = 162;

const money = (k) => (k >= 10 ? `$${Math.round(k)}K` : `$${k.toFixed(1)}K`);

function Bricks({ cost }) {
  const full = Math.floor(cost / BRICK), part = (cost % BRICK) / BRICK;
  return Array.from({ length: SLOTS }, (_, i) => {
    const col = i % COLS, row = Math.floor(i / COLS);
    const x = BX + col * (BW + GAP), y = BY + (3 - row) * (BH + GAP);
    const keep = i < full ? 1 : i === full ? part : 0;
    // Bricks fall from the top of the stack first, a beat apart.
    const delay = ((SLOTS - i) * 0.035).toFixed(3);
    return html`<rect class=${`brick ${keep ? "" : "gone"}`} x=${x} y=${y} width=${BW} height=${BH}
      rx="4" style=${`--s: ${keep || 1}; --d: ${delay}s`} />`;
  });
}

// The pot: a neck at the top, a round belly, a narrow foot on the wheel.
const POT = "M574 280 L574 296 C 574 322, 492 344, 492 418 C 492 470, 530 498, 556 498 L644 498 C 670 498, 708 470, 708 418 C 708 344, 626 322, 626 296 L626 280 Z";

export function PotteryScale({ step = 0 }) {
  const cost = LEVERS[step][3];
  return html`<svg class="pottery" viewBox="0 0 800 540" role="img"
      aria-label=${`Same pot, less clay. A pot on a potter's wheel stands for Clay's 70 million chips captioned to the same quality bar. Beside it, clay bricks show the cost, one per ten thousand dollars: ${money(cost)} after ${LEVERS[step][1].replace(/^\+ /, "")}.`}>
    <defs>
      <clipPath id="pot-inside"><path d=${POT} /></clipPath>
    </defs>

    <text class="pot-label" x=${BX} y="58">CLAY YOU PAY FOR</text>
    ${LEVERS.map((l, k) => html`<text class=${`pot-cost ${k === step ? "on" : ""}`} x=${BX} y="122">
      ${money(l[3])}</text>`)}
    <text class="pot-unit" x=${BX} y="148">one brick = $10K</text>
    <g class="bricks">${Bricks({ cost })}</g>

    <path class="chute" d="M376 170 C 480 172, 586 186, 600 230" />
    <g class="drips">
      ${[0, 1, 2].map((k) => html`<circle class="drip" cx="600" cy="238" r="9" style=${`--k: ${k}`} />`)}
    </g>

    <g class="wheel">
      <rect x="560" y="512" width="80" height="22" rx="4" />
      <ellipse class="wheel-top" cx="600" cy="506" rx="150" ry="17" />
      <ellipse class="wheel-spin" cx="600" cy="506" rx="150" ry="17" />
    </g>
    <rect class="pot-clay" x="480" y="358" width="240" height="160" clip-path="url(#pot-inside)" />
    <path class="pot" d=${POT} />
    <line class="quality" x1="470" y1="358" x2="736" y2="358" />
    <text class="quality-label" x="744" y="352">quality</text>
    <text class="quality-label" x="744" y="372">bar</text>
  </svg>`;
}

export function LeverList({ step = 0 }) {
  return html`<ol class="pot-levers">
    ${LEVERS.map(([pottery, technique, , total, basis], k) => html`<li
        class=${`pot-lever build ${k <= step ? "in" : ""} ${k === step ? "now" : ""}`}>
      <div><b>${pottery}</b><span>${technique}</span></div>
      <b class="pot-total">${money(total)}</b>
      <span class=${`basis ${basis}`}>${BASIS[basis]}</span>
    </li>`)}
  </ol>`;
}

// How big "at scale" is, as three Chips: a real dev Chip each, behind the 3 × 3 grid every Claim
// is placed on, with the count on top. Figures: Clay v1.5's training set (a ~5% stratified
// sample), one NAIP pass over CONUS, and the Sentinel-2 archive over land (scale-napkin-math.md).
const SIZES = [
  ["70M", "chips in Clay v1.5", "a ~5% sample", "ca-uswtdb-3073564-20220702"],
  ["86M", "in one NAIP pass", "over CONUS", "ca-uspvdb-400565-20220702"],
  ["~13B", "in the Sentinel-2", "archive, over land", "ca-neg-6-20220703"],
];

export function ChipStats() {
  return html`<div class="chip-stats">
    ${SIZES.map(([n, what, note, chip]) => html`<figure class="chip-stat"
        style=${`background-image: url("/api/chips/${chip}.png")`}>
      <b>${n}</b><figcaption>${what}<span>${note}</span></figcaption>
    </figure>`)}
    <p class="chip-def">A <b>chip</b> is one small square tile cut from a big aerial or satellite
      image, like these.</p>
  </div>`;
}
