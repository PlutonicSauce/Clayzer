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

function Chip() {
  return html`<figure class="ex-chip">
    <div class="ex-frame">
      <img src=${CHIP} alt="Aerial photo of desert hills crossed by dirt roads, with wind turbines
        spread across most of the image" />
      <div class="ex-grid" aria-hidden="true">
        ${CELLS.map((c) => html`<span class=${c === "south_east" ? "hit" : ""}></span>`)}
      </div>
    </div>
    <figcaption>NAIP aerial photo, 0.6 m per pixel, Tehachapi, California. The highlighted cell
      holds the turbine USGS doesn't list.</figcaption>
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
