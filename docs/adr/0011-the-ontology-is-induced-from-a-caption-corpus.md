# The Object Ontology is induced from a caption corpus

Layers A and C of the data-driven ontology (ADR-0010) have to be built from something. We weighed two sources: a **VLM pass over Chips** (caption many images, then mine the captions) and an **existing caption corpus** (RSICD's reference captions, Clay's example captions). We chose the **caption corpus** (decided 2026-11-04).

The corpus is cheaper — no imagery to fetch under NAIP's Requester-Pays, no VLM inference, no embeddings — and it is the right source for the job: Layer A is a vocabulary question ("what objects do captions name, in what words, confused with what"), and a corpus of captions answers it directly, in the house style we want the captioner to match. A VLM pass would mostly re-derive our own model's vocabulary and inherit its blind spots, which is what the eval exists to catch. The corpus is also text-only, so induction needs no image model and can run and be reviewed offline.

Induction runs as **map–reduce over the corpus, then a deterministic reconcile with the anchor**:

- **Map (LLM, over chunks):** extract candidate terms, proposed classes, synonyms, look-alike cues, and example phrasings from each bounded, representative chunk.
- **Reduce (LLM, one pass):** consolidate the candidates into one ontology — classes, the is-a hierarchy, synonyms, confusers, and caption exemplars.
- **Reconcile (code, deterministic):** merge the induced terms into the anchor's **keyed** classes and Answer-Key crosswalks. The agent never invents `keyed_by` or `osm`; Layer C is owned by code, so ADR-0006 and ADR-0010's Layer-C rule hold.

The result is a **candidate `objects.toml`** that is validated by tests and reviewed as a diff before adoption. Nothing is adopted automatically.

## Consequences

Induction is a design on paper until built; this ADR fixes the source and the shape so the build is a mechanical follow-through. The corpus's licence governs: RSICD has no clear licence, so it is downloaded at run time and never committed (the plan's rule), and the induced ontology must not reproduce corpus text beyond short exemplar phrasings. Because the LLM only proposes Layers A and C-adjacent vocabulary and code owns the keyed crosswalks, a bad induction can widen or mis-synonym the vocabulary but cannot silently change what grounding scores. Layer B (embedding-measured confusers, ADR-0010) remains an optional cross-check on the induced look-alikes.
