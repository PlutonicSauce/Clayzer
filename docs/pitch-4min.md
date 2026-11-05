# Clayzer: 4-minute pitch

The spoken script for the 10-slide deck (`src/clayzer/ui/static/deck/slides.js`), one section per
slide, with the deck's time budgets (they add up to 4:00). Each script is the slide's `spoken`
text, the same words the A key reads aloud, so the presenter and the Listen button agree. The
demo slide adds the Baseline's numbers, which the deck leaves to the live Overview.

Numbers come from the committed Baseline `20261105T011537Z-dev74-absence` (74 Cases, 3 Repeats,
222 Runs). Quote nothing else, except the figures the deck itself prints.

| # | Slide | Section | Time | Ends at |
|---|---|---|---|---|
| 1 | Clayzer | | 0:10 | 0:10 |
| 2 | The problem | Problem Statement | 0:35 | 0:45 |
| 3 | Example search | Value Unlock | 0:22 | 1:07 |
| 4 | How it works | Our Solution | 0:30 | 1:37 |
| 5 | Our solution | Our Solution | 0:34 | 2:11 |
| 6 | The ontology | Our Solution | 0:22 | 2:33 |
| 7 | On AWS | Our Solution | 0:25 | 2:58 |
| 8 | Live demo | Our Solution | 0:26 | 3:24 |
| 9 | At Clay's scale | Scale | 0:20 | 3:44 |
| 10 | Thank you | | 0:16 | 4:00 |

T starts the deck's timer; the notes panel warns when a slide runs long.

---

## 1. Clayzer (0:00–0:10)

**On screen:** the title, with the date in its first line (2026 NOV 5). No presses.

> Clayzer, said KLAY-zer. It comes from glaze, the finish a potter fires onto clay. A solution
> for producing captions you can trust, at scale.

## 2. The problem (0:10–0:45)

**On screen:** a photo of rows of white roofs (`fixed-dev-lookalike-neg-110`), and beside it how
its caption was made: the real prompt, Nova Pro shown only the photo, and its caption, stamped
unchecked. A line on the photo ties "Caption: a solar array" to the north-east cell it names.
Two presses.

> New caption, who dis? That is how captions on Clay's imagery work today. Here is a real one: we
> gave a vision-language model one photo and a simple prompt, and it said a large solar array,
> three times out of three.

*Press 1: the claim crossed out, "Actually: white roofs", and "Same answer 3 times in 3".*

> These are white roofs.

*Press 2: the records disagree too: a loupe on a wind-farm turbine at the photo's edge (USGS pin
just outside, OSM pin just inside, 2 m apart), and the two records side by side, USGS 17 ≠
OpenStreetMap 18.*

> So check it against the public records? They disagree too: on this wind farm, the government
> database counts seventeen turbines and OpenStreetMap counts eighteen, because they put one
> turbine two metres apart, either side of the edge.

## 3. Example search (0:45–1:07)

**On screen:** the paddy-search video, played once; it holds on the end card. No presses. It
searches for rice fields near Bangkok that became buildings since 2011, shows three
before-and-after pairs, and drops the third when the check finds fish ponds, not roofs.

> Why does this matter? Trusted captions make satellite imagery searchable in plain words. Ask
> which rice fields near Bangkok became buildings since the 2011 flood, and you get matching
> before-and-after images. No map layer, no GIS skills. Fish ponds can pass for buildings, so we
> check every caption. Then anyone can ask questions like this, about homes, harvests and jobs,
> and trust the answers.

## 4. How it works (1:07–1:37)

**On screen:** the start-to-finish flow. Point at each numbered box as you say it.

> Here is how it works, start to finish. An aerial image and public records go in. One: a model
> writes the caption from the image alone. Two: each fact is checked against the imagery before
> it is kept. Three: we score it against the public records, which the model never sees. Four: a
> gate keeps a change only if it beats the baseline. Only pairs that pass go on to Clay, ready to
> search.

## 5. Our solution (1:37–2:11)

**On screen:** the wind farm from slide 2's records comparison, with five points beside it. One
press per point as you say it, and a sixth that turns its caption green.

> Here is how we make captions you can trust. We verify, then write: each fact is checked
> against the imagery before the caption is written. The answer keys are public records,
> cross-checked by code: where they agree, labels are automatic, and only where they conflict
> does a person look. The captioner never sees them. One shared vocabulary of objects and
> their look-alikes. We tune on one region and test on another it never saw. And a
> self-improvement loop keeps only the changes that beat the baseline. The result: a caption
> that matches what is really there.

