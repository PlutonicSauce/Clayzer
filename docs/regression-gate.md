# Regression gate: running a prompt experiment

Step 9 compares a candidate Batch against an accepted Baseline. The gate already exists;
`clayzer experiment` adds a saved decision and optional promotion. It uses stored scores,
with no model calls. Generating a new Batch still calls Bedrock.

## Local verification

```sh
uv run --extra ui --extra tools pytest tests/test_gate.py tests/test_gate_policy.py tests/test_experiments.py tests/test_loop.py
```

These tests use fake Bedrock responses and temporary stores. They cover passing, regressed,
and incomplete Batches; the Baseline's Spread; exact threshold boundaries; token caps; missing
Cases and Repeats; one-change experiments; recording decisions; and guarded promotion.
They verify the workflow, without claiming that a prompt improves real captions.

The [adversarial audit](regression-gate-audit.md) includes the additional corruption,
concurrency, disk failure, and recovery tests, plus policy limitations that remain.

## Enforcing the bounded policy

Use the versioned policy for acceptance decisions:

```sh
uv run clayzer gate <candidate-batch-id> --policy policies/regression-gate.json
uv run clayzer experiment <candidate-batch-id> \
  --policy policies/regression-gate.json --hypothesis "Describe the one change"
# After reviewing the recorded comparison, repeat the experiment with --accept to keep it.
```

The supplied policy caps every allowed score drop at **0.05** (five points on the
0–100 display), including retrieval, even when the Baseline's Spread is larger.
This retains the existing tolerance as the maximum loss budget; it is not a claim
that a five-point loss is acceptable for every use case.

Candidates must also pass against `baselines/regression-anchor/`, a frozen copy of
the complete `20261104T211847Z-dev74-base` Baseline: 74 Cases × 3 Repeats.
The policy pins its configuration, summary and score rows by SHA-256. Moving the
working Baseline after a promotion never moves this reference, so successive small
losses cannot silently accumulate beyond the fixed margin. A missing or edited
anchor is an error; a changed measuring setup remains inconclusive. An experiment
cannot promote into the anchor's name. Establishing a new reference after a
measurement change requires explicit review of the new baseline and policy hash.

Policy version 1 also supports:

- `minimum_scores`: a mapping of `correctness`, `coverage`, `fidelity`, `workflow`
  or `retrieval` to required scores in `[0, 1]`. Quality metrics are checked per
  Case, retrieval per Batch. Scores not applicable on both sides are skipped;
  an entirely unmeasured required metric cannot pass. For example,
  `"minimum_scores": {"correctness": 0.8}` requires at least 0.8 on every measured
  Case. This is an example, not a validated threshold.
- `require_improvement`: when true, at least one score must improve beyond its
  allowed margin versus the working Baseline. An unchanged control then fails
  this optional requirement. The supplied policy leaves it false so control
  reruns can pass.
- `max_allowed_drop`: a non-negative cap up to 1; set to `0` for no score losses
  beyond numerical boundary tolerance.

No absolute floors are imposed in the supplied policy: the team must choose
them from the consequences of errors and independently checked examples.
Invalid versions, misspelled fields, duplicate JSON fields, non-finite numbers
and unpinned anchors are refused. Logs and promotion receipts include the exact
policy, anchor configuration and snapshot, and all anchor comparisons.

`--policy` is explicit: commands without it, the web previews and spoken summaries
retain the original gate rule for compatibility. Use the policy-bearing CLI result
and experiment receipt for this stricter acceptance workflow. The policy does not
automatically gate the dollar/GPU metrics shown in comparison reports; the existing
`--max-token-increase` option still supplies an optional token cap.

## First real experiment

Use development Cases only. Freeze the same Cases, Chips, Judge, rubric, embedding model,
ontology, scorer, and Repeats for both Batches. A prompt experiment changes only the prompt;
leave the caption model, tool list, turn budget, and verifier unchanged.

