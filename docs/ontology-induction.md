# Ontology induction from a caption corpus (design)

**Status:** design only, for review — nothing built yet.
**Decision:** [ADR-0011](adr/0011-the-ontology-is-induced-from-a-caption-corpus.md). Builds on
[ADR-0008](adr/0008-object-classes-live-in-one-ontology-file.md) (one ontology file; `claimable`
vs `keyed`), [ADR-0006](adr/0006-answer-keys-are-hidden-from-caption-inputs.md) (circularity), and
[ADR-0010](adr/0010-the-ontology-is-data-driven-and-feeds-the-captioner.md) (the three layers;
Layer B demoted to enrichment).
**Chosen source (2026-11-04):** caption text (RSICD / Clay examples), not a VLM pass over Chips.
**Vocabulary:** capitalized terms (Caption, Claim, Chip, Answer Key, Object Class, Object
Ontology…) are defined in [GLOSSARY.md](../GLOSSARY.md).

## 1. Goal

Build Layers A and C of the ontology **from data**: feed a caption corpus to an LLM agent that
extracts the object vocabulary — classes, is-a children, synonyms, look-alikes, and house-style
example phrasings — and emits a candidate `objects.toml`. That ontology then feeds the Clayzer
captioning agent (ADR-0010). No embeddings required; Layer B stays optional enrichment.

Today `ontology/objects.toml` is hand-written (v0.1: 11 claimable classes under 5 roots, 9 of them
keyed). Induction replaces the hand-authoring of Layer A with a reviewed, reproducible pass over a
corpus, while leaving Layer C (the Answer-Key crosswalks) to deterministic code.

## 2. Data flow

```
caption corpus (RSICD / Clay examples, JSONL)
│ 1. load + sample (bounded, representative)
▼
MAP: extract candidates per chunk ──► {terms, proposed classes, synonyms, look-alike cues, phrasings}
│ (LLM, map over chunks)
▼
REDUCE: consolidate into one candidate ontology ──► classes + is-a hierarchy + synonyms +
│ (LLM, single pass)                                confusers + caption_exemplars
▼
RECONCILE with the anchor ──► merge induced terms into the KEYED classes + Answer-Key crosswalks
│ (code, deterministic; the agent never invents keyed_by / osm)
▼
candidate objects.toml ──► validate (tests) + human-review diff ──► adopt (bump version, update code lists)
│
Layer B (optional): embedding-measured confusers cross-check
```

## 3. The stages

### 3.1 Load and sample

The corpus is JSONL, one caption per line (RSICD reference captions converted to this shape, or
Clay's example captions). Loading **samples a bounded, representative slice** rather than the whole
corpus: enough captions to cover the vocabulary without an unbounded LLM bill, stratified by any
scene or source label the corpus carries so rare objects aren't dropped. The sample size and seed
are recorded, so a run is reproducible and its provenance is inspectable.

RSICD has no clear licence (caption-plan.md §8), so the corpus is downloaded at run time and never
committed, and the induced ontology carries only short exemplar phrasings, never bulk corpus text.

### 3.2 Map — extract candidates per chunk

The sample is split into bounded chunks, and an LLM extracts, per chunk, a structured record:

- **terms** — object words and phrases the captions use;
- **proposed classes** — the objects worth a class, with a suggested is-a parent;
- **synonyms** — words that name the same object ("solar farm", "PV plant", "photovoltaic array");
- **look-alike cues** — pairs captions confuse or contrast (a greenhouse read as a solar array);
- **phrasings** — short, house-style example sentences, for the captioner's prompt.

Map is independent per chunk, so it parallelises and a failed chunk is retried alone. Each call is
a Step in the induction Trace (same Trace format as a caption Run), so the pass is observable.

### 3.3 Reduce — consolidate into one candidate ontology

A single LLM pass folds the per-chunk candidates into one ontology: it merges synonymous terms,
settles the is-a hierarchy (at most three levels, per ADR-0008), keeps the confuser pairs, and
selects a few `caption_exemplars` per class. Output is a draft class list with Layer-A fields
(`id`, `name`, `parent`, `synonyms`, `confusers`, exemplars) — **no** `keyed_by`, `osm`, or
`queries`: those belong to Layer C.

### 3.4 Reconcile — merge with the anchor (code, deterministic)

The anchor is the current `objects.toml`. Deterministic code, not the LLM, reconciles the draft
against it (this is the Layer-C guarantee of ADR-0010 and the ADR-0006 firewall):

- **Keyed classes are preserved.** Every class with an Answer Key in the anchor keeps its
  `keyed_by`, `osm`, and `queries` exactly. Induction may add synonyms, confusers, and exemplars
  to a keyed class, but may not change what verifies it.
- **New classes land as `claimable` but un-keyed.** An induced class with no anchor match is added
  with `claimable = true` and no `keyed_by`; its Claims are scored as unscored (reported, not
  counted) until a human attaches an Answer Key, exactly as `vegetation` and `bare_ground` are
  today.
- **The agent never invents a crosswalk.** `keyed_by` and `osm` are only ever copied from the
  anchor or added by a human reviewer, never emitted by the LLM.

### 3.5 Validate, review, adopt

The candidate `objects.toml` is run through `tests/test_ontology.py` (the file parses, parents
resolve, no duplicate ids, the code lists still agree) and presented as a **diff against the
anchor** for human review: classes added or merged, synonyms and confusers gained, exemplars
chosen. Adoption is a deliberate step — a version bump (0.1 → 0.2) and any code-list update — never
automatic. The induction Trace, the sample's provenance, and the diff travel with the proposal.

### 3.6 Layer B — embedding-measured confusers (optional)

As enrichment only (ADR-0010), the induced confuser pairs can be cross-checked against how close
two classes sit in embedding space: pairs the corpus flags but embeddings place far apart are
worth a second look, and vice versa. This needs an embedding model, so it is never a blocker on
adoption and can be added after Layers A and C are in.

## 4. What this is not

- **Not a VLM pass over Chips.** The source is caption text; images are never read (ADR-0011).
  Induction runs and reviews offline, with no imagery fetch and no image model.
- **Not an Answer-Key author.** The LLM proposes vocabulary; code owns `keyed_by` and `osm`, so
  induction cannot change what grounding scores (ADR-0006).
- **Not automatic adoption.** Induction emits a candidate; a human reviews the diff and bumps the
  version. The ontology stays a small, reviewed, hand-adoptable file (ADR-0008).

## 5. Open questions (for review)

- **Sample size and stratification.** How many captions, split how, to cover rare objects without
  an unbounded bill? Needs a first run on RSICD to calibrate.
- **New-class threshold.** How often must a term appear across chunks before it earns a class,
  rather than a synonym of an existing one?
- **Exemplar selection and licence.** How many phrasings per class, and how short, to stay well
  inside RSICD's unclear licence while still guiding the captioner.
- **Re-induction cadence.** Is this a one-off bootstrap, or re-run when Clay's real caption set
  arrives? The reconcile step is built to re-run against any anchor, so either works.

## 6. Traceability

| Closes / supports | Where |
|---|---|
| ADR-0010 Layers A and C, built from data | §1–§4 |
| ADR-0011 corpus source, map–reduce–reconcile | §2–§3 |
| ADR-0008 one small reviewed file; ≤ 3 levels | §3.3, §3.5 |
| ADR-0006 nothing that writes the ontology reads an Answer Key | §3.4, §4 |
| CAP-22 ontology feeds the dataset card's per-class error patterns | the card already reads `objects.toml` |
