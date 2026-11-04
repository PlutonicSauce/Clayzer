// Renders every slide of the pitch deck through Preact to a text tree, without a browser:
//   node tests/deck_smoke.mjs
// Fails on a component that throws, an empty slide, or a slide with no heading.
import { register } from "node:module";
import { pathToFileURL } from "node:url";

const deck = new URL("../src/clayzer/ui/static/deck/", import.meta.url);
const vendor = { preact: "vendor/preact.js", "preact/hooks": "vendor/preact-hooks.js", htm: "vendor/htm.js" };
register(`data:text/javascript,${encodeURIComponent(`
  const map = ${JSON.stringify(Object.fromEntries(Object.entries(vendor).map(([k, v]) => [k, new URL(v, deck).href])))};
  export async function resolve(spec, ctx, next) { return map[spec] ? { url: map[spec], shortCircuit: true } : next(spec, ctx); }
`)}`, pathToFileURL("./"));

const { SLIDES } = await import(new URL("slides.js", deck).href);

const text = (v) => {
  if (v == null || typeof v === "boolean") return { text: "", tags: [] };
  if (typeof v === "string" || typeof v === "number") return { text: String(v), tags: [] };
  if (Array.isArray(v)) return v.map(text).reduce((a, b) => ({ text: a.text + " " + b.text, tags: [...a.tags, ...b.tags] }), { text: "", tags: [] });
  if (typeof v.type === "function") return text(v.type(v.props));
  const inner = text(v.props.children);
  return { text: inner.text, tags: [v.type, ...inner.tags] };
};

let failed = 0;
SLIDES.forEach((s, i) => {
  try {
    const out = text(s.component({}));
    const words = out.text.split(/\s+/).filter(Boolean).length;
    const ok = words > 5 && out.tags.some((t) => t === "h1" || t === "h2");
    if (!ok) failed++;
    console.log(`${ok ? "ok  " : "FAIL"} ${i + 1}. ${s.title}: ${words} words, ${out.tags.filter((t) => t === "svg").length ? "svg, " : ""}${out.tags.length} elements`);
  } catch (e) {
    failed++;
    console.log(`FAIL ${i + 1}. ${s.title}: ${e.message}`);
  }
});
process.exit(failed ? 1 : 0);
