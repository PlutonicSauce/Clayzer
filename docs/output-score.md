# Output Score handoff

Implemented locally on 2026-11-04. No paid inference, real benchmark run, Baseline replacement,
or deployment was performed. All generated demo scores use explicitly scripted synthetic providers.

## Five criteria and evidence semantics

`output_score.score_caption` is the shared native/imported engine. There is no weighted Output
Score. Workflow Score code and weights are unchanged. New native Batches use scorer
`output-1+grounding-5+retrieval-2+workflow-1`; imported reports omit Workflow Score entirely.

- **Grounding:** correctness and coverage remain separate. Missing map rows are unknown, never
  absence. Contradiction requires independent evidence, including `count: 0` with
  `absence_verified: true` and a source for an explicit negative. Existing USGS/OSM counts are
  lower bounds; overcounts and equal counts are not independently verified without
  `count_complete: true`. Count completeness must come from reviewed reference preparation,
  never the captioner. Under-counts below an established lower bound contradict that bound.
  All reference counts default to incomplete unless completeness is explicitly recorded; benchmark
  adapters also mark their potentially incomplete counts. Counts sum split Claims; duplicate
  class Reference Labels are rejected rather than silently overwritten. Position requires membership
  in the reference's covered cells, with no neighbour credit. Directional relations must hold across
  every pair of covered cells; ambiguous relations are unknown. Only the direct generalization
  greenhouse → building gets 0.5 presence/coverage credit; sibling similarity is not evidence.
  Rows expose `outcome`, `unknown_fields`, component scores and denominators. A supported object
  does not imply every count or attribute is verified. Correctness excludes unknown components.
- **Fidelity:** a validated finite [0,1] score and string-array issues, exactly one `submit_verdict`.
  It is model opinion. Regional inference prefixes are normalized to flag self-judging, including
  in HTML and the dashboard. Unknown model aliases cannot prove independence. The rubric no
  longer assumes every imported image is NAIP at 0.6 m, and its changed hash is recorded.
  Imported runs retain grounding if judging fails. Native runs preserve the existing Sandbox
  Failure/retry contract: a failed Judge leaves the Run excluded until resumed successfully.
- **Retrieval:** text-only embeddings; Recall@K = relevant retrieved / relevant known, MRR =
  reciprocal first relevant rank. Hit@K is separate. The dashboard uses hit@1 for its top-result
  percentage; historical Recall@1 is not relabelled as hit rate. Query text and positive relevance
  are frozen in `retrieval-queries.jsonl`, hashed and checked before resume. Saved embeddings,
  corpus and queries allow `rank_recording` without network. Ties break by id. Missing relevant
  documents skip the query instead of shrinking its denominator; no positives is unavailable.
  Tiny corpus, K covering the corpus and incomplete relevance are flagged. Map-derived relevance
  remains incomplete, so these are conditional retrieval metrics. Synonym expansion is optional
  (`retrieval(..., compare_synonyms=True)`); imported provider evaluation reports both versions.
- **Cost:** GPU seconds/count/type are null on hosted Bedrock. Operational latency/tokens are
  labelled separately. `cost_observation` accepts actual self-hosted observations with a method.
  Native caption latency now includes verification/tools/rewrite; judging is outside that scope.
  Imported rows default to an unknown provider and unmeasured generation unless supplied.
- **Preparation time:** legacy `prep_seconds` measures Case-building wall time, including imagery,
  reference queries and processing, not isolated annotation time. Explicit measurements use
  `preparation: {value, units: "seconds", scope: "reference_labels" | "case_build", method}`.
  Missing timings remain null; zero is retained. Aggregation exposes measured/total denominators
  and per-scope totals. Caption generation time is a separate observation. Clay's interpretation
  of the fifth criterion is still unconfirmed; both scopes are exposed rather than conflated.

Historical scores and the committed Baseline are untouched. The regression gate warns on scorer,
Judge rubric and retrieval-query changes; it retains its existing warning-only comparability
policy. Re-evaluate a new, explicitly labelled Batch before accepting a scientifically comparable
Baseline. Do not treat a cross-version gate PASS as proof of improved caption accuracy.

## Imported-caption interface

`clayzer evaluate` reads normalized JSONL without invoking a Harness, model or network. Each row
needs `id` (or `caption_id`/`case_id`) and `text` (or `caption`). Supply `objects`, `relations` and
`uncertain`, or a `claims` object with those arrays. Counts and grid positions may be null.
Supplied structured Claims are explicitly marked as not independently checked against their prose.
Free text without extraction reports unavailable grounding, not zero coverage.

Independent `reference_labels` may be inline or in `--cases` JSONL joined by `case_id`. The separate
team-owned Case importer remains responsible for geolocation, acquisition dates, resolution and
reference provenance. This module does not fetch Answer Keys or implement GeoParquet ingestion.
An `image_loader` callback, explicit judge client/model and embedding client/model enable image
judging and retrieval via the Python `imported_score.evaluate` API. No provider is constructed
implicitly. Provider errors do not become zero fidelity; input validation errors remain errors.

