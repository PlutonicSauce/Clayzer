# Look-alike negatives

Ten negative Cases in Kern County that look like solar arrays from the air: things the
captioner should not call solar. The Object Ontology lists `solar_array`'s confusers as
greenhouses, parking lots, and water; reflective roofs are added here.

| Look-alike | Cases | Examples |
|---|---|---|
| Greenhouse | 4 | glasshouses, a nursery, polytunnel rows over crops |
| Parking lot | 4 | shopping-centre and warehouse lots full of cars |
| Reflective roof | 2 | rows of white storage-unit roofs, a warehouse roof |

How they were found and checked (2026-11-04):
- LGND Geo's `search_place_find` over NAIP in eastern Kern County (34.85..35.55 N,
  119.25..117.80 W), with the texts "greenhouses", "greenhouse rows" / "plastic greenhouse",
  "parking lot", "large parking lot with cars", "white warehouse roof", and "large flat white
  roof" / "distribution warehouse": 120 matches, 82 distinct places.
- A shortlist of 12, spread over separate places, built with `clayzer case neg <lon> <lat>
  --n <k>` (numbered from 101, clear of the development negatives' Chip names). It refuses a
  point with a USGS site within about 300 m: one roof was refused, next to USPVDB 405771.
- Each Chip checked by eye for solar panels, since USPVDB lists only large ground-mounted farms
  and misses rooftop and carport panels. One was dropped: a strip that LGND's imagery check
  couldn't tell from stacked panels. One doubtful greenhouse was kept after the check confirmed
  crops under greenhouses, not panels.

Each Case records what it imitates and how it was found (`lookalike`). The Reference Labels come
from OpenStreetMap, so `cases/` is under the ODbL ([NOTICE.md](cases/NOTICE.md)).

```sh
uv run clayzer push --from fixtures/caption-lookalike    # into your store
uv run clayzer --region dev-lookalike batch --repeats 3 --label lookalike
```

They live apart from the development set (`fixtures/caption`) until `dev-cases` is finished,
so they don't change its mix or its Baseline.
