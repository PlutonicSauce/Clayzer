# Regression gate: running a prompt experiment

Step 9 compares a candidate Batch against an accepted Baseline. The gate already exists;
`clayzer experiment` adds a saved decision and optional promotion. It uses stored scores,
with no model calls. Generating a new Batch still calls Bedrock.

## Local verification

```sh
uv run --extra ui --extra tools pytest tests/test_gate.py tests/test_experiments.py tests/test_loop.py
```

These tests use fake Bedrock responses and temporary stores. They cover passing, regressed,
and incomplete Batches; the Baseline's Spread; exact threshold boundaries; token caps; missing
Cases and Repeats; one-change experiments; recording decisions; and guarded promotion.
They verify the workflow, without claiming that a prompt improves real captions.

The [adversarial audit](regression-gate-audit.md) includes the additional corruption,
concurrency, disk failure, and recovery tests, plus policy limitations that remain.

## First real experiment

Use development Cases only. Freeze the same Cases, Chips, Judge, rubric, embedding model,
ontology, scorer, and Repeats for both Batches. A prompt experiment changes only the prompt;
leave the caption model, tool list, turn budget, and verifier unchanged.

The committed Baseline now contains 63 development Cases. Its older score-only export omitted
Workflow Scores from individual Run records, so the gate cannot verify those summary values
and reports incomplete evidence. Re-accept it from the original complete Batch, or run a fresh
control on the current fixtures and accept that before testing changes:

```sh
uv run clayzer push --from fixtures/caption
uv run clayzer batch --repeats 3 --label gate-control --no-narrate
uv run clayzer baseline accept <control-batch-id>
uv run clayzer batch --repeats 3 --label coverage-v1 --prompt prompts/coverage-v1.txt --no-narrate
uv run clayzer experiment <candidate-batch-id> \
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