Official retrieval sets use a JSON array of `{id, query, relevant: [caption-id, ...],
relevance_complete: bool}`. Optional `target` links an ontology class for synonym expansion.
Official example captions can be imported with their independently prepared Cases; their text
alone is not a grounding label. There is no validated style-similarity rubric yet.

`extraction.extract(client, model, text, tracer=None)` is a separate opt-in text-only stage. It
uses a versioned prompt/schema, records model/request/response/source hash and a Trace Step,
and never receives an image or Reference Labels. Literal evidence spans and vocabulary checks
reject invented objects, unattested counts/positions/attributes, negation and reversed relation
endpoints in the supported grammar. Ambiguous phrasings are rejected, not guessed. These checks
cannot prove arbitrary natural-language entailment: extraction is conservative model opinion
and still requires human calibration. Unstated counts and positions remain null. Extraction
failures are raised; a caller must correct the input/provider rather than scoring invalid Claims.

## Benchmarks, calibration and dataset diagnostics

`benchmarks.rsicd` accepts a local `dataset_rsicd.json` structure, selects up to 100 test images
deterministically, deduplicates captions and merges identical queries' relevant-image sets.
It records dataset version, source hash, ids and the Lu et al. citation. Captions do not become
object labels. Real imagery access/licensing and real fidelity/retrieval evaluation are BLOCKED.
No downloader or restricted samples are bundled.

`benchmarks.vrsbench_boxes` accepts normalized distinct-instance pixel boxes and an explicit
reviewed category crosswalk, maps covered grid cells and counts, records unsupported categories,
image size, version and license note. Duplicate referring expressions must be resolved upstream.
These boxes are not assumed exhaustive. Raw release-format conversion, image access/licensing
and real evaluation are BLOCKED. Both adapters are tested only on synthetic fixtures.

`calibration.blind_packet` exports text/image ids and the exact rubric without model answers.
Import real human records with id, score, issues, annotator, `blind: true` and matching rubric_sha
into `calibration_metrics`; it reports MAE, RMSE, bias and agreement within 0.25, with denominators.
`claim_calibration` compares imported blind human Claims with extracted Claims (exact object,
count, grid cell and attributes); relation calibration still requires review. Blindness is an
attestation, not a cryptographic guarantee. No real human labels or agreement results exist here.

Imported reports include per-class/region/terrain strata, deterministic hashed sampling,
duplicate-caption counts, per-class mean correctness, measured counts and unknown denominators.
Wilson 95% intervals apply only to caption-level binary contradiction outcomes that can be
established. Continuous correctness has no Wilson interval. Strata can overlap; spatially
correlated images or selectively known evidence do not justify an unqualified population verdict.
The cheap Judge cascade remains deferred until calibration data and Priority A/B evidence exist.

## Offline demonstration and checks

```sh
uv run --python 3.12 --extra ui --extra tools pytest -q
uv run ruff check src tests scripts/output_score_demo.py
uv run ruff format --check src tests scripts/output_score_demo.py
uv run python scripts/output_score_demo.py --output /tmp/clayzer-output-demo
uv run clayzer evaluate /tmp/clayzer-output-demo/captions.jsonl \
  --cases /tmp/clayzer-output-demo/cases.jsonl \
  --queries /tmp/clayzer-output-demo/queries.json \
  --recording /tmp/clayzer-output-demo/embeddings.json \
  --output /tmp/clayzer-output-offline
```

The script runs the native Harness/Batch plumbing using scripted synthetic providers, and imports
the same captions through the shared engine. It writes native Trace/report files and separate
imported JSON/HTML reports. This verifies contracts, not real-world model accuracy. To view the
native Batch in the local web app with no cloud store, use:

```sh
CLAYZER_STORE='' CLAYZER_DATA_DIR=/tmp/clayzer-output-demo/data \
  CLAYZER_BATCHES_DIR=/tmp/clayzer-output-demo/batches uv run clayzer ui
```

The synthetic demo Case set is not installed as the production region's Cases or as a Baseline.
Open the generated report paths or the Batches page. Real native `clayzer batch` continues to
require staged real Cases and paid model authorization; it was not executed in this handoff.

## Local change inventory

- `src/clayzer/grounding.py`: open-world evidence, conservative counts, exact cells, relation
  ambiguity, direct-parent credit and denominators.
- `src/clayzer/judge.py`: generic image rubric, response validation and self-judging detection.
- `src/clayzer/retrieval.py`: ontology queries, correct metric semantics, frozen relevance,
  deterministic ranking, saved embeddings, missing-evidence flags and synonym comparisons.
- `src/clayzer/output_score.py` (new): shared engine, GPU observation interface and timing scopes.
- `src/clayzer/extraction.py` (new): versioned text-only extraction, provenance, Trace and literal
  evidence validation.
- `src/clayzer/imported_score.py` (new): normalized caption evaluation and escaped JSON/HTML reports.
- `src/clayzer/benchmarks.py` (new): local RSICD and normalized VRSBench-box adapters.
- `src/clayzer/calibration.py` (new): blind packets, human fidelity labels and Claim agreement.
- `src/clayzer/dataset_score.py` (new): strata, sampling, binary intervals and per-class diagnostics.
- `src/clayzer/batch.py`: shared scoring integration, pipeline timing, query freezing/checking,
  version and observed-measurement summaries.
