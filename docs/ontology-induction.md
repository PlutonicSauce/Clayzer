# Ontology induction from a caption corpus (design)

**Status:** design only, for review — nothing built yet.
**Decision:** [ADR-0011](adr/0011-the-ontology-is-induced-from-a-caption-corpus.md). Builds on
[ADR-0008](adr/0008-object-classes-live-in-one-ontology-file.md) (one ontology file; `claimable`
vs `keyed`), [ADR-0006](adr/0006-answer-keys-are-hidden-from-caption-inputs.md) (circularity), and
[ADR-0010](adr/0010-the-ontology-is-data-driven-and-feeds-the-captioner.md) (the three layers;
Layer B demoted to enrichment).
**Chosen source (2026-11-04):** caption text (RSICD / Clay examples), not a VLM pass over chips.

## 1. Goal

Build Layers A and C of the ontology **from data**: feed a caption corpus to an LLM agent that
extracts the object vocabulary — classes, is-a children, synonyms, look-alikes, and house-style
example phrasings — and emits a candidate `objects.toml`. That ontology then feeds the Clayzer
captioning agent (ADR-0010). No embeddings required; Layer B stays optional enrichment.

## 2. Data flow

```
caption corpus (RSICD / Clay examples, JSONL)
   │  1. load + sample (bounded, representative)
   ▼
MAP: extract candidates per chunk  ──► {terms, proposed classes, synonyms, look-alike cues, phrasings}
   │  (LLM, map over chunks)
   ▼
REDUCE: consolidate into one candidate ontology  ──► classes + is-a hierarchy + synonyms +
   │  (LLM, single pass)                                confusers + caption_exemplars
   ▼
RECONCILE with the anchor  ──► merge induced terms into the KEYED classes + Answer-Key crosswalks
   │  (code, deterministic; the agent never invents keyed_by / osm)
   ▼
candidate objects.toml  ──► validate (tests) + human-review diff  ──► adopt (bump version, update code lists)
                                                                          │
                                       Layer B (optional): embedding-measured confusers cross-check
```

## 3. Corpus format

