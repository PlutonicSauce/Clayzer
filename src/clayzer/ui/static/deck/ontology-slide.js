// The ontology slide: one photo, then what the caption harness knows about what's in it. Case
// fixed-dev-neg-6, Chip ca-neg-6-20220703 (NAIP 2022, Tehachapi): a greenhouse beside buildings
// and a road, farm fields, two ponds. Object positions are Chip pixels (512 x 512): the greenhouse
// is OSM way 1366245529, x 273-317, y 245-262; the rest are placed by eye on the Case's OSM
// Reference Labels.
//
// Builds, one per press (`steps: 2` in slides.js):
//   0  the photo, its objects tagged, and the ontology's "near" links between them
//   1  the photo pixelates (24 x 24, then 12 x 12 blocks of its real colours), the blocks scatter,
//      and each tag glides to its class in the ontology graph: families as clusters, is-a solid,
//      "near" dashed amber (the Ontology page's graph, ADR-0012), look-alikes dotted
//   2  why it helps the caption: numbered badges on the graph match the slide's three benefits
//      (look-alikes to tell apart, neighbours to look for, words that can be checked)
// All motion is CSS transitions keyed off the step (no hooks, so tests/deck_smoke.mjs can render
// it); arriving at a build directly shows its end state. Reduced motion: no transitions.
//
// The pixel colours are box-filter averages of the Chip, computed once with Pillow
// (Image.resize(n, BOX)), one 6-digit hex colour per block, row by row.

import { html } from "./html.js";

