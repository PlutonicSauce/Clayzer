# Clayzer public experience: local review handoff

The working frontend is in `/Users/seshank/Desktop/Clayzer-public-redesign`, branch
`feat/accessible-public-redesign-with-reports`, based on `f9450f5`. It is uncommitted and stacked
on the Step 6/7 contribution. No commits, pushes, merges, deployments, AWS changes or paid model
calls were made for this UI work. Refresh an already-open preview tab to load the new scripts.

## Review the experience

- Home: http://localhost:8786/#/
- Five-scene story: http://localhost:8786/#/journey
- Image-led method: http://localhost:8786/#/how
- Explore imagery: http://localhost:8786/#/cases
- Results and original reports: http://localhost:8786/#/batches
- Dataset cards: http://localhost:8786/#/datasets

**Discover → Explore → Describe → Verify → Understand** is one continuous document with one
persistent input image. Ordinary scrolling updates the current scene; deliberate scene links
create normal history entries. Direct scene URLs, browser Back/Forward and keyboard navigation
preserve the image instead of recreating five pages. There is no scroll interception, forced
loading screen or text waiting to be revealed. Motion is progressive enhancement; device-level
reduced motion and the optional Reduce motion control preserve the entire story.

The grid explains position. Reference overlays show coarse named areas, not detections or
segmentation. Choose a reference entry, toggle areas, read the complete spatial text alternative,
or expand the uncropped image in a native dialog. Scene-local audio mirrors the existing native
play/pause/resume/stop/speed controls; narration stops on scene changes and route exit and never
starts automatically. Only the active scene contributes to guided narration.

Gallery filters and return position persist in memory. Supported browsers can carry the chosen
image into a Case using a short native view transition; other browsers and reduced-motion users
navigate immediately. A delayed transition cannot overwrite a newer route. Cases and Run reports
have contextual guided-story links. Results, datasets and developer collections use editorial
indexes instead of uniform rounded-card grids. Existing technical views remain available.

## Evidence and compatibility

The offline store contains 64 genuine development reference Cases but **zero evaluated model
captions for those real images**. The story states when no evaluated caption is attached. Its
record discovery checks the first repeat of up to eight recent complete Batches, not the entire
store. It never invents a caption, outcome, denominator or score.

A separate saved synthetic recording demonstrates actual recorded claim outcomes on its own
Pillow fixture. Before pairing any recording with an image, the frontend checks the served bytes'
SHA256 against stored provenance. It displays those exact verified bytes through a temporary
object URL, then revokes it on exit. Frozen references and recorded outcomes stay together.
Missing hashes, incompatible single-image inputs and mismatches refuse the pairing and offer the
full report. Old recordings remain accessible even when they cannot support a verified story.
Correctness and coverage remain separate recorded measurements. The browser does not rescore them.

A Change Case story uses its later image and links to the existing two-date Case inspection and
keyboard comparison slider. Reference overlays stay on the later-image viewer. Image source/date,
OpenStreetMap attribution and evidence limitations remain visible. Input chips are 512×512;
cinematic framing does not create additional imagery or resolution.

All existing routes, JSON APIs, scoring definitions, offline replay, trace/provenance links,
accepted Baselines, Case/Texas fixtures, dependencies and infrastructure are preserved. The former
team overview remains at `#/overview`. Stored historical reports are not rewritten; the existing
fixed presentation overlay keeps older report HTML readable without changing stored scores/JSON.
Read-only remains the default. No held-out Texas tuning or model evaluation was performed.

## File inventory