Reuse the assumed Caption-Set import format already designed for CAP-20
([caption-design.md §3.6](caption-design.md#assumed-import-format-to-confirm-with-clay)): one
record per caption with at least `caption` text; `kind`, `sensor`, `gsd_m`, location optional. For
induction we need only the **text** (and any scene/class hint). An RSICD adapter converts RSICD's
reference captions to this format; Clay's example captions slot in the same way when they arrive.

## 4. Methodology: Noy & McGuinness's seven steps, applied

The agent prompts follow *Ontology Development 101* (Noy & McGuinness, 2001). Their seven steps
map onto our pipeline, and their modeling rules become the agent's instructions and the
validator's checks. Their three **fundamental rules** frame everything:

1. *No single correct model — the best one depends on the application and anticipated extensions.*
   So the agent optimises for **our** task (captioning + grounding + retrieval), not abstract
   correctness.
2. *Ontology development is iterative.* Hence map → reduce → reconcile → review, re-runnable.
3. *Concepts are the nouns (objects) and verbs (relationships) in sentences describing the domain.*
   Captions **are** those sentences — so classes come from noun phrases, relationships from the
   spatial verbs/prepositions.

| N&M step | In this pipeline |
|---|---|
| 1. Domain & scope, via **competency questions** | Fixed by our task (§4.1); handed to the agent as the scope it must cover and not exceed |
| 2. **Reuse** existing ontologies | The anchor (keyed classes + OSM/USGS/NLCD/WorldCover/RSICD crosswalks) is the reuse; the agent maps onto it, never reinvents it (§5) |
| 3. **Enumerate terms** | MAP step: list candidate object noun-phrases from captions, overlaps and all |
| 4. **Classes & hierarchy** | REDUCE step: is-a hierarchy, combination approach, with N&M's structural rules (§4.2) |
| 5. **Properties (slots)** | Attributes (`size`, `surface`), the relationship vocabulary (ADR-0007), and the "is typically found near" relation between classes (ADR-0012) — which the agent can propose from how often classes co-occur in captions |
| 6. **Facets** | Allowed attribute values (enumerated) and count cardinality |
| 7. **Instances** | N/A to the ontology — chips and their Claims are the instances, created downstream |

### 4.1 Competency questions (our scope, per N&M step 1)

The ontology must contain exactly enough to answer these — the litmus test for what to include and
what to leave out (N&M: *"do not specialise or generalise more than you need … at most one extra
level each way"*):

- What object classes can a caption **claim**, and which are **scored** against an Answer Key?
- For a given object, what **look-alikes** must the captioner be warned to tell apart?
- What **house-style phrasing** describes each class?
- What **synonyms** should retrieval expand a query onto ("solar farm" → solar_array)?
- Which classes are **kinds of** a broader class (for partial-credit grounding, ADR-0008)?

Anything a caption/grounding/retrieval step never needs (soil chemistry, ownership, price) is out
of scope and must not be induced.

### 4.2 The agent (map → reduce), with N&M's rules baked into the prompts

- **Model:** a strong model for extraction quality — Opus 5.5 (the Judge model) — through the one
  Bedrock abstraction (AWS-01). One-time, bounded run; never per caption.
- **MAP (N&M step 3, enumerate terms).** Chunk the corpus (batch N captions per call). Per call,
  extract candidate object **noun-phrases**, any **synonyms** used for the same thing, textual
  **look-alike** cues ("looks like", "resembles", frequent co-mention), and 1–2 lightly-cleaned
  **exemplar phrasings** in the corpus's style. Enumerate freely; do not resolve overlaps yet.
- **REDUCE (N&M steps 4–6).** One consolidation call turns candidates into a hierarchy under
  the structural rules below.
- **Structured output.** JSON mirroring `ObjectClass`: `id, name, parent, claimable, synonyms,
  confusers, attributes, caption_exemplars`. The agent **never** emits `keyed_by`, `osm`, or
  `land_cover` — those belong to the anchor (§5).
- **Provenance.** Record corpus id, model, prompt hash, date; written to the ontology header.

**Rules embedded verbatim in the REDUCE prompt (from N&M §4–6):**

- *is-a means kind-of:* make B a child of A only if **every** instance of B is necessarily an A
  (a greenhouse is a kind of building; a solar array is **not** a kind of parking lot).
- *A class is a concept, not a word:* **synonyms never become their own class** — "PV plant",
  "photovoltaic array", "solar farm" are synonyms of one `solar_array` class (N&M §4.1).
- *New class vs. property value (the key decision):* introduce a subclass **only** if it (1) has
  extra properties, (2) has different restrictions, or (3) enters different relationships than its
  parent. Otherwise it is a **property value**. So "large solar array" is a `size` attribute value,
  **not** a class; "ground-mounted vs. rooftop solar" is a subclass only if we score or relate them
  differently. *A class an instance belongs to should not change often* — transient/extrinsic traits
  stay attributes (N&M §4.4–4.5).
- *Siblings:* direct children of a class sit at the **same level of generality**, and number
  **roughly 2–12** — a lone child signals a modelling gap; >12 wants intermediate categories
  (N&M §4.2).
- *Naming:* consistent, singular, no abbreviations, no "class/type" suffixes; sibling names
  consistently include-or-exclude the parent term; `snake_case` id + Title `name` (N&M §6).
- *No cycles; ≤3 levels* (ADR-0008); *disjointness* noted where real (solar_array vs. greenhouse
  are disjoint) so the validator can flag a child placed under two disjoint parents.
- *Scope limit:* include only salient properties and at most one extra level of depth beyond what
  the competency questions need (N&M §4.7).

## 5. Reconciliation with the anchor (the critical, deterministic step)

The **anchor** is the keyed classes and their Answer-Key crosswalks (`keyed_by`, `osm`,
`land_cover`), maintained by humans against USGS/OSM — never LLM-invented. Reconciliation:

1. **Match** each induced class to an anchor class by name/synonym (and, if a prototype file
   exists, by embedding nearest-centroid as a tiebreak — the one place Layer B helps here).
2. **Merge** matches: induced synonyms/confusers/exemplars enrich the anchor class; the induced
   label becomes a synonym, not a duplicate class ("photovoltaic array" → `solar_array`).
3. **Admit** unmatched induced classes as new **claimable-but-unkeyed** classes (allowed by
   ADR-0008; their Claims are reported unscored until an Answer Key covers them).
4. **Preserve** every keyed class and crosswalk exactly, so grounding and retrieval keep working.

Output: a candidate `objects.toml` = anchored keyed classes + induced enrichment.

## 6. Validation and adoption

Two layers of checks before a candidate becomes the ontology:

**Contract checks (existing `tests/test_ontology.py`):** `claimable()` must equal
`harness.OBJECTS`, `keyed()` equal `grounding.KEYED`, `queries()` match, hierarchy ≤3 levels and
acyclic, confusers are known classes, OSM rules map to their class. Adding a claimable class means
updating the code lists in lockstep — enforced by the test, which *is* the human-review trigger.

**Structural checks (new, from N&M — a `clayzer ontology lint` over the candidate):** these catch
the modelling errors the paper warns about, so a reviewer sees them as warnings on the diff:
- *is-a sanity:* every child is plausibly a "kind of" its parent (flag suspicious placements).
- *siblings:* warn on any class with exactly **one** child, or with **>12** children (N&M §4.2).
- *no synonym-classes:* a candidate class whose name is already a synonym of another class is an
  error (N&M §4.1) — it must be merged in reconciliation (§5).
- *naming:* singular, consistent, no abbreviations/"class" suffixes; sibling names uniformly
  include-or-exclude the parent term (N&M §6).
- *class-vs-value smell:* a class distinguished from its parent only by an adjective that matches
  an existing attribute value (e.g. a "large_solar_array" class vs. the `size` attribute) is
  flagged as a probable property-value, not a class (N&M §4.5).
- *disjointness:* a class placed under two parents declared disjoint is an error (N&M §4.8).

Adoption bumps the ontology version (0.2 → 0.3) and is reviewed as a diff. The candidate is written
to a side path (`ontology/candidates/vNEXT.toml`) first, never straight over `objects.toml`.

## 7. Circularity, cost, and limits

- **Circularity (ADR-0006):** induce from a corpus disjoint from the scored chips (RSICD or a dev
  region), class-level only. The agent sees captions, never a scored chip's Answer Key.
- **Cost:** bounded one-time LLM calls (map over a caption sample + one reduce). Nonprofit-
  friendly; no GPU, no per-caption cost.
- **Limits:** an LLM can over-split or hallucinate classes; the anchor + tests + human review
  contain that. Text-only induction can't discover a purely *visual* class that captions never
  name — that's where the optional VLM-over-chips source (deferred) or Layer B embeddings help.

## 8. How Layer B now fits

Layer B is enrichment, not a dependency: (a) the nearest-class **hint** at caption time
(unchanged, ADR-0010); (b) a **cross-check** — after induction, embedding-measured `learned_
confusers` can confirm or flag the agent's look-alikes; (c) a **tiebreak** when matching induced
terms to anchor classes (§5.1). All optional; the ontology induces and feeds the captioner with no
embeddings at all.

## 9. Proposed build phases (for the confirm-before-build step)

| Phase | Delivers | Needs |
|---|---|---|
| 1 | Corpus loader + RSICD adapter to the §3 format | RSICD (run-time download; check license) |
| 2 | `clayzer ontology induce` — map/reduce agent (N&M-grounded prompts, §4) → candidate ontology JSON | Bedrock (Opus); one-time |
| 3 | Deterministic reconciliation with the anchor → candidate `objects.toml` | the keyed-class anchor |
| 4 | `clayzer ontology lint` (N&M structural checks, §6) + contract tests + review diff; adoption | `tests/test_ontology.py` |
| 5 | Optional: Layer B cross-check of induced look-alikes | a prototype file |

## 10. Pointers

| Need | Where |
|---|---|
| Ontology schema and loader | `src/clayzer/ontology.py`, `ontology/objects.toml` |
| `claimable` vs `keyed` split | `Ontology.claimable()`, `Ontology.keyed()` (ADR-0008) |
| Anchor (Answer-Key crosswalks) | `ontology/objects.toml` keyed classes, `src/clayzer/answer_keys.py` |
| Contract tests (the adoption gate) | `tests/test_ontology.py` |
| Assumed caption-set format | [caption-design.md §3.6](caption-design.md#assumed-import-format-to-confirm-with-clay) |
| Layer B enrichment | `src/clayzer/prototypes.py` |

## 11. Reference

Noy, N. F., & McGuinness, D. L. (2001). *Ontology Development 101: A Guide to Creating Your First
Ontology.* Stanford KSL Technical Report (SMI-2001-0880). The methodology — the seven steps, the
three fundamental rules, and the §4–6 modelling rules — is the basis for the agent prompts (§4) and
the structural lint (§6).
