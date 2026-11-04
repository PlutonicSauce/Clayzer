# Output Score: change review and demonstration

This is the historical Step 6 review. For the current clean-branch integration, test results
and Step 7 usage, see [Report handoff](report-handoff.md).

**Independent-audit follow-up:** the two findings below have now been addressed with 12 passing
regression cases and a 241-test passing suite. Vague Claims retain the existing correctness/type
coverage definitions but now expose explicit count/position field coverage and prominent scope
qualifiers. Parent partial credit is preserved in both class slices and dataset diagnostics.
The original review below records the pre-fix state; its parent-credit defect is resolved in
`grounding-5`. See `docs/output-score.md` → Independent audit follow-up for the changes and evidence.
The regression gate and historical Baseline were not modified by that follow-up.

Reviewed locally on 2026-11-04 against Git `HEAD` (`ee8dddc`). This review made no implementation
changes. Only this changelog was added to the repository. Demo artifacts were generated under
`/tmp/clayzer-output-review-u9k_o2_1/`. No paid model calls, commits, pushes or deployments occurred.

## 1. What changed, file by file

At the start of this review, `git status --short` showed **16 modified tracked files and 9 new
untracked files**, with **no deletions**. `git diff --stat` reported **629 insertions and 180
deletions across the 16 tracked files**; it did not include the nine new files. Those files were
listed with `git ls-files --others --exclude-standard` and inspected separately.

The file set matches the preceding Output Score implementation session. However, Git does not
record the authorship of uncommitted lines, so the comparison below is working tree versus HEAD,
not independent proof that every uncommitted line belongs to one author. This review captured
SHA-256 hashes before inspecting and running demonstrations to check that existing files were
not subsequently altered.

Types: **fix** corrects existing behavior; **feature** adds an interface or capability;
**integration** connects it to existing consumers; **docs/tests** records or verifies behavior.