## 6. The ontology (2:11–2:33)

**On screen:** a photo that pixelates into the ontology graph, then three numbered benefits. Two
presses.

*Press 1: the photo pixelates into the graph; each tag lands on its class.*

> Our caption harness also reads an ontology: a semantic layer of what things are, what they sit
> near, and what they are mistaken for.

*Press 2: the three benefits, badged 1, 2, 3 on the graph.*

> Without it, the captioner called greenhouses solar farms nine times in twelve. With it, it is
> warned before it writes, and every claim uses words we can check.

## 7. On AWS (2:33–2:58)

**On screen:** the AWS architecture diagram. No presses.

> All of it runs on AWS, deployed with CDK. Bedrock writes, judges and searches the captions. The
> agentic captioner runs on AgentCore, which holds its LGND sign-in and reaches two MCP servers:
> LGND Geo to check imagery, and RODA for AWS open data. Results live in S3, and the site runs on
> Fargate behind CloudFront. Next: Step Functions to fan out, and SageMaker for GPU cost.

## 8. Live demo (2:58–3:24)

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

## 9. At Clay's scale (3:24–3:44)

**On screen:** "How it scales". A pot on a turning potter's wheel, filled above a dashed quality
bar, stands for the job: Clay's 70M chips captioned to the same quality. Beside it, bricks of
clay are the estimated cost, one brick per $10K. Across the top right, three chip tiles: 70M
(Clay v1.5), 86M (one NAIP pass), ~13B (Sentinel-2). Below them, one row per technique. Four
presses, one per technique as you name it: the bricks it saves fall away, the clay drops onto
the quality bar, and the gate catches it.

> What does this cost at Clay's scale? Clay's own training set is seventy million chips, and that
> is only a five percent sample of the world. Captioning all of it with our current model would
> cost about one hundred and eighty thousand dollars.

*Press 1: fire a full kiln, $91K.*

> Batch pricing halves that.

*Press 2: rough out on a cheap wheel, $25K.*

> A cheap model first, with only the hard images sent to the strong one,

*Press 3: thinner walls where they hold, $20K.*

> smaller images where objects are still visible,

*Press 4: cast from a mould, $3.9K.*

> and reusing captions for look-alike chips bring it to about four thousand dollars, forty-six
> times cheaper. Time scales too: one at a time it would take six years, but captions run in
> parallel, so it's days.

## 10. Thank you (3:44–4:00)

**On screen:** the closing slide, with links to the live site and the repository. Leave it up
for questions.

> Thank you. You can see it live on our site, and read every line of the code on GitHub. Our ask
> is Clay's real caption set and its rubric weights. And any slide here reads itself aloud.

---

## Rehearsal notes

- At a calm 145 words a minute the whole script is about 645 words, 4:27, so it runs about 27
  seconds over. Slide 9 is most of it: about 104 words, 43 seconds against a 20-second budget.
  Rehearse it fast, or give only the first and last price and the time line. Slide 5 runs about
  6 seconds long (it now carries the cross-check rule), slide 3 about 5 (65 words against 22
  seconds; drop "No map layer, no GIS skills" if you need it), and slide 7 about 2. Slide 2 fits
  its 35 seconds. Slide 8 has about 7 seconds spare, which the clicks will use.
- Verify-then-write is part of the approach, but the Baseline ran without it. If asked whether
  77% includes it, say no: the Baseline is the plain captioner. In the 4-image test, every object
  it named was really there, and correctness rose from 0.53 to 0.65.
- The problem slide's caption ("18 turbines, mostly in the centre") is Repeat 1 of an earlier
  Baseline. The live site shows the current Baseline's captions, so don't open
  `fixed-dev-uswtdb-3073564` in the demo and call it the same caption.
- In the demo, open Run 3 of `fixed-dev-uswtdb-3025453`, the one that scored 1.00. Its three
  Runs average 0.80 correct, so don't call the site perfect.
- The ontology's "nine times in twelve" is measured on the Baseline, which captioned without the
  ontology's guidance. The effect with it isn't measured yet, so don't claim it fixed the
  greenhouses. The guidance is a Batch option, off in the Baseline.
- AgentCore is live, but the Baseline ran locally with no tools: don't tie its numbers to
  AgentCore. X-Ray spans are built but opt-in, so don't say they're on.
- On slide 9, if "chip" needs a word: one small square tile of a big aerial or satellite image,
  like the three on screen. It's Clay's own term (their v1.5 spec: "70 million … chips").
