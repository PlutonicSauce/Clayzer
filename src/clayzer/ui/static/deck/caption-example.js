// One real Caption next to the Answer Key it was graded against, and the public records behind
// that key disagreeing. Case fixed-dev-uswtdb-3073564, Repeat 1 of Baseline
// 20261104T211847Z-dev74-base; the correction is in fixtures/caption/cases/label-corrections.toml.

import { html } from "./html.js";

const CHIP = "/api/chips/ca-uswtdb-3073564-20220702.png";
const CELLS = ["north_west", "north", "north_east", "west", "centre", "east",
  "south_west", "south", "south_east"];

const CAPTION = `The image shows a desert landscape with a network of roads and wind turbines. The
  roads are unpaved and form a grid-like pattern across the image. There are 18 wind turbines
  distributed along the roads, primarily in the center and eastern parts of the image.`;

const CLAIMS = [
  ["Wind turbines", "18", "centre"],
  ["Road", "unpaved", "centre"],
  ["Bare ground", "", "centre"],
];

const SOURCES = [
  ["USGS wind turbine database", "17 turbines", "missed one", "bad"],
  ["OpenStreetMap", "roads, and an 18th turbine in the south-east corner", "", "ok"],
  ["Checked by eye", "18 turbines: the photo shows the south-east one", "answer key", "ok"],
];

const WRONG = [
  ["USGS", "missed this turbine"],
  ["OpenStreetMap", "no houses on a street of about 30"],
  ["OpenStreetMap", "a dry wash mapped as water"],
];

// The Claims drawn on the grid the way the web app's Overview draws them: a pill in the cell each
// Claim names, coloured by its verdict, over the cells where the Answer Key puts turbines.
const C = 512 / 3;
const PILLS = [
  ["18 turbines", "centre", "near"],
  ["road, unpaved", "centre", "good"],
  ["bare ground", "centre", "none"],
];
const TURBINE_CELLS = ["north_west", "north", "north_east", "west", "east", "south_west", "south",
  "south_east"];

function cellXY(cell) {
  const i = CELLS.indexOf(cell);
  return [(i % 3) * C, Math.floor(i / 3) * C];
}

function Chip() {
  const per = {};
  return html`<figure class="ex-chip">
    <div class="ex-frame">
      <img src=${CHIP} alt="Aerial photo of desert hills crossed by dirt roads, with wind turbines
        spread across every part of the image except the centre" />
      <svg viewBox="0 0 512 512" aria-hidden="true">
        <g class="grid">${[1, 2].map((k) => html`<line x1=${k * C} y1="0" x2=${k * C} y2="512" />
          <line x1="0" y1=${k * C} x2="512" y2=${k * C} />`)}</g>
        ${TURBINE_CELLS.map((cell) => {
          const [x, y] = cellXY(cell);
          return html`<rect class=${cell === "south_east" ? "ref only-osm" : "ref"} x=${x + 4}
            y=${y + 4} width=${C - 8} height=${C - 8} rx="6" />`;
        })}
        ${PILLS.map(([label, cell, tone]) => {
          const [x0, y0] = cellXY(cell);
          const n = (per[cell] = (per[cell] || 0) + 1) - 1;
          const x = x0 + 5, y = y0 + 14 + n * 50;
          return html`<g class=${`pill ${tone}`}><rect x=${x} y=${y} width=${C - 10} height="42"
            rx="21" /><text x=${x + (C - 10) / 2} y=${y + 28} text-anchor="middle">${label}</text></g>`;
        })}
      </svg>
    </div>
    <figcaption class="ex-legend">
      <span><i class="dot good"></i>right, right place</span>
      <span><i class="dot near"></i>right, wrong cell</span>
      <span><i class="dot none"></i>no record to check</span>
      <span><i class="sq"></i>turbines, per the answer key</span>
      <span><i class="sq only-osm"></i>the one only OpenStreetMap had</span>
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
          have earned half credit.<br /><b class="bad">Position wrong:</b> no turbine stands in the
          centre cell.</p>
      </div>
    </div>
    <p class="ex-wrong"><b>Public records are wrong too.</b>
      ${WRONG.map(([src, what]) => html`<span><i>${src}</i> ${what}</span>`)}
      <span>Every image checked by eye; the fixes live in one file.</span>
    </p>
  </div>`;
}
