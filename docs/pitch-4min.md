# Clayzer: 4-minute pitch

The spoken script for the 9-slide deck (`src/clayzer/ui/static/deck/slides.js`), one section per
slide, with the deck's time budgets (they add up to 4:00). Each script is the slide's `spoken`
text, the same words the A key reads aloud, so the presenter and the Listen button agree. The
demo slide adds the Baseline's numbers, which the deck leaves to the live Overview.

Numbers come from the committed Baseline `20261105T011537Z-dev74-absence` (74 Cases, 3 Repeats,
222 Runs). Quote nothing else, except the figures the deck itself prints.

| # | Slide | Section | Time | Ends at |
|---|---|---|---|---|
| 1 | Clayzer | | 0:10 | 0:10 |
| 2 | The problem | Problem Statement | 0:35 | 0:45 |
| 3 | Example search | Value Unlock | 0:28 | 1:13 |
| 4 | How it works | Our Solution | 0:30 | 1:43 |
| 5 | Our solution | Our Solution | 0:40 | 2:23 |
| 6 | On AWS | Our Solution | 0:25 | 2:48 |
| 7 | Live demo | Our Solution | 0:32 | 3:20 |
| 8 | At Clay's scale | Scale | 0:20 | 3:40 |
| 9 | What it means for Clay | | 0:20 | 4:00 |

T starts the deck's timer; the notes panel warns when a slide runs long.

---

## 1. Clayzer (0:00–0:10)

**On screen:** the title. No presses.

> Clayzer, said KLAY-zer. It comes from glaze, the finish a potter fires onto clay. A solution
> for producing captions you can trust, at scale.

## 2. The problem (0:10–0:45)

**On screen:** one wind-farm photo, `fixed-dev-uswtdb-3073564`, and its real caption.
Three presses.

> New caption, who dis? That is how captions on Clay's imagery work today. Here is a real one:
> the model saw only this photo and said eighteen wind turbines, mostly in the centre.

*Press 1: the 17 turbines both records agree on.*

> The public records put the turbines all around the centre, not in it.

*Press 2: the gold turbine at the top edge.*

> But the records disagree too: the government database counts seventeen, OpenStreetMap counts
> eighteen, because they put this turbine two metres apart, either side of the edge.

*Press 3: the triage card.*

> So we never trust one source. We cross-check them: when they agree, the label is automatic,
> and only when they conflict, like here, does a person look.

## 3. Example search (0:45–1:13)

**On screen:** the flood-search video, looping. No presses.

> Why does this matter? Trusted captions make satellite imagery searchable in plain words. Ask
> about the economic impact of flooding in Bangkok and access to aid, and you get the images
> whose checked captions match: flooded streets, a market under water, a relief site, and the
> route to reach it. Search results are only as good as the captions behind them.

## 4. How it works (1:13–1:43)

**On screen:** the start-to-finish flow. Point at each numbered box as you say it.

> Here is how it works, start to finish. An aerial image and public records go in. One: a model
> writes the caption from the image alone. Two: each fact is checked against the imagery before
> it is kept. Three: we score it against the public records, which the model never sees. Four: a
> gate keeps a change only if it beats the baseline. Only pairs that pass go on to Clay, ready to
> search.

## 5. Our solution (1:43–2:23)

**On screen:** the same photo and caption, with five points beside it. One press per point as
you say it, and a sixth that turns the caption green.

> Here is how we make captions you can trust. We verify, then write: each fact is checked
> against the imagery before the caption is written. The answer keys are public records,
> cross-checked by code, that the captioner never sees. One shared vocabulary of objects and
> their look-alikes. We tune on one region and test on another it never saw. And a
> self-improvement loop keeps only the changes that beat the baseline. The result: a caption
> that matches what is really there.

## 6. On AWS (2:23–2:48)

**On screen:** the AWS architecture diagram. No presses.

> All of it runs on AWS, from one deploy command. Bedrock writes, judges and searches the
> captions, with Nova Pro, Claude Opus and Titan embeddings. Results live in S3, and the site
> runs on Fargate behind CloudFront. The dashed boxes are next: Step Functions to fan out,
> SageMaker for GPU cost, and AgentCore for the agentic captioner.

## 7. Live demo (2:48–3:20)

**On screen:** the live site, in four stops. Rehearse the clicks. Keep the recorded Batch open
in another tab as the offline fallback.

1. **Overview**
   > Now the site. The overview shows the current baseline: 74 places, 222 captions, zero
   > failures, and 77% of the facts correct.
2. **Cases → `fixed-dev-uswtdb-3025453`, Run 3**
   > A caption, with each claim marked supported or not, right on the image.
3. **Batches → the latest report → Listen**
   > The report, five criteria side by side, which can read itself aloud.
4. **Compare**
   > And compare to baseline: the gate says better, worse, or inconclusive.

## 8. At Clay's scale (3:20–3:40)

**On screen:** the cost ladder. No presses.

> What does this cost at Clay's scale? Clay's own training set is seventy million chips, and that
> is only a five percent sample of the world. Captioning all of it with our current model would
> cost about one hundred and eighty thousand dollars. Batch pricing halves that. A cheap model
> first, with only the hard images sent to the strong one, smaller images where objects are
> still visible, and reusing captions for look-alike chips bring it to about four thousand
> dollars, forty-six times cheaper. Checking matters too: a large model judging every caption
> would cost over a million dollars, but our checks against open data need no model at all.

## 9. What it means for Clay (3:40–4:00)

**On screen:** the closing slide.

> Hand Clayzer a caption set and get a verdict: how much to trust, where it fails, what it costs
> to fix. Our ask is Clay's real caption set and its rubric weights. And any slide here reads
> itself aloud.

---

## Rehearsal notes

- At a calm 145 words a minute the whole script is about 600 words, 4:09, so it runs 9 seconds
  over. Slide 8 is the problem: about 110 words, 46 seconds against a 20-second budget. Rehearse
  it fast, or cut it to the first three sentences and the judge line. Slide 2 also runs about 6
  seconds long. Slides 5 and 7 have about 6 and 8 seconds spare.
- Verify-then-write is part of the approach, but the Baseline ran without it. If asked whether
  77% includes it, say no: the Baseline is the plain captioner. In the 4-image test, every object
  it named was really there, and correctness rose from 0.53 to 0.65.
- The problem slide's caption ("18 turbines, mostly in the centre") is Repeat 1 of an earlier
  Baseline. The live site shows the current Baseline's captions, so don't open
  `fixed-dev-uswtdb-3073564` in the demo and call it the same caption.
- In the demo, open Run 3 of `fixed-dev-uswtdb-3025453`, the one that scored 1.00. Its three
  Runs average 0.80 correct, so don't call the site perfect.
- The example search is illustrative: our Cases today are US solar, wind and land cover. Don't
  imply we have run that search.
- On the problem slide, if asked: the cross-check is built for solar and wind. A confidence
  threshold for labels is planned, not built.
- Say "tune", not "train": we tune the captioner's prompt and checks.
- Before the pitch, check that the Listen button is on the deployed site and that the MP3 exists
  for the Batch you'll open.
- Speak the numbers as words people can picture ("77% of the facts are correct"), not metric
  names (correctness, MRR).
- Judging criteria each slide covers: the story is slides 4 and 6, a non-technical proof of
  concept is slide 7, audio is slides 7 and 9 (Listen, and the A key), scale is slides 6 and 8,
  and originality is slides 2 and 5.
