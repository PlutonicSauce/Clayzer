// The ontology slide, as a 4-stage pipeline (revealed one stage per press, `steps: 3` in slides.js):
//   0  Built once, offline: hundreds of training images -> an AI ontology agent -> the ontology
//      (shown small: the real class graph — families, is-a / near / look-alike edges).
//   1  For a new image: the input chip is embedded with Clay.
//   2  That embedding is matched to the ontology by cosine similarity -> the top-k nearest classes.
//   3  Those classes, plus the chip, go to Nova Pro, which writes the caption.
// The ontology graph (the Ontology page's graph, ADR-0012) is reused small, inside the "ontology"
// box. Motion is CSS opacity keyed off the step (no hooks, so tests/deck_smoke.mjs can render it);
// arriving at a build directly shows its end state. Reduced motion: no transition.

import { html } from "./html.js";

const TRAIN = "/api/chips/ca-neg-6-20220703.png"; // stands in for the training set
const INPUT = "/api/chips/ca-uspvdb-400117-20220702.png"; // the one new image we caption

// Family colours: the Ontology page's graph (app.js ONTO_GROUP), [fill, border, short label].
const FAMILY = {
  energy_infrastructure: ["#f4dcd4", "#b06a4f", "Energy"],
  transportation: ["#dde7e9", "#4a7a86", "Transport"],
  built_structure: ["#efe8e3", "#8a7a63", "Built"],
  hydrography: ["#dbe6ec", "#4a6a86", "Water"],
  land_cover: ["#dfe9df", "#5a7a4a", "Land cover"],
};
const CLUSTERS = [
  ["energy_infrastructure", 30, 70, 230, 160], ["hydrography", 30, 340, 230, 160],
  ["built_structure", 355, 70, 270, 430], ["transportation", 720, 70, 250, 230],
  ["land_cover", 720, 340, 250, 160],
];
const NODES = [
  { id: "solar_array", name: "Solar array", family: "energy_infrastructure", node: [145, 155] },
  { id: "wind_turbine", name: "Wind turbine", family: "energy_infrastructure", node: [145, 240], dashed: true },
  { id: "water", name: "Water", family: "hydrography", node: [145, 425] },
  { id: "greenhouse", name: "Greenhouse", family: "built_structure", node: [490, 395] },
  { id: "building", name: "Building", family: "built_structure", node: [490, 175] },
  { id: "road", name: "Road", family: "transportation", node: [845, 150] },
  { id: "parking_lot", name: "Parking lot", family: "transportation", node: [845, 240], dashed: true },
  { id: "field", name: "Farm field", family: "land_cover", node: [845, 425] },
];
const NODE_W = 170, NODE_H = 48;
const EDGES = [
  { kind: "isa", d: "M490 371 L490 203" },
  { kind: "near", d: "M575 380 C 625 340, 625 230, 575 190" },
  { kind: "near", d: "M575 400 C 690 400, 680 170, 758 158" },
  { kind: "near", d: "M575 166 L758 148" },
  { kind: "near", d: "M575 184 L758 236" },
  { kind: "alike", d: "M405 395 C 330 395, 300 165, 230 158" },
  { kind: "alike", d: "M215 401 L215 179" },
];
const EDGE_STROKE = { isa: ["#6b6461", "none"], near: ["#b06a4f", "8 6"], alike: ["#9a4a35", "3 7"] };

// The classes nearest the solar input chip (illustrative) — the top-k the query keeps.
const TOPK = [
  ["solar array", "energy_infrastructure"], ["road", "transportation"], ["bare ground", "land_cover"],
];

// The ontology, drawn small inside its box: a nested SVG scales the real graph to fit.
function MiniGraph() {
  return html`<svg x="462" y="54" width="516" height="192" viewBox="0 0 1000 560" preserveAspectRatio="xMidYMid meet">
    ${CLUSTERS.map(([f, x, y, w, h]) => html`<g>
      <rect x=${x} y=${y} width=${w} height=${h} rx="16" fill="#fffdfb" stroke=${FAMILY[f][1]} stroke-width="2" />
      <text x=${x + 14} y=${y + 34} fill=${FAMILY[f][1]} font-size="26" font-weight="800">${FAMILY[f][2]}</text></g>`)}
    ${EDGES.map((e) => { const [stroke, dash] = EDGE_STROKE[e.kind];
      return html`<path d=${e.d} fill="none" stroke=${stroke} stroke-width="2.5" stroke-dasharray=${dash} />`; })}
    ${NODES.map((c) => { const [x, y] = c.node, [fill, line] = FAMILY[c.family];
      return html`<g><rect x=${x - NODE_W / 2} y=${y - NODE_H / 2} width=${NODE_W} height=${NODE_H} rx="24"
          fill=${fill} stroke=${line} stroke-width="2" stroke-dasharray=${c.dashed ? "6 4" : "none"} />
        <text x=${x} y=${y + 9} text-anchor="middle" font-size="27" font-weight="700" fill="#252323">${c.name}</text></g>`; })}
  </svg>`;
}

