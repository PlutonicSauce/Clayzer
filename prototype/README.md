# Caption flow walkthrough

Open [`flow-walkthrough.html`](flow-walkthrough.html) in a browser. It needs no server, install, or network.

It follows one Case through the flow in [`docs/caption-plan.md`](../docs/caption-plan.md):
Case → draft Claims → verify, then write → grounding, fidelity and retrieval → Batch and Compare → regression gate.
Pick any of three Cases (solar, wind, and a greenhouse look-alike negative), and use **Try breaking it** to see what goes wrong when:

- verify-then-write is switched off;
- the Harness can read the Answer Key ([ADR-0006](../docs/adr/0006-answer-keys-are-hidden-from-caption-inputs.md));
- positions are free text instead of the 3×3 grid ([ADR-0007](../docs/adr/0007-claims-use-a-grid-and-a-fixed-relation-vocabulary.md)).

Link to a step with `#<step>/<case>`, for example `flow-walkthrough.html#score/wind`.
Steps: `case`, `draft`, `verify`, `score`, `batch`, `gate`. Cases: `solar`, `wind`, `neg`.

## What is real and what is scripted

| Part | In the prototype |
|---|---|
| Case and Caption formats, grid, relation vocabulary | As drafted in caption-plan.md §5 |
| Grounding | Real logic: presence precision and recall, count, and grid-cell position against Reference Labels. Only `solar_array` and `wind_turbine` can be graded, because the Answer Key is USGS |
| Chips | Drawn SVGs, not NAIP |
| Harness (Nova Pro) and verifying tools | Scripted outputs |
| Fidelity Judge (Opus 5.5) | Scripted rules |
| Retrieval | Keyword-concept similarity standing in for a text embedding model; reciprocal rank |
| Gate rule and tolerance | A prototype rule to ratify on Day 1 |

The grounding formula (the mean of its four parts) and the gate rule are proposals for discussion, not agreed decisions.