- Slide 9's $181K is our measured $0.0026 per caption (2,559 tokens, Nova Pro, AWS list price)
  × Clay's ~70M chips. Ours are 512 px NAIP chips; Clay's are 256 px and from several sensors, so
  it's likely on the high side, and radar chips may not caption well. Neither is measured.
- Slide 9's quality, if asked: batch pricing changes only billing and turnaround, so the output
  is the same. The three "assumed" rows are hypotheses: each becomes a gated run, kept only if no
  score drops beyond the Baseline's run-to-run spread. Say "$3.9K is the best case if all three
  pass". The gate catching the clay on each press shows the mechanism, not a result.
- Slide 9's time: 2.9 s per caption is measured; 6.4 years one at a time. "Days" assumes about
  1,000 in parallel (about 2.3 days), which we haven't been granted or tested: the Bedrock quota
  sets it. The judge cost ($1.1M for Opus on every caption, against our $5.5K) is in the slide's
  footnote: use it only if asked.
- The example search video runs 22 s, the slide's whole budget, and holds on its end card.
- The example search is illustrative: our Cases today are US solar, wind and land cover. Don't
  imply we have run that search.
- If asked why not just look at the latest image: that works when you know where to look. This
  search is for when you don't: the change is slow, a few fields a year, nobody keeps a layer of
  it, and it only shows across dates. That building on the floodplain made 2011 worse is reported
  but not checked by us; don't quote it as a figure.
- On the problem slide, the solar caption and the turbine records are two different Cases: the
  white roofs are `lookalike-neg-110` (3 of 3 Repeats said solar), the 17 or 18 turbines are
  `uswtdb-3073564`. Don't present them as one photo.
- If asked about the cross-check: it's built for solar and wind. A confidence threshold for labels
  is planned, not built.
- Say "tune", not "train": we tune the captioner's prompt and checks.
- Before the pitch, check that the Listen button is on the deployed site and that the MP3 exists
  for the Batch you'll open.
- Speak the numbers as words people can picture ("77% of the facts are correct"), not metric
  names (correctness, MRR).
- Judging criteria each slide covers: the story is slides 4 and 7, a non-technical proof of
  concept is slide 8, audio is slides 8 and 10 (Listen, and the A key), scale is slides 7 and 9,
  and originality is slides 2, 5 and 6.

---

## Appendix: questions to expect

Where Clayzer stands against the hackathon's vision and tech documents
(`docs/vision-hackathon.md`, `docs/tech-hackathon.md`). Numbers are from the Baseline above
unless a line says otherwise. Each item gives the gap, then an answer to give.

### A. The five hardest questions

**1. "The brief says evaluating the agent is the product. Where's the agent?"**

- The Baseline captioner calls no tools (`"tools": []`), so its Workflow Score is 1.0 on every
  Run: there are no tool calls to get wrong.
- The agentic Harness exists: it calls RODA and LGND Geo over MCP, runs on AgentCore, and is
  held to a tool allowlist. No committed Batch uses it yet.
- *Answer:* it was a design choice. Models given tools often skipped them, so our code does the
  checking, every time, and each check is a step in the Trace. The agentic Harness is built and
  hosted, but it hasn't beaten the Baseline yet.

**2. "Do you get counts right?"**

- The Overview shows a count score of 0.00. USGS and OSM are incomplete, so their counts are
  lower bounds. A claim at or above the bound is unknown, and one below it scores 0. So the
  score only ever records failures: 45 counts were scored, all 0.
- 37% of claim fields are unscored for reasons like this.
- *Answer:* public maps are incomplete, so we refuse to reward a count we can't prove. Count is
  the weakest-measured part of grounding. The problem slide's "18" was confirmed by a person,
  not by the scorer.

**3. "Relationality is a named requirement. How do you score it?"**

