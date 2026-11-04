# The shared development Cases

The team's development Case set for the Mojave / Tehachapi region (caption-plan.md §3): 64 Cases,
each one NAIP Chip (or, for a Change Case, a Chip Pair) and the Reference Labels a good Caption
would agree with.

| | Cases | Spread |
|---|---|---|
| Solar | 30 | 9 under 5 MW, 11 at 5 to 50 MW, 10 over 50 MW |
| Wind | 13 | turbines from 13 different projects |
| Negatives | 20 | farmland, towns, industry, parking lots, shops, open desert |
| Change | 1 | Kingbird B Solar (USPVDB 401501, built 2016): farmland in NAIP 2014, panels in 2022 |

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