const CHIP = "/api/chips/ca-neg-6-20220703.png";
const PX24 = "897e6b887f6b8a816c8c826c867f69827d68827d68807c65827c66827b66847d6596836898826696816693806591816894826995826998856b9b866b9c876d9b876e676254373e3c867c68847d68867e6a88806a837d69827d687c7a64817c66847d688b8069897e689081699382679782659481648f7f658e7f6595856a94836995846a9483688878628678617f7360897d6a817965807964857e698d7f69857d697f7a65847d6690826a8f81679182688f80669181688e7f6794816694826592806398856996836a81745d8d8064887c62766f587f755c8d7e64887b647f78628a7d657d715d7a725b847d629885699783669582658f81678f816892826991816a938166907f658e80669d886a8b7b654948416e6953756b558d7f629a896b5d5b4c7b725b5c594b756e57695f4e746d579885689f89699e8b6d9684678b7e648e816b94846b92826991826c776f5e6160507d735a6c6352736e578e7f629b87697b6e585756476262508d7e648e8063917f619583669a87689380619c88689684669d896b6f64517e745b9584688e806b8c806b80776759574b5b5a464e4d42595a4767644e837c60736b5740453c6962525f5b4d887f6595866a9c8a6e9a8769505148494f4765684e9280638372595d58485756455b5d4864664f716f5c52534566634e6a664e907f657167545956485e5e4b54534498856b96856c8b7f65857e5e847d5f958a6e8480716362587e765d93836a918166766c57746b558e8061746e5958584a605f4a6e675166614e99876a8f7f6459544758584669644f8e816d897c66887f63827e5d807f5d7c7c598b83698a8a849c8b75776c5a84755db1a180a492719e8c6897876b7b725c7d765c7b6f576e65517770569785677b6f577e73599d8c6b8174607d72608b7f637c7c567c7e597a7b55787766989d9eb5afa57b736174715b877c64897f64898062847b5f948b6c93846966604d978c6e77755b8a7e619884659c8a6ca897787c745f92846c94846b93856a918469867d609a9788878270a29b898a8572736f5942473f4d514455594a444a3e7c785d9c8d7193876d706c5877745c8880669081649381639a87678b7d65887c66857b668277618d81669789709d927fa9a29074765e86806c8379647b725e6864547578677074636766539d98887e796880847e838176736e5a6865505a5b465d6249857a61877a618b7c638578607a715c7e765e8f82689688709a917d857e687a745e746e5a6c6756847e6b88806f6c6e58616c6b757d6ba1a6a474786b5f67635f68537c7362796e5f76755b7c745b776e5859584878735b82785f887b6495856a93836b9a8c759489759189738d867389836f918a768f8f80a6a59a7d7f64787b5e7072629286787577707a6b5e4d4c435b5e4e4a4e415155455c5f4a60614a79725888775d8c7c6394846a9b8a709b886d9486668c826296896b908268817b668b89787476647c7d6a515c58535a4848524376675c82746867634d4a4b404b4c415359474f51425558465555447a7159766d5a85795f9d8d72a08f73877c628c7c619d8b6d95876b817a6275786a72755b9f9a889b98869e9988aca594aca5927e7759807759766d556c684f7169516f6a5966645144483f39413b686951918168988a6f9d907491836b8c7d635e5c513b433e5e634d82795a90806295856a9a8a6f9f8e6f9a886a81775d897d6192846682775b66614b66624b4b50443a42395960466966508d8069827a5f746c587a745e8d846a90826a867a638c8068877b648f836b94866c9c8b6fa492739a896d82785e786f5a9284689b896a8278596f6b504b52413e473c404a3a575d478d826a696b5b424d45726d578c7f66776f5c7270588983629c8d709c8d709e8e719c8e708f82649083679687699b8a6d8a7d64887d6193846285785b6968515a6049434d3d78745e837f63526c63204f58275157425d59454f4639413c4b57414b553f6b764e676d4c7e7d5b727053525b429586699587699487688c80648e81629e8b6c9383664b4d42424a3e897f658a876a2855591e505a1e505a1f505a425d565558493a473749573f4e5842434d3d434d3d3e483a3a433799876998886a9787689686677e735c615f4c8f83666a6556696956898266948d728087715971692a575d1f515a52665a454d4646523f59654855604a353f37353f37353f36353f3694856997876a948467635e4e474a40545948827b5f6a6856887f678e876a6a6a568f8a6ba79d7f9d967d7f8371828065414b3f374438616d4c505845353f37353f37353f36353f368780668c82679685669585677f745c786f586f68566a6553867f638f8467807a5f898468a096799a9172948b6e8d86684a53424d58415d684959624b353f37353f36353f36364037";
const PX12 = "877e6989806b837d69807c66857d678d806796826692806593826897846a9582696a6355877c66847b65827862887e659382678f81679181699381669583677a6e5b7e745b877b60726c577c715982755c9a86679a876981765f92826a857a6765614f625e4d857a5e625d4d7e725e8b806494866960615682785e7a6e586d6851686753615f4b7f745b6d64525d5b49857965847e5e7d7d5989897d9186758c80679587688a80657c735a7d755c8d7e6197886a897c658c7f678f83689993828a86726d68565f6152656754938a747a796a7d755d7972567f775e786e597d745d918369938871857d68827c6985826f7f84757f82737273686f66595556475256465f5f4a796f578b7d659b8b6e8d816491846a7e7d6a777a6975776694897b82795c7d74596b65504c4f43595c498e8168887d658178626a67558a7e6397886d9e8c6e8b7e6490826683785a535846555a477376633f57536266585f624d7b795b87816278745897876993856783785e756e596f6d58727c6a305a5f345959475041515d453c463a384238908468887b6064614f716c578b8267807c629f977988856b444e3e5a6449353f37353f36";

const K = 540 / 512; // Chip pixels to canvas units: the photo is 540 square at (0, 10)
const at = ([x, y]) => [x * K, 10 + y * K];

// Family colours: the Ontology page's graph (app.js ONTO_GROUP), [fill, border].
const FAMILY = {
  energy_infrastructure: ["#f4dcd4", "#b06a4f", "Energy infrastructure"],
  transportation: ["#dde7e9", "#4a7a86", "Transportation"],
  built_structure: ["#efe8e3", "#8a7a63", "Built structure"],
  hydrography: ["#dbe6ec", "#4a6a86", "Water features"],
  land_cover: ["#dfe9df", "#5a7a4a", "Land cover"],
};

