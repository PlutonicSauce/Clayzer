# Layer B prototypes

Generated class prototypes for the data-driven ontology ([ADR-0010](../../docs/adr/0010-the-ontology-is-data-driven-and-feeds-the-captioner.md),
[design](../../docs/ontology-data-driven.md)). **Do not hand-edit** — build them.

A file here is `v<ontology-version>.json`: one unit centroid per 10 m-discriminable class, their
exemplar counts, measured look-alikes, and the build provenance (region, source, embedding
model). Each is a few vectors, small enough to commit so demos replay offline (REQ-09).

Build from a **development region only** — never a region you score against (circularity,
ADR-0006). The usual path, using the Clay foundation model for the embeddings:

```sh
# 1. embed the dev region's Chips with Clay, offline on a GPU box (see scripts/clay_embed.py)
python scripts/clay_embed.py --region dev --out dev-embeddings.jsonl
# 2. attach those vectors to the dev Cases
clayzer ontology embed-cases --region dev --source file --from dev-embeddings.jsonl
# 3. build prototypes from the embedded Cases (class membership from their Reference Labels)
clayzer ontology build-prototypes --region dev --build-region dev --embedding-model clay-v1.5
clayzer ontology show
```

Or build straight from a curated exemplar file, bypassing Cases:

```sh
clayzer ontology build-prototypes exemplars.jsonl --build-region dev
```

`exemplars.jsonl`: one `{"class_id": "...", "embedding": [ ... ]}` per line, from confirmed
example Chips (verify each via LGND's imagery check first). Classes outside
`prototypes.LAYER_B_CLASSES` are dropped.

No prototype file committed yet — Layer B is inert until one exists; Layers A and C run regardless.
