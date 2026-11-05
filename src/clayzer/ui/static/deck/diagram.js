// The AWS deployment, as built by infra/app.py plus what docs/caption-design.md §3.4 plans next.
// Solid = deployed now; dashed = planned (AWS-04, -05, -09, -11). Keep it in step with both.

import { html } from "./html.js";

// Colours are SVG attributes, not CSS, so the diagram renders the same anywhere it is exported.
// Same palette as the site (../style.css).
const INK = "#252323", MUTED = "#6b6461", SUB = "#4a4240", PLANNED = "#a59d99";
const KINDS = {
  platform: { fill: "#dde7e9", stroke: "#9fb7bc" },
  data: { fill: "#efe8e3", stroke: "#cebeb5" },
  captions: { fill: "#f4dcd4", stroke: "#e8beb2" },
  evaluation: { fill: "#dfe9df", stroke: "#a9c2a9" },
  external: { fill: "#fffdfb", stroke: "#cebeb5" },
};

// x, y, w, h in the 1400 × 640 viewBox.
const NODES = [
  { id: "browser", x: 10, y: 98, w: 182, h: 84, kind: "external", title: "Judges' browser", sub: ["HTTPS"] },

  { id: "cdn", x: 236, y: 98, w: 170, h: 84, kind: "platform", title: "CloudFront", sub: ["HTTPS URL, no caching"] },
  { id: "alb", x: 446, y: 98, w: 170, h: 84, kind: "platform", title: "Load balancer", sub: ["accepts CloudFront only"] },
  { id: "web", x: 656, y: 88, w: 210, h: 104, kind: "platform", title: "ECS Fargate", sub: ["Clayzer web app", "1 ARM64 task · read-only"] },
  { id: "s3", x: 926, y: 88, w: 170, h: 300, kind: "data", title: "S3 store", sub: ["Chips, Cases,", "Captions, Traces,", "scores, reports,", "Batches", "", "encrypted,", "public access", "blocked"] },

  { id: "bedrock", x: 236, y: 284, w: 380, h: 104, kind: "captions", title: "Amazon Bedrock", sub: ["Nova Pro writes Captions · Opus 5.5 judges", "Titan Text Embeddings v2 for retrieval"] },
  { id: "pipe", x: 656, y: 284, w: 210, h: 104, kind: "evaluation", title: "Caption pipeline", sub: ["clayzer CLI: Cases →", "Captions → scores → report"] },

  { id: "sm", x: 236, y: 470, w: 170, h: 104, kind: "captions", planned: true, title: "SageMaker", sub: ["open VLM on one GPU", "GPU-seconds for cost"] },
  { id: "sfn", x: 446, y: 470, w: 170, h: 104, kind: "evaluation", planned: true, title: "Step Functions", sub: ["runs the pipeline,", "fan-out over Chips"] },
  { id: "otel", x: 656, y: 470, w: 210, h: 104, kind: "platform", planned: true, title: "ADOT", sub: ["→ X-Ray and CloudWatch:", "Traces, faults, cost metrics"] },
  { id: "agent", x: 926, y: 470, w: 170, h: 104, kind: "captions", planned: true, title: "AgentCore", sub: ["agentic captioner,", "holds LGND sign-in"] },

  { id: "naip", x: 1206, y: 284, w: 176, h: 104, kind: "external", title: "NAIP on AWS", sub: ["0.6 m aerial imagery", "Requester-Pays"] },
  { id: "lgnd", x: 1206, y: 470, w: 176, h: 104, kind: "external", planned: true, title: "LGND Geo MCP", sub: ["imagery claim checks"] },
];

// [from, to, label, planned]. Points are picked by hand so lines stay straight.
const EDGES = [
  [[192, 140], [236, 140], ""],
  [[406, 140], [446, 140], ""],
  [[616, 140], [656, 140], ""],
  [[866, 140], [926, 140], "reads"],
  [[656, 336], [616, 336], ""],
  [[866, 336], [926, 336], "writes"],
  [[1206, 336], [1096, 336], "Chips"],
  [[531, 470], [700, 388], "", true],
  [[761, 388], [761, 470], "", true],
  [[1096, 522], [1206, 522], "", true],
];

function Node({ n }) {
  const lines = n.sub.length;
  const top = n.y + n.h / 2 - ((lines + 1) * 19) / 2 + 14;
  const { fill, stroke } = KINDS[n.kind];
  const cx = n.x + n.w / 2;
  return html`<g opacity=${n.planned ? 0.8 : 1}>
    <rect x=${n.x} y=${n.y} width=${n.w} height=${n.h} rx="12" fill=${fill}
      fill-opacity=${n.planned ? 0.55 : 1} stroke=${stroke} stroke-width="2"
      stroke-dasharray=${n.planned ? "7 6" : "none"} />
    <text x=${cx} y=${top} text-anchor="middle" font-size="20" font-weight="700" fill=${INK}>${n.title}</text>
    ${n.sub.map((line, k) => html`<text x=${cx} y=${top + 22 + k * 19} text-anchor="middle"
      font-size="15.5" fill=${SUB}>${line}</text>`)}
  </g>`;
}