// Clusters in the graph: [family, x, y, width, height].
const CLUSTERS = [
  ["energy_infrastructure", 30, 70, 230, 160],
  ["hydrography", 30, 340, 230, 160],
  ["built_structure", 355, 70, 270, 430],
  ["transportation", 720, 70, 250, 230],
  ["land_cover", 720, 340, 250, 160],
];

// What's in the photo: the Chip pixel it's at, where its tag sits on the photo, and its node in
// the graph. The tag is one element that moves from one to the other.
const TAGS = [
  { id: "greenhouse", name: "Greenhouse", family: "built_structure", px: [295, 253], tag: [300, 232], node: [490, 395] },
  { id: "building", name: "Building", family: "built_structure", px: [490, 288], tag: [458, 270], node: [490, 175] },
  { id: "road", name: "Road", family: "transportation", px: [420, 385], tag: [450, 456], node: [845, 150] },
  { id: "water", name: "Water", family: "hydrography", px: [285, 437], tag: [228, 516], node: [145, 425] },
  { id: "field", name: "Farm field", family: "land_cover", px: [85, 185], tag: [98, 160], node: [845, 425] },
];
// Classes the graph adds that aren't in the photo (drawn dashed).
const ELSEWHERE = [
  { id: "solar_array", name: "Solar array", family: "energy_infrastructure", node: [145, 155] },
  { id: "parking_lot", name: "Parking lot", family: "transportation", node: [845, 240] },
];
const NODE_W = 170, NODE_H = 48;

// The last build's badges: which part of the graph each numbered benefit on the slide comes from.
const BADGES = [[1, 300, 236], [2, 700, 236], [3, 406, 150]];

// The ontology's "near" pairs among the photo's objects (objects.toml), drawn on the photo.
const PHOTO_NEAR = [["greenhouse", "building"], ["greenhouse", "road"], ["building", "road"]];

// Graph edges: kind, path, label and its position. `hi` edges stay lit on the last build.
const EDGES = [
  { kind: "isa", d: "M490 371 L490 203", label: "is a kind of", lx: 480, ly: 292, end: true },
  { kind: "near", hi: true, d: "M575 380 C 625 340, 625 230, 575 190", label: "near", lx: 580, ly: 292 },
  { kind: "near", hi: true, d: "M575 400 C 690 400, 680 170, 758 158", label: "near", lx: 672, ly: 288, mid: true },
  { kind: "near", d: "M575 166 L758 148", label: "near", lx: 660, ly: 146 },
  { kind: "near", d: "M575 184 L758 236", label: "near", lx: 650, ly: 224 },
  { kind: "alike", hi: true, d: "M405 395 C 330 395, 300 165, 230 158", label: "looks like", lx: 268, ly: 300 },
  { kind: "alike", hi: true, d: "M215 401 L215 179", label: "looks like", lx: 205, ly: 292, end: true },
];

function Pixels({ hex, n, scatter = false }) {
  const s = 540 / n;
  return Array.from({ length: n * n }, (_, i) => {
    const x = (i % n) * s, y = 10 + Math.floor(i / n) * s;
    const fill = `#${hex.slice(i * 6, i * 6 + 6)}`;
    if (!scatter) return html`<rect x=${x} y=${y} width=${s + 0.5} height=${s + 0.5} fill=${fill} />`;
    // Each block drifts away from the photo's centre and falls a little, in a fixed shuffled order.
    const dx = (x + s / 2 - 270) * 0.35, dy = (y + s / 2 - 280) * 0.35 + 40;
    const delay = (((i * 53) % (n * n)) / (n * n)) * 0.6;
    return html`<rect x=${x} y=${y} width=${s + 0.5} height=${s + 0.5} fill=${fill}
      style=${`--dx: ${dx.toFixed(1)}px; --dy: ${dy.toFixed(1)}px; --d: ${delay.toFixed(2)}s`} />`;
  });
}

