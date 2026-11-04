# Output Score and Report handoff

The final feature branch `feat/output-score-report-ready` starts at `149528d`, refreshed
from `origin/main` on 2026-11-04. It transfers the hash-verified 41-file Step 6/7 patch from
the earlier `0f20505` handoff into a new isolated worktree. Both original worktrees and all
prior backups are preserved. Publication evidence, final patch and backup manifests are
kept in a separate local handoff package, outside the PR.

## Integration scope

The transfer contains only Step 6 Output Score, Step 7 Report and necessary compatibility
adjustments. Case construction/validation, genuine NAIP imagery and corrections, independent
USGS/OSM/manual references, the geospatial and RSICD importers, extraction/labelling workflows,
Change Cases, the Texas holdout, look-alike negatives, ontology 0.2, verifier routing/spread, GRW dating, GitHub Actions/OIDC and the extractor complexity fix are upstream teammate contributions.
The PR preserves these features and does not introduce their fixtures or historical results.

The accepted `baselines/default/` files remain byte-identical to `149528d`: the upstream
63-Case, 189-Run `20261104T164843Z-dev63-base` Batch under `grounding-4+workflow-1`.
New scores retain `output-1+grounding-5+retrieval-2+workflow-1`. Historical results are not
relabelled, rescored or replaced. The existing gate warns about measurement changes; its
thresholds and decision policy remain unchanged. A cross-version gate PASS cannot establish
improvement. Establish comparable measurements deliberately before accepting a new Baseline.

The 61 held-out Texas Cases are untouched. Full-suite validation checks their static fixture
integrity and metadata; neither the tests nor this demo evaluate their Captions or tune on them.

### Necessary overlap resolutions

| Area | Resolution |
|---|---|
| `batch.py` | Keep the shared Output Score engine, frozen retrieval queries and full pipeline timing alongside upstream Chip Pair inputs, change-prompt hashes and resume validation. Fidelity receives both images and their corresponding recorded keys. Preserve upstream verifier-route hashes and classifier setup. |
| `grounding.py` | Preserve grounding-5's open-world evidence, count bounds, specificity and parent-class context. Retain upstream's temporal change component where reference change is known. Fixed-Case correctness and coverage definitions are unchanged. |
| Report HTML/JSON | Preserve change annotations, later-image positioning and the Run's actual change-prompt hash, alongside replay origins, unavailable reasons, field coverage and navigation. |
| CLI and UI | Keep upstream import/extract/calibration, verifier/spread and GRW-dated Change Case flows; retain both sets of additive parser/dispatch blocks and add evaluate/replay, dataset cards and the isolated local read-only demo root. |
| `docs/tasks.toml` | Preserve the upstream completed extraction task, its calibration caveats and new follow-up tasks. Preserve completed Case/importer tasks, the protected Texas split and CI notes; apply only Output Score/Report task updates. |
| Upstream CI compatibility | Keep the new lint/coverage/duplication thresholds. Extract existing scoring, text-validation and replay stages into helpers and use explicit strict zips. Upstream PR #72 independently resolved the extractor complexity issue; its `extract.py` is retained unchanged, so the final PR remains 41 files. |
| Extraction regression | Make an exhaustive synthetic count fixture explicit with `count_complete=True`; retain assertions that omitted fields are unevaluated, and add a check that an incomplete count remains unknown. |

The stricter text-evidence adapter in `extraction.py` serves the imported Output Score API.
It supplements the unchanged upstream `extract.py` CLI/labelling workflow; the two interfaces
have different validation and calibration contracts. This PR does not claim the upstream
extractor, human labels, Case builder or imagery fixes as new work.

## What the change adds

- Grounding distinguishes supported, contradicted and unverifiable claims. Missing map records
  are not verified absence; incomplete map counts are lower bounds. Correctness and reference
  type coverage remain separate. Omitted count/position details are prominently disclosed.
- Per-class diagnostic slices retain full matching context, including partial parent credit.
  Overlapping class strata are not independent populations.
- Shared native/imported Output Score paths validate Fidelity Judge responses, record self
  judging, freeze retrieval evidence, distinguish Recall@K from hit rate, and support optional
  synonym-query comparisons. Fidelity remains model opinion.
- Imported evaluation adapters, conservative text-only extraction, reproducible dataset
  diagnostics, benchmark adapters and calibration interfaces expose evidence and limitations.
- Label/Case preparation, caption latency, token usage and observed GPU use remain separate.
  Missing measurements are unavailable rather than zero.
- Local replay reconstructs deterministic scores, summaries and reports into a fresh directory,
  retaining recorded Judge/retrieval evidence and original failure statuses without models.
- Versioned dataset cards, Batch/Run/Trace navigation, report-side X-Ray links, redacted report
  projections and read-only dataset views improve review and demonstration.

## Report task status