| File | State | Type | Before → current behavior / purpose |
|---|---|---|---|
| `src/clayzer/grounding.py` | Modified | Fix, feature | Missing mapped classes were false positives and neighbouring cells earned credit → missing evidence is unknown, cells require exact coverage, incomplete counts are lower bounds, relations account for spatial ambiguity, and rows expose outcomes and denominators. |
| `src/clayzer/judge.py` | Modified | Fix | First tool response was accepted and its score cast to float → exactly one named verdict, validated envelope, finite numeric score in [0,1], string issues, model-opinion metadata and self-judging detection. The prompt no longer assumes all imagery is NAIP at 0.6 m. |
| `src/clayzer/retrieval.py` | Modified | Fix, feature | Runtime hardcoded queries and unsaved embeddings → ontology queries, frozen relevance, saved embeddings, stable ties, invalid-vector handling, evidence warnings, distinct hit rate and optional synonym comparison. Recall and MRR formulas already existed and were correct. |
| `src/clayzer/output_score.py` | New | Feature | No shared engine → `score_caption` supplies native/imported grounding and fidelity plus explicit cost and preparation observations. There is no combined five-criterion score. |
| `src/clayzer/imported_score.py` | New | Feature | No external-caption evaluation entry point → normalized JSONL captions can be evaluated without a Harness; references/provenance are frozen and JSON plus escaped HTML are written. |
| `src/clayzer/extraction.py` | New | Feature | Free text had no extraction path → a versioned text-only provider interface extracts Claims, validates literal evidence and records provenance and a Trace. |
| `src/clayzer/benchmarks.py` | New | Feature | No benchmark adapters → local RSICD test-caption normalization and VRSBench normalized-box conversion, with version/license notes and source hashes. No benchmark downloader or real results. |
| `src/clayzer/calibration.py` | New | Feature | No calibration interface → blind packets, validated imported human fidelity labels, agreement metrics and exact Claim agreement. No human answers are generated. |
| `src/clayzer/dataset_score.py` | New | Feature | No imported dataset diagnostics → class/region/terrain strata, deterministic sampling, per-class means, duplication, unknown denominators and Wilson intervals for eligible binary outcomes. |
| `src/clayzer/batch.py` | Modified | Integration, fix | Native scoring called components directly → shared engine integration; scorer version updated; queries frozen and checked before resume; caption timing includes verification/rewrite; missing preparation totals stay null. |
| `src/clayzer/cli.py` | Modified | Feature | No imported evaluation command → `clayzer evaluate` reads JSONL and optional Cases, queries and embedding recordings without a provider call. |
| `src/clayzer/gate.py` | Modified | Integration | Frozen query changes were not compared → retrieval-query hash joins measurement-setting warnings. Pass/fail thresholds and decision policy are unchanged. |
| `src/clayzer/provenance.py` | Modified | Integration | No query artifact in provenance → frozen query file and hash are listed and available through existing file routes. |
| `src/clayzer/report.py` | Modified | Integration | Ambiguous Judge/cost/timing wording → Markdown identifies model opinion, GPU unavailability, operational usage and preparation provenance. |
| `src/clayzer/report_html.py` | Modified | Integration | Missing references appeared as false positives → evidence-aware claim verdicts, unknown/contradicted legends, model-opinion Fidelity and an unavailable GPU-cost card. |
| `src/clayzer/run_report.py` | Modified | Integration | Run reports lacked the complete criterion details → JSON includes evidence denominators, Fidelity metadata, retrieval, cost and preparation; HTML exposes the added details. |
| `src/clayzer/ui/app.py` | Modified | Integration, fix | Overview used Recall@1 for top-result success → it uses hit@1 when available; self-judging and claim outcomes are exposed, and contradicted rows are excluded from the exact-match showcase count. |
| `src/clayzer/ui/static/app.js` | Modified | Integration | Overstated map certainty and preparation wording → unknown evidence, model opinion, timing scope and limited showcase claims are explained. This does not add import or calibration screens. |
| `tests/test_grounding.py` | Modified | Tests | Old neighbour/absence expectations → exact cells and unknown evidence; synthetic exhaustive-count fixtures explicitly declare completeness. |
| `tests/test_output_score.py` | New | Tests | Adds 78 collected test cases covering the new scoring contracts, negative controls and offline integrations. |
| `scripts/output_score_demo.py` | New | Demo | Adds two drawn synthetic images, scripted caption/Judge/embedding providers, a six-Run native Batch and an imported evaluation. Values are fixtures, not measured model accuracy. |
| `docs/caption-plan.md` | Modified | Docs | Adds the scoring, preparation-time and historical-score preservation decisions in section 10. |
| `docs/cli.md` | Modified | Docs | Documents offline imported evaluation and links its contracts. |
| `docs/tasks.toml` | Modified | Docs | Updates the fourteen Output Score tasks with evidence-based PASS/PARTIAL/BLOCKED notes. |
| `docs/output-score.md` | New | Docs | Implementation handoff: contracts, measurement definitions, blockers, commands and file inventory. |

This requested `docs/OUTPUT_SCORE_CHANGELOG.md` is the **tenth new file** after the review.
The Harness, MCP implementation, Workflow Score, deployment configuration and committed Baseline
have no working-tree diffs. No files were deleted.

For an exact patch including the original nine untracked files, open:

```sh
code /tmp/clayzer-output-review-u9k_o2_1/output-score-review.patch
```

That patch is a review artifact, not something this review applied. In VS Code, Source Control
shows tracked before/after diffs; untracked files need to be opened separately.

## 2. One caption: actual before-and-after behavior

Illustrative synthetic caption:

> Two buildings in the centre, a solar array in the north, and a road in the south.

Independent example references establish **two buildings in the north** with an explicitly
complete count and a **road in the south** with no exact count. They contain **no solar record**.

The committed HEAD scorer and current scorer were both invoked on these same inputs, without
changing either file:

