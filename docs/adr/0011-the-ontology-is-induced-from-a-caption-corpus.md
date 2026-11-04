# The ontology is induced from a caption corpus, not from embeddings

ADR-0010 made the ontology feed the captioner in three layers, and wired Layer A's look-alikes to
embedding-measured `learned_confusers`. That coupled the ontology's data-drivenness to Layer B
(Clay embeddings): no embeddings, no data-driven A. That dependency direction is wrong.

**Layers A and C are induced directly from a caption corpus by an LLM agent, with no embeddings
required.** Given a body of captions (and later, captions written from chips), an ontology-
induction agent extracts the object vocabulary: classes and their is-a children, synonyms,
look-alikes, and house-style example phrasings. The result is the ontology (`objects.toml`) that
feeds the Clayzer captioning agent. **Layer B embeddings become optional enrichment** stored in
the prototype sidecar (a nearest-class hint at caption time, and a cross-check on the agent's
look-alikes) — an ideal addition, never a prerequisite.

## The one hard constraint: the ontology is also the scoring contract

`objects.toml` drives grounding and retrieval, not just captioning (ADR-0008), and grounding
compares Claims to Answer Keys (USGS, OSM). So the induction agent may **freely add** claimable
classes, children, synonyms, look-alikes, and exemplars — these enrich captioning and retrieval —
but the **keyed** subset (the classes an Answer Key verifies) and their crosswalks (`keyed_by`,
`osm`, land cover) stay **anchored**, maintained against the Answer Keys, not invented by the
agent. ADR-0008 already separates these two roles (`claimable` vs `keyed`), so an induced ontology
fits: new classes are claimable-but-unscored until an Answer Key covers them. A reconciliation
step merges induced terms into the anchor (mapping "photovoltaic array" onto the keyed
`solar_array` as a synonym, not a new class), and `tests/test_ontology.py` fails until the file
and the code's lists agree — the human-review gate before a new ontology is adopted.

## The agent follows an established methodology

The induction agent's prompts are grounded in *Ontology Development 101* (Noy & McGuinness, 2001),
not ad-hoc: competency questions set scope; classes come from the nouns in captions and
relationships from their verbs; and the paper's modelling rules — is-a means "kind of", synonyms
are never their own class, a distinction is a new class only if it has its own properties/
restrictions/relationships (else it's a property value), siblings sit at one level of generality
and number ~2–12, consistent singular naming — are written into the prompts and re-checked by a
structural lint. See [docs/ontology-induction.md §4, §6](../ontology-induction.md).

## Circularity and provenance

The corpus must be disjoint from the chips we score (ADR-0006): induce from a human-captioned set
(RSICD, Clay's examples) or a development region, class-level only — never from the scored chips'
Answer Keys. Each induced ontology records its corpus, model, prompt hash, and date, bumps the
ontology version, and is adopted only after human review of the diff.

## Consequences

Data-driven A and C no longer wait on Clay embeddings or a GPU; they need only a caption corpus
and one bounded, one-time set of LLM calls (not per caption). The embedding-measured confusers
from ADR-0010 are demoted to an enrichment cross-check, and the Layer B nearest-class hint is
unchanged. The captioner, grounding, and retrieval keep reading one `objects.toml` (ADR-0008);
only how that file is *authored* changes — from hand-curation to agent-induction-then-review.
