// Development-only browser tools; run against an isolated read-only demo.
const assert = require("node:assert/strict");
const { chromium } = require("playwright-core");
const base = process.env.CLAYZER_UI_URL || "http://127.0.0.1:8786";
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
    await context.addInitScript(() => {
      window.audioLog = [];
      Object.defineProperty(window, "SpeechSynthesisUtterance", {
        value: class {
          constructor(text) {
            this.text = text;
          }
        },
      });
      Object.defineProperty(window, "speechSynthesis", {
        value: {
          cancel() {
            audioLog.push("cancel");
          },
          pause() {
            audioLog.push("pause");
          },
          resume() {
            audioLog.push("resume");
          },
          getVoices() {
            return [];
          },
          speak(u) {
            audioLog.push({ text: u.text, rate: u.rate });
            window.lastSpeech = u;
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
    await page.goto(base);
    await ready();
    assert.equal(
      (await page.request.get(base + "/api/config").then((r) => r.json()))
        .allow_launch,
      false,
    );
    assert.equal(
      await page.evaluate(
        () => audioLog.filter((x) => typeof x === "object").length,
      ),
      0,
    );
    await page.keyboard.press("Tab");
    assert.equal(await page.locator(":focus").textContent(), "Skip to content");
    await page.keyboard.press("Enter");
    assert.equal(await page.locator(":focus").getAttribute("id"), "view");
    await page.locator("#nav-toggle").focus();
    await page.keyboard.press("Enter");
    assert.equal(
      await page.locator("#nav-toggle").getAttribute("aria-expanded"),
      "true",
    );
    await page.keyboard.press("Escape");
    assert.equal(
      await page.locator("#nav-toggle").getAttribute("aria-expanded"),
      "false",
    );
    await page.locator(".listen-panel>summary").click();
    await page.locator("#listen-play").click();
    assert.equal(
      await page.evaluate(
        () => audioLog.filter((x) => typeof x === "object").length,
      ),
      1,
    );
    assert.equal(
      await page.evaluate(() => lastSpeech.text.length <= 220),
      true,
    );
    await page.locator("#listen-pause").click();
    assert.equal(await page.locator("#listen-pause").textContent(), "Resume");
    await page.locator("#listen-pause").click();
    assert.equal(await page.evaluate(() => audioLog.includes("resume")), true);
    await page.locator("#listen-speed").selectOption("1.5");
    assert.equal(await page.evaluate(() => lastSpeech.rate), 1.5);
    await page.evaluate(() => {
      window.obsoleteSpeech = lastSpeech;
      location.hash = "#/cases";
    });
    await ready();
    await page.evaluate(() => obsoleteSpeech.onend());
    assert.equal(await page.locator("#listen-stop").isDisabled(), true);
    assert.equal(await page.locator(":focus").getAttribute("id"), "view");
    await page.locator("#image-category").selectOption("Wind");
    assert.ok((await page.locator(".case-card").count()) > 0);
    await page.locator("#image-search").fill("no-such-reference-987");
    assert.equal(await page.locator(".case-card").count(), 0);
    await page.locator("#image-search").fill("");
    await page.locator(".case-card h2 a").first().click();
    await ready();
    assert.equal(await page.locator("#t-grid").isChecked(), false);
    await page.locator("#case-zoom").focus();
    await page.keyboard.press("g");
    assert.equal(await page.locator("#t-grid").isChecked(), true);
    await page.evaluate(() => (location.hash = "#/how"));
    await ready();
    await page.locator('[data-method="1"]').focus();
    await page.keyboard.press("Enter");
    assert.equal(
      await page.locator('[data-method="1"]').getAttribute("aria-pressed"),
      "true",
    );
    assert.match(
      await page.locator("#method-detail").textContent(),
      /no caption attached/,
    );
    await page.locator('[data-method="2"]').click();
    assert.match(
      await page.locator("#method-detail").textContent(),
      /References are not claim outcomes/,
    );
    const examples = await (await page.request.get(base + "/api/cases")).json();
    const change = examples.find((c) => c.kind === "change");
    await page.evaluate(
      (id) => (location.hash = "#/cases/" + encodeURIComponent(id)),
      change.id,
    );
    await ready();
    await page.locator("#compare-position").focus();
    await page.keyboard.press("ArrowRight");
    assert.equal(await page.locator("#compare-position").inputValue(), "51");
    assert.equal(
      await page.locator("#compare-position").getAttribute("aria-valuetext"),
      "51 percent later image",
    );
    assert.equal(await page.locator("#t-grid").isChecked(), true);
    await page.evaluate(() => (location.hash = "#/datasets/synthetic-output"));
    await ready();
    assert.match(
      await page.locator(".dataset-ledger").textContent(),
      /2 captions/,
    );
    assert.match(
      await page.locator(".dataset-ledger").textContent(),
      /grounding-5/,
    );
    await page.locator("#listen-play").click();
    await page.evaluate(() => lastSpeech.onend());
    assert.equal(
      await page.locator("#listen-progress").getAttribute("value"),
      "1",
    );
    await page.locator("#listen-stop").click();
    assert.equal(
      await page.locator(".listen-panel").getAttribute("data-state"),
      "idle",
    );
    await page.evaluate(() => (location.hash = "#/%ZZ"));
    await ready();
    assert.equal(
      await page.locator("#view h1").textContent(),
      "Page not found",
    );
    await page.route("**/api/cases", (r) =>
      r.fulfill({
        status: 500,
        contentType: "application/json",
        body: JSON.stringify({
          detail: "<img src=x onerror=alert(1)> offline",
        }),
      }),
    );
    await page.evaluate(() => (location.hash = "#/cases"));
    await ready();
    assert.equal(await page.locator("#view img").count(), 0);
    assert.match(
      await page.locator("#view [role=alert]").textContent(),
      /<img/,
    );
    await page.evaluate(() => {
      document.getElementById("view").innerHTML = runStory({
        status: "ok",
        case_id: "test",
        chip: { id: "test", source: "synthetic" },
        scores: {
          grounding: {},
          retrieval: {
            query_count: '<img src=x onerror="window.unsafe=1">',
            corpus_size: "2",
          },
        },
      });
    });
    assert.equal(await page.locator("#view img[onerror]").count(), 0);
    assert.match(await page.locator("#view").textContent(), /<img src=x/);
    assert.deepEqual(errors, []);
    const unsupported = await browser.newContext();
    await unsupported.addInitScript(() =>
      Object.defineProperty(window, "speechSynthesis", { value: undefined }),
    );
    const other = await unsupported.newPage();
    await other.goto(base);
    await other.locator(".listen-panel>summary").click();
    assert.equal(await other.locator("#listen-play").isDisabled(), true);
    assert.match(
      await other.locator("#listen-status").textContent(),
      /unavailable/,
    );
    console.log(
      "Public UI smoke passed: keyboard, focus, filters, viewer, malformed routes, safe errors, speech controls/cancellation and unsupported speech.",
    );
  } finally {
    await browser.close();
  }
})().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