The committed Baseline now contains 74 development Cases and complete per-Run
Workflow Scores. Its unchanged comparison passes the existing gate. The latest
`20261105T011537Z-dev74-absence` Baseline uses the updated Output Score and solar
absence labels; it is incompatible with the older pinned regression anchor.
The stricter policy therefore does not pass that comparison. Pulling main does
not automatically replace the frozen reference. Review a new reference and its
snapshot before using this policy for the updated measurement setup.
The earlier incomplete 63-Case export is no longer the baseline. For a fresh real
experiment, run a control and verify its measurement configuration against the
reviewed anchor before testing changes:

```sh
uv run clayzer push --from fixtures/caption
uv run clayzer batch --repeats 3 --label gate-control --no-narrate
uv run clayzer baseline accept <control-batch-id>
uv run clayzer batch --repeats 3 --label coverage-v1 --prompt prompts/coverage-v1.txt --no-narrate
uv run clayzer experiment <candidate-batch-id> \
  --policy policies/regression-gate.json \
  --hypothesis "A final scan of all nine cells improves coverage without reducing correctness or fidelity"
```

`prompts/coverage-v1.txt` is an **untested candidate**, consisting of the built-in prompt plus
one final coverage scan instruction. The built-in prompt and committed Baseline remain unchanged.
The commands above use the full development set and incur model usage; choose Repeats and a
spending limit before running them. Keep the same `--tools` and `--verify` options on the control
and candidate if evaluating an agentic Harness.

Review the saved Markdown report. To keep a passing candidate:

```sh
uv run clayzer experiment <candidate-batch-id> \
  --policy policies/regression-gate.json \
  --hypothesis "A final scan of all nine cells improves coverage without reducing correctness or fidelity" \
  --accept
```

The command returns 0 for pass, 1 for regression or missing scores, and 2 for inconclusive.
`--accept` replaces the named Baseline only after a passing decision. A pass means no measured
regression beyond the gate's tolerance; review the comparison to assess whether anything improved.
A changed measurement setting, newly unrecorded provenance, or different Repeats makes the
experiment inconclusive. A failed or incomplete attempt still gets a record. Resume an
interrupted Batch with `clayzer batch --resume <id>`, then evaluate it again.

## The experiment log

Every invocation writes a new pair of files under
`batches/<candidate-id>/experiments/<timestamp>-<unique-id>.json` and `.md` in the configured
store. The CLI prints both addresses. The JSON records the hypothesis, both configurations,
thresholds, per-score checks, reasons, warnings, comparison, and decision:

| Decision | Meaning |
|---|---|
| eligible | Passed; not promoted |
| kept | Passed and promoted with `--accept` |
| rejected | Regressed or missing Baseline Cases/scores |
| inconclusive | Incomplete or not comparable |

Earlier records retain the Baseline used at that moment, even after a later promotion or rescore.
Copy each Markdown log into the PR (including rejected attempts), and commit a promoted
`baselines/<name>/` plus the prompt file to share them. `--baseline <name>`, `--tolerance`, and
`--max-token-increase 0.5` work on both `gate` and `experiment`. The plain `gate` command remains
a read-only score comparison. Both commands prevent a pass when measurement settings change
or essential measurement provenance is missing, even when it is missing on both sides.

Local Baseline writes are staged and coordinated by a filesystem lock; a stale experiment
cannot overwrite a newer Baseline. A successful promotion includes an `experiment.json` receipt
inside the Baseline directory. This local write and the store's log writes are separate operations.
If a later log write fails, the command explicitly says the Baseline **was promoted**. Restore
the store and run `clayzer experiment-recover --baseline <name>` to recreate both log formats.
An outage before the initial record is saved leaves the old Baseline in place.

The automatic Proposer remains deferred. Real prompt improvement and acceptance on the team's
data remain to be measured; offline tests do not complete that evaluation task.
