# Caption generation: design notes

**Status:** design only, nothing built yet (as of 2026-11-03). Written as a starting point to
elaborate in a later session.
**Vocabulary:** capitalized terms (Task, Case, Harness, Run, Trace, Judge, Rubric, Batch, Gate…)
are defined in [GLOSSARY.md](../GLOSSARY.md).

## 1. Sources and their state

- The authoritative requirements are in **`tech-hackathon.docx`** and **`vision-hackathon.docx`**
  at the repo root. They are **newer** than `Clay-Foundry-Technical-Hackathon.md` and
  `Clay-Foundry-Vision-Hackathon.md` and add most of the caption-track detail. To read them
  as text: `textutil -convert txt -stdout tech-hackathon.docx` (macOS).
- `docs/spec.md` was built from the older `.md` files. **REQ-C1 and REQ-C2 (caption) are out of
  date** and should be rewritten from section 2 below. `docs/questions-for-clay.md` §4 is also
  out of date for the same reason.
- Facts marked *(from memory)* in sections 6–8 come from general knowledge of the field, not from
  the source documents, and should be re-checked before they go into a demo or the spec.

## 2. What the documents require

| Area | Requirement |
|---|---|
| Purpose | Training captions for the text-native Clay v2 model, and retrieval from text (e.g. "find railroads") |
| Inputs | NAIP high-resolution imagery (us-west-2, Requester-Pays); sample Vantor data (`s3://vantor-opendata`); LGND embeddings (https://source.coop/clay/lgnd-embeddings); optional auxiliary caption datasets |
| Task types | **Fixed:** one image of a place at one date. **Change:** two images of the same place at different dates; the caption describes what changed |
| What every caption must get right | **Position** (where objects are), **counts** (how many), **relationality** (how they sit relative to each other, e.g. "a road between two fields"), or for Change, changes in all three |
| Rubric | Five criteria. **Weights are not set yet: score and report each separately**, apply weights later |
| Answer keys | Global Renewables Watch v1.0 (solar and wind worldwide, MIT); USGS USPVDB / USWTDB (US solar and wind, public domain); OpenStreetMap (ODbL) |
| ADB's suggestion | Build on one region of GRW or USGS USPVDB/USWTDB, then test on another region that already has an LGND collection, using GRW, USGS, or OSM there as the answer key |
| VLM comparison | Run the same images and prompt through **more than one VLM**; compare cost in **GPU time and GPU count/size**, not tokens (a Should Have) |
| Tools | LGND Geo MCP server (commercial; teams are whitelisted for the hackathon, https://lgnd.ai/geo); RODA MCP server |
| Auxiliary datasets | Change: LEVIR-CC, Change-Agent (adds change masks), SECOND-CC, RSCC (larger; only a small subset may be human-labeled). Fixed: VRSBench, RSICD_optimal. Also listed: SkyScript, MegaEarth (Sentinel-2 + OSM labels, 485 classes). **Check each license; score only against human-labeled subsets** |
| Constraints | Public or synthetic data only. No SageMaker HyperPod or large Trainium clusters ("modest instance / managed endpoint" is fine). Training Clay v2 itself is out of scope |

### The five rubric criteria

| Criterion | What it checks | How the documents say to measure it |
|---|---|---|
| **Retrieval quality** | A caption can be found from a text query alone, with no image | Embed captions and queries with any off-the-shelf text model; record how often the right caption is in the top results |
| **Grounding** (most important) | The caption matches what's on the ground: objects, attributes, counts | Compare caption claims with reference labels (GRW, USGS, OSM, Vantor vectors, or human-labeled datasets) |
| **Fidelity** | The caption represents the image accurately overall | An LLM judge compares caption and image and gives a score |
| **Cost** | Throughput and time to output across VLMs | Same images and prompt for each VLM; record GPU time and number or size of GPUs |
| **Label preparation time** | How long labels take to prepare | Record the time taken to prepare each label set |

## 3. Architecture

Captioning becomes a second **Task** in the existing Sandbox, with its own Cases, Harness, and
Rubric. Traces, the Judge, reports, Batches, Compare, the regression gate, provenance, and the UI
carry over.

```
answer keys (USGS / GRW / OSM) ──► Case builder ──► Cases: chip location, date(s), reference labels
                                                       │
NAIP chips ──────────────────────► Caption Harness ◄───┘  (a VLM; swappable: Bedrock VLMs,
                                   │  structured caption:      self-hosted open VLMs on a GPU)
                                   │  text + objects/counts/positions/relations
                                   ▼
                                 Trace  (+ GPU time, GPU type/count for self-hosted VLMs)
                                   ▼
             ┌─────────────┬─────────────┬─────────────┬──────────┬────────────────┐
         Retrieval     Grounding      Fidelity        Cost      Label prep time
        (text embed,  (claims vs     (VLM Judge:   (GPU-sec,   (wall time per
         recall@k)    answer key)    image+caption) captions/h)  label set)
             └─────────────┴──────── five separate scores ───────┴────────────────┘
                                   ▼
                    report · Batch per VLM · Compare · gate
```

### 3.1 Cases, built from answer keys

- Start with **solar and wind**. USGS USPVDB and USWTDB give exact locations, sizes, and turbine
  counts, so a chip containing an array or turbines comes with a reference answer: what is
  there, and how many.
- Add OSM features (roads, water, buildings) so **relationality** can be checked ("a solar array
  south of a road"), plus **negative chips** with no target.
- **Change Cases almost build themselves.** USGS records each site's installation year. A site
  built between two NAIP flights (NAIP revisits a state every 2–3 years) gives a natural "before:
  empty field / after: solar array" pair.
- **Region split, following ADB:** a development region for tuning prompts, and a held-out test
  region that has an LGND collection, scored once. This doubles as the held-out Case set the
  improvement loop needs (see readiness item `held-out`).
- A caption Case would extend `TaskSpec` (`src/breaking_barriers/tasks.py`) with: chip bounding
  box, date or date pair, task type (fixed/change), and reference labels (object type → count,
  position, relations). Exact schema is open.

### 3.2 Caption Harness

- A VLM gets the chip(s) and returns a **structured caption**: free text (for retrieval and Clay
  v2 training) plus a list of **claims** (object type, count, position, relations) that grounding
  can check mechanically.
- **Two kinds of VLM:**
  - **Bedrock VLMs** (Claude, Nova). Reachable now through the existing Converse adapter, which
    accepts image blocks, but the Sandbox's `Message` type (`src/breaking_barriers/types.py`)
    has no image content yet and needs it. They report tokens and latency only.
  - **Open VLMs on a GPU instance.** The only way to measure the **GPU time** the rubric asks for.
    A modest GPU instance or a managed endpoint is allowed. Needs AWS work, which is on hold.
- **Agentic version (later):** the Harness uses the LGND Geo MCP server and RODA to find and fetch
  imagery, so the Workflow Score applies to captioning too.

### 3.3 Scoring the five criteria

The output-scoring engine (`src/breaking_barriers/scoring/output.py`) already handles weighted
criteria and Gates. For captions it should **report the five criteria separately** and drop the
weighted overall until Clay sets weights.

| Criterion | Proposed implementation |
|---|---|
| Retrieval | Embed every test-region caption and a query set ("find solar farms", "find wind turbines", "find railroads"…) with an off-the-shelf text embedding model; recall@k and MRR, with the answer key defining which chips are correct per query |
| Grounding | Deterministic: per-claim comparison with reference labels: count error, presence precision/recall, position agreement (e.g. by image quadrant), relation agreement |
| Fidelity | The existing Judge, extended to see the image and the caption; reuse judge sampling (ADR-0005) and calibration labels (`bb ui --calibrate`). Also gives a visual check for Unsupported Claims |
| Cost | Per Step: GPU-seconds, GPU type and count, captions per GPU-hour, time to first output. Bedrock VLMs: tokens and latency only, marked as not comparable |
| Label prep time | Wall time per label set; **meaning is ambiguous**, see section 5 |

## 4. Phases

| Phase | Delivers | Depends on |
|---|---|---|
| 0. Check the facts | Access to NAIP, GRW, USGS, `vantor-opendata`, LGND collections (and which regions have them); license of each auxiliary dataset; what Vantor's sample data contains | Mostly doable now |
| 1. Fixed-caption MVP | ~50 chips from one region; one Bedrock VLM; grounding and fidelity scores; reports and UI | Image content in the model interface |
| 2. Retrieval | Dev and test regions; query set; recall@k | Phase 1 |
| 3. VLM comparison | 2–3 open VLMs on one GPU instance plus Bedrock VLMs; GPU-time capture; a Batch per VLM; Compare and gate | A GPU instance (AWS, on hold) |
| 4. Change captions | Before/after pairs from USGS installation years | Phase 1 |
| 5. Agentic captioning | Harness uses the LGND MCP server; Workflow Score; label prep timing; demo Stories | LGND access |

## 5. Decisions and risks

1. **Don't grade captions with the data used to write them.** If the Harness sees OSM labels
   while captioning, grounding against OSM is circular. Answer keys must stay hidden from caption
   inputs; ADB's region split helps.
2. **Cost in GPU time means self-hosting.** Bedrock doesn't expose GPU time. Phases 1–2 can use
   Bedrock VLMs with the cost criterion marked partial.
3. **"Label preparation time" is ambiguous:** the time to build the reference labels (answer
   keys), or the time to produce captions, which are themselves training labels for Clay v2?
   Ask Clay.
4. **NAIP Requester-Pays cost:** pre-stage a small chip set once and reuse it across Batches.
   Chips should also go into the demo pack (NAIP is public domain) so caption Stories replay
   offline.
5. **Clay's example captions** are still needed to check caption style; until then, use the
   auxiliary datasets' human-labeled subsets.
6. **Rubric weights are unset:** never publish a single combined caption score until Clay sets
   them.

## 6. How VLMs produce captions *(from memory)*

```
image ──► vision encoder (a ViT, often CLIP-style) ──► projector ──► language model ──► caption, word by word
                                                               ▲
                                                    prompt: "Describe this image…"
```

The vision encoder turns the image into visual tokens; a small projector maps them into the
language model's input space; the language model writes the caption one token at a time.
Caption quality depends on the training data (image-text pairs, then instruction tuning), the
prompt ("one sentence" vs "list every object with counts and positions"), and decoding
(deterministic vs sampled; length).

**Why overhead imagery is hard for general VLMs:** they're trained mostly on ground-level
photos. From above they miscount (panel rows, cars, turbines), misjudge scale (pond or lake),
confuse look-alikes (greenhouses vs solar arrays), and write generic text ("an aerial view of a
rural area"). Remote-sensing VLMs and datasets exist to close that gap.

## 7. Known patterns for creating captions automatically *(from memory)*

| Pattern | How it works | Examples | Strength / weakness |
|---|---|---|---|
| Labels to text | Turn map labels (OSM tags, land-cover classes) into sentences by template or LLM | SkyScript; ChatEarthNet | Grounded by construction / only as rich as the labels; can be stilted |
| Teacher recaptioning | A strong VLM writes detailed captions; a smaller model is trained on them | ShareGPT4V; recaptioning of web datasets (as for DALL-E 3) | Rich text / inherits the teacher's errors and cost |
| Generate then filter | Generate several candidates; keep the one an image-text matching model scores highest | BLIP's CapFilt | Cheap quality boost / the filter has blind spots |
| Tools first, then words | Detectors/segmenters produce a structured scene; an LLM writes the caption from it plus the image | Scene-graph-to-text; "visual programming" | Counts and positions are measured / tool errors carry through |
| Region-level, then whole-image | Caption regions with locations, then combine | Dense and grounded captioning (e.g. Kosmos-2 location tokens) | Good for position and relations / more steps and cost |
| Change captioning | Encode both dates together, often with a change mask, and describe the difference | LEVIR-CC, Change-Agent, SECOND-CC | Purpose-built for two dates / generic VLMs do poorly here |

## 8. Novel ideas for this hackathon

Each idea is mapped to the rubric criterion it serves.

1. **Verify, then write** (Grounding, Fidelity). The VLM first produces claims ("3 turbines,
   north-east of the road"); each claim is checked with an independent tool (a detector, an OSM
   lookup, a search over Clay/LGND embeddings); the final caption is written only from verified
   claims, with the rest marked uncertain. This is the Sandbox's Unsupported Claims idea applied
   to images. **Catch:** verify with different sources from those used to score, or grounding is
   circular.
2. **Embeddings choose what to caption** (Label prep time, Cost). Cluster Clay/LGND embeddings
   and caption a diverse sample instead of thousands of near-identical fields; send only
   uncertain chips to an expensive VLM or a human.
3. **Embeddings find change** (Cost, Change task). Compare a place's embeddings across two dates
   to find where something changed, and only send those pairs to the change captioner; most
   pairs show no meaningful change.
4. **Write captions so they can be found** (Retrieval). Generate likely queries for a chip
   ("find solar farms near highways"), test whether the caption ranks highly for them, and
   rewrite it if not: the image-captioning version of doc2query.
5. **Teacher → student on the cost frontier** (Cost, Fidelity). A large VLM captions a seed set;
   a small open VLM is fine-tuned or prompted to match it. Plot every VLM on quality vs
   GPU-seconds per caption; the rubric explicitly asks for this comparison.
6. **Several VLMs, keep the consensus** (Grounding). Run 2–3 VLMs per chip and keep the claims
   most agree on; the generation-side version of the Judge's median-of-samples.
7. **Improve the captioner with the existing loop** (all criteria). Treat the caption prompt or
   pipeline as the Harness: Batches, the five scores, Compare, and keep a change only if the gate
   passes. This is the team's main differentiator: not just a captioner, but one shown to get
   measurably better, with the cost of each improvement visible.

**Recommended combination:** 1 + 2 + 7, plus 5 if a GPU instance is available. It attacks
grounding and label-preparation cost directly, and every step reuses something the Sandbox
already has.

## 9. Open questions for Clay

- What does "label preparation time" measure (section 5, item 3)?
- Format and location of the example captions; are they fixed, change, or both?
- Which regions have LGND collections, and how is the LGND Geo MCP server accessed?
- Which VLMs should be compared, and what GPU instance and budget are acceptable?
- What is in Vantor's sample data, and is it meant as caption input or as reference labels?
- When will rubric weights be set?

## 10. Pointers into the existing code

| Need | Where it lives now |
|---|---|
| Case definition | `src/breaking_barriers/tasks.py` (`TaskSpec`), Cases in `tasks/adb.toml` |
| Model interface (needs image content) | `src/breaking_barriers/types.py`, `src/breaking_barriers/model/bedrock.py` |
| Run loop and Trace | `src/breaking_barriers/agent.py`, `src/breaking_barriers/tracing/` |
| Judge and rubric engine | `src/breaking_barriers/scoring/output.py`, `rubrics/adb.toml` |
| Cost recording | `src/breaking_barriers/cost.py`, `config/prices.toml` |
| Batches, Compare, gate | `src/breaking_barriers/batch.py`, `src/breaking_barriers/gate.py` |
| Provenance and reports | `src/breaking_barriers/report.py` |
| Requirements and status | `docs/spec.md` (REQ-C1/C2 need rewriting), `docs/readiness.toml` |
| Design decisions | `docs/adr/` (ADR-0001 Trace format, ADR-0005 judge sampling are relevant) |
