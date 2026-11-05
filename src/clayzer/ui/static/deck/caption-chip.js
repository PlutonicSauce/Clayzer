// One real Caption on its Chip, for the problem slide. Case fixed-dev-uswtdb-3073564, Repeat 1 of
// Baseline 20261104T211847Z-dev74-base: Nova Pro said 18 turbines, all in the centre cell.
//
// Turbine positions are Chip pixels (512 x 512, from Chip.pixel), fetched 2026-11-04 from the USGS
// USWTDB API and OpenStreetMap's power=generator nodes. The two agree on 17 turbines to within a
// few pixels. They disagree on one at the top edge: USGS puts it at y = -1, just outside the Chip,
// and OSM at y = 2, just inside, about 2 m apart.

import { html } from "./html.js";

const CHIP = "/api/chips/ca-uswtdb-3073564-20220702.png";
const C = 512 / 3;
const CELLS = ["north_west", "north", "north_east", "west", "centre", "east", "south_west", "south",
  "south_east"];

// The 17 turbines both records place inside the Chip (USGS positions), and the one they disagree on.
const AGREED = [[98, 282], [237, 92], [354, 315], [2, 39], [277, 414], [471, 159], [167, 187],
  [431, 207], [312, 363], [393, 264], [132, 233], [281, 46], [238, 465], [57, 326], [203, 143],
  [509, 116], [25, 377]];
const DISPUTED = [316, 2];

// `records` shows the turbines from the public records; `fixed` shows the goal, a Caption whose
// cells match them. What the records identify is drawn on the objects; the Caption's Claim is
// drawn on the cell it names, because Claims are cells, not boxes (ADR-0007).
export function CaptionChip({ records = true, fixed = false }) {
  const xy = (cell) => { const i = CELLS.indexOf(cell); return [(i % 3) * C, Math.floor(i / 3) * C]; };
  return html`<figure class="ex-chip">
    <div class="ex-frame">
      <img src=${CHIP} alt="Aerial photo of desert hills crossed by dirt roads, with wind turbines
        spread across every part of the image except the centre" />
      <svg viewBox="0 0 512 512" aria-hidden="true">
        <g class="grid">${[1, 2].map((k) => html`<line x1=${k * C} y1="0" x2=${k * C} y2="512" />
          <line x1="0" y1=${k * C} x2="512" y2=${k * C} />`)}</g>
        ${fixed
          ? CELLS.filter((c) => c !== "centre").map((c) => { const [x, y] = xy(c);
              return html`<rect class="claim ok" x=${x + 4} y=${y + 4} width=${C - 8} height=${C - 8} rx="6" />`; })
          : html`<rect class="claim" x=${C + 4} y=${C + 4} width=${C - 8} height=${C - 8} rx="6" />
            <g class="pill near"><rect x=${C + 10} y=${2 * C - 50} width=${C - 20} height="40" rx="20" />
              <text x=${1.5 * C} y=${2 * C - 23} text-anchor="middle">caption: all 18</text></g>`}
        <g class=${`records ${records ? "in" : ""}`}>
          ${AGREED.map(([x, y]) => html`<circle class="turbine" cx=${x} cy=${y} r="8" />`)}
          <circle class="turbine disputed" cx=${DISPUTED[0]} cy=${DISPUTED[1] + 4} r="9" />
        </g>
      </svg>
    </div>
    <figcaption class="ex-legend">
      <span><i class=${`sq claim ${fixed ? "ok" : ""}`}></i>where the caption puts the turbines</span>
      ${records && html`<span><i class="dot rec"></i>a turbine in the public records</span>
        <span><i class="dot disputed"></i>one the two records place 2 m apart</span>`}
    </figcaption>
  </figure>`;
}