- Relations were scored on only 2 Cases, and both scored 0.
- *Answer:* the scoring is built (OSM roads and water against fixed relations such as "south
  of"), but the captioner rarely asserts relations we can check. This is an honest gap.

**4. "Cost is meant to be GPU time across VLMs, not tokens."**

- We record seconds, tokens and dollars per caption. Hosted Bedrock doesn't expose GPU
  metrics, and the code says so in each Run's cost record.
- An open VLM on a SageMaker GPU (`gpu-vlm`) is blocked on GPU quota.
- Opus 5.5 ran as a second captioner. Its scores are flagged as self-graded, because the judge
  is Opus too.
- The scale slide is in dollars, which the brief says not to use. Its footnote says so: cost
  is from tokens, not GPU time and size. It does show time: 2.9 s per caption, measured.
- *Answer:* cost records are ready for GPU-seconds, and verified claims per GPU-second is a
  metric already, but we have no GPU numbers yet.

**5. "Can a caption be found from text alone?"**

- MRR is 0.73, but recall@1 is only 0.09. The cause isn't checked yet. A likely one is that
  captions of similar solar fields compete for the same query.
- Clay's own retrieval evaluation set never arrived (`example-captions` is blocked).
- *Answer:* don't quote MRR alone. Captions are usually near the top of the results, but
  rarely first.

### B. Change captions (two dates of one place)

- Built end to end. A Change Case is two NAIP images of one place, before and after a USGS site
  was built, cut to the same footprint. The captioner gets both, earlier first, with its own
  prompt. Each object it names says whether it appeared, disappeared, or was unchanged.
- The answer keys come free. USGS records each site's install year. Global Renewables Watch
  cross-checks it, and if the two disagree by more than a year, a person chooses.
- Only 1 Change Case, Kingbird B Solar (2014 → 2022), and none in the Texas set. The change
  was right on all 3 Repeats: the solar array appeared. Count was wrong every time, and the
  judge scored 0.2, 0.6 and 0.6.
- Change Cases aren't verified with LGND Geo, because its images aren't dated to the pair. OSM
  has no history, so roads and water aren't scored for change.
- *Answer:* "Yes. The pipeline handles before-and-after pairs, and USGS install years give us
  change answer keys for free, cross-checked against a second dataset. We've proven it on one
  site: it sees that the solar farm appeared, but miscounts the arrays. More pairs are cheap,
  because the labels come free."

### C. LGND Geo: a corroborator, never the truth

- Answer keys are public records only: USGS, OSM, and GRW for dates. LGND Geo never feeds a
  score (ADR-0006).
- Verify-then-write asks LGND whether its image of a Claim's grid cell shows the object. If it
  doesn't, the Claim moves to `uncertain`; it isn't deleted. If LGND is down, the Claim stays,
  marked unverified.
- If LGND wrongly rejects a true fact, the hidden records catch it as lost coverage. That is
  why the gate kept verify-then-write out of the Baseline.
- LGND also supplies the Clay embeddings used to pick images, find look-alike negatives, and
  give class-level hints. None of these is an answer key (ADR-0010).
- The Baseline ran with no LGND at all. Its free tier allows 150 calls a day.
- *Answer:* "LGND corroborates and never decides. Public records are our answer keys and the
  only thing we score against. If LGND is wrong, the hidden records catch it, and the gate
  measures the trade-off."

### D. Other gaps against the briefs

| The brief asks for | Where we are | Answer |
|---|---|---|
| ADB agentic eval (the recommended starting task) | Clayzer is caption-only | Our Trace format follows the Sandbox's (`breaking-barriers`), so its summarizer can read ours |
| Vantor sample data | Not used | Disaster Change Cases were a Could |
| Change caption datasets (LEVIR-CC and others) | Not used | Our Change Cases come from USGS and GRW instead |
| Clay's example captions | Never received | This is the closing slide's ask; an RSICD importer stands in |
| Model swappable | Yes: Opus 5.5 ran as a second captioner | A strength |
| Tracing tool swappable | Own Trace format with pluggable sinks; OpenTelemetry and X-Ray through AgentCore | Partly: a side-by-side tracer swap is still a to-do (`tracing-swap`) |
| Recorded-trace replay | Done, with no model or network | A strength, and the demo fallback |
| Fidelity (LLM judge) | 0.56 | The judge is strict, and calibration against people is blocked; don't call it caption quality |
| Label preparation time | About 54 s per Case | The exact definition is still a question for Clay |
| Sensitivity analysis (stretch) | 3 Repeats with spread, and the gate | Partial: inputs and models aren't varied yet |
| Multi-agent traces (stretch) | No | Draft, verify and rewrite is one pipeline, not several agents |

### E. Strengths to lean on

- **Region split, as ADB suggested.** Tuned on Mojave, tested once on Texas. Texas against
  dev, from the earlier Baseline `20261104T193330Z-dev74-base`: correctness 0.76 vs 0.75,
  fidelity 0.57 vs 0.56. Texas coverage was higher (0.86 vs 0.76) because its labels are
  sparser, not because the captioner is better.
- **Answer keys for free,** cross-checked across sources, with a person only where they
  conflict.
- **Provenance on every Batch:** models, prompt hashes, code commit and Case set.
- **Open by default:** Apache-2.0, with an ODbL notice for the OSM labels.
- **One deploy command per account,** and nothing crosses accounts, which the brief disallows
  anyway.
