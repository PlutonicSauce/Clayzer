// Downstream value: how Clayzer's captions reach Clay. Public imagery and records go in on the
// left, Clayzer turns them into image + caption pairs it has checked, and Clay uses them to make
// imagery searchable in words. The flood search in Thailand is an illustration of the use, not a
// result: Clayzer's Cases today are US solar, wind and land cover.
// The dashed loop is planned: Chips are joined to LGND's Clay embeddings, but nothing uses them to
// choose places yet. Colours are SVG attributes, as in diagram.js, so it renders the same anywhere.

import { html } from "./html.js";

const INK = "#252323", MUTED = "#6b6461", SUB = "#4a4240", PLANNED = "#a59d99", ACCENT = "#9a4a35";
const KINDS = {
  data: { fill: "#efe8e3", stroke: "#cebeb5" },
  captions: { fill: "#f4dcd4", stroke: "#e8beb2" },
  evaluation: { fill: "#dfe9df", stroke: "#a9c2a9" },
  platform: { fill: "#dde7e9", stroke: "#9fb7bc" },
  clay: { fill: "#f3e6cf", stroke: "#d9bd86" },
};

// x, y, w, h in the 1400 × 600 viewBox.
const NODES = [
  { x: 10, y: 70, w: 220, h: 110, kind: "data", title: "Aerial imagery", sub: ["NAIP · Vantor"] },
  { x: 10, y: 250, w: 220, h: 110, kind: "data", title: "Public records", sub: ["USGS · OpenStreetMap"] },
  { x: 300, y: 70, w: 230, h: 110, kind: "captions", title: "Write the caption", sub: ["from the image alone"] },
  { x: 300, y: 250, w: 230, h: 110, kind: "evaluation", title: "Check every fact", sub: ["against the records,", "hidden from the captioner"] },
  { x: 590, y: 150, w: 240, h: 130, kind: "platform", strong: true, title: "Trusted pairs", sub: ["image + caption,", "with a trust score"] },
  { x: 900, y: 150, w: 190, h: 130, kind: "clay", strong: true, title: "Clay", sub: ["makes the imagery", "searchable in words"] },
];

// [from, to, label]; points picked by hand so lines stay straight.
const EDGES = [
  [[230, 125], [300, 125], ""],
  [[230, 305], [300, 305], ""],
  [[415, 180], [415, 250], ""],
  [[530, 305], [590, 250], ""],
  [[830, 215], [900, 215], ""],
  [[1090, 215], [1135, 215], ""],
];

const COLUMNS = [
  { x: 10, w: 220, title: "Public data" },
  { x: 290, w: 550, title: "Clayzer", ours: true },
  { x: 900, w: 490, title: "Clay" },
];

const VALUE = [
  { x: 10, w: 220, head: "Answer keys for free", lines: ["public records,", "no hand-labelling"] },
  { x: 290, w: 550, head: "Wrong captions caught before anyone searches", lines: ["a caption that says “flooded” when it isn't", "never turns up as a result"] },
  { x: 900, w: 490, head: "Search the Earth in words", lines: ["across the 15.2 billion embeddings", "Clay has published"] },
];

// An illustrative search: the query, the captions it matches, and why their accuracy matters.
const RESULTS = ["rice fields under water", "river over its banks", "village road flooded"];

function SearchCard() {
  const x = 1135, w = 255;
  return html`<g>
    <rect x=${x} y="58" width=${w} height="320" rx="14" fill=${KINDS.clay.fill} stroke=${KINDS.clay.stroke}
      stroke-width="2.5" />
    <text x=${x + 18} y="88" font-size="14" font-weight="700" letter-spacing="1.5" fill=${MUTED}>EXAMPLE SEARCH</text>
    <rect x=${x + 14} y="102" width=${w - 28} height="44" rx="22" fill="#fffdfb" stroke=${KINDS.clay.stroke}
      stroke-width="2" />
    <circle cx=${x + 36} cy="122" r="7" fill="none" stroke=${MUTED} stroke-width="2.5" />
    <line x1=${x + 41} y1="127" x2=${x + 47} y2="133" stroke=${MUTED} stroke-width="2.5" />
    <text x=${x + 56} y="130" font-size="16.5" font-weight="600" fill=${INK}>floods in Thailand</text>
    ${RESULTS.map((r, k) => html`<g>
      <rect x=${x + 18} y=${164 + k * 52} width="40" height="40" rx="6" fill="#c9d6d8" />
      <path d=${`M ${x + 18} ${192 + k * 52} q 10 -8 20 0 t 20 0 v 12 h -40 z`} fill="#7fa3b5" />
      <text x=${x + 70} y=${180 + k * 52} font-size="15" fill=${MUTED}>caption says</text>
      <text x=${x + 70} y=${199 + k * 52} font-size="16" font-weight="600" fill=${INK}>${r}</text>
    </g>`)}
    <text x=${x + w / 2} y="340" text-anchor="middle" font-size="16" font-weight="700" fill=${ACCENT}>results are only as</text>
    <text x=${x + w / 2} y="360" text-anchor="middle" font-size="16" font-weight="700" fill=${ACCENT}>good as the captions</text>
  </g>`;
}