| Claim | HEAD behavior | Current behavior |
|---|---|---|
| Two buildings at centre | `matched`; position 0.5 because centre neighbours north | `contradicted`; position 0.0 because the evidence places them north |
| Solar array at north | `false positive` because no solar record exists | `not_verifiable`; missing reference evidence is not proof of absence |
| Road at south | `matched`; position 1.0 | `supported`; position 1.0, with the asserted count explicitly unverified |

Observed component outputs:

| Metric | HEAD | Current |
|---|---:|---:|
| Presence precision | 0.666667 | 1.000000 |
| Position | 0.750000 | 0.500000 |
| Grounding correctness | 0.805556 | 0.833333 |
| Grounding coverage | 1.000000 | 1.000000 |

**The higher correctness value is not a model improvement.** The caption is identical; the
measurement semantics changed. Unknown solar evidence no longer enters the precision denominator,
and the incorrect building cell loses its bonus. Coverage still measures which reference types
were mentioned, not whether every position was right. These are reasons to read the components,
unknowns and denominators, and not compare old and new scores as if their scale were unchanged.

Other important fixes:

- Exact cell membership replaces neighbour credit for every cell, not just centre.
- An explicit sourced `count: 0, absence_verified: true` can contradict object presence; an absent
  database row cannot. The evaluator relies on the reference preparer's completeness/absence declarations.
- Counts default to incomplete. Claiming fewer than a known lower bound contradicts it; equality
  or a larger count is unverified unless `count_complete: true`. Duplicate class reference rows
  raise an error rather than overwriting each other.
- Directional relations use all covered-cell pairs; ambiguous geometry produces an unscored
  relation. Same-class and unsupported relation types are not independently resolved.
- Missing preparation time used to sum to zero; it now stays null. Actual zero remains zero.
- Native caption latency now includes tool/verification/rewrite work; it excludes judging.
- Recall@1 was incorrectly presented as top-result success. Hit@1 now supplies that percentage;
  older records without hit@1 do not receive an invented replacement percentage.

## 3. Feature locations and how they work

| Feature | Exact entry points | What to inspect / use |
|---|---|---|
| Grounding outcomes | `grounding.py:grounding`, `_position_score`, `_count_score` | `rows[].outcome`, `unknown_fields`, `denominators`, components, `missed`, correctness and coverage. `verdict` is retained for older consumers. |
| Shared native/imported engine | `output_score.py:score_caption`; `batch.py:_run_one` | Same grounding implementation and image-aware Judge path; retrieval is a separate corpus-level criterion. |
| Fidelity validation | `judge.py:fidelity`, `validate_verdict`, `self_judging` | Validated response envelope and exactly one `submit_verdict`; booleans, NaN, infinity, out-of-range values and malformed issues are rejected. Regional model prefixes are normalized for self-judging flags. |
| Retrieval | `retrieval.py:freeze_queries`, `rank_recording`, `retrieval` | Recall@K = relevant retrieved / known relevant; hit@K = any relevant retrieved; MRR uses first relevant rank. Corpus/query hashes, stored vectors, stable id tie-breaking, skipped queries and warnings make interpretation reproducible. |
| Synonyms | `retrieval.py:synonym_queries`; `retrieval(..., compare_synonyms=True)` | Original query text and ontology-synonym expansion are evaluated separately. Imported provider evaluation enables this comparison. Native batches do not automatically enable synonym comparison. |
| Imported captions | `imported_score.py:normalize`, `evaluate`, `write_evaluation`; `cli.py:main` | JSONL text plus optional structured Claims; independent Cases can be joined by case id. Missing references/Claims/images/providers are explicitly unavailable. The CLI is offline; provider-enabled judging/extraction uses the Python API. |
| Free-text extraction | `extraction.py:extract`, `validate_claims`, `PROMPT`, `TOOL`, `VERSION` | Only caption text and vocabulary reach the extractor. Literal evidence, count-to-noun attachment, grid direction, attributes, negation and relation endpoints are checked. Original text, model/prompt/schema/source provenance and a Trace are retained. Unstated fields stay null. |
| GPU cost | `output_score.py:cost_observation` | Hosted Bedrock GPU seconds/count/type remain null. Observed self-hosted metrics require a measurement method. Latency/tokens are separate operational fields. |
| Preparation time | `output_score.py:preparation`; `batch.py:summarize` | Legacy `prep_seconds` is total Case-building time including imagery/reference queries. Explicit reference-only observations identify scope, method and seconds. Observed counts, missing values and caption-generation time remain separate. |
| Dataset diagnostics | `dataset_score.py:dataset_report`, `stratified_sample`, `wilson` | Imported JSON reports include class/region/terrain strata, deterministic samples, duplicates, per-class means and eligible binary contradiction rates. Wilson intervals do not apply to continuous correctness or unknown outcomes. |
| Human calibration | `calibration.py:blind_packet`, `calibration_metrics`, `claim_calibration` | Export text/image ids and rubric without Judge answers; import actual blind human labels with annotator and rubric hash. Report MAE, RMSE, bias, agreement within 0.25, and exact Claim agreement. |
| Benchmark adapters | `benchmarks.py:rsicd`, `vrsbench_boxes` | Local input normalization only: up to 100 deterministic RSICD test entries and distinct-instance pixel boxes with an explicit VRSBench category crosswalk. |

