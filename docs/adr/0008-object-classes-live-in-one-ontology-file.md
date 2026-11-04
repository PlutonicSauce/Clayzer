# Object classes live in one ontology file

Every object class a Claim can name is defined once, in `ontology/objects.toml`, with its is-a parent, the Answer Keys that can verify it, the OSM tags that map to it, synonyms, look-alikes, minimum visible size in NAIP, allowed attributes, retrieval queries, and crosswalks to benchmark and land-cover classes. The vocabulary had grown in four places (the Harness's allowed objects, grounding's keyed classes, the OSM mapping, and the retrieval queries) that could drift apart, and a flat list can't give partial credit when a Caption says "building" for what the Answer Key calls a greenhouse. We chose a small, plain data file (about 20 classes, at most three levels, built as a crosswalk over OSM tags and standard land-cover classes) over both a flat list and a formal semantic-web ontology. The file is part of the Caption contract (ADR-0007): changing a class changes what Claims mean for every functional area, and `tests/test_ontology.py` fails if code and file disagree.

## Consequences

Caption free text stays free; only Claims use ontology classes, so retrieval and Clay v2's training text aren't constrained to a fixed vocabulary. Mapping a class to OSM tags is allowed; letting the Harness look up OSM data is still forbidden (ADR-0006).
