// The problem slide: a caption from one simple prompt is confidently wrong, and the public records
// we'd check it against can't settle things on their own either.
//
// The caption: Case fixed-dev-lookalike-neg-110, Chip ca-neg-110-20220607 (NAIP 2022, Bakersfield),
// Repeat 1 of Baseline 20261105T011537Z-dev74-absence. Rows of white roofs beside a road and
// houses; USPVDB has no solar here, checked by eye ("no solar panels"). Nova Pro called it "a large
// solar array in the north-east section" in all 3 Repeats.
//
// The records: the turbine Case on caption-chip.js (fixed-dev-uswtdb-3073564). USWTDB and OSM agree
// on 17 turbines in the Chip to within a few pixels; one turbine at the top edge is at y = -1.5 in
// USWTDB (outside) and y = 1.7 in OSM (inside), about 2 m apart. Checked live against both APIs on
// 2026-11-05.
//
// Builds, one per press (`steps: 2` in slides.js):
//   0  the prompt, Nova Pro and its caption; on the photo, the cell the caption names
//   1  the claim crossed out: white roofs, no panels, and the same answer 3 times in 3
//   2  the records disagree too: a loupe on the turbine at the top edge, then the two records side
//      by side, 17 against 18
// All motion is CSS transitions keyed off the step, as on the ontology slide.

import { html } from "./html.js";
import { CHIP as WIND_CHIP, AGREED, DISPUTED } from "./caption-chip.js";

const CHIP = "/api/chips/ca-neg-110-20220607.png";
const C = 512 / 3;
const OSM = DISPUTED; // [316, 2]: just inside the top edge
const USGS = [DISPUTED[0], -1]; // just outside it, about 2 m away

const PROMPT = "Write a caption for it … describing what is on the ground, where, how many.";
const CAPTION = "An aerial view shows a large solar array in the north-east section, a road cutting " +
  "through the center, and residential buildings in the south. …";

const on = (cond) => (cond ? "in" : "");

function Photo({ step }) {
  const [x0, y0] = [2 * C, 0]; // the north-east cell the caption names
  return html`<div class="pz-photo">
    <img src=${CHIP} alt="Aerial photo of rows of long white roofs beside a road, with houses along
      the south edge and bare ground in the north-west" />
    <svg viewBox="0 0 512 512" aria-hidden="true">
      <g class="pz-grid">${[1, 2].map((k) => html`<line x1=${k * C} y1="0" x2=${k * C} y2="512" />
        <line x1="0" y1=${k * C} x2="512" y2=${k * C} />`)}</g>
      <rect class="pz-claim" x=${x0 + 4} y=${y0 + 4} width=${C - 8} height=${C - 8} rx="6" />
      <g class="pz-tag cap">
        <line x1="246" y1="34" x2=${x0 + 8} y2="40" />
        <rect x="12" y="14" width="246" height="38" rx="19" />
        <text x="135" y="39">Caption: a solar array</text>
      </g>
      <g class=${`pz-build ${on(step >= 1)}`}>
        <path class="pz-cross" d=${`M${x0 + 26} ${y0 + 26}L${x0 + C - 26} ${y0 + C - 26}M${x0 + C - 26} ${y0 + 26}L${x0 + 26} ${y0 + C - 26}`} />
        <g class="pz-tag rec">
          <line x1="246" y1="83" x2=${x0 + 8} y2="96" />
          <rect x="12" y="64" width="246" height="38" rx="19" />
          <text x="135" y="89">Actually: white roofs</text>
        </g>
      </g>
    </svg>
  </div>`;
}

