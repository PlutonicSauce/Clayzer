# The shared development Cases

The team's development Case set for the Mojave / Tehachapi region (caption-plan.md §3): 78 Cases,
each one NAIP Chip (or, for a Change Case, a Chip Pair) and the Reference Labels a good Caption
would agree with.

| | Cases | Spread |
|---|---|---|
| Solar | 31 | 9 under 5 MW, 11 at 5 to 50 MW, 11 over 50 MW; one beside year-round ponds (SEGS IX) |
| Wind | 16 | turbines from 16 different projects; 2 on grassland hills, 2 in pinyon-juniper woodland |
| Negatives | 20 | farmland, towns, industry, parking lots, shops, open desert |
| Change | 1 | Kingbird B Solar (USPVDB 401501, built 2016): farmland in NAIP 2014, panels in 2022 |
| Look-alike negatives | 10 | things that look like solar from the air: 4 greenhouses, 4 parking lots, 2 reflective roofs |

Every Chip is at least 1 km from the others. Positives start from a USGS record and use a NAIP
image taken after the site was built; negatives have no USGS site nearby.

- `cases/caption-dev.jsonl`: one Case per line, with its Reference Labels. These include
  OpenStreetMap data, so the folder is under the ODbL ([NOTICE.md](cases/NOTICE.md)).
- A Change Case (`kind = "change"`) has two Chips of one footprint, earlier first, and each
  USGS label says whether its object `appeared`, `disappeared`, or was `unchanged`
  (`clayzer case uspvdb <id> --change`).
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

## Setting gaps

Four Cases were added on 2026-11-04 because `clayzer spread` found settings the set lacked:
Tehachapi Windplant I (USWTDB 3073276) and Voyager II (3087460) on grassland hills, Sky River
Repower (3114946) in pinyon-juniper woodland, and SEGS IX (USPVDB 405019) beside two ponds,
water being a solar look-alike. USPVDB lists SEGS IX as fixed-tilt PV; its 1990 year is the
original solar-thermal plant's. Its labels have two hand corrections: the north-west cell is
pond, not panels, and the ponds are water.

`--suggest` proposed more. Two turbine Cases in desert scrub, the setting most wind Cases already
have, were left out; two solar sites (USPVDB 404709, 404762) were built after California's
latest NAIP, 2022, so no image shows them. Rooftop and car-park solar have no USPVDB site to
start from (it lists sites of 1 MW and up).

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