| Task | Status | Evidence or remaining dependency |
|---|---|---|
| Run reports | PASS | Standalone HTML/JSON, separate Workflow/Output evidence, missing-data qualifiers and navigation. |
| Batch provenance | PASS | Existing frozen references/settings retained; replay adds hashes, original/current evaluator versions and metric origins. |
| Web app | PASS | Read-only default, local replay root, dataset cards and existing upstream routes covered by tests. |
| Offline replay | PASS | Provider/network prohibition, original hash preservation, deterministic repeated output, partial/historical recordings and Chip Pair regression. |
| Dataset card | PASS | Versioned JSON/HTML and UI links; empty/duplicate/partial/unknown/overlapping data tested. |
| X-Ray links | PARTIAL | Validated export-context link and serialization/replay tests. Genuine capture/export verification awaits the capture owner's recording. |
| Claims per dollar | PARTIAL | Per-Run deduplicated evidence accounting and measured-cost interface. Real pricing, billing, GPU measurements and Batch/Compare aggregation remain unavailable. |

## Offline demonstration

With dependencies installed, choose a new output directory:

```sh
uv sync --extra ui --extra tools --extra import
uv run --no-sync python scripts/report_demo.py --output /tmp/clayzer-report-demo-new
uv run --no-sync clayzer ui --local-root /tmp/clayzer-report-demo-new/replayed --port 8772
```

The command prints the generated Batch and card paths. Open them directly, or use the app's
Dataset cards, Cases and Batches navigation. `--local-root` bypasses `.env`/S3 configuration and
keeps Batch launching disabled by default. The normal `uv run clayzer ui` retains the configured
store behavior. Do not accept the synthetic demo as a historical Baseline.

The demo contains six **scripted synthetic** Runs: two drawn images, three Repeats each.
Fixture correctness/coverage are 1.0 and scripted Fidelity is 0.75. It replays those records,
creates an imported-set card and adds a separate gallery of the existing 64 development Cases:
63 Fixed Cases (30 solar, 13 wind, 20 negative) plus the upstream Kingbird B Change Case.
That gallery contains **zero evaluated model Captions** and 64 pending Runs; caption accuracy and Fidelity are unavailable. Genuine USGS/OSM reference
provenance and OSM attribution are preserved. The self-contained gallery is about 26 MB;
individual Case views are easier to inspect.

## Replay contract

```sh
uv run clayzer replay /path/to/batches/recorded-id --data /path/to/data --output /tmp/fresh-replay
uv run clayzer ui --local-root /tmp/fresh-replay --port 8772
```

Omitting `--output` creates a fresh temporary directory; explicit outputs must be new and
outside the source/data directories. The source requires `batch.json` and frozen `cases.jsonl`.
Optional results, captions, traces, narratives, retrieval evidence and images are used only
when available. No cloud store is discovered or downloaded. Existing `rescore` retains its
original behavior of writing into the source Batch; use replay for a non-destructive review.

Duplicate or mismatched Run/Case identities and malformed core JSON are rejected. Missing
captions/references, images, Judge/retrieval evidence, changed image hashes and incomplete or
malformed individual Traces produce explicit warnings/unavailable metrics. Harness Faults
retain their zero-score rule; Sandbox Failures remain excluded; pending Runs are not executed.

Deterministic grounding, Workflow and summaries are recomputed where evidence allows.
Recorded Fidelity/retrieval and valid saved narratives are retained, not represented as new
model measurements. `replay.json` records source hashes, evaluator versions, metric origins,
pending Runs and warnings. Version changes warn against direct historical comparisons.
Exported redaction can change payload bytes; original input hashes remain recorded.

```text
output/
  data/chips/<id>.png
  batches/<original-batch-id>/
    batch.json, cases.jsonl, captions.jsonl, results.jsonl, retrieval.jsonl
    summary.json, replay.json, report.html, report.md
    traces/<case>--r<N>.jsonl
    traces/<case>--r<N>.summary.json
    traces/<case>--r<N>.narrative.json  # only when valid and recorded
    runs/<case>--r<N>.html, .json
```

## Imported dataset cards

```sh
uv run clayzer evaluate captions.jsonl --cases cases.jsonl --output /tmp/card-store/data/datasets/review-set
uv run clayzer ui --local-root /tmp/card-store --port 8772
```

Optional `--queries`/`--recording` use matching saved text embeddings for offline ranking.
The command makes no Judge or extractor calls. `write_evaluation()` writes linked Output Score
and `dataset-card.{json,html}` files. API callers may supply `dataset_metadata` with dataset
name/source/date/split/provenance; absent metadata remains unavailable.

