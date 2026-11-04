// Optional browser-native audio. Never starts without an intentional control activation.
(() => {
  const synth = window.speechSynthesis;
  const status = document.getElementById("listen-status");
  const play = document.getElementById("listen-play");
  const pause = document.getElementById("listen-pause");
  const stop = document.getElementById("listen-stop");
  const speed = document.getElementById("listen-speed");
  let generation = 0,
    chunks = [],
    index = 0,
    active = false,
    paused = false;
  const update = (message) => {
    status.textContent = message;
    document.querySelector(".listen-panel").dataset.state = active
      ? paused
        ? "paused"
        : "playing"
      : "idle";
    const progress = document.getElementById("listen-progress");
    progress.max = Math.max(chunks.length, 1);
    progress.value = index;
    play.textContent = active ? "Restart summary" : "Play summary";
    pause.disabled = !active;
    stop.disabled = !active;
    pause.textContent = paused ? "Resume" : "Pause";
  };
  const cancel = (options = {}) => {
    if (options.silentIfIdle && !active) return;
    generation++;
    active = false;
    paused = false;
    index = 0;
    chunks = [];
    synth?.cancel();
    update(
      synth
        ? "Stopped. The page text remains available below."
        : "Audio reading is unavailable in this browser. Read the page text below.",
    );
  };
  window.cancelPageSpeech = cancel;
  if (!synth || !window.SpeechSynthesisUtterance) {
    play.disabled = true;
    speed.disabled = true;
    update(
      "Audio reading is unavailable in this browser. Read the page text below.",
    );
    return;
  }
  const speak = (token) => {
    if (token !== generation || !active) return;
    if (index >= chunks.length) {
      active = false;
      update("Finished reading.");
      return;
    }
    const utterance = new SpeechSynthesisUtterance(chunks[index]);
    utterance.lang = document.documentElement.lang || "en";
    utterance.rate = Number(speed.value);
    const voice = synth
      .getVoices()
      .find((v) => v.lang.startsWith("en") && v.localService);
    if (voice) utterance.voice = voice;
    utterance.onend = () => {
      if (token === generation) {
        index++;
        update(
          `Reading section ${Math.min(index + 1, chunks.length)} of ${chunks.length}.`,
        );
        speak(token);
      }
    };
    utterance.onerror = () => {
      if (token === generation) {
        cancel();
        update(
          "Audio stopped. Your browser may not have an available voice; the page text remains available.",
        );
      }
    };
    // Keep an explicit reference while native callbacks are pending (Safari/Chromium).
    window.clayzerUtterance = utterance;
    synth.speak(utterance);
  };
  play.addEventListener("click", () => {
    cancel();
    const regions = [
      ...document.querySelectorAll("#view [data-listen]"),
    ].filter((n) => !n.closest("[data-listen-skip]"));
    const text = (
      regions.length
        ? regions.map((n) => n.innerText).join(". ")
        : `${document.querySelector("#view h1")?.textContent || "Clayzer"}. ${document.querySelector("#view p")?.textContent || "Inspect the visible report for detailed evidence."}`
    )
      .replace(/\s+/g, " ")
      .trim();
    chunks = text.match(/.{1,220}(?:\s|$)|.{1,220}/g) || [];
    index = 0;
    active = chunks.length > 0;
    paused = false;
    update(
      active
        ? "Reading the page summary."
        : "No page summary is available yet.",
    );
    speak(generation);
  });
  pause.addEventListener("click", () => {
    if (!active) return;
    paused = !paused;
    if (paused) synth.pause();
    else synth.resume();
    update(paused ? "Paused." : "Reading the page summary.");
  });
  stop.addEventListener("click", cancel);
  speed.addEventListener("change", () => {
    if (active) {
      const wasPaused = paused;
      generation++;
      synth.cancel();
      paused = false;
      update("Reading at the selected speed.");
      speak(generation);
      if (wasPaused) {
        synth.pause();
        paused = true;
        update("Paused at the selected speed.");
      }
    }
  });
  window.addEventListener("hashchange", cancel);
  window.addEventListener("pagehide", cancel);
  update("Ready. Listen reads a curated summary, not code or raw data.");
})();