function ClassChip({ id, family, x, y, w = 178, h = 24 }) {
  const [fill, line] = FAMILY[family];
  return html`<g class="fchip">
    <rect x=${x} y=${y} width=${w} height=${h} rx=${h / 2} fill=${fill} stroke=${line} stroke-width="2" />
    <text x=${x + w / 2} y=${y + h / 2 + 5} text-anchor="middle" style="font-size:14px">${id}</text>
  </g>`;
}

export function OntologyViz({ step = 0 }) {
  const show = (n) => (step >= n ? "shown" : "");
  return html`<svg class="onto-flow" viewBox="0 0 1000 560" role="img"
      aria-label="A pipeline in two lanes. Built once, offline: hundreds of training images go to an AI ontology agent, which writes the ontology — shown as a small class graph with families and relations. For every new image: the input chip is embedded with Clay; that embedding is compared to the ontology by cosine similarity to keep the top-k nearest classes; and those classes, with the chip, go to Nova Pro, which writes the caption.">
    <defs>
      <marker id="flow-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="9" markerHeight="9" orient="auto-start-reverse">
        <path d="M0 0 L10 5 L0 10 Z" fill="#6b6461" /></marker>
      <marker id="flow-arrow-clay" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="9" markerHeight="9" orient="auto-start-reverse">
        <path d="M0 0 L10 5 L0 10 Z" fill="#b06a4f" /></marker>
    </defs>
    <line class="flow-divider" x1="0" y1="268" x2="1000" y2="268" />
    <text class="flow-lane" x="4" y="20">Built once, offline</text>
    <text class="flow-lane" x="4" y="302">For every new image</text>

    <g class=${`stage ${show(0)}`}>
      <g class="flow-stack">
        <image href=${TRAIN} x="56" y="92" width="88" height="88" />
        <image href=${TRAIN} x="40" y="78" width="88" height="88" />
        <image href=${TRAIN} x="24" y="64" width="88" height="88" />
      </g>
      <text class="flow-cap" x="76" y="206" text-anchor="middle">100s of training images</text>
      <line class="flow-link" x1="156" y1="112" x2="230" y2="112" marker-end="url(#flow-arrow)" />
      <g class="flow-box"><rect x="238" y="76" width="150" height="74" rx="16" />
        <text class="flow-box-t" x="313" y="108" text-anchor="middle">AI ontology</text>
        <text class="flow-box-t" x="313" y="130" text-anchor="middle">agent</text></g>
      <line class="flow-link" x1="396" y1="112" x2="452" y2="112" marker-end="url(#flow-arrow)" />
      <g class="flow-onto"><rect x="458" y="40" width="522" height="216" rx="16" />
        <text class="flow-onto-t" x="470" y="32">The ontology — classes and how they relate</text>
        <${MiniGraph} /></g>
    </g>

    <g class=${`stage ${show(1)}`}>
      <image class="flow-input" href=${INPUT} x="24" y="324" width="104" height="104" />
      <text class="flow-cap" x="76" y="448" text-anchor="middle">input chip</text>
      <line class="flow-link clay" x1="136" y1="380" x2="226" y2="380" marker-end="url(#flow-arrow-clay)" />
      <text class="flow-edge-t clay" x="182" y="362" text-anchor="middle">embed with Clay</text>
      <g class="flow-box"><rect x="234" y="354" width="128" height="52" rx="10" />
        ${[0, 1, 2, 3, 4, 5, 6, 7].map((i) => html`<rect class="flow-vec" x=${242 + i * 14} y="368" width="10" height="24" rx="2" />`)}</g>
      <text class="flow-cap" x="298" y="432" text-anchor="middle">Clay embedding</text>
    </g>

    <g class=${`stage ${show(2)}`}>
      <line class="flow-link clay" x1="366" y1="380" x2="452" y2="380" marker-end="url(#flow-arrow-clay)" />
      <text class="flow-edge-t clay" x="409" y="362" text-anchor="middle">cosine top-k</text>
      <path class="flow-match" d="M600 256 L600 342" marker-end="url(#flow-arrow-clay)" />
      <text class="flow-match-t" x="612" y="300">drawn from the ontology</text>
      <g class="flow-topk"><rect x="460" y="342" width="214" height="124" rx="14" />
        <text class="flow-topk-t" x="478" y="370">top-k nearest classes</text>
        ${TOPK.map((c, i) => html`<${ClassChip} id=${c[0]} family=${c[1]} x=${478} y=${382 + i * 28} />`)}</g>
      <text class="flow-cap" x="567" y="504" text-anchor="middle">handed to the captioner — next</text>
    </g>
  </svg>`;
}