function Node({ n }) {
  const { fill, stroke } = KINDS[n.kind];
  const cx = n.x + n.w / 2;
  const top = n.y + n.h / 2 - ((n.sub.length + 1) * 21) / 2 + 12;
  return html`<g>
    <rect x=${n.x} y=${n.y} width=${n.w} height=${n.h} rx="14" fill=${fill} stroke=${stroke}
      stroke-width=${n.strong ? 4 : 2.5} />
    <text x=${cx} y=${top} text-anchor="middle" font-size="23" font-weight="700" fill=${INK}>${n.title}</text>
    ${n.sub.map((line, k) => html`<text x=${cx} y=${top + 26 + k * 21} text-anchor="middle"
      font-size="17" fill=${SUB}>${line}</text>`)}
  </g>`;
}

function Edge({ e }) {
  const [[x1, y1], [x2, y2], label] = e;
  return html`<g>
    <line x1=${x1} y1=${y1} x2=${x2} y2=${y2} stroke=${MUTED} stroke-width="2.5"
      marker-end="url(#value-arrow)" />
    ${label && html`<text x=${(x1 + x2) / 2} y=${Math.min(y1, y2) - 10} text-anchor="middle"
      font-size="15" fill=${MUTED}>${label}</text>`}
  </g>`;
}

export function ValueFlow() {
  return html`<svg class="arch" viewBox="0 0 1400 600" role="img"
      aria-label="Aerial imagery and public records go into Clayzer. Step 1, Clayzer writes a caption from the image alone. Step 2, it checks every fact against records the captioner never saw. Only trusted image and caption pairs go on to Clay, which makes the imagery searchable in words: for example, a search for floods in Thailand returns the images whose captions say so. Planned: Clay's embeddings choose which places to caption next.">
    <defs>
      ${[["value-arrow", MUTED], ["value-arrow-planned", PLANNED]].map(([id, color]) => html`<marker
        id=${id} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8"
        orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill=${color} /></marker>`)}
    </defs>
    <rect x="285" y="34" width="560" height="400" rx="18" fill="#fbf4ef" stroke="#e8beb2"
      stroke-width="2" stroke-dasharray="8 6" />
    ${COLUMNS.map((c) => html`<text x=${c.x + c.w / 2} y="24" text-anchor="middle" font-size="17"
      font-weight="700" letter-spacing="2.5" fill=${c.ours ? ACCENT : MUTED}>${c.title.toUpperCase()}</text>`)}
    ${EDGES.map((e) => html`<${Edge} e=${e} />`)}
    ${NODES.map((n) => html`<${Node} n=${n} />`)}
    <${SearchCard} />
    <text x="865" y="122" text-anchor="middle" font-size="15" font-weight="700" fill=${ACCENT}>only pairs</text>
    <text x="865" y="141" text-anchor="middle" font-size="15" font-weight="700" fill=${ACCENT}>that pass</text>
    <polyline points="1000,280 1000,412 710,412 710,286" fill="none" stroke=${PLANNED}
      stroke-width="2.5" stroke-dasharray="7 6" marker-end="url(#value-arrow-planned)" />
    <text x="1012" y="406" font-size="15" fill=${MUTED}>planned: Clay's embeddings pick</text>
    <text x="1012" y="425" font-size="15" fill=${MUTED}>which places to caption next</text>
    <line x1="10" y1="462" x2="1390" y2="462" stroke="#e4dbd6" stroke-width="2" />
    ${VALUE.map((v) => html`<g>
      <text x=${v.x + v.w / 2} y="494" text-anchor="middle" font-size="21" font-weight="700"
        fill=${ACCENT}>${v.head}</text>
      ${v.lines.map((line, k) => html`<text x=${v.x + v.w / 2} y=${522 + k * 22} text-anchor="middle"
        font-size="17" fill=${SUB}>${line}</text>`)}
    </g>`)}
  </svg>`;
}
