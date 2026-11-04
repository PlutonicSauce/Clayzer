// Development-only axe/Playwright review of a populated offline demo.
const { chromium } = require("playwright-core");
const { default: AxeBuilder } = require("@axe-core/playwright");
const fs = require("fs");
const output = process.env.CLAYZER_AUDIT_OUTPUT || "/tmp/clayzer-public-audit";
fs.mkdirSync(output, { recursive: true });
const base = process.env.CLAYZER_UI_URL || "http://127.0.0.1:8786";
(async () => {
  const browser = await chromium.launch({
    executablePath: process.env.CLAYZER_CHROMIUM,
    headless: true,
  });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 1000 },
  });
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  const batches = await (await page.request.get(base + "/api/batches")).json();
  const bid = batches.find((b) => b.batch_id.includes("SYNTHETIC")).batch_id;
  const cases = await (await page.request.get(base + "/api/cases")).json();
  const storyCase = cases.find((c) =>
    c.labels.some((l) => l.object === "solar_array" && l.count !== 0),
  ).id;
  const paths = [
    "journey",
    ...["explore", "describe", "verify", "understand"].map(
      (scene) => `journey/${storyCase}/${scene}`,
    ),
    ...["describe", "verify", "understand"].map(
      (scene) => `journey-run/${bid}/synthetic-building/1/${scene}`,
    ),
    "",
    "how",
    "cases",
    `cases/${cases[0].id}`,
    `cases/${cases.find((c) => c.kind === "change").id}`,
    "batches",
    "overview",
    `compare/${bid}/${bid}`,
    `batches/${bid}`,
    `runs/${bid}/synthetic-building/1`,
    "about",
    "developer",
    "ontology",
    "ontology/graph",
    "ontology/build",
    "ontology/measure",
    "ontology/use",
    "datasets",
    "datasets/synthetic-output",
    "concepts",
    "sources",
    "how/output",
    "tasks",
    "%ZZ",
    "/api/datasets/synthetic-output/dataset-card.html",
  ];
  const findings = [];
  for (const width of [1440, 390, 768, 320]) {
    await page.setViewportSize({ width, height: 1000 });
    for (const path of paths) {
      await page.goto(base + (path.startsWith("/api/") ? path : "/#/" + path));
      await page.waitForFunction(
        () =>
          document.querySelector("h1") &&
          !document.querySelector("#view[aria-busy]"),
      );
      if (
        !path.startsWith("/api/") &&
        (await page.locator("#view [role=alert]").count())
      )
        throw new Error(`Unexpected loading failure on ${path}`);
      if (path === "how") await page.locator('[data-method="2"]').click();
      if (path === "datasets/synthetic-output")
        await page.locator(".listen-panel>summary").click();
      for (const frame of page.frames().slice(1)) {
        await frame.locator("h1").waitFor({ state: "visible" });
      }
      // Script-free dataset iframes intentionally have an opaque sandbox origin.
      // Audit their wrapper here and their exact artifact as a standalone URL above.
      const builder = new AxeBuilder({ page });
      if (path === "datasets/synthetic-output")
        builder.exclude("iframe").options({ iframes: false });
      const result = await builder
        .withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"])
        .analyze();
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth > innerWidth + 1,
      );
      findings.push({
        width,
        path,
        title: await page.title(),
        overflow,
        violations: result.violations.map((v) => ({
          id: v.id,
          impact: v.impact,
          nodes: v.nodes
            .map((n) => ({ target: n.target, summary: n.failureSummary }))
            .slice(0, 8),
        })),
      });
      console.log(`Audited ${width} ${path || "home"}`);
      if (width === 1440 || width === 390)
        if (
          [
            "",
            "how",
            "cases",
            "batches",
            "about",
            "developer",
    "ontology",
    "ontology/graph",
    "ontology/pipeline",
            "datasets",
            "datasets/synthetic-output",
          ].includes(path)
        )
          await page.screenshot({
            path: `${output}/${(path || "home").replaceAll("/", "-")}-${width}.png`,
            fullPage: true,
          });
    }
  }
  fs.writeFileSync(
    output + "/accessibility.json",
    JSON.stringify({ errors, findings }, null, 2),
  );
  console.log(
    JSON.stringify(
      {
        errors,
        pages: findings.length,
        failures: findings.filter((x) => x.overflow || x.violations.length),
      },
      null,
      2,
    ),
  );
  await browser.close();
  if (errors.length || findings.some((x) => x.overflow || x.violations.length))
    process.exitCode = 1;
})();
