# The shared development Cases

The team's development Case set for the Mojave / Tehachapi region (caption-plan.md §3): 73 Cases,
each one NAIP Chip and the Reference Labels a good Caption would agree with.

| | Cases | Spread |
|---|---|---|
| Solar | 30 | 9 under 5 MW, 11 at 5 to 50 MW, 10 over 50 MW |
| Wind | 13 | turbines from 13 different projects |
| Negatives | 20 | farmland, towns, industry, parking lots, shops, open desert |
| Look-alike negatives | 10 | things that look like solar from the air: 4 greenhouses, 4 parking lots, 2 reflective roofs |

Every Chip is at least 1 km from the others. Positives start from a USGS record and use a NAIP
image taken after the site was built; negatives have no USGS site nearby.

- `cases/caption-dev.jsonl`: one Case per line, with its Reference Labels. These include
  OpenStreetMap data, so the folder is under the ODbL ([NOTICE.md](cases/NOTICE.md)).
- `chips/<chip-id>.png`: the 512 × 512 Chip at 0.6 m (NAIP, public domain), and
  `chips/<chip-id>.json`: its date, bounding box, and NAIP item.

## Load them

Into your store: your S3 bucket if `CLAYZER_STORE` is set, otherwise the local `data/` folder,
which needs no AWS account:

```sh
uv run clayzer push --from fixtures/caption
uv run clayzer ui     # the Cases page shows them
```

This replaces the store's `cases/caption-dev.jsonl`. Don't edit these files by hand: build a Case
with `clayzer case`, then copy the store's files back here in a PR.

## Look-alike negatives

The ten `fixed-dev-lookalike-neg-*` Cases (Kern County) look like solar arrays from the air, so
they test whether the captioner can tell them apart. Each records what it imitates and the search
that found it (`lookalike`), and a Batch report counts how often each kind fooled the captioner.

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

The first Batch on them alone (Nova Pro, 1 Repeat) called 4 of the 10 a solar array: 3 of 4
greenhouses, 1 of 2 roofs, 0 of 4 parking lots.
