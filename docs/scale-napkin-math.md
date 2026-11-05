# Napkin math: captioning at Clay's scale

What it would cost to caption the imagery Clay works with, starting from what one Caption costs
us today, and how far each scaling idea brings that down. Every number is labelled as
**measured**, **published** (a price or a figure from Clay's docs), or **assumed**. The assumed
ones are the next Batches to run, because the evaluation loop is what tells us whether a cheaper
setup keeps its quality.

## 1. What one Caption costs today (measured)

From the `dev63-base` Batch: 63 Cases × 3 Repeats = 189 Captions by Nova Pro on Bedrock.

| | Per Caption |
|---|---|
| Tokens | 2,559: 2,332 in (the same for every Chip) and about 227 out |
| Of the input, the image | about 1,800 tokens (77%); the prompt and tool schema are about 530 |
| Time to output | 2.9 s |
| Cost, on-demand | **$0.0026** (2,332 × $0.80/M + 227 × $3.20/M) |
| Judge (Opus 5.5) | about 1,300 in and 530 out, **$0.016**: about 6× the Caption itself |

Prices: AWS Price List, Bedrock, us-east-1, on 2026-11-04 (Nova Pro $0.80 / $3.20 per M tokens
in / out; batch $0.40 / $1.60). The Opus 5.5 judge is priced at Anthropic's list price
($4 / $20); Bedrock's price for it isn't in the public price list.

## 2. How many images there are

Clay is a **stratified sample**, not full coverage. In Clay's own words, "we only train on a very
small sample of the source archives, both in terms of spatial coverage and time".

| Image set | Images | Where the number comes from |
|---|---|---|
| Clay v1.5 training set | **~70M** chips (256 × 256 px) | Published: "33.8 TB of imagery, with about 70 million chips". NAIP 21.0M, Sentinel-2 18.7M, Sentinel-1 16.1M, Landsat 11.6M, LINZ 3.3M, MODIS 1.4M |
| How much of the world that is | 2,728 MGRS tiles out of about 57,000 (**~5%**); at most 6 dates per place; 2018–2023; no poles or open ocean | Published, stratified by ESA WorldCover land cover |
| One NAIP cycle over CONUS, at our Chip size | **~86M** Chips | Assumed: 8.08M km² ÷ (512 px × 0.6 m)² |
| One cloud-free Sentinel-2 view of all land | ~21M chips | Assumed: 135M km² ÷ (256 px × 10 m)² |
| The Sentinel-2 archive over land, 2017–2025 | **~13B** chips | Assumed: ~21M × 73 dates a year (5-day revisit) × 9 years, before removing cloudy views |

Sources: [Clay training data](https://clay-foundation.github.io/model/release-notes/data_sampling.html),
[Clay v1.5 specification](https://clay-foundation.github.io/model/release-notes/specification.html).

## 3. The levers, stacked

Each row is applied on top of the one above it.

| Lever | Per 1,000 Captions | Clay training set (70M) | NAIP cycle (86M) | S2 archive (13B) | Basis |
|---|---|---|---|---|---|
| Baseline: Nova Pro, on-demand, every Chip | $2.59 | $181K | $223K | $35M | measured |
| + Bedrock batch inference | $1.30 | $91K | $111K | $17.5M | published: 50% off |
| + Nova Lite on every Chip, the 20% that fail a cheap confidence check escalated to Pro | $0.36 | $25K | $31K | $4.8M | price published; the 20% rate and Lite's quality are assumed |
| + 256 px instead of 512 px where the class is still visible, on half the Chips | $0.28 | $20K | $24K | $3.8M | assumed: image tokens scale with area; half the Chips have no small objects |
| + Captioning 1 Chip in 5 and reusing it for near-duplicates in Clay embedding space | **$0.056** | **$3.9K** | **$4.9K** | **$0.76M** | assumed reuse rate; Clay's embeddings already exist, so this adds no new model cost |

That is **about 46× cheaper** than the baseline, and every step after batch is a hypothesis we can
test with a Batch and the gate.

### Evaluation costs more than generation unless it's designed not to

| How every Caption gets scored | Per 1,000 | 70M |
|---|---|---|
| Opus judge on every Caption | $15.80 | **$1.1M** (6× the cost of writing them) |
| Haiku 5.5 judge on every Caption | $0.40 | $28K (quality as a judge not measured) |
| **Ours:** grounding against open data on every Caption (no model call) + an Opus judge on a 1% stratified sample, in batch | $0.08 | **$5.5K** |

This is why grounding is deterministic: it's the part that scales for free.

## 4. Smaller levers, sized honestly

- **Prompt caching** saves at most **~12%** on a Caption, because the image is 77% of the input
  and an image can't be cached across Chips. It's worth more on the judge and on the
  text-only rewrite call, whose inputs are mostly fixed text. Bedrock publishes a cache-read
  price for Nova 2 Lite (75% off input); we haven't checked one for Nova Pro.
- **Claims only, prose from a template:** cutting output by ~40% saves **~11%**.
- **Claims straight from embeddings** (design idea 14): at archive scale the cheapest Caption is
  no VLM call at all. A small probe on existing Clay embeddings gives presence and count Claims
  for the cost of a matrix multiply; the VLM is kept for small objects that 10 m pixels can't
  show.

## 5. Throughput

Captioning Clay's 70M chips is about 179B tokens, and **6.4 years** of calls at 2.9 s if they run
one at a time. Batch inference jobs run in parallel, so the limit in practice is the
account's Bedrock token quota, not the code. The Step Functions fan-out in the design gives
per-Chip retries.

## 6. What to measure next

1. Nova Lite against Nova Pro on `dev63` (the same Cases and the gate): does the cheap model hold
   grounding, and what share of its Captions fail the confidence check?
2. A 256 px Batch: the real image-token count, and grounding by class.
3. The reuse error: caption a cluster's representative, reuse it on its neighbours, and score
   the neighbours.

The figures come from a short calculation at 2.9 s, 2,332 in and 227 out per Caption. Change
those three inputs and every row above moves with them.