| File                                                                                   | Purpose                                                                                                                                                                               |
| -------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `src/clayzer/ui/static/index.html`                                                     | Semantic shell, navigation, audio, new journey asset loading, attribution                                                                                                             |
| `src/clayzer/ui/static/public.css`                                                     | Cream/forest foundations, local typography, responsive views and accessible technical presentation                                                                                    |
| `src/clayzer/ui/static/public.js`                                                      | Home/How/About/Developer, searchable gallery, evidence-first Run summary, retained gallery state                                                                                      |
| `src/clayzer/ui/static/journey.js`                                                     | Five-scene story, byte verification, frozen references, overlays/text alternatives, dialog, narration bridge, scene history and progressive Case transition                           |
| `src/clayzer/ui/static/journey.css`                                                    | Persistent-image composition, editorial collection treatments, responsive and reduced-motion behavior                                                                                 |
| `src/clayzer/ui/static/listen.js`                                                      | Intentional native speech, bounded chunks/progress, pause/resume/stop/speed and scene/route cancellation                                                                              |
| `src/clayzer/ui/static/app.js`                                                         | Preserve routing; integrate story, focused viewer keys, Case transitions, contextual links, dataset ledger and error/focus handling                                                   |
| `src/clayzer/ui/static/manrope-regular.ttf`, `manrope-semibold.ttf`, `Manrope-OFL.txt` | Locally hosted Manrope and its SIL Open Font License; no runtime font CDN                                                                                                             |
| `src/clayzer/report_html.py`                                                           | Existing UI-branch accessible presentation for newly generated reports; scoring definitions unchanged                                                                                 |
| `src/clayzer/run_report.py`                                                            | Existing UI-branch contrast correction for evaluation-step text                                                                                                                       |
| `src/clayzer/ui/app.py`                                                                | Existing fixed presentation overlay for old HTML; endpoint/security contracts preserved                                                                                               |
| `tests/test_ui.py`                                                                     | Existing regression proving presentation preserves stored HTML and Run JSON                                                                                                           |
| `tests/ui_public_smoke.cjs`                                                            | Original keyboard/menu/filter/viewer/error escaping/native-speech regressions                                                                                                         |
| `tests/ui_journey.cjs`                                                                 | Story continuity, deep links/history, focus/dialog/overlays/text, audio, verified and mismatched bytes, report navigation, gallery return, delayed-navigation race and reduced motion |
| `tests/ui_upstream_compatibility.cjs` | Preserved Ontology, saved-audio interface and Pitch Deck integration regressions |
| `tests/ui_public_accessibility.cjs`                                                    | 132 axe/overflow checks at four widths; unexpected loading failures cannot pass as valid pages                                                                                        |
| `docs/ui/CINEMATIC_JOURNEY.md`                                                         | Experience audit, five-scene interaction/evidence design and acceptance criteria                                                                                                      |
| `docs/ui/PUBLIC_REDESIGN.md`                                                           | This current handoff                                                                                                                                                                  |

Final publication scope remains 20 files. This follow-up targets **main directly**, with
`feat/public-redesign-main` refreshed through `0ecb386` (including corrected absence references, the reaccepted Baseline,
Transaction Search infrastructure and updated Pitch Deck). PR #82 merged into main,
but PR #94 merged into its feature branch; #94's frontend therefore did not reach production.
This PR transfers that reviewed UI without duplicating scoring or teammate contributions.
Merging main can trigger an automatic AWS deployment; no merge/deployment is part of this handoff.

Upstream Ontology navigation/API, all five walkthrough steps, recorded Batch audio and the
Pitch Deck route remain. Integration fixes use native list/button semantics with the current
step announced, an explicit previous-step label, a saved-audio label, light banner headings, and readable unavailable
experiment metadata. The Ontology and audio content remain the teammate's work. The updated Mermaid view retains
its relation overlay and gains keyboard activation and native class buttons for offline access.
Self-grading warnings from AgentCore remain visible in public Results as well as technical reports.
The latest gallery conflict preserves the public design while showing reference entries in a
native disclosure: verified zero counts say “No … (checked: source)”; zero counts without verified
absence say “Reference count: 0 … (absence unverified)”. Neither creates an object marker or
changes the scoring definitions. Browser regressions cover both cases.
The latest teammate Pitch Deck remains byte-identical to main. Its public navigation link and
four-minute-pitch homepage CTA are retained alongside the existing imagery and story actions;
its new nine-slide content and media are not part of the frontend contribution. All Pitch
Deck files are byte-identical to current main; ongoing presentation edits must be refreshed
before merge. No Case fixture, historical baseline, scorer, dependency, CI or infrastructure
change belongs to the UI diff.

## Verification and actual artifacts

Final integrated full suite: **719 passed, 1 skipped**, **85.60% coverage**, 40 upstream
Shapely warnings, zero failures. The optional AgentCore telemetry module is skipped without the
OpenTelemetry dependency in this local environment. Current CI infrastructure scope: **34 passed**,
including CDK tests also present in the full suite. Counts are not added as unique tests.
Ruff lint/format over the CI scope (`src tests`, 131 files), Vulture, 18 JavaScript syntax checks,
nine-slide deck smoke, duplication (0.30% lines against the unchanged 3% gate) and Git whitespace
checks pass. The broader upstream scripts lint has an existing EXE001 executable-bit issue in
`upload_to_s3.py`; it is outside CI's lint scope and was not changed in this frontend work.