- `src/clayzer/gate.py`: query-hash comparability warning; decision logic unchanged.
- `src/clayzer/provenance.py`: frozen retrieval-query file and hash in provenance panels.
- `src/clayzer/cli.py`: fully offline `evaluate` command.
- `src/clayzer/report.py`: five-criterion semantics, unavailable GPU cost and timing provenance.
- `src/clayzer/report_html.py`: evidence-aware verdicts and accurate criterion labels.
- `src/clayzer/run_report.py`: all five criteria in per-Run JSON/HTML and evidence denominators.
- `src/clayzer/ui/app.py`: self-judging metadata and distinct top-result hit-rate data.
- `src/clayzer/ui/static/app.js`: unknown/contradicted labels, correct retrieval and timing wording.
- `tests/test_grounding.py`: exhaustive synthetic count fixtures and changed position/unknown semantics.
- `tests/test_output_score.py` (new): 78 Output Score tests, including negative and offline integration tests.
- `scripts/output_score_demo.py` (new): scripted synthetic native/imported contract demonstration.
- `docs/caption-plan.md`: local scoring and preparation-time decisions in section 10.
- `docs/cli.md`: imported offline command reference.
- `docs/tasks.toml`: evidence-based statuses for the fourteen Output Score tasks only.
- `docs/output-score.md` (new): interfaces, scientific limits, blockers and handoff commands.

No changes to the Harness, MCP implementation, Workflow Score, deployment, or committed Baseline.

## Independent audit follow-up

The audit was read from the independent local `clayzer_output_score_audit.md` document; the requested
`docs/clayzer_output_score_audit.md` path was absent. Its recommendations were treated as review
evidence, within the user's explicit scope of fixing the two findings without changing gate policy.

Both findings were reproduced before implementation: the new audit module had **11 failing
tests and one passing safeguard**, while the existing suite passed **229 tests**.

1. **Vague captions and misleading perfect scores:** correctness remains the mean of evaluated
   asserted facts; coverage remains reference type recall. A building-present Claim with null
   count and position against three buildings east still correctly returns 1.0/1.0 under those
   narrow definitions. It now also returns `specificity.count` and `.position`, each with explicit
   `available`, `stated` and `evaluated` denominators, and `specificity.share: 0.0`. The row records
   `omitted_fields: ["count", "position"]`. This is a count/position field-coverage diagnostic,
   not another accuracy score or weighted Output Score. Wrong but detailed Claims can have full
   field coverage. Incomplete reference counts can be stated but unevaluated. Missing reference
   fields are ineligible, rather than penalized as caption omissions; a split type's field is
   fully stated/evaluated only when all matching Claims supply it/can be checked.
2. **Parent partial credit:** class slices now use the complete original matching context instead
   of filtering labels before matching. A building Claim over a greenhouse at the correct cell
   retains correctness 0.75, presence precision 0.5 and coverage 0.5 in the aggregate, the building
   slice, the greenhouse slice and the dataset diagnostics. Both claimed and matched reference
   class groups can include the same Claim; these are overlapping diagnostic groups, not disjoint
   populations. An exact building reference still takes precedence over a greenhouse reference.

Native Markdown/HTML, Run reports and standalone imported HTML prominently explain conditional
score scope. Imported HTML shows field detail before its raw JSON. Native claim tables identify
unstated fields rather than printing `None`, and unstated positions are not drawn at invented
grid cells. Historical results without diagnostics explicitly say completeness was not recorded.
The Overview wording warns that 100% is not proof of full caption quality.

Reports and provenance UI also explain that measurement-incompatible Batches are not comparable
and that gate PASS alone does not demonstrate improvement. **The gate implementation and policy
were not modified in this follow-up.** The version advances to `grounding-5` for corrected class
diagnostics; aggregate correctness/coverage formulas remain unchanged. No historical rescore or
Baseline acceptance was run.

Verification: **241 tests passed**, including all **12 audit regression cases**. Ruff and formatting
passed for all 58 checked Python files, JavaScript syntax passed, and the existing six-Run scripted
offline demo plus saved-embedding imported evaluation both completed. No real model accuracy,
human calibration or benchmark result is claimed.

Inspect the audit fixtures:

- `/tmp/clayzer-audit-fix-lk91sma9/vague/output-score.html`: unchanged 1.0/1.0 metrics, zero field
  coverage and explicit unevaluated count/position notes.
- `/tmp/clayzer-audit-fix-lk91sma9/parent/output-score.json`: consistent aggregate/class/stratum
  partial credit.
- `/tmp/clayzer-audit-fix-lk91sma9/demo/`: rerun of the existing scripted demonstration.

Follow-up files: `grounding.py`, `output_score.py`, `imported_score.py`, `report.py`,
`report_html.py`, `run_report.py`, `ui/static/app.js`, new `tests/test_output_score_audit.py`,
this handoff and the historical changelog's resolution notice. Other existing edits are preserved.
