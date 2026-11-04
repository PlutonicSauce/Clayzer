# Caption flow walkthrough

Open [`flow-walkthrough.html`](flow-walkthrough.html) in a browser. It needs no server, install, or network.

It follows one Case through the flow in [`docs/caption-plan.md`](../docs/caption-plan.md):
Case → draft Claims → verify, then write → Trace → grounding, fidelity and retrieval → Batch and Compare → regression gate.

Pick one of four Cases: solar, wind, a greenhouse look-alike negative, and a **Change Case**. The Change Case is a 2018/2022 Chip Pair where a solar array appeared; USGS records it as installed in 2020.

## The side panel

**Answer Keys**
- **Add OpenStreetMap as an Answer Key.** Roads, fields and greenhouses become gradable, and so do relations ("a road south of the greenhouses"). USGS alone knows only solar and wind, and has no relations.
- **Road check reads OSM.** This is allowed on its own. Combined with the option above, it breaks [ADR-0006](../docs/adr/0006-answer-keys-are-hidden-from-caption-inputs.md): road Claims are confirmed and graded by the same data. The scores don't change, which is the point.

**Try breaking it**
- **Verify, then write** off: every drafted Claim goes into the Caption.
- **Let the Harness read the Answer Key** ([ADR-0006](../docs/adr/0006-answer-keys-are-hidden-from-caption-inputs.md)): grounding becomes perfect by copying.
- **Free-text positions** ([ADR-0007](../docs/adr/0007-claims-use-a-grid-and-a-fixed-relation-vocabulary.md)): position becomes uncheckable.
- **Inject a failure into the Run.** See how each failure type is classified on the Trace step:

  | Failure | What happens |
  |---|---|
  | Soft Failure | Success status with an error body; a true Claim is dropped |
  | Harness Fault | A guessed Chip id; counts against the Workflow Score |
  | Environment Fault | A TLS failure; doesn't count against the Harness |
  | Sandbox Failure | No valid score; one Repeat is excluded from the Batch instead of being scored 0 |

## Links

Link to a step with `#<step>/<case>`, for example `flow-walkthrough.html#trace/wind`.
- Steps: `case`, `draft`, `verify`, `trace`, `score`, `batch`, `gate`.
- Cases: `solar`, `wind`, `neg`, `change`.

## What is real and what is scripted

| Part | In the prototype |
|---|---|
| Case and Caption formats, grid, relation vocabulary, `change` field | As drafted in caption-plan.md §5 |
| Grounding | Real logic, scored against Reference Labels from USGS, plus OSM when that option is on:<br>• presence precision and recall<br>• count<br>• grid-cell position<br>• change (Change Cases)<br>• relations, compared as (subject type, relation, object type) |
| Chips | Drawn SVGs, not NAIP |
| Harness (Nova Pro), verifying tools, Trace contents | Scripted outputs |
| Fidelity Judge (Opus 5.5) | Scripted rules |
| Retrieval | Keyword-concept similarity standing in for a text embedding model; reciprocal rank |
| Workflow Score, gate rule and tolerance | Prototype rules to ratify on Day 1 |

The grounding formula (the mean of the parts that apply), the Workflow Score rule, and the gate rule are proposals for discussion, not agreed decisions.