The extraction demonstration used a scripted provider for `Two buildings in the north.` and
returned object `building`, count `2`, position `north`, the literal evidence phrase and
`claims_status: extracted_model_opinion`. It did not use imagery or hidden labels. Separately,
Judge validation accepted 0.75 but rejected 2.0 and NaN. Neither demonstration invoked a real model.

The extraction checks are deliberately conservative but do not prove arbitrary natural-language
entailment. Supplied structured Claims are not independently checked against their prose. Real
human calibration is still required.

## 4. Working demonstration and what is actually visible

### Commands

From the repository root, rerun the existing synthetic demonstration:

```sh
uv run python scripts/output_score_demo.py --output /tmp/clayzer-output-demo

uv run clayzer evaluate /tmp/clayzer-output-demo/captions.jsonl \
  --cases /tmp/clayzer-output-demo/cases.jsonl \
  --queries /tmp/clayzer-output-demo/queries.json \
  --recording /tmp/clayzer-output-demo/embeddings.json \
  --output /tmp/clayzer-output-offline
```

The first command writes native Batch/Run reports and imported reports using scripted providers.
The second recalculates imported grounding and retrieval offline; Fidelity is unavailable with
reason `Judge disabled`, because that CLI command does not run a Judge or invent its verdict.

This review's actual output directory is `/tmp/clayzer-output-review-u9k_o2_1`. Open its reports
on macOS with:

```sh
open /tmp/clayzer-output-review-u9k_o2_1/demo/batches/20261104T160736Z-SYNTHETIC-OUTPUT-DEMO/report.html
open /tmp/clayzer-output-review-u9k_o2_1/demo/imported/output-score.html
open /tmp/clayzer-output-review-u9k_o2_1/offline/output-score.html
```

Inspect the machine-readable output in VS Code:

```sh
code /tmp/clayzer-output-review-u9k_o2_1/demo/imported/output-score.json
code /tmp/clayzer-output-review-u9k_o2_1/example-before-after.json
code /tmp/clayzer-output-review-u9k_o2_1/demo/queries.json
code /tmp/clayzer-output-review-u9k_o2_1/demo/embeddings.json
```

The example run produced **2 synthetic Cases × 3 Repeats = 6 successful Runs**, zero Harness
Faults and zero Sandbox Failures. Fixture correctness/coverage were 1.00, scripted Fidelity was
0.75 and the two-query/two-caption fixture's MRR was 1.00. GPU measurements, preparation time
and token counts were unavailable. Near-instant local execution rounded to 0.0 seconds; this is
not real inference throughput. Canonical and synonym-expanded retrieval both scored 1.00 in the
scripted imported example; that does not establish synonym effectiveness on real data.

