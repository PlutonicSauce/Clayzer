# Frozen regression reference

This is a score-only copy of the accepted `20261104T211847Z-dev74-base` Baseline
at commit `1d98631`: 74 development Cases, three Repeats and complete Workflow
Score samples. No new model evaluation was performed to create this copy.

`policies/regression-gate.json` pins `batch.json`, `summary.json` and
`results.jsonl` using `clayzer.baseline_files.snapshot`. Policy-aware experiments
read this reference but cannot promote over it. It stays fixed when the working
`default` Baseline advances. Never update it automatically on candidate acceptance.

If the Cases, labels, scorer, Judge, rubric or other measuring configuration
changes, evaluate the new reference, review the policy change and update its
snapshot explicitly. No policy-bearing comparison can pass with a mismatched
snapshot or incompatible measurement configuration.