// A loupe on the wind-farm turbine the records disagree on: the photo's top edge, USGS's pin just
// outside it and OSM's just inside.
function Loupe() {
  const R = 92, Z = 7, cx = 100, cy = 108;
  const at = ([x, y]) => [cx + (x - OSM[0]) * Z, cy + (y - OSM[1]) * Z];
  const [ux, uy] = at(USGS), [ox, oy] = at(OSM), edge = at([0, 0])[1];
  return html`<svg class="pz-loupe" viewBox="0 0 200 236" aria-hidden="true">
    <defs>
      <clipPath id="pz-loupe-clip"><circle cx=${cx} cy=${cy} r=${R} /></clipPath>
      <pattern id="pz-hatch" width="8" height="8" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
        <rect width="8" height="8" fill="#fffdfb" /><line x1="0" y1="0" x2="0" y2="8" stroke="#cebeb5" stroke-width="3" />
      </pattern>
    </defs>
    <g clip-path="url(#pz-loupe-clip)">
      <rect x=${cx - R} y=${cy - R} width=${2 * R} height=${2 * R} fill="url(#pz-hatch)" />
      <image href=${WIND_CHIP} width="512" height="512"
        transform=${`translate(${cx - OSM[0] * Z} ${cy - OSM[1] * Z}) scale(${Z})`} />
      <line class="pz-edge" x1=${cx - R} y1=${edge} x2=${cx + R} y2=${edge} />
      <text class="pz-outside" x=${cx} y=${edge - 34}>outside the photo</text>
      <circle class="pz-pin usgs" cx=${ux} cy=${uy} r="9" />
      <circle class="pz-pin osm" cx=${ox} cy=${oy} r="9" />
      <text class="pz-pin-label usgs" x=${ux - 16} y=${uy - 4}>USGS</text>
      <text class="pz-pin-label osm" x=${ox + 16} y=${oy + 20}>OSM</text>
    </g>
    <circle class="pz-loupe-ring" cx=${cx} cy=${cy} r=${R} />
    <text class="pz-loupe-cap" x=${cx} y="228">2 m apart</text>
  </svg>`;
}

// One record's view of the wind farm: the 17 shared turbines, plus that record's version of the
// disputed one.
function RecordMap({ name, count, inside }) {
  return html`<figure class="pz-record">
    <div class="pz-mini">
      <img src=${WIND_CHIP} alt="" />
      <svg viewBox="0 -40 512 552" aria-hidden="true">
        <rect class="pz-mini-edge" x="0" y="0" width="512" height="512" />
        ${AGREED.map(([x, y]) => html`<circle class="pz-turbine" cx=${x} cy=${y} r="13" />`)}
        <circle class="pz-target" cx=${OSM[0]} cy=${inside ? 14 : -20} r="34" />
        ${inside
          ? html`<circle class="pz-pin osm" cx=${OSM[0]} cy="14" r="18" />
            <text class="pz-where osm" x=${OSM[0] + 44} y="62">inside</text>`
          : html`<circle class="pz-pin usgs ghost" cx=${USGS[0]} cy="-20" r="18" />
            <text class="pz-where usgs" x=${USGS[0] + 44} y="-6">outside</text>`}
      </svg>
    </div>
    <figcaption><b class=${inside ? "osm" : "usgs"}>${name}</b><span class="pz-count">${count}</span></figcaption>
  </figure>`;
}

export function ProblemViz({ step = 0 }) {
  return html`<div class="pz">
    <div class="pz-left">
      <${Photo} step=${step} />
      <div class=${`pz-verdict pz-build ${on(step >= 1)}`}>
        <span class="bad">✗ No solar here</span>
        <span class="bad">Same answer 3 times in 3</span>
      </div>
    </div>
    <div class="pz-right">
      <div class="pz-flow">
        <div class="pz-step prompt"><p class="pz-k">The prompt</p><p>“${PROMPT}”</p></div>
        <span class="pz-arrow">→</span>
        <div class="pz-step model"><p class="pz-k">Nova Pro</p><p>a vision-language model, shown only the photo</p></div>
        <span class="pz-arrow">→</span>
        <div class="pz-step caption"><p class="pz-k">Its caption</p><p>“${CAPTION}”</p><span class="pz-stamp">✗ Unchecked</span></div>
      </div>
      <div class=${`pz-compare pz-build ${on(step >= 2)}`}>
        <p class="pz-head">Check it against public records? They disagree too</p>
        <div class="pz-vs">
          <${Loupe} />
          <${RecordMap} name="USGS" count="17" inside=${false} />
          <span class="pz-ne">≠</span>
          <${RecordMap} name="OpenStreetMap" count="18" inside=${true} />
        </div>
        <p class="pz-foot">On a wind farm, the same turbine sits 2 m apart: USGS puts it just outside the
          photo, OpenStreetMap just inside. One of them is wrong.</p>
      </div>
    </div>
  </div>`;
}
