// One real Caption next to the Answer Key it was graded against, and the public records behind
// that key disagreeing. Case fixed-dev-uswtdb-3073564, Repeat 1 of Baseline
// 20261104T211847Z-dev74-base.
//
// Turbine positions are Chip pixels (512 x 512, from Chip.pixel), fetched 2026-11-04 from the USGS
// USWTDB API and OpenStreetMap's power=generator nodes. The two agree on 17 turbines to within a
// few pixels. They disagree on one at the top edge: USGS puts it at y = -1, just outside the Chip,
// and OSM at y = 2, just inside, about 2 m apart.

import { html } from "./html.js";

const CHIP = "/api/chips/ca-uswtdb-3073564-20220702.png";
const C = 512 / 3;

const CAPTION = `The image shows a desert landscape with a network of roads and wind turbines. The
  roads are unpaved and form a grid-like pattern across the image. There are 18 wind turbines
  distributed along the roads, primarily in the center and eastern parts of the image.`;

const CLAIMS = [
  ["Wind turbines", "18", "centre"],
  ["Road", "unpaved", "centre"],
  ["Bare ground", "", "centre"],
];

const SOURCES = [
  ["USGS wind turbine database", "17 turbines in the photo", "one just outside", "bad"],
  ["OpenStreetMap", "18: it puts the top-edge turbine 2 m further in", "", "ok"],
  ["Automatic cross-check", "flags the disagreement; a person confirms 18", "answer key", "ok"],
];

const WRONG = [
  ["Two sources", "cross-checked by code on every image"],
  ["A person", "only looks where they disagree"],
];

// The 17 turbines both records place inside the Chip (USGS positions), and the one they disagree on.
const AGREED = [[98, 282], [237, 92], [354, 315], [2, 39], [277, 414], [471, 159], [167, 187],
  [431, 207], [312, 363], [393, 264], [132, 233], [281, 46], [238, 465], [57, 326], [203, 143],
  [509, 116], [25, 377]];
const DISPUTED = [316, 2];

// What the records identify is drawn on the objects; the Caption's Claim is drawn on the cell it
// names, because Claims are cells, not boxes (ADR-0007).
function Chip() {
  return html`<figure class="ex-chip">
    <div class="ex-frame">
      <img src=${CHIP} alt="Aerial photo of desert hills crossed by dirt roads, with wind turbines
        spread across every part of the image except the centre" />
      <svg viewBox="0 0 512 512" aria-hidden="true">
        <g class="grid">${[1, 2].map((k) => html`<line x1=${k * C} y1="0" x2=${k * C} y2="512" />
          <line x1="0" y1=${k * C} x2="512" y2=${k * C} />`)}</g>
        <rect class="claim" x=${C + 4} y=${C + 4} width=${C - 8} height=${C - 8} rx="6" />
        <g class="pill near"><rect x=${C + 10} y=${2 * C - 50} width=${C - 20} height="40" rx="20" />
          <text x=${1.5 * C} y=${2 * C - 23} text-anchor="middle">caption: all 18</text></g>
        ${AGREED.map(([x, y]) => html`<circle class="turbine" cx=${x} cy=${y} r="8" />`)}
        <circle class="disputed-ring" cx=${DISPUTED[0]} cy=${DISPUTED[1]} r="22" />
        <circle class="turbine disputed" cx=${DISPUTED[0]} cy=${DISPUTED[1] + 4} r="9" />
      </svg>
    </div>
    <figcaption class="ex-legend">
      <span><i class="dot rec"></i>a turbine both records agree on</span>
      <span><i class="dot disputed"></i>the one they place 2 m apart</span>
      <span><i class="sq claim"></i>where the caption put all 18</span>
    </figcaption>
  </figure>`;
}

export function CaptionExample() {
  return html`<div>
    <p class="kicker">What a caption looks like</p>
    <h2 class="ex-title">One caption, graded against records that disagree</h2>
    <div class="ex">
      <${Chip} />
      <div class="ex-col">
        <h3>The caption <span>Nova Pro saw only the photo</span></h3>
        <blockquote>${CAPTION}</blockquote>
        <h3>Its checkable facts</h3>
        <table class="ex-claims">
          <thead><tr><th>What</th><th>How many</th><th>Where</th></tr></thead>
          <tbody>${CLAIMS.map(([w, n, p]) => html`<tr><td>${w}</td><td>${n}</td><td>${p}</td></tr>`)}</tbody>
        </table>
      </div>
      <div class="ex-col">
        <h3>The answer key</h3>
        <ul class="ex-sources">
          ${SOURCES.map(([src, says, tag, tone]) => html`<li class=${tone}>
            <b>${src}</b><span>${says}</span>${tag && html`<em>${tag}</em>`}
          </li>`)}
        </ul>
        <h3>The verdict</h3>
        <p class="ex-verdict"><b class="ok">Count right:</b> 18 of 18. With USGS alone it would
          have earned half credit.<br /><b class="bad">Position wrong:</b> it puts them all in the
          centre; the records put them all around it.</p>
      </div>
    </div>
    <p class="ex-wrong"><b>Labels are automatic: about a minute per image, no hand-labelling.</b>
      ${WRONG.map(([src, what]) => html`<span><i>${src}</i> ${what}</span>`)}
    </p>
  </div>`;
}
