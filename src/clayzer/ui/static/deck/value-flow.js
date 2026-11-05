// How it works, start to finish, and where the value lands: public imagery and records go in on
// the left, Clayzer's four steps turn them into image + caption pairs it has checked, and Clay
// uses them to make imagery searchable in words. The dashed loop is planned: Chips are joined to
// LGND's Clay embeddings, but nothing uses them to choose places yet. Colours are SVG attributes,
// as in diagram.js, so it renders the same anywhere.

import { html } from "./html.js";

const INK = "#252323", MUTED = "#6b6461", SUB = "#4a4240", PLANNED = "#a59d99", ACCENT = "#9a4a35";
const KINDS = {
  data: { fill: "#efe8e3", stroke: "#cebeb5" },
  captions: { fill: "#f4dcd4", stroke: "#e8beb2" },
  evaluation: { fill: "#dfe9df", stroke: "#a9c2a9" },
  platform: { fill: "#dde7e9", stroke: "#9fb7bc" },
  clay: { fill: "#f3e6cf", stroke: "#d9bd86" },
};

// x, y, w, h in the 1400 × 600 viewBox. Steps run 1 → 2 → 3 → 4 around the Clayzer box.
const NODES = [
  { x: 10, y: 80, w: 200, h: 100, kind: "data", title: "Aerial imagery", sub: ["NAIP · Vantor"] },
  { x: 10, y: 280, w: 200, h: 100, kind: "data", title: "Public records", sub: ["USGS · OpenStreetMap"] },
  { x: 280, y: 80, w: 280, h: 100, kind: "captions", n: "1", title: "Write the caption", sub: ["Nova Pro sees the image only"] },
  { x: 280, y: 280, w: 280, h: 100, kind: "captions", n: "2", title: "Verify each fact", sub: ["against imagery at its cell,", "before it's written"] },
  { x: 620, y: 280, w: 280, h: 100, kind: "evaluation", n: "3", title: "Score vs the records", sub: ["hidden from the captioner"] },
  { x: 620, y: 80, w: 280, h: 100, kind: "evaluation", n: "4", title: "Gate the change", sub: ["kept only if it beats", "the baseline"] },
  { x: 965, y: 70, w: 190, h: 120, kind: "platform", strong: true, title: "Trusted pairs", sub: ["image + caption,", "with a trust score"] },
  { x: 1195, y: 70, w: 195, h: 120, kind: "clay", strong: true, title: "Clay", sub: ["search the Earth", "in words"] },
];

// [from, to]; points picked by hand so lines stay straight.
const EDGES = [
  [[210, 130], [280, 130]],
  [[420, 180], [420, 280]],
  [[560, 330], [620, 330]],
  [[760, 280], [760, 180]],
  [[900, 130], [965, 130]],
  [[1155, 130], [1195, 130]],
];

const COLUMNS = [
  { x: 10, w: 200, title: "Public data" },
  { x: 250, w: 680, title: "Clayzer", ours: true },
  { x: 965, w: 425, title: "Clay" },
];

const VALUE = [
  { x: 10, w: 200, head: "Answer keys for free", lines: ["public records,", "no hand-labelling"] },
  { x: 250, w: 680, head: "Wrong captions caught before anyone searches", lines: ["a caption that says “flooded” when it isn't", "never turns up as a result"] },
  { x: 965, w: 425, head: "Search the Earth in words", lines: ["across the 15.2 billion embeddings", "Clay has published"] },
];

function Node({ n }) {
  const { fill, stroke } = KINDS[n.kind];
  const cx = n.x + n.w / 2 + (n.n ? 16 : 0); // clear the step badge
  const top = n.y + n.h / 2 - ((n.sub.length + 1) * 21) / 2 + 12;
  return html`<g>
    <rect x=${n.x} y=${n.y} width=${n.w} height=${n.h} rx="14" fill=${fill} stroke=${stroke}
      stroke-width=${n.strong ? 4 : 2.5} />
    ${n.n && html`<circle cx=${n.x + 24} cy=${n.y + 24} r="15" fill=${INK} />
      <text x=${n.x + 24} y=${n.y + 30} text-anchor="middle" font-size="17" font-weight="800"
        fill="#fffdfb">${n.n}</text>`}
    <text x=${cx} y=${top} text-anchor="middle" font-size="23" font-weight="700" fill=${INK}>${n.title}</text>
    ${n.sub.map((line, k) => html`<text x=${cx} y=${top + 26 + k * 21} text-anchor="middle"
      font-size="17" fill=${SUB}>${line}</text>`)}
  </g>`;
}

export function SolutionFlow() {
  return html`<svg class="arch" viewBox="0 0 1400 600" role="img"
      aria-label="Aerial imagery and public records go into Clayzer. Step 1, a model writes a caption from the image alone. Step 2, each fact is verified against the imagery before it is written. Step 3, the caption is scored against the public records, which the captioner never sees. Step 4, a gate keeps a change only if it beats the baseline. Only trusted image and caption pairs go on to Clay, which makes the imagery searchable in words. Planned: Clay's embeddings choose which places to caption next.">
    <defs>
      ${[["flow-arrow", MUTED], ["flow-arrow-planned", PLANNED]].map(([id, color]) => html`<marker
        id=${id} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8"
        orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill=${color} /></marker>`)}
    </defs>
    <rect x="250" y="40" width="680" height="440" rx="18" fill="#fbf4ef" stroke="#e8beb2"
      stroke-width="2" stroke-dasharray="8 6" />
    ${COLUMNS.map((c) => html`<text x=${c.x + c.w / 2} y="24" text-anchor="middle" font-size="17"
      font-weight="700" letter-spacing="2.5" fill=${c.ours ? ACCENT : MUTED}>${c.title.toUpperCase()}</text>`)}
    ${EDGES.map(([[x1, y1], [x2, y2]]) => html`<line x1=${x1} y1=${y1} x2=${x2} y2=${y2}
      stroke=${MUTED} stroke-width="2.5" marker-end="url(#flow-arrow)" />`)}
    <polyline points="110,380 110,440 760,440 760,386" fill="none" stroke=${MUTED} stroke-width="2.5"
      marker-end="url(#flow-arrow)" />
    <text x="435" y="464" text-anchor="middle" font-size="15" fill=${MUTED}>answer key, hidden from the captioner</text>
    <text x="1060" y="56" text-anchor="middle" font-size="15" font-weight="700" fill=${ACCENT}>only pairs that pass</text>
    ${NODES.map((n) => html`<${Node} n=${n} />`)}
    <polyline points="1292,190 1292,300 940,300" fill="none" stroke=${PLANNED} stroke-width="2.5"
      stroke-dasharray="7 6" marker-end="url(#flow-arrow-planned)" />
    <text x="1110" y="326" text-anchor="middle" font-size="15" fill=${MUTED}>planned: Clay's embeddings</text>
    <text x="1110" y="345" text-anchor="middle" font-size="15" fill=${MUTED}>pick which places to caption next</text>
    <line x1="10" y1="500" x2="1390" y2="500" stroke="#e4dbd6" stroke-width="2" />
    ${VALUE.map((v) => html`<g>
      <text x=${v.x + v.w / 2} y="534" text-anchor="middle" font-size="21" font-weight="700"
        fill=${ACCENT}>${v.head}</text>
      ${v.lines.map((line, k) => html`<text x=${v.x + v.w / 2} y=${560 + k * 22} text-anchor="middle"
        font-size="17" fill=${SUB}>${line}</text>`)}
    </g>`)}
  </svg>`;
}