function Node({ c, graph, dashed = false }) {
  const [fill, line] = FAMILY[c.family];
  const [x, y] = graph || !c.tag ? c.node : c.tag;
  const scale = graph || !c.tag ? 1 : 0.85;
  return html`<g class=${`onto-node ${dashed ? "elsewhere" : ""}`}
      style=${`transform: translate(${x}px, ${y}px) scale(${scale})`}>
    <rect x=${-NODE_W / 2} y=${-NODE_H / 2} width=${NODE_W} height=${NODE_H} rx="24"
      fill=${fill} stroke=${line} />
    <text y="7" text-anchor="middle">${c.name}</text>
  </g>`;
}

export function OntologyViz({ step = 0 }) {
  const graph = step >= 1;
  const byId = Object.fromEntries(TAGS.map((t) => [t.id, t]));
  return html`<svg class=${`onto-viz ${graph ? "graph" : ""} ${step >= 2 ? "told" : ""}`}
      viewBox="0 0 1000 560" role="img"
      aria-label=${graph
        ? "The ontology graph: a greenhouse is a kind of building; greenhouses are typically found near buildings and roads; buildings near roads and parking lots; a greenhouse, and water, look like a solar array."
        : "Aerial photo of a farm: a greenhouse in the centre, buildings to the east, a road, farm fields, and two ponds to the south, each tagged with its class."}>
    <defs>
      <marker id="onto-arrow-isa" viewBox="0 0 10 10" refX="9" refY="5" markerUnits="userSpaceOnUse" markerWidth="14" markerHeight="14" orient="auto-start-reverse">
        <path d="M0 0 L10 5 L0 10 Z" fill="#6b6461" /></marker>
      <marker id="onto-arrow-near" viewBox="0 0 10 10" refX="9" refY="5" markerUnits="userSpaceOnUse" markerWidth="14" markerHeight="14" orient="auto-start-reverse">
        <path d="M0 0 L10 5 L0 10 Z" fill="#b06a4f" /></marker>
    </defs>
    <g class="clusters">
      ${CLUSTERS.map(([f, x, y, w, h]) => html`<g class="cluster">
        <rect x=${x} y=${y} width=${w} height=${h} rx="16" stroke=${FAMILY[f][1]} />
        <text x=${x + 16} y=${y + 28} fill=${FAMILY[f][1]}>${FAMILY[f][2]}</text>
      </g>`)}
    </g>
    <image class="photo" href=${CHIP} x="0" y="10" width="540" height="540" />
    <g class="px px24">${Pixels({ hex: PX24, n: 24 })}</g>
    <g class="px px12">${Pixels({ hex: PX12, n: 12, scatter: true })}</g>
    <g class="photo-only">
      ${PHOTO_NEAR.map(([a, b]) => { const [x1, y1] = at(byId[a].px), [x2, y2] = at(byId[b].px);
        return html`<line class="photo-near" x1=${x1} y1=${y1} x2=${x2} y2=${y2} />`; })}
      ${TAGS.map((t) => { const [x, y] = at(t.px);
        return html`<line class="leader" x1=${x} y1=${y} x2=${t.tag[0]} y2=${t.tag[1]} />
          <circle class="anchor" cx=${x} cy=${y} r="7" />`; })}
    </g>
    <g class="edges">
      ${EDGES.map((e) => html`<g class=${`edge ${e.kind} ${e.hi ? "hi" : ""}`}>
        <path d=${e.d} marker-end=${e.kind === "alike" ? undefined : `url(#onto-arrow-${e.kind})`} />
        <text x=${e.lx} y=${e.ly} text-anchor=${e.end ? "end" : e.mid ? "middle" : "start"}>${e.label}</text>
      </g>`)}
    </g>
    <g class="elsewhere-nodes">${ELSEWHERE.map((c) => html`<${Node} c=${c} graph dashed />`)}</g>
    ${TAGS.map((t) => html`<${Node} c=${t} graph=${graph} />`)}
    <g class="badges">${BADGES.map(([n, x, y]) => html`<g class="badge">
      <circle cx=${x} cy=${y} r="19" /><text x=${x} y=${y + 7} text-anchor="middle">${n}</text>
    </g>`)}</g>
  </svg>`;
}