function Edge({ e }) {
  const [[x1, y1], [x2, y2], label, planned] = e;
  return html`<g>
    <line x1=${x1} y1=${y1} x2=${x2} y2=${y2} stroke=${planned ? PLANNED : MUTED} stroke-width="2.2"
      stroke-dasharray=${planned ? "6 6" : "none"} marker-end=${planned ? "url(#arrow-planned)" : "url(#arrow)"} />
    ${label && html`<text x=${(x1 + x2) / 2} y=${Math.min(y1, y2) - 10} text-anchor="middle"
      font-size="14.5" fill=${MUTED}>${label}</text>`}
  </g>`;
}

// A story version of the architecture: one image enters on the left, a trustworthy verdict leaves
// on the right, with four numbered stops a non-technical listener can follow. Colours are SVG
// attributes (not CSS) so it renders the same wherever it's exported.
const STORY = [
  { n: "in", x: 12, y: 150, w: 150, h: 120, kind: "external", title: "Aerial image", sub: ["NAIP tile", "0.6 m / pixel"] },
  { n: "1", x: 212, y: 60, w: 212, h: 130, kind: "captions", title: "Write a caption", sub: ["Nova Pro on Bedrock", "objects, counts, places"] },
  { n: "2", x: 212, y: 250, w: 212, h: 130, kind: "captions", title: "Verify each claim", sub: ["checked against imagery", "wrong claims dropped"] },
  { n: "3", x: 474, y: 60, w: 212, h: 130, kind: "evaluation", title: "Score vs open data", sub: ["USGS, OpenStreetMap", "the model never sees them"] },
  { n: "4", x: 474, y: 250, w: 212, h: 130, kind: "evaluation", title: "Gate the change", sub: ["better, worse, or", "inconclusive vs Baseline"] },
  { n: "out", x: 736, y: 150, w: 200, h: 130, kind: "platform", title: "A verdict you trust", sub: ["scores, failure modes,", "cost — kept with its Trace"] },
];
const STORY_EDGES = [
  [[162, 210], [212, 125], "", false],
  [[162, 210], [212, 315], "", false],
  [[424, 125], [474, 125], "", false],
  [[424, 315], [474, 315], "", false],
  [[686, 125], [736, 205], "", false],
  [[686, 315], [736, 225], "", false],
];

function StoryNode({ n }) {
  const { fill, stroke } = KINDS[n.kind];
  const cx = n.x + n.w / 2;
  const lines = n.sub.length;
  const top = n.y + n.h / 2 - ((lines + 1) * 20) / 2 + 10;
  const badge = !["in", "out"].includes(n.n);
  return html`<g>
    <rect x=${n.x} y=${n.y} width=${n.w} height=${n.h} rx="14" fill=${fill} stroke=${stroke} stroke-width="2.5" />
    ${badge && html`<circle cx=${n.x + 26} cy=${n.y + 26} r="17" fill=${INK} />`}
    ${badge && html`<text x=${n.x + 26} y=${n.y + 33} text-anchor="middle" font-size="20" font-weight="800" fill="#fffdfb">${n.n}</text>`}
    <text x=${cx} y=${top} text-anchor="middle" font-size="23" font-weight="700" fill=${INK}>${n.title}</text>
    ${n.sub.map((line, k) => html`<text x=${cx} y=${top + 26 + k * 20} text-anchor="middle"
      font-size="16.5" fill=${SUB}>${line}</text>`)}
  </g>`;
}

export function StoryArchitecture() {
  return html`<svg class="arch" viewBox="0 0 950 430" role="img"
      aria-label="One aerial image enters on the left. Step 1, a model writes a caption. Step 2, each claim is verified against imagery. Step 3, the caption is scored against open map data the model never saw. Step 4, a gate decides if it is good enough. A trustworthy verdict leaves on the right.">
    <defs>
      <marker id="story-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse">
        <path d="M 0 0 L 10 5 L 0 10 z" fill=${MUTED} />
      </marker>
    </defs>
    ${STORY_EDGES.map(([[x1, y1], [x2, y2]]) => html`<line x1=${x1} y1=${y1} x2=${x2} y2=${y2}
      stroke=${MUTED} stroke-width="2.5" marker-end="url(#story-arrow)" />`)}
    ${STORY.map((n) => html`<${StoryNode} n=${n} />`)}
  </svg>`;
}

export function ArchitectureDiagram() {
  return html`<svg class="arch" viewBox="0 0 1400 640" role="img"
      aria-label="AWS deployment: browser to CloudFront, load balancer, and a Fargate task that reads the S3 store; the caption pipeline calls Bedrock and writes to S3; SageMaker, Step Functions, ADOT, and AgentCore are planned.">
    <defs>
      ${[["arrow", MUTED], ["arrow-planned", PLANNED]].map(([id, color]) => html`<marker id=${id}
        viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
        <path d="M 0 0 L 10 5 L 0 10 z" fill=${color} />
      </marker>`)}
    </defs>
    <rect x="206" y="20" width="920" height="600" rx="18" fill="#fbf8f6" stroke="#cebeb5" stroke-width="2" />
    <text x="230" y="56" font-size="19" font-weight="600" fill=${MUTED}>One AWS account · us-west-2 · created by one cdk deploy</text>
    <text x="1110" y="452" text-anchor="end" font-size="15" font-weight="700" letter-spacing="1.2" fill=${MUTED}>PLANNED</text>
    ${NODES.map((n) => html`<${Node} n=${n} />`)}
    ${EDGES.map((e) => html`<${Edge} e=${e} />`)}
  </svg>`;
}
