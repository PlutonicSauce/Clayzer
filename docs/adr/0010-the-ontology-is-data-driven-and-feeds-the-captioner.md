# The Object Ontology is data-driven and feeds the captioner

ADR-0008 made `ontology/objects.toml` the one place Object Classes are defined, but the ontology
only ever flowed *out* of captioning: it scored and retrieved, it never helped write a Caption.
This ADR extends it into the caption step as retrieval-augmented, class-level guidance, in three
layers, so the captioner knows the vocabulary, the look-alikes, and the house style before it
writes — the team's data-driven differentiator.

- **Layer A — symbolic (already in the file).** Classes, is-a hierarchy, allowed attributes,
  look-alikes (`confusers`), and `min_visible_m`. Injected into the prompt as a compact
  look-alike caution.
- **Layer C — caption exemplars (new, `caption_exemplars` in `objects.toml`).** One or two
  short, **class-level** caption phrases per keyed class, in house style, injected as few-shot
  examples. They teach phrasing (helping retrieval and fidelity); they never state what is in a
  particular Chip.
- **Layer B — embedding prototypes (new, a generated sidecar).** The centroid of a few confirmed
  example Chips' Clay/LGND embeddings per class, built once from a disjoint development region
  and stored in `ontology/prototypes/<version>.json` (`prototypes.py`). At caption time the
  Chip's own already-published embedding is matched against the centroids and the nearest classes
  become a one-line prompt hint, disambiguating look-alikes with no second vision call.

`objects.toml` stays the small, hand-curated, diff-able symbolic layer (A and C). The learned
part (B: centroids, measured look-alikes, counts) is a generated artifact, versioned by ontology
version, never hand-edited. Layers A and C are always available; Layer B is used only when a
prototype file and a Chip embedding both exist, and is silently skipped otherwise, so the feature
degrades to zero extra cost rather than failing.

## Two constraints are first-class, not afterthoughts

**Circularity (ADR-0006).** The captioner must not be fed knowledge distilled from the very Chips
it is scored against. So every exemplar and prototype is **class-level** ("what a solar array
looks like in general"), built from a **development region disjoint** from the scored region
(the ADB split, CAP-16), and from **Clay/LGND embeddings, which are not an Answer Key** we grade
against (we grade against USGS and OSM). Caption exemplars are generic phrases, never a label for
a scored Chip. `prototypes.guard_scoring_region` refuses, mechanically, to use prototypes to
caption the region they were built on.

**Cost and latency (a nonprofit pitch).** Layer B adds **no model call**: it reuses an embedding
Clay/LGND already published, so each Caption costs one in-memory dot product over a handful of
centroids and ~20 prompt tokens. `LAYER_B_CLASSES` restricts prototypes to classes discriminable
at Sentinel-2's 10 m (solar arrays, fields, water, parking, land cover) and excludes small or
thin objects (wind turbines, roads, individual buildings) that 10 m embeddings can't separate. A
hint is emitted only above a similarity floor, so tokens — and anchoring — aren't spent on noise.
The Layer A+C block is a fixed prefix, so Bedrock prompt caching can absorb it (caption-design.md
§16). If reusing Clay/LGND embeddings proves infeasible, Layer B drops out and A + C stand alone.

## Consequences

Caption free text stays free; only Claims use ontology classes (ADR-0008 unchanged). The feature
is a Batch option (`ontology_context`, default off), recorded in the Batch's provenance, so its
effect is measured by the existing loop — Batches, Compare, the regression gate — and a version
of the ontology is kept only if it raises grounding or retrieval without inflating cost. That
measurement *is* the differentiator: the ontology is shown to help, not asserted to. Adding Layer
C exemplars did not change any class, key, OSM rule, synonym, attribute, or query, so every
`tests/test_ontology.py` crosswalk from ADR-0008 still holds; the ontology version is 0.1 → 0.2.
