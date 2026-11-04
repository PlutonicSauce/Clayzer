// Development-only integration checks; the recorded audio metadata below is a test double.
const assert = require("node:assert/strict");
const { chromium } = require("playwright-core");
const base = process.env.CLAYZER_UI_URL || "http://127.0.0.1:8788";
(async () => {
  const browser = await chromium.launch({
    headless: true,
    executablePath: process.env.CLAYZER_CHROMIUM,
  });
  try {
    const context = await browser.newContext({
      viewport: { width: 390, height: 844 },
      reducedMotion: "reduce",
    });
    const page = await context.newPage();
    const errors = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await page.goto(base + "/#/ontology");
    await page.locator(".onto-wz-dot[aria-current=step]").waitFor();
    assert.equal(await page.locator(".onto-wz-steps[role=tablist]").count(), 0);
    assert.equal(
      await page
        .locator(".hero h1")
        .evaluate((el) => getComputedStyle(el).color),
      "rgb(255, 253, 251)",
    );
    const keys = ["what", "build", "graph", "measure", "use"];
    for (let i = 0; i < keys.length; i++) {
      const step = page.locator(`.onto-wz-dot[data-i='${i}']`);
      await step.focus();
      await page.keyboard.press("Enter");
      assert.equal(await step.getAttribute("aria-current"), "step");
      assert.equal(new URL(page.url()).hash, "#/ontology/" + keys[i]);
      assert.equal(
        await page.locator(".onto-wz-dot[aria-current=step]").count(),
        1,
      );
      if (keys[i] === "graph") {
        const node = page.locator(".onto-node").first();
        await node.focus();
        await page.keyboard.press("Enter");
        await page.locator("#onto-node-detail h3").waitFor();
      }
    }
    await page.locator('[data-mode="off"]').click();
    assert.match(
      await page.locator('[data-mode="off"]').getAttribute("class"),
      /active/,
    );
    const batches = await (
      await page.request.get(base + "/api/batches")
    ).json();
    const bid = batches.find((b) => b.batch_id.includes("SYNTHETIC")).batch_id;
    await page.route(`**/api/batches/${bid}/listen`, (route) =>
      route.fulfill({
        json: {
          source: "code",
          model: null,
          voice: "Emma",
          created: "test recording",
          baseline_id: null,
          text: "This is a test transcript for the saved audio interface.",
        },
      }),
    );
    await page.goto(base + "/#/batches/" + bid);
    const audio = page.getByLabel("Recorded Batch summary");
    await audio.waitFor();
    assert.equal(
      await audio.getAttribute("src"),
      `/api/batches/${bid}/listen.mp3`,
    );
    assert.equal(await audio.getAttribute("preload"), "none");
    await page.getByText("Transcript", { exact: true }).click();
    assert.match(await page.locator("#view").innerText(), /test transcript/);
    assert.equal(await audio.evaluate((a) => a.paused), true);
    await page.goto(base + "/#/overview");
    await page.locator(".hero h1").waitFor();
    assert.equal(
      await page
        .locator(".hero h1")
        .evaluate((el) => getComputedStyle(el).color),
      "rgb(255, 253, 251)",
    );
    await page.goto(base + "/deck");
    await page.locator("#deck h1, #deck h2").first().waitFor();
    await page.waitForFunction(() => location.hash === "#1");
    await page.keyboard.press("ArrowRight");
    await page.waitForFunction(() => location.hash === "#2");
    await page.keyboard.press("ArrowLeft");
    await page.waitForFunction(() => location.hash === "#1");
    assert.deepEqual(errors, []);
    console.log(
      "Upstream compatibility passed: keyboard Ontology walkthrough/graph, saved-audio controls/transcript (mock metadata; no audio generation), and unchanged Pitch Deck navigation.",
    );
  } finally {
    await browser.close();
  }
})().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
