# Data-driven Object Ontology for captioning

**Status:** implemented on branch `feat/ontology-data-driven` (2026-11-04). Layers A and C are
live; Layer B is implemented and tested, and needs a prototype file built from real Clay/LGND
embeddings before it does anything in a Batch.
**Decision record:** [ADR-0010](adr/0010-the-ontology-is-data-driven-and-feeds-the-captioner.md).
Builds on [ADR-0008](adr/0008-object-classes-live-in-one-ontology-file.md) (one ontology file)
and [ADR-0006](adr/0006-answer-keys-are-hidden-from-caption-inputs.md) (Answer Keys hidden from
caption inputs).

## 1. Why

Today the Object Ontology only flows *out* of captioning — it scores (grounding), retrieves, and
reports. It never helps the model *write* a Caption. The differentiator is to feed the captioner
class-level, data-derived knowledge — vocabulary, look-alikes, house style, and an
embedding-nearest-class hint — so it makes fewer of the mistakes overhead VLMs are known for
(miscounting, confusing greenhouses with solar arrays, generic text), and to **prove** it helps
with the loop we already have (Batches, Compare, the gate) rather than asserting it.

## 2. The three layers

| Layer | Holds | Where it lives | Fed to the captioner as | Serves |
|---|---|---|---|---|
| **A — symbolic** | classes, is-a, attributes, look-alikes, min visible size | `ontology/objects.toml` (ADR-0008) | a compact "look-alikes to tell apart" line | grounding, fidelity |
| **C — caption exemplars** | 1–2 class-level caption phrases in house style | `objects.toml` `caption_exemplars` (new) | few-shot "example phrasings" lines | retrieval, fidelity/style |
| **B — embedding prototypes** | per-class centroid of example Chips' Clay/LGND embeddings, measured look-alikes, counts | `ontology/prototypes/<version>.json` (generated) | "this tile is closest to solar_array (0.82), greenhouse (0.74)…" | grounding (disambiguation) |

**A and C are hand-curated and diff-able; B is generated and never hand-edited.** A and C are
always available and cost only tokens. B is used only when a prototype file *and* a Chip
embedding both exist, and is skipped silently otherwise.

### What Layer B does and doesn't hold

It holds a **handful of unit vectors** (one centroid per class), their exemplar counts, and the
measured nearest-neighbour look-alikes. It does **not** hold images, per-Chip embeddings, or any
per-location answer. It's tiny (a few vectors), which is why it commits to the repo as JSON for
offline replay (REQ-09) and maps cheaply onto a cloud vector index.

## 3. How Layer B is built (data-driven, from a disjoint region)

```
development region (NOT scored)            caption time (any scored region)
───────────────────────────────           ─────────────────────────────────
confirmed sites (USGS/OSM)                 Chip + its Clay/LGND embedding
   │  pull Clay/LGND embedding                │
   ▼                                          ▼
(class_id, embedding) exemplars            nearest class centroids  (dot product, no model call)
   │  verify via LGND imagery check           │
   ▼                                          ▼
mean → unit centroid per class    ──────►  prompt hint: "closest to solar_array (0.82), …"
measured look-alikes, counts               + Layer A look-alike note + Layer C exemplars
   │                                          │
   ▼                                          ▼
ontology/prototypes/<version>.json         captioner writes, then verify-then-write (unchanged)
```

Build command (dev region only):

```sh
clayzer ontology build-prototypes exemplars.jsonl --build-region dev \
    --source lgnd-embeddings --embedding-model clay-v1
clayzer ontology show      # inspect the index: classes kept, counts, learned look-alikes
```

`exemplars.jsonl` is one `{"class_id": "...", "embedding": [...]}` per line. Classes outside
`LAYER_B_CLASSES` are dropped with a note. The command prints a circularity reminder naming the
build region.

## 4. How it plugs into the caption flow

`harness.caption(...)` gains an optional `ontology_context: str`. When a Batch sets
`ontology_context=True` (default off), `batch._ontology_context` assembles the block per Chip:

1. `ontology.prompt_context(focus)` → Layer A look-alike note + Layer C exemplars (token-bounded).
2. If a prototype file for the ontology version exists **and** the Chip carries an `embedding`,
   `prototypes.caption_context` adds the Layer B hint and narrows the exemplars to the nearest
   classes, after `guard_scoring_region` confirms the Batch's region ≠ the build region.

The Harness still sees only the Chip id, image, and this class-level text — never the Case's
Reference Labels (ADR-0006). The block is appended after the base prompt, before any tools note.

### The Chip embedding — where the vectors come from

Embeddings are computed **once, at prep time**, and stored on the Case (`chip["embedding"]`),
never per caption — that is what keeps a caption to a dot product. `embeddings.py` defines one
`EmbeddingSource` interface with three implementations, so the rest of the code doesn't care
which produced the vectors:

| Source | What it is | Cost | When |
|---|---|---|---|
| **Clay foundation model** | Run Clay's encoder over each Chip (`scripts/clay_embed.py`, offline on a GPU box) → a `{chip_id, embedding}` JSONL, loaded via `PrecomputedEmbedding` | one-time, GPU; zero per caption | the real "Clay asset" path |
| **Precomputed file** | Any published Clay/LGND export keyed by Chip id or location | zero (reuse) | when an export is to hand |
| **Titan multimodal** (`TitanImageEmbedding`) | Bedrock image embeddings of the Chip PNG | one Bedrock call per Chip, prep-time only | fallback when Clay isn't set up |