Cards report exact normalized duplication, vocabulary/length, observed unique identities,
class/region/terrain distributions, separate correctness/coverage, field coverage, per-class
outcomes, overlapping strata, existing sampling/interval diagnostics and missing evidence.
Ontology confusers are review candidates, not measured visual confusions. Partial parent
mappings are not fabricated confusion labels. No new quality weights or training-benefit
claims are introduced.

## Trace and cost contracts

The capture owner can populate the existing `RunInfo.metadata` envelope:

```python
run.metadata['otel'] = {
    'trace_id': actual_exported_trace_id,  # OTel 32 hex or AWS 1-8hex-24hex
    'aws_region': actual_export_region,
    'exported_to': 'xray',
}
```

`trace_link.xray_link()` validates the ID and region without contacting AWS. Missing export
context, zero/malformed IDs or missing region yield no link and an unavailable reason. Unit
test IDs are synthetic. Links follow the [AWS X-Ray deep-link contract](https://docs.aws.amazon.com/xray/latest/devguide/xray-console-deeplinks.html).
This work does not implement/deploy the exporter or verify a live exported trace.

`report_cost.evidence_yield()` deduplicates object Claims ignoring local IDs, respects existing
parent credit, and reports supported-as-stated claim credit and supported field units separately
from correctness. Relations are excluded. It does not infer billing or GPU use from tokens.
USD ratios require positive observed values, USD currency, `verified=True`, and explicit
method/model/region/source/date provenance. This is a caller-attestation boundary, not an
independent bill verification. GPU ratios require observed positive GPU seconds and a method.
All real dollar/GPU ratios remain unavailable without those inputs.

## Validation

Validation ran from this refreshed worktree using an existing Python 3.12 environment with
the UI, tools, import and infra extras to conserve disk space. An explicit source path and
import/REPO assertions verified that the new worktree supplied the code. No dependency or
CI thresholds changed. In a fresh checkout, install those extras first; the standard commands are:

```sh
uv run --no-sync pytest -q --cov --cov-report=term
uv run --no-sync pytest -q infra/tests
uv run --no-sync ruff check src tests scripts
uv run --no-sync ruff format --check src tests scripts
uv run --no-sync vulture
node --check src/clayzer/ui/static/app.js
node tests/deck_smoke.mjs
npx --yes jscpd@5.4.2 src --min-tokens 50 --threshold 3 --ignore "**/vendor/**" --reporters consoleFull
git diff --check
uv run --no-sync python scripts/report_demo.py --output /tmp/clayzer-report-demo-new
```

Clean-branch validation: **388 passed total (385 application + 3 infrastructure); 0 failed, 0 skipped**, including all 12 independent
audit regression cases. Coverage is **85.19%**, above the unchanged upstream 75% gate.
Forty Shapely deprecation warnings remain (the existing three plus upstream GRW tests/code). Ruff lint and formatting (89 Python files),
Vulture, JavaScript syntax, deck smoke test, duplication (0.32% lines; threshold 3%), Git diff
checks, the three upstream IAM trust-policy tests, both credential-free CDK synthesis checks and the complete offline Report demo pass. No infrastructure was deployed or modified. Earlier 151/229/241/255/289/327/342-test counts
are historical checkpoints, not evidence for the refreshed base.

The demo produced six scripted Runs with fixture correctness/coverage 1.0 and Fidelity 0.75,
a replayed imported dataset card, and the separate 64-development-Case reference gallery.
The gallery has zero evaluated Captions and 64 pending Runs. No Texas Batch was run.
Replay regressions prohibit provider/network access, preserve source hashes, compare repeated
exports, exercise unavailable evidence and retain Chip Pair images, change scores and prompt
provenance. Genuine model accuracy and independent calibration remain unmeasured. The replay fixture regression
first failed on its stale 63-Case assertion; it now checks the exact current Cases and all unique
Chip files, including the upstream pair. The demo ID/count follow the frozen Case file.
Credential-free synth used `--no-staging` to avoid duplicate local asset copies on the nearly full
disk; templates and trust policies were still synthesized and tested. No AWS calls/deployments
were performed. Both original worktrees, all source backups and the separate diagram files are preserved.

## Scientific and operational limitations

Correctness is conditional on evaluated assertions and does not establish complete caption
quality. Coverage is reference type recall, not an exhaustive object census. Map evidence can
be incomplete, stale or spatially mismatched. Counts are exhaustive only when declared so.
Structured Claim/prose alignment and strict extraction still need calibrated independent review.
Fidelity is model opinion; human-label provenance and the upstream calibration's known caveats
remain documented in the upstream extraction files. Overlapping strata and spatially related
samples cannot be treated as independent populations. Continuous correctness has no invented
Wilson interval.

The real Case reference gallery is not a caption benchmark. No paid model evaluation, genuine
GPU observation, verified bill, live X-Ray export or downstream training gain was obtained for
this handoff. Original internal recordings remain unchanged. Report redaction is a defensive
projection; review material before public sharing.
