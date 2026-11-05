// Offline browser regression for voice discovery, selection and playback.
const assert = require("node:assert/strict");
const { chromium } = require("playwright-core");
(async () => {
  const browser = await chromium.launch({
    executablePath: process.env.CLAYZER_CHROMIUM,
    headless: true,
  });
  try {
    const context = await browser.newContext({
      viewport: { width: 390, height: 844 },
      reducedMotion: "reduce",
    });
    await context.addInitScript(() => {
      window.availableVoices = [];
      window.voiceListeners = {};
      window.spoken = [];
      window.SpeechSynthesisUtterance = class {
        constructor(text) {
          this.text = text;
        }
      };
      Object.defineProperty(window, "speechSynthesis", {
        value: {
          getVoices: () => availableVoices,
          addEventListener: (event, callback) => {
            voiceListeners[event] = callback;
          },
          speak: (utterance) => spoken.push(utterance),
          cancel: () => {},
          pause: () => {},
          resume: () => {},
        },
      });
    });
    const page = await context.newPage();
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.goto(process.env.CLAYZER_UI_URL || "http://127.0.0.1:8793");
    await page.waitForSelector("#view h1");
    await page.locator(".listen-panel > summary").click();
    assert.equal(await page.locator("#listen-voice").inputValue(), "");
    await page.evaluate(() => {
      availableVoices.push(
        { voiceURI: "us", name: "US voice", lang: "en-US", localService: true },
        {
          voiceURI: "uk-basic",
          name: "British voice",
          lang: "en-GB",
          localService: true,
        },
        {
          voiceURI: "uk-premium",
          name: "British Premium",
          lang: "en-GB",
          localService: true,
        },
        {
          voiceURI: "uk-cloud",
          name: "British service",
          lang: "en-GB",
          localService: false,
        },
      );
      voiceListeners.voiceschanged();
    });
    assert.equal(
      await page.locator("#listen-voice").inputValue(),
      "uk-premium",
    );
    await page.locator("#listen-play").click();
    assert.deepEqual(
      await page.evaluate(() => [
        spoken.at(-1).voice.voiceURI,
        spoken.at(-1).lang,
      ]),
      ["uk-premium", "en-GB"],
    );
    await page.locator("#listen-pause").click();
    await page.locator("#listen-voice").selectOption("us");
    assert.deepEqual(
      await page.evaluate(() => [
        spoken.at(-1).voice.voiceURI,
        spoken.at(-1).lang,
      ]),
      ["us", "en-US"],
    );
    assert.equal(await page.locator("#listen-pause").textContent(), "Resume");
    await page.evaluate(() => voiceListeners.voiceschanged());
    assert.equal(await page.locator("#listen-voice").inputValue(), "us");
    assert.match(
      await page
        .locator('#listen-voice option[value="uk-cloud"]')
        .textContent(),
      /browser service/,
    );
    await page.locator("#listen-stop").click();
    assert.equal(await page.locator("#listen-stop").isDisabled(), true);
    await page
      .getByRole("link", { name: "Follow one image, start to finish", exact: false })
      .click();
    await page.waitForSelector(".journey-frame");
    await page.locator(".story-audio > summary").click();
    assert.equal(await page.locator("#story-voice").inputValue(), "us");
    await page.locator("#story-voice").selectOption("uk-basic");
    assert.equal(await page.locator("#listen-voice").inputValue(), "uk-basic");
    await page.locator("#story-listen").click();
    assert.equal(
      await page.evaluate(() => spoken.at(-1).voice.voiceURI),
      "uk-basic",
    );
    assert.deepEqual(errors, []);
    console.log(
      "Voice regression passed: async discovery, British preference, choice, locale, pause and stop.",
    );
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
