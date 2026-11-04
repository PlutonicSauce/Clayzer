# Hand-made Claims for calibrating extraction

`sample.jsonl` holds 20 real Captions (12 from the Baseline Batch, 8 from the first `--verify`
Batch), one per line, each with `"claims": null`. The easiest way to label them is the web app:

```sh
uv run clayzer ui --calibrate      # then open http://127.0.0.1:8770/label
```

It shows one caption at a time, its text only, with a form for objects (type, count, a 3×3 grid
for position, "not stated" for either), relations, and hedged phrases. Each save is checked and
written straight into `sample.jsonl`; commit the file when you're done. To edit the file by hand
instead, replace `null` with the Claims the caption's **text** makes, in the format
`clayzer extract` writes (ADR-0007):

```json
{"objects": [{"id": "o1", "object": "solar_array", "count": 1, "position": "centre"}],
 "relations": [{"subject": "o2", "relation": "west_of", "object": "o1"}],
 "uncertain": ["possibly a pond"]}
```

- Label what the text says, not what you think is in the image: you don't need the image.
- `object` is a class id from `ontology/objects.toml` (its synonyms say which words mean it).
- `count` is the number the text gives ("a" = 1); `null` for "several", "some", or a plural
  without a number.
- `position` is a 3×3 cell (`north_west` … `centre` … `south_east`); `null` if the text
  doesn't say where.
  - **One thing that spans cells** ("a large solar array in the west and center") is **one**
    Claim, at the first cell named. Two would read as two arrays: counts add up per type.
  - **Several things, or spread land cover, in different areas** ("several buildings to the
    north and west", "vegetation in the north and west") is **one Claim per area**, each with
    the same count rule (usually not stated).
  - **A group with one total spread over areas** ("two wind turbines in the west and
    north-west") is **one** Claim with that count, at the first cell named: one per area would
    lose the count, which is worth more than the second position.
- Hedged things ("likely", "may be", "appears to be") go in `uncertain`, not `objects`.
- Relations only when the text states one in words; don't add ones that follow from positions.
  "X surrounded by Y", "X within Y", "Y around X" → X `inside` Y. "X next to Y", "X bordering
  Y" → X `adjacent_to` Y. "X between Y and Z" → X `between` Y (the first named).

**Proposals and blind captions.** 15 captions come with a label proposed by the extractor
(`proposed`, `proposed_by`): check every field against the text and fix anything wrong. 5 are
`blind`, one or more per Case: no proposal, label them from scratch. A checked proposal pulls you
toward the model's answer, so only the blind ones are an unbiased check; each saved label
records its `source` ("proposal accepted", "proposal edited", "blind", "by hand"), and
calibration reports each group and how many proposals were changed. Then:

```sh
uv run clayzer extract --labels labels/extraction/sample.jsonl
```

Lines still `null` are skipped, so it can be run part-way. The result goes to the store under
`calibration/extraction/sample/`.
