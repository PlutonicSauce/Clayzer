// Run against the read-only offline Report demo. No live model/provider calls.
const assert = require("node:assert/strict");
const { chromium } = require("playwright-core");
const base = process.env.CLAYZER_UI_URL || "http://127.0.0.1:8786";
(async () => {
  const browser = await chromium.launch({
    executablePath: process.env.CLAYZER_CHROMIUM,
    headless: true,
  });
  try {
    const context = await browser.newContext({
      viewport: { width: 1440, height: 950 },
    });
    await context.addInitScript(() => {
      window.speechLog = [];
      Object.defineProperty(window, "SpeechSynthesisUtterance", {
        value: class {
          constructor(text) {
            this.text = text;
          }
        },
      });
      Object.defineProperty(window, "speechSynthesis", {
        value: {
          getVoices: () => [],
          cancel: () => speechLog.push("cancel"),
          pause: () => speechLog.push("pause"),
          resume: () => speechLog.push("resume"),
          speak: (u) => {
            window.spoken = u;
            speechLog.push(u.text);
          },
        },
      });
    });
    const page = await context.newPage();
    const errors = [];
    page.on("pageerror", (e) => errors.push(e.message));
    const ready = () =>
      page.waitForFunction(
        () =>
          document.querySelector("#view h1") &&
          !document.querySelector("#view[aria-busy]"),
      );
    const scene = async (s) => {
      await page.locator(`[data-scene-link="${s}"]`).click();
      await page.waitForFunction(
        (s) => document.querySelector(".journey-frame")?.dataset.scene === s,
        s,
      );
    };
    await page.goto(base);
    await ready();
    await page
      .getByRole("link", { name: "Explore how Clayzer works", exact: false })
      .click();
    await ready();
    await page.waitForSelector(".journey-frame");
    const canonical = await page.evaluate(() =>
      location.hash.split("/").slice(0, 3).join("/"),
    );
    await page
      .locator("#story-image")
      .evaluate((n) => (n.dataset.preserved = "yes"));
    await scene("explore");
    assert.equal(
      await page.locator(":focus").getAttribute("id"),
      "explore-title",
    );
    await scene("describe");
    assert.match(
      await page.locator(".no-caption").textContent(),
      /No evaluated caption/,
    );
    assert.equal(await page.locator(".story-verdicts").count(), 0);
    await page.goBack();
    await page.waitForFunction(
      () =>
        document.querySelector(".journey-frame").dataset.scene === "explore",
    );
    await page.goForward();
    await page.waitForFunction(
      () =>
        document.querySelector(".journey-frame").dataset.scene === "describe",
    );
    assert.equal(
      await page.locator("#story-image").getAttribute("data-preserved"),
      "yes",
    );
    await page.locator(".story-audio > summary").click();
    await page.locator("#story-listen").click();
    assert.match(
      await page.evaluate(() => spoken.text),
      /Describe|description|evaluated caption/,
    );
    assert.doesNotMatch(
      await page.evaluate(() => spoken.text),
      /A clearer view/,
    );
    await page.locator("#story-pause").click();
    assert.equal(await page.locator("#story-pause").textContent(), "Resume");
    await page.locator("#story-pause").click();
    await page.locator("#story-speed").selectOption("1.25");
    assert.equal(await page.evaluate(() => spoken.rate), 1.25);
    await page.evaluate(() => (window.oldStorySpeech = spoken));
    await page.locator(".story-audio > summary").click();
    await scene("verify");
    assert.equal(await page.locator("#listen-stop").isDisabled(), true);
    const speechCount = await page.evaluate(() => speechLog.length);
    await page.evaluate(() => oldStorySpeech.onend());
    assert.equal(await page.evaluate(() => speechLog.length), speechCount);
    await page.locator("[data-story-ref]").first().click();
    assert.ok((await page.locator("#story-ref-cells rect").count()) > 0);
    assert.match(
      await page.locator("#story-ref-status").textContent(),
      /Coarse grid cells/,
    );
    await page
      .getByText("Read the reference areas as text", { exact: true })
      .click();
    assert.match(
      await page.locator("#scene-verify").textContent(),
      /north west/,
    );
    await page.locator("#story-refs").uncheck();
    await scene("understand");
    assert.equal(await page.locator("#story-refs").isChecked(), false);
    await scene("explore");
    await page.locator("#story-expand").click();
    assert.equal(
      await page.locator("#story-image-dialog").evaluate((n) => n.open),
      true,
    );
    await page.keyboard.press("Escape");
    assert.equal(
      await page.locator(":focus").getAttribute("id"),
      "story-expand",
    );
    // Passive scrolling changes the current scene URL without remounting the visual.
    await page.locator("#scene-understand").evaluate((n) => n.scrollIntoView());
    await page.waitForFunction(() => location.hash.endsWith("/understand"));
    await page.goto(base + "/" + canonical + "/verify");
    await ready();
    assert.equal(
      await page.locator(".journey-frame").getAttribute("data-scene"),
      "verify",
    );
    assert.equal(
      await page
        .locator("[aria-current=step]")
        .textContent()
        .then((x) => x.trim()),
      "04 Verify",
    );
    // A recorded synthetic story uses verified bytes and the actual frozen reference/outcome.
    const batches = await (
      await page.request.get(base + "/api/batches")
    ).json();
    const bid = batches.find((b) => /SYNTHETIC/.test(b.batch_id)).batch_id;
    const scripted = `#/journey-run/${bid}/synthetic-building/1`;
    await page.goto(base + "/" + scripted + "/describe");
    await ready();
    assert.match(
      await page.locator("#story-image").getAttribute("src"),
      /^blob:/,
    );
    assert.equal(
      await page.locator("#scene-describe blockquote").textContent(),
      "Two buildings in the north.",
    );
    assert.match(
      await page.locator(".caption-kind").textContent(),
      /NO VISION MODEL INVOKED/,
    );
    await scene("verify");
    assert.match(
      await page.locator(".story-verdicts").textContent(),
      /Supported 1/,
    );
    await scene("understand");
    await page.locator(".story-report-link").click();
    await page.waitForFunction(
      () =>
        location.hash.startsWith("#/runs/") &&
        document.querySelector("#view h1")?.textContent === "Evaluation report",
    );
    await ready();
    assert.match(
      await page.locator("#view h1").textContent(),
      /Evaluation report/,
    );
    await page.goBack();
    await ready();
    assert.equal(
      await page.locator(".journey-frame").getAttribute("data-scene"),
      "understand",
    );
    // Synthetic imagery does not itself imply a scripted caption provider.
    await page.route("**/runs/synthetic-building--r1.json", async (route) => {
      const response = await route.fetch();
      const data = await response.json();
      data.config.caption_model = "test-vision-model";
      await route.fulfill({ json: data });
    });
    await page.goto(base + "/#/about");
    await ready();
    await page.goto(base + "/" + scripted + "/describe");
    await ready();
    await page.locator(".caption-kind").waitFor();
    assert.doesNotMatch(
      await page.locator(".caption-kind").textContent(),
      /SCRIPTED|NO VISION/,
    );
    assert.match(
      await page.locator(".story-topline").textContent(),
      /Synthetic input/,
    );
    await scene("understand");
    await page.locator(".story-report-link").click();
    await page.waitForFunction(
      () =>
        document.querySelector("#view h1")?.textContent === "Evaluation report",
    );
    assert.match(
      await page.locator(".run-story > p.evidence-note").textContent(),
      /Synthetic input/,
    );
    assert.doesNotMatch(
      await page.locator(".run-story > p.evidence-note").textContent(),
      /Scripted demonstration/,
    );
    await page.unrouteAll({ behavior: "wait" });
    // Integrity failure must not attach a recording, image or verdicts to the story.
    await page.route(
      "**/runs/synthetic-building--r1/provenance",
      async (route) => {
        const response = await route.fetch();
        const data = await response.json();
        data.case.chips.forEach((c) => (c.sha256 = "0".repeat(64)));
        data.case.chip_sha256 = "0".repeat(64);
        await route.fulfill({ json: data });
      },
    );
    await page.goto(base + "/#/about");
    await ready();
    await page.goto(base + "/" + scripted + "/verify");
    await ready();
    assert.match(
      await page.locator("[role=alert]").textContent(),
      /bytes differ/,
    );
    assert.equal(await page.locator("#story-image").count(), 0);
    assert.equal(await page.locator(".story-verdicts").count(), 0);
    await page.unrouteAll({ behavior: "wait" });
    await page.goto(base + "/#/cases");
    await ready();
    await page.locator("#image-category").selectOption("Wind");
    const selected = await page
      .locator(".case-card h2 a")
      .first()
      .getAttribute("href");
    await page.locator(".gallery-image").first().click();
    await ready();
    assert.equal(await page.evaluate(() => location.hash), selected);
    await page.locator("#t-grid").waitFor({ state: "visible" });
    assert.equal(await page.locator("#t-grid").isVisible(), true);
    await page.locator("#case-fig img").waitFor();
    await page.goBack();
    await ready();
    assert.equal(await page.locator("#image-category").inputValue(), "Wind");
    assert.ok((await page.locator(".case-card").count()) > 0);
    // A delayed native transition must not overwrite a newer route.
    await page.evaluate(() => {
      document.startViewTransition = (update) => {
        const pending = new Promise((resolve) => {
          window.commitDelayedCase = () =>
            Promise.resolve(update()).then(resolve);
        });
        return { updateCallbackDone: pending, finished: pending };
      };
    });
    await page.locator(".gallery-image").first().click();
    await page.waitForFunction(
      () => typeof window.commitDelayedCase === "function",
    );
    await page.evaluate(() => (location.hash = "#/developer"));
    await page.waitForFunction(
      () =>
        document.querySelector("#view h1")?.textContent === "Developer tools",
    );
    await page.evaluate(() => commitDelayedCase());
    assert.equal(
      await page.locator("#view h1").textContent(),
      "Developer tools",
    );
    assert.equal(await page.locator("#t-grid").count(), 0);
    assert.deepEqual(errors, []);
    await context.close();
    // OS reduced motion is authoritative and keeps the complete story and controls.
    const reduced = await browser.newContext({
      viewport: { width: 390, height: 844 },
      reducedMotion: "reduce",
    });
    const mobile = await reduced.newPage();
    await mobile.goto(base + "/" + canonical + "/verify");
    await mobile.waitForSelector(".journey-frame");
    assert.equal(await mobile.locator(".journey-scene").count(), 5);
    assert.equal(await mobile.locator(".story-motion").isDisabled(), true);
    assert.equal(
      await mobile
        .locator("#story-image")
        .evaluate((n) => getComputedStyle(n.parentElement).transitionDuration),
      "0s",
    );
    assert.equal(
      await mobile.evaluate(
        () => document.documentElement.scrollWidth > innerWidth,
      ),
      false,
    );
    await reduced.close();
    console.log(
      "Guided journey passed: five scenes, persistent image, deep links, Back/Forward, passive scroll, scene focus, overlay/dialog keys, narration lifecycle, recorded synthetic report, SHA256 rejection, gallery return and reduced motion.",
    );
  } finally {
    await browser.close();
  }
})().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