All four browser suites pass: public smoke, five-scene journey, upstream compatibility, and
**132 axe/overflow checks at 1440, 768, 390 and 320 pixels**. Zero reported WCAG-rule violations,
horizontal page overflows or runtime errors in the final audit. After visual banner corrections,
24 additional affected-route/viewport audits and the banner-style regression also pass. Initial integration findings
(Ontology list semantics, overview status contrast and the new relation legend contrast) were corrected and the full audit rerun.
The opaque script-free dataset iframe and exact standalone card artifact are audited separately;
the security sandbox is preserved. Upstream compatibility tests keyboard use of every Ontology
step and the new Mermaid graph, including a native text alternative when the CDN is unavailable, saved-audio controls/transcript using explicitly mocked metadata, and the unchanged
Pitch Deck's forward/back navigation. Audio generation and real MP3 playback are not claimed by
that test. Native speech lifecycle, cancellation and reduced motion are covered in browser tests.

The complete offline Report demo passes: six scripted Runs, imported dataset card, replay and
**74 real development Cases as reference-only imagery**. No real-image model captions evaluated,
no held-out Texas tuning, no paid calls. The newly accepted upstream grounding-5 Baseline and historical
measurements are unchanged; the UI reads recorded scoring provenance rather than rescoring.

Current validation logs, screenshots, accessibility trees/JSON, source hashes and complete UI
patch/archive live outside the repository under
`/Users/seshank/Desktop/Clayzer-public-redesign-review/pr96-9cd971e/`.
The original worktrees and earlier hash-verified backups remain intact. Prior cinematic captures,
a silent browser tour and local timing observations are retained under `cinematic/`; those
performance observations are not production benchmarks. No generated review outputs are in the PR.

Human VoiceOver/NVDA use, audible speech quality and mobile Safari/Firefox remain unverified.
Automated axe checks and accessibility-tree inspection do not certify full WCAG 2.2 AA conformance.
Figma remains unsynced because of the previously documented Starter-plan limit; no retry performed.

## Run safely

```sh
uv run python scripts/report_demo.py --output /tmp/clayzer-cinematic-demo-new
uv run clayzer ui --local-root /tmp/clayzer-cinematic-demo-new/replayed --port 8786
```

Use a new output directory and a free port. Do not enable `--allow-launch` for review. For the
normal configured installation, `uv run clayzer ui` is unchanged. Development-only browser tools
can live outside the application:

```sh
npm install --prefix /tmp/clayzer-browser-tools playwright-core @axe-core/playwright
export NODE_PATH=/tmp/clayzer-browser-tools/node_modules
export CLAYZER_CHROMIUM="/path/to/a/testing/chromium/executable"
node tests/ui_public_smoke.cjs
node tests/ui_journey.cjs
CLAYZER_UI_URL=http://127.0.0.1:8786 node tests/ui_upstream_compatibility.cjs
CLAYZER_AUDIT_OUTPUT=/tmp/clayzer-cinematic-audit node tests/ui_public_accessibility.cjs
```

The browser suites expect the offline Report demo's synthetic experiment and development Change
Case. They make no paid model calls. Source-scoped Python tests still require the UI/tools extras.

## References and unsynced design

[Apple](https://www.apple.com/) was visually inspected for image scale and pacing. The
[Lando Norris site](https://landonorris.com/) was inspected, but its loading/interactive entry did
not complete reliably in the automated browser; a full motion review is not claimed.
[Made with Clay](https://madewithclay.org/) and [Watermelon UI](https://ui.watermelon.sh/) were
visually inspected in the preceding refinement. No reference branding, artwork, proprietary fonts
or exact layouts were copied.

Existing Figma file: https://www.figma.com/design/GxqnqG6JwiKSNcmPNNhZNr?node-id=6-10

It preserves the earlier editable foundations/screens, but does not match this newer experience.
Its Starter-plan MCP limit blocked the previous sync. As requested, this round did not retry,
create a new file or claim Figma parity. The unsynced scene/motion design is documented locally.