The prep step is `clayzer ontology embed-cases --region <r> --source <file|titan>`, which attaches
`chip["embedding"]` to every Case in the region. The Clay script is standalone (torch + Clay stay
out of the package and its lockfile); it emits the JSONL that `--source file` loads. Pipeline:

```
scripts/clay_embed.py (Clay model, GPU, offline)
    → dev-embeddings.jsonl
    → clayzer ontology embed-cases --region dev --source file --from dev-embeddings.jsonl
    → clayzer ontology build-prototypes --region dev --build-region dev
    → clayzer batch --region held-out --ontology-context      # Layer B fires here
```

## 5. Storage and maintenance on AWS

| Artifact | Local (committed, offline demo) | Cloud |
|---|---|---|
| Layers A + C | `ontology/objects.toml` (+ S3 snapshot with version & hash, like the Rubric, REQ-14) | S3 |
| Layer B prototypes | `ontology/prototypes/<version>.json` (`prototypes.LocalPrototypes`) | **Amazon S3 Vectors** (`prototypes.S3VectorsBackend`): each centroid a vector keyed by class id, with build provenance as metadata; a query returns nearest class centroids |

**Why S3 Vectors** (the hackathon choice over OpenSearch Serverless / Bedrock Knowledge Bases):
native vector buckets with nothing running between queries, so there is no idle cost — the right
fit for a cost-sensitive nonprofit. The committed JSON keeps demos replayable with no network
(REQ-09); the cloud index is the AWS-integration story. The vector bucket and index are created
by the CDK app (AWS-03); the `s3vectors` client is used defensively since it isn't in every boto3.

**Maintenance.** The ontology is a versioned input to the Harness. Changing it (adding exemplars,
rebuilding prototypes) bumps the version, is recorded in each Batch's provenance
(`ontology_version`, `ontology_sha`), and is kept only if a Batch → Compare → gate shows it helps.

## 6. Cost and risk accounting (for the pitch)

| | Cost | Mitigation in the code |
|---|---|---|
| Layer A+C tokens | small, recurring | token-bounded block; fixed prefix for prompt caching (§16) |
| Layer B build | one-time, tiny | a few hundred embeddings averaged once |
| Layer B per caption | **one dot product**, no model call | reuse Clay/LGND embeddings; `SIM_FLOOR` emits a hint only when confident |
| Vector storage/query | cents | a handful of centroids; S3 Vectors has no idle cost |
| **Circularity** (ADR-0006) | would invalidate grounding | class-level only; disjoint build region; built from Clay/LGND (not a scored Answer Key); `guard_scoring_region` |
| **Resolution mismatch** (10 m vs 0.6 m) | bad hints for small objects | `LAYER_B_CLASSES` excludes turbines, roads, individual buildings |
| **Bad exemplars** | poison a class | verify each exemplar through LGND's imagery check before it enters the index |
| **Anchoring** | over-claim the top class | always name top-2+ with a "tell them apart" clause; the gate measures whether it helped |

## 7. Status

Done on the branch (tested end to end against fakes, `tests/test_embeddings.py`,
`tests/test_prototypes.py::test_layer_b_fires_end_to_end_through_the_batch_path`):

- The embedding seam and all three sources (`embeddings.py`).
- Attaching embeddings to Cases (`clayzer ontology embed-cases`).
- Building prototypes from embedded Cases or an exemplar JSONL (`clayzer ontology build-prototypes`).
- The Clay offline embedding script (`scripts/clay_embed.py`).
- Batch wiring (`--ontology-context`) that fires Layer B when a prototype file and Chip embeddings
  both exist, with the circularity guard.

Still to do (needs data / a GPU / AWS, not code in this branch):

- Run `scripts/clay_embed.py` on a Clay-capable box to produce real embeddings; verify the two
  version-specific Clay functions in it against the installed package (it prints the dim as a
  check).
- Build and commit a real prototype file under `ontology/prototypes/`.
- Co-occurrence priors (typical counts, class co-occurrence) — a documented extension of the
  build step, not yet implemented.
- CDK: an S3 Vectors bucket and index (AWS-03) and loading the prototypes into it.
- Run A, A+C, and A+C+B as Batches on a held-out region and record the grounding/retrieval and
  cost deltas against the Baseline (the headline pitch number).

## 8. Pointers into the code

| Need | Where |
|---|---|
| Layers A + C data | `ontology/objects.toml` (`caption_exemplars`, `confusers`, `min_visible_m`) |
| Prompt context (A + C) | `ontology.prompt_context` |
| Layer B: build, query, guards, backends | `src/clayzer/prototypes.py` |
| Embedding sources (Clay file, precomputed, Titan) | `src/clayzer/embeddings.py` |
| Clay model embedding (offline, standalone) | `scripts/clay_embed.py` |
| Context assembly (A + C + B) | `prototypes.caption_context` |
| Caption injection point | `harness.caption(..., ontology_context=...)` |
| Batch opt-in and per-Chip assembly | `batch.BatchConfig.ontology_context`, `batch._ontology_context` |
| CLI | `clayzer ontology embed-cases | build-prototypes | show` |
| Tests | `tests/test_prototypes.py`, `tests/test_embeddings.py`, `tests/test_ontology.py`, `tests/test_agentic.py` |