The dataset report explicitly showed 2 captions, only 1 eligible binary outcome and 1 unknown
outcome. Its zero observed contradictions had a Wilson interval of approximately [0, 0.79345],
illustrating that a tiny fixture cannot support a strong dataset-quality claim.

### Local application

Normal application startup remains:

```sh
uv run clayzer ui
```

Open `http://127.0.0.1:8770`. It uses the configured store; it does not automatically load the
temporary demo. Repository `.env` values override shell settings, so blindly exporting a demo
store is not a reliable override if `.env` specifies one.

For this review I started an isolated **read-only** app on port **8771**, with explicit local
Settings, the temporary demo store and no accepted Baseline. It does not read the cloud store.
The exact restart command is:

```sh
.venv/bin/python -c 'from dataclasses import replace; from pathlib import Path; from clayzer.config import Settings; from clayzer.ui.app import serve; s=replace(Settings.from_env(), store_url=None, data_dir=Path("/tmp/clayzer-output-review-u9k_o2_1/demo/data"), batches_dir=Path("/tmp/clayzer-output-review-u9k_o2_1/demo/batches"), baselines_dir=Path("/tmp/clayzer-output-review-u9k_o2_1/no-baseline")); serve(s,"synthetic",False,"127.0.0.1",8771)'
```

Open `http://127.0.0.1:8771/#/batches`. The missing-Baseline notice in this isolated demo is
expected; the committed Baseline was not replaced with synthetic data.

### Verified in the browser

Using the local Helium browser, I opened and inspected the Batches list, Batch page, standalone
native HTML report, one Run report and the imported standalone report. A screenshot of the
native report was displayed in chat.

| Surface | Verified visible | What is not implemented there |
|---|---|---|
| Batches list | Synthetic Batch, 2×3 size, separate correctness/coverage/Fidelity/retrieval and 6 successful Runs | No imported-caption upload workflow |
| Batch provenance | Scorer version, ontology, rubric and frozen-retrieval-query hashes plus stored-file links | Hashes are provenance, not proof that a caption is correct |
| Native Batch report | Five criteria (grounding has two cards), model-opinion label, GPU `Unavailable`, unmeasured preparation, grid overlays, repeats and retrieval rankings | No dedicated synonym comparison chart |
| Native Run report | Caption, supported Claim row, reference source, position score, scripted-Judge warning, retrieval/cost/timing details, separate Workflow Score and Trace Steps | No calibration form or Claim-extraction button |
| Imported HTML | Escaped, preformatted JSON containing criteria, provenance, dataset diagnostics and synonym comparison | It is a standalone data report, not a designed dashboard screen or app route |
| Extraction/calibration/benchmark adapters | Python interfaces and tests | No corresponding app screens were added |
| Overview changes | API/JavaScript changes inspected | The isolated demo has no Baseline, so new Overview scorecard behavior and self-judging flags were not visually demonstrated here |

## 5. Verification, preserved behavior and outstanding limitations

### Checks rerun

```sh
uv run --python 3.12 --extra ui --extra tools pytest -q
.venv/bin/ruff check src tests scripts/output_score_demo.py
.venv/bin/ruff format --check src tests scripts/output_score_demo.py
node --check src/clayzer/ui/static/app.js
git diff --check
```

Results: **229 passed in 7.85 seconds; 0 failures, 0 skipped tests**. Ruff passed; all 57 checked
Python files were formatted; JavaScript syntax and whitespace checks passed. The suite includes
78 Output Score tests, 15 evaluation-loop tests, 10 Workflow Score tests, 17 UI tests, 10 provenance
tests, 8 agentic tests, 11 MCP-auth tests and 6 verification tests. Existing team paths therefore
remain covered by passing offline tests; this does not certify live AWS or model behavior.

All four committed Baseline files (`ACCEPTED_FROM`, `batch.json`, `results.jsonl`, `summary.json`)
were compared byte-for-byte with HEAD and matched. No historical rescore or Baseline acceptance
command was run. No diffs exist for the Harness, Workflow Score, MCP tools or deployment files.
Untracked/ignored historical data outside Git cannot be authenticated against a prior snapshot;
this review used only its isolated temporary store.

