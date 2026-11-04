# Regression gate: adversarial audit

## What the offline evidence establishes

The first 40 adversarial test cases produced 34 failures against the earlier implementation.
These included false passes, uncontrolled input errors, and loss of the previous Baseline on a
failed file write. Additional tests reproduced a Batch identity collision: two attempts with
the same label and timestamp reused a store folder, allowing the second attempt to skip evaluation.

The implementation now checks score types, ranges and finiteness; both sides' Spreads; Run
identities and counters; actual per-Run scores against saved summaries; partial metric and cost
samples; and changed or absent measurement provenance. A malformed input is an error, not a pass.
Both `gate` and `experiment` return inconclusive for incomparable evidence unless a separate
failure has already been established. Batch ids include a unique identifier.

Baseline files are serialized before the old Baseline is touched and written to a staged
directory. A local lock coordinates readers and writers. Failed replacement restores the old
directory, and a read recovers an interrupted replacement. Experiments check a content snapshot
before promotion, preventing an experiment evaluated against an older Baseline from overwriting
a newer one. Names and symlinks cannot redirect Baseline reads or writes outside their directory.

Tests inject errors before and after promotion, including simulated S3 `AccessDenied` responses.
A kept experiment's receipt is published with its Baseline. If the external log is unavailable
after that, the CLI reports that promotion happened and offers `experiment-recover` to reconstruct
the log. Tests verify that recovery can be repeated and that concurrent readers do not observe
half-written Baselines. This is not a distributed transaction or a power-loss durability test.

Run the offline gate suite:

```sh
uv run --extra ui --extra tools pytest \
  tests/test_gate.py tests/test_gate_adversarial.py tests/test_baseline_failures.py \
  tests/test_experiments.py tests/test_loop.py tests/test_ui.py -v
```

## Limits that a green suite does not remove

1. **The acceptance rule is a heuristic.** It allows a drop up to the larger of 0.05 and the
   Baseline's sample standard deviation. One test demonstrates that 0.80 to 0.60 passes with
   a Baseline Spread of 0.30. This follows the existing rule; it is not evidence that such a
   drop is acceptable for the intended use.
2. **Successive promotions can drift downward.** Another test shows five successive drops of
   0.04 each passing against the previous result, accumulating a drop of 0.20. A fixed anchor,
   a maximum allowed loss and absolute minimum quality levels are policy choices still needed.
3. **No quality floor or improvement requirement.** An unchanged poor captioner can pass.
   `--accept` means the user chose to keep a passing candidate; it does not prove improvement.
4. **Model accuracy is unverified here.** The fake Judge and captions check plumbing. These
   tests do not validate the real Judge, Reference Labels, imagery alignment, the proposed
   coverage prompt, or benefits to Clay v2 training. Classes with no Answer Key remain unscored.
5. **Coverage is limited to the Cases evaluated.** The committed Baseline now has 63 Cases,
   but its older export omitted per-Run Workflow Scores, preventing verification of those
   means. Re-accept it from a complete source Batch. The current development fixtures have
   not been evaluated in this offline task. Held-out geographical Cases must remain separate
   from prompt tuning, with independently checked examples of omissions and hallucinations.
6. **Files remain editable.** Consistency checks detect stale or mismatched artifacts, not
   coordinated fabrication of all scores, hashes and summaries. Git commit plus a dirty flag
   also cannot establish equality of two different uncommitted code versions. Review traces
   and freeze the evaluation code for actual experiments.
7. **Coordination is local.** The lock covers one Baseline directory on a Mac/Linux filesystem.
   It does not coordinate separate teammates' clones or provide an S3-wide acceptance lock.
   Storage tests use local stores and simulated S3 failures, not a live S3 integration.
8. **Cheap web previews read summaries.** The explicit gate API and CLI validate Run results.
   Overview summaries are not an independent verification of the underlying scores.

Before using results for substantive decisions, the team still needs independent checks of
Reference Labels and Judge verdicts, real unchanged-control and deliberately degraded runs,
and a frozen held-out evaluation. Decide acceptable losses and quality floors based on the
consequences of errors. The existing gate should not be represented as proof of real-world reliability.
