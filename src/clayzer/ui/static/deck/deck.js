// The deck shell: a fixed 1600 × 900 stage scaled to the window, one slide at a time, with the
// slide number in the URL (#3) so a reload or a shared link lands on the same slide.
//
//   → / Space / PageDown   next build, then next slide     ← / PageUp   back a build, then a slide
//   Home / End             first / last  N            presenter notes and timer
//   T                      start or reset the timer    A   read this slide aloud (stop with A)
//
// Accessibility: each slide carries a plain-language `spoken` script in slides.js. Pressing A (or
// the speaker button) reads it with the browser's own speech synthesis — no network, no install —
// so a non-technical listener, or someone who finds dense slides hard to read, can hear the point.
// Motion is dropped for anyone who asks for reduced motion (CSS).
//
// Builds: a slide with `steps: n` in slides.js gets a `step` prop (0..n) and reveals its points
// one press at a time, so they arrive as the presenter says them. Going back into a slide shows it
// complete.
//
// Sections: a slide with a `section` shows the deck's sections across the top, its own
// highlighted; clicking one jumps to that section's first slide.
//
// Slides, their time budgets, their notes, and their spoken scripts live in slides.js.

import { render } from "preact";
import { useEffect, useState } from "preact/hooks";
import { html } from "./html.js";
import { SECTIONS, SLIDES } from "./slides.js";

const canSpeak = typeof speechSynthesis !== "undefined";

function speak(text) {
  if (!canSpeak) return;
  speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(text);
  u.rate = 1.0;
  speechSynthesis.speak(u);
}

function stopSpeaking() {
  if (canSpeak) speechSynthesis.cancel();
}

const W = 1600, H = 900;
const TOTAL = SLIDES.reduce((sum, s) => sum + s.seconds, 0);

const fromHash = () => {
  const n = parseInt(location.hash.slice(1), 10);
  return Number.isFinite(n) ? Math.min(Math.max(n - 1, 0), SLIDES.length - 1) : 0;
};

// "#2.3" opens slide 2 at build 3, for rehearsing a slide part way through.
const stepFromHash = () => parseInt(location.hash.split(".")[1], 10) || 0;

const clock = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

function useScale() {
  const fit = () => Math.min(innerWidth / W, innerHeight / H);
  const [scale, setScale] = useState(fit());
  useEffect(() => {
    const onResize = () => setScale(fit());
    addEventListener("resize", onResize);
    return () => removeEventListener("resize", onResize);
  }, []);
  return scale;
}

function useTimer() {
  const [start, setStart] = useState(null);
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    if (start === null) return;
    const id = setInterval(() => setNow(Date.now()), 250);
    return () => clearInterval(id);
  }, [start]);
  const elapsed = start === null ? 0 : (now - start) / 1000;
  const toggle = () => setStart((s) => (s === null ? Date.now() : null));
  return [elapsed, start !== null, toggle];
}

function Notes({ i, elapsed, running }) {
  const slide = SLIDES[i];
  const due = SLIDES.slice(0, i + 1).reduce((sum, s) => sum + s.seconds, 0);
  const late = running && elapsed > due;
  return html`<aside class="notes" aria-label="Presenter notes">
    <div class="notes-head">
      <span>Slide ${i + 1} of ${SLIDES.length} · ${clock(slide.seconds)} budget</span>
      <span class=${late ? "late" : ""}>
        ${running ? `${clock(elapsed)} elapsed · this slide ends by ${clock(due)}` : "T starts the timer"}
      </span>
      <span>${clock(TOTAL)} total</span>
    </div>
    <ul>${slide.notes.map((n) => html`<li>${n}</li>`)}</ul>
  </aside>`;
}

function Sections({ current, onGo }) {
  const at = SECTIONS.indexOf(current);
  return html`<nav class="sections" aria-label="Sections">
    ${SECTIONS.map((name, k) => html`<button type="button"
        class=${k === at ? "current" : k < at ? "done" : ""}
        aria-current=${k === at ? "step" : undefined}
        onClick=${(e) => { e.stopPropagation(); onGo(SLIDES.findIndex((s) => s.section === name)); }}>
      <span class="n">${k + 1}</span>${name}</button>`)}
  </nav>`;
}

function Deck() {
  const [i, setI] = useState(fromHash());
  const [step, setStep] = useState(stepFromHash());
  const [notes, setNotes] = useState(false);
  const [elapsed, running, toggleTimer] = useTimer();
  const scale = useScale();

  const go = (n, atEnd = false) => {
    stopSpeaking(); // moving on cancels any narration from the slide we're leaving
    const j = Math.min(Math.max(n, 0), SLIDES.length - 1);
    setI(j);
    setStep(atEnd ? SLIDES[j].steps || 0 : 0);
  };
  const next = () => (step < (SLIDES[i].steps || 0) ? setStep(step + 1) : go(i + 1));
  const prev = () => (step > 0 ? setStep(step - 1) : go(i - 1, true));

  const readAloud = () => {
    const s = SLIDES[i];
    speak(s.spoken || s.notes.join(". "));
  };

  useEffect(() => {
    history.replaceState(null, "", `#${i + 1}`);
    document.title = `Clayzer · ${SLIDES[i].title}`;
    return stopSpeaking; // never let speech outlive the slide
  }, [i]);

  useEffect(() => {
    const onHash = () => { setI(fromHash()); setStep(stepFromHash()); };
    const onKey = (e) => {
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const k = e.key;
      if (k === "ArrowRight" || k === " " || k === "PageDown") next();
      else if (k === "ArrowLeft" || k === "PageUp") prev();
      else if (k === "Home") go(0);
      else if (k === "End") go(SLIDES.length - 1);
      else if (k === "n" || k === "N") setNotes((v) => !v);
      else if (k === "t" || k === "T") toggleTimer();
      else if (k === "a" || k === "A") {
        if (canSpeak && speechSynthesis.speaking) stopSpeaking();
        else readAloud();
      } else return;
      e.preventDefault();
    };
    addEventListener("hashchange", onHash);
    addEventListener("keydown", onKey);
    return () => {
      removeEventListener("hashchange", onHash);
      removeEventListener("keydown", onKey);
    };
  }, [i, step]);

  const Slide = SLIDES[i].component;
  return html`
    <div class="viewport" onClick=${(e) => e.target.closest("a, button") || (e.clientX < innerWidth / 3 ? prev() : next())}>
      <div class="stage" style=${{ width: `${W}px`, height: `${H}px`, transform: `translate(-50%, -50%) scale(${scale})` }}>
        <section class=${`slide ${SLIDES[i].theme || ""}`} aria-roledescription="slide"
          aria-label=${`${i + 1} of ${SLIDES.length}: ${SLIDES[i].title}`}>
          <${Slide} step=${step} />
        </section>
        ${SLIDES[i].section && html`<${Sections} current=${SLIDES[i].section} onGo=${go} />`}
        <div class="progress" style=${{ width: `${((i + 1) / SLIDES.length) * 100}%` }}></div>
        <div class="pageno">${i + 1} / ${SLIDES.length}</div>
        ${canSpeak && html`<button class="speak" title="Read this slide aloud (A)"
          aria-label="Read this slide aloud"
          onClick=${(e) => { e.stopPropagation(); speechSynthesis.speaking ? stopSpeaking() : readAloud(); }}>
          ${"\u25BA"} Listen</button>`}
      </div>
    </div>
    ${notes && html`<${Notes} i=${i} elapsed=${elapsed} running=${running} />`}`;
}

render(html`<${Deck} />`, document.getElementById("deck"));