### Important limitations, including one issue reproduced during this review

1. **Per-class partial-credit inconsistency:** a Claim of `building` against a `greenhouse`
   reference receives aggregate presence/coverage credit of 0.5, but `score_caption` filters
   references by exact class when constructing `grounding_by_class`. Both related per-class
   precision values then become null. I reproduced this through `imported_score.evaluate`.
   Aggregate and per-class reporting therefore disagree for parent matches. This is an unresolved
   implementation defect, not an external data blocker; no code was changed during this review.
2. **New and old scores are not interchangeable.** The scorer is now
   `output-1+grounding-4+retrieval-2+workflow-1` for native Batches. The Judge prompt hash also changed.
   The upstream hardened gate makes otherwise passing measurement-incompatible comparisons inconclusive. Older
   unfinished judged Batches can refuse resume when their saved rubric differs from the current one.
3. **Real evaluation is still outstanding.** The new extraction, calibration, RSICD and VRSBench
   interfaces have synthetic tests, not validated human agreement or real benchmark results.
   Clay's examples/retrieval set are absent. No new real Bedrock, Titan or geospatial-service run
   was performed. Historical real results are preserved records, not a new validation of this scorer.
4. **Reference preparation remains a dependency.** Spatial/temporal alignment and completeness
   declarations must be trustworthy. Unknown fields are excluded, so a high correctness value
   does not mean the complete caption has been verified. Read coverage, unknowns and denominators.
5. **Imported evaluation has a defined boundary.** JSONL works; GeoParquet ingestion, reference
   acquisition, raw benchmark-release conversion and image loading are separate integration work.
   The offline CLI does not automatically extract Claims or invoke a vision Judge.
6. **Dataset intervals are conditional.** Strata may overlap, neighbouring images may correlate,
   and selective reference coverage changes which outcomes are eligible. Wilson intervals do not
   establish a representative population verdict or a confidence interval for continuous correctness.
7. **Native Judge failures retain the older retry contract.** A failed native Judge makes the Run
   a Sandbox Failure excluded until resumed. Imported evaluation retains deterministic grounding
   when its Judge fails. This difference was preserved, not harmonized.
8. **Some report wording is still generic to NAIP.** The native report displayed `NAIP` beside
   an explicitly synthetic acquisition placeholder. The source is `synthetic-pillow`; this fixture
   must not be presented as real aerial imagery. The standalone imported HTML is primarily JSON.
9. **Calibration is not automatic truth.** Blindness is attested; self-judging detection is based
   on normalized model identifiers and cannot resolve every alias. Claim calibration excludes relations.
10. The cheap Judge cascade, real GPU instrumentation, official benchmark results and broad UI
    integration remain unfinished. No weighted combined Output Score was introduced.

## 6. What teammates should know before review or merge

- Review the complete patch, including new files; normal `git diff` omits untracked files.
- Review the scoring policy as a measurement change, not a demonstrated caption-quality gain.
  Read the same-caption example above before interpreting improved numbers.
- Resolve the reproduced aggregate/per-class parent-credit discrepancy before relying on per-class
  diagnostics for those cases. Passing tests do not cover every semantic consistency condition.
- Preserve the existing accepted Baseline. Establish a deliberately versioned, comparable evaluation
  before accepting a new Baseline; do not silently rewrite old scores.
- Coordinate shared-file changes in `batch.py`, reports, UI, provenance and gate with their owners.
  The gate policy, Harness, MCP implementation and Workflow Score logic were not rewritten.
- Supply real, permitted benchmark data and independent human labels before claiming calibration
  or real-world accuracy. Review reference completeness/date alignment upstream.
- Use the isolated local demo for inspection. No new cloud resource, live-site change, paid call,
  Git commit, push, merge or rebase is part of this review.

This changelog records the reviewed state and its limitations; it is not a merge approval.
