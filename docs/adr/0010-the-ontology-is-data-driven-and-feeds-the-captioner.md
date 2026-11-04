# The Object Ontology is data-driven and feeds the captioner

The Object Ontology (`ontology/objects.toml`, ADR-0008) was written by hand: eleven claimable classes under five roots, with their is-a parents, synonyms, look-alikes, minimum visible sizes, Answer-Key crosswalks, and retrieval queries. Hand-authoring doesn't scale to the vocabulary Clay's real captions use, and it bakes in our guesses about which objects and phrasings matter rather than the corpus's. We decided the ontology should be **built from data and then feed the captioner**, in three layers, so each part comes from the source best suited to it:

- **Layer A — the vocabulary:** the classes, their is-a hierarchy, synonyms, look-alikes, and house-style example phrasings. Induced from a caption corpus (ADR-0011).
- **Layer B — measured look-alikes (optional enrichment):** confuser pairs confirmed by how close two classes sit in embedding space. A cross-check on Layer A, never a blocker; demoted to enrichment because it needs embeddings and adds little the corpus and the briefs don't already give.
- **Layer C — the Answer-Key crosswalks:** `keyed_by`, the OSM tag rules, and the retrieval queries that tie a class to the open data that can verify it. These are not induced; they are reconciled against the anchor by deterministic code (ADR-0011), because they decide what grounding can score, and an induced guess there would be wrong in a way that quietly changes scores.

The ontology then **feeds the Clayzer captioning agent**: the prompt lists each claimable class, its synonyms, its look-alikes, and its minimum visible size, so the model names objects in the vocabulary grounding and retrieval already understand. The ontology stays the one contract (ADR-0007, ADR-0008); only its authorship changes, from hand-written to induced-then-reviewed.

## Consequences

The ontology remains a small, plain, reviewed data file: induction proposes, a human adopts (a version bump and the code-list update `tests/test_ontology.py` guards). Layer C stays off-limits to any model, so ADR-0006 holds — nothing that writes the ontology may read an Answer Key for a region being scored. Because the captioner reads the induced vocabulary, a change to the corpus can shift what the model is told to look for; that is the point, but it means the ontology's version is part of a Batch's provenance, like the prompt. Layer B can be added later without touching A or C.
