# Vision Document: Clay Earth Dataset Foundry

**How to use this document (developer teams):** This is your context and scope for the build, not a rigid spec. Read the Executive Summary and "The Three Tasks" first, pick one task to drive end to end (start with the ADB agentic eval), and treat the "In Scope / Out of Scope" lists as your guardrails for a 2-day build. A short list of items to confirm with Clay at kickoff is at the end.

## Executive Summary

The Earth Dataset Foundry is an open platform that helps public-interest practitioners turn free satellite imagery into usable, trustworthy datasets. The hardest and least-served part of that mission—and the focus of this hackathon—is **evaluating agentic geospatial workflows**: when an AI agent plans and runs a dataset build by calling geospatial tools, how do you observe what it did and judge whether it did it well? Clay has the ingredients (known tasks, input data, example outputs, and a large catalog of MCP servers) but has never had the capacity to connect them into an evaluation system. The hackathon MVP builds that system: an **observability + evaluation sandbox** where an LLM harness calls geospatial tools over MCP, the agent's activity is captured as traces, and those traces plus the task output are summarized and scored against a rubric or reference examples. The point to prove is that an agentic geospatial workflow can be **observed, summarized, and scored end to end**, on one or more of Clay's real tasks.

## Business Context

### Problem Statement

Organizations working on urgent public problems have more satellite data than ever but lack the practical datasets they need, and building those datasets increasingly means orchestrating AI agents that call many specialized geospatial tools. The bottleneck Clay faces is not running an agent—it is **knowing whether to trust one**. Clay has long lists of evaluations it has never had capacity to run, a new text-native Clay model that needs synthetic caption data it cannot bandwidth-test, and partners (e.g., the Asian Development Bank) who need custom evals to understand how to use AI to build datasets. Without a way to observe and score agentic workflows, every agent-built dataset is a black box.

### Business Drivers

- **Evaluating agentic workflows is the #1 unmet need.** Clay has assembled tasks, input data, and tooling but lacks the observability + scoring layer to judge agentic runs.
- **Clay v2 depends on caption data nobody has tested.** The next, text-native Clay model is trained on synthetic captions of satellite imagery; Clay has no bandwidth to evaluate those caption workflows.
- **Partners need eval capacity Clay cannot supply.** ADB and others need custom evals for AI-assisted dataset building; Clay's eval backlog is real and growing.
- **The ingredients already exist.** Known tasks, public input data (NAIP, Vantor), Clay/LGND embeddings, and a catalog of geospatial MCP servers mean a team can focus on the evaluation loop rather than assembling raw materials.

### Target Users and Stakeholders

| **User Type** | **Description** | **Primary Need** |
|---|---|---|
| Clay model & data team | Build and improve the Clay model and Foundry datasets | A way to evaluate agentic caption/dataset-build workflows without hand-checking every run |
| Partner organizations (e.g., ADB) | Need custom evals for AI-assisted dataset building | A reusable harness that scores an agent against their tasks and rubric |
| Agent / harness developers | Build the agentic workflows under test | Observable traces and clear scores that show where a workflow succeeds or fails |
| Domain experts | Judge whether outputs are trustworthy | Summarized traces + output scored against a rubric or reference examples |

### Business Constraints

- Open and reproducible by default (Apache-2.0, consistent with Clay's existing releases).
- Trust and provenance are first-class: every scored run keeps its traces, inputs, and the rubric/reference it was judged against.
- Public or synthetic data only for the hackathon (NAIP, Vantor open data, LGND embeddings, synthetic prompts/captions, and openly licensed reference data such as Global Renewables Watch, USGS USPVDB/USWTDB and OpenStreetMap).
- Keep the model and the tracing tool behind abstractions so both are swappable.

## Solution Concept and Terminology

This section grounds the hackathon in how Clay frames the problem and sets shared vocabulary for the teams.

### Core Concepts

| **Term** | **Definition** |
|---|---|
| Task | A known unit of work to evaluate an agent on. Three are available this hackathon (below); teams pick one or more. |
| LLM harness | The agent (on Amazon Bedrock, kept swappable) that performs a task by calling geospatial tools. |
| MCP tools | Geospatial capabilities the agent reaches via Model Context Protocol servers. Clay maintains ~99 and will share a free/priority shortlist. |
| Trace | The captured record of the agent's activity—tool calls, sequence, failures, cost—produced while it runs. |
| Observability sandbox | The component that captures and summarizes traces so a human (or a score) can judge the run. |
| Scoring / rubric | How a run is judged: trace-derived workflow signals plus output quality vs. a rubric or reference examples. |
| Fixed caption task | A caption task on one image of one place at one date. |
| Change caption task | A caption task on two images of the same place at different dates. The caption describes what changed. |
| Position, counts, relationality | What each caption task tests: where objects are, how many there are, and how they sit relative to each other (for example, a road between two fields). |
| Caption rubric | The five criteria used to score caption output. See "Caption Generation: Tasks and Rubric". |

### Design Principles

- **Evaluating the agent is the product.** The deliverable is the observe-summarize-score loop, not a one-off dataset.
- **Known task + known input + a reference to score against.** Every evaluated task needs all three; the scoping session confirmed these for the first two tasks.
- **Keep the model and tracing tool swappable.** The team recommends a tracing/observability tool but must not hard-wire it.
- **Recorded-trace fallback.** If a live agent is flaky, replay recorded traces through the scoring sandbox so the demo always lands.

### The Three Tasks (teams pick one or more)

Avery confirmed teams should show up able to work on one or more of three tasks, with progress on each.

- **ADB agentic eval (recommended starting task).** Evaluate an agent (or set of agentic harnesses) on an ADB-style "how to use AI / build datasets" task. Needs: input data, the harness(es) under test, a scoring rubric, and prompts (teams bring synthetic prompts); the output is the source of traces gathered from observing the system. The eval scores the agentic workflow itself.
- **Caption generation (for the text-native Clay v2).** Input high-resolution satellite imagery (NAIP) plus sample Vantor data; the agent develops training captions and enables retrieval (e.g., "find railroads"). Captions cover fixed tasks (one image) and change tasks (two dates of the same place), and each tests position, counts and relationality. Output is scored on the five-criterion caption rubric below. Clay has example captions, and evaluation datasets check whether captions support the retrieval tasks.

### Caption Generation: Tasks and Rubric

#### Task types

| **Task type** | **Input** | **What the caption must get right** |
|---|---|---|
| Fixed | One image of a place at one date | Position, counts and relationality of the objects in the image |
| Change | Two images of the same place at different dates | Changes in position, counts and relationality between the two dates |

#### Rubric

Five criteria. Weighting is still to be decided, so report each score on its own until it is.

| **Criterion** | **Question it answers** |
|---|---|
| Retrieval quality | Can a caption be retrieved from a text query alone, with no image, using any off-the-shelf text model? |
| Grounding (most important) | Does the caption match what is actually on the ground, including objects, attributes and counts? |
| Fidelity | Does an LLM judge rate the caption as an accurate account of the image overall? |
| Cost | What are throughput and time to output for the same images and prompt across VLMs, measured in GPU time and number or size of GPUs rather than token cost? |
| Label preparation time | How long does it take to prepare the labels? |

#### Retrieval answer key (ADB suggestion)

ADB (Kinzah) reviewed both documents and suggested open data for the retrieval task. Teams could train on one region of Global Renewables Watch v1.0 or USGS USPVDB/USWTDB and test on another region that already has an LGND collection, using GRW, USGS or OpenStreetMap there as the answer key. Sources are listed under External Dependencies.

## MVP Scope

### MVP Objective

Build an observability + evaluation sandbox that runs an LLM harness against a known Clay task, lets the agent call geospatial tools via MCP, captures the agent's traces, and summarizes and scores both the workflow and the output against a rubric or reference examples—proving an agentic geospatial workflow can be evaluated end to end.

### MVP Success Criteria

- An LLM harness performs a chosen task (ADB eval or caption generation) by calling geospatial tools via MCP over public/synthetic input data.
- The agent's activity is captured as **traces** in an observability sandbox and **summarized** into a human-readable view.
- The run is **scored** on two dimensions: workflow signals from the traces (tool-call correctness/sequence, failures, steps/cost) and output quality vs. a rubric or reference examples.
- For the caption task, output is scored on each of the five **caption rubric** criteria: retrieval quality, grounding, fidelity, cost and label preparation time.
- The sandbox produces an **evaluation report** for the run.
- The tracing/observability tool and the model are both **swappable** (behind an abstraction).
- If the live agent fails, **recorded traces** can be replayed through the scoring sandbox to still produce a report.

### Features In Scope (MVP)

| **Feature** | **Description** | **Priority** | **Rationale for Inclusion** |
|---|---|---|---|
| LLM harness over MCP tools | Agent on Bedrock performs the task by calling geospatial MCP tools | Must Have | The agentic workflow is what we evaluate |
| Trace capture | Record the agent's tool calls, sequence, failures, cost | Must Have | No evaluation without observability |
| Trace summarization | Summarize traces into a readable view of what the agent did | Must Have | Clay explicitly wants to "summarize traces from agentic activity" |
| Scoring against rubric/reference | Score workflow + output vs. a rubric (ADB) or the five-criterion caption rubric and example captions | Must Have | A score is the point of the eval |
| Evaluation report | Per-run report combining summary + scores | Must Have | The deliverable a practitioner/partner reads |
| Swappable tracing tool + model | Abstraction over the observability tool and the Bedrock model | Must Have | Confirmed requirement: team recommends, keep swappable |
| Recorded-trace replay (fallback) | Replay stored traces through scoring when the live agent is flaky | Must Have | Keeps the demo reliable |
| Caption cost comparison | Run the same images and prompt through more than one VLM and record GPU time, GPU count and size, and time to output | Should Have | The caption rubric compares VLMs on hardware use, not tokens |
| Second task | Run the loop on a second of the three tasks | Exploratory | Shows the eval generalizes if time allows |
| Multi-agent traces | Planner/executor/checker traces | Exploratory | Bolder architecture if time allows |
| Minimal UI | Thin view to launch a run and read the report | Should Have | Makes the loop demonstrable |

### Features Explicitly Out of Scope (MVP)

| **Feature** | **Reason for Deferral** |
|---|---|
| Training the Clay v2 model itself | The hackathon evaluates workflows, it does not train the model |
| Running Clay's entire eval backlog | One (or a few) representative evals prove the loop |
| Partner-account deployment | Not needed to prove the eval loop; sandbox only |
| Continental-scale builds / Trainium-HyperPod orchestration | Exceeds a 2-day sandbox |
| Full production observability + warehouse stack (Snowflake/Iceberg/Athena, Managed Grafana) | Represent with lightweight tooling for the slice |

### MVP User Journeys

#### Journey 1: Evaluate an agentic run on a known task

- A developer selects a task (e.g., ADB eval) and provides its input data and synthetic prompts.
- The LLM harness runs, calling geospatial MCP tools to perform the task.
- The observability sandbox captures the agent's traces and summarizes them.
- The scorer rates the workflow (from traces) and the output (vs. rubric/examples).
- The sandbox emits an evaluation report.

**Outcome**: A trustworthy, inspectable judgment of how the agent performed—not just a final artifact.

**Limitation vs Full Vision**: One task, bounded input, representative rubric; not Clay's full eval catalog.

#### (Stretch) Journey 2: Robustness via sensitivity analysis

- Re-run the task while varying inputs, prompts, tool selection, or model.
- The sandbox compares traces and scores across variants.
- The report shows how stable the workflow and the evaluation are.

**Outcome**: Shows whether the agent's performance and the eval itself are robust.

**Why this is a stretch**: Requires the core loop solid first, plus multiple runs and comparison tooling.

### MVP Definition of Done

- A chosen task runs end to end: harness → MCP tools → trace capture → summarize → score → report.
- Scoring covers both workflow and output, against a rubric or example references.
- Tracing tool and model demonstrated as swappable.
- Recorded-trace fallback verified.
- Code committed to an open-source repo the Beneficiary can access after the event.

## Risks and Dependencies

### Key Risks

| **Risk** | **Likelihood** | **Impact** | **Mitigation** |
|---|---|---|---|
| No clear reference to score against for the chosen task | Medium | High | Confirmed sources: ADB rubric + synthetic prompts; example captions + retrieval eval set; GRW, USGS or OSM as retrieval answer keys. Secure these before the event |
| Live agent flaky in a 2-day build | Medium | High | Recorded-trace replay through the scoring sandbox |
| MCP server coverage/maturity gaps | Medium | Medium | Use Clay's free/priority shortlist from the 99; RODA MCP server as a known-good tool |
| NAIP Requester-Pays cost in the sandbox | Medium | Medium | Pre-stage a small NAIP sample; confirm cost handling |
| Scope creep across all three tasks | Medium | Medium | One task fully working first; others are stretch |
| Caption rubric weights not yet set | High | Medium | Report each criterion score on its own; apply weights once Clay sets them |
| Auxiliary caption datasets have unclear licenses or few human labels | Medium | Medium | Check each license before use; score only against human-labeled subsets (e.g., in RSCC) |

### External Dependencies

- **Input imagery**: NAIP on AWS — [https://registry.opendata.aws/naip/](https://registry.opendata.aws/naip/) (Requester-Pays, us-west-2).
- **Sample vector data**: s3://vantor-opendata.
- **Embeddings**: LGND embeddings (Clay) — [https://source.coop/clay/lgnd-embeddings](https://source.coop/clay/lgnd-embeddings).
- **Geospatial MCP tool**: RODA MCP server (AWS, Apache-2.0) — [https://aws.amazon.com/blogs/opensource/introducing-mcp-server-for-registry-of-open-data-on-aws/](https://aws.amazon.com/blogs/opensource/introducing-mcp-server-for-registry-of-open-data-on-aws/) — plus Clay's free/priority shortlist from Geo-MCP servers.
  - [geoMCP](https://docs.google.com/spreadsheets/d/1cMoPxhNTzNHuWEAK_PtAgFUqEMxQ1AyoZxMCzfdkYzQ/edit?usp=sharing)
- **ADB task**: input data, harness(es), scoring rubric (from Clay).
- **Caption task**: example captions + retrieval evaluation set (from Clay); five-criterion caption rubric (weights to be decided).
- **Retrieval answer keys** (suggested by ADB):
  - Global Renewables Watch v1.0, solar and wind worldwide, MIT license: [https://github.com/microsoft/global-renewables-watch/releases/tag/v1.0](https://github.com/microsoft/global-renewables-watch/releases/tag/v1.0)
  - USGS USPVDB and USWTDB, US solar and wind, public domain: [https://eerscmap.usgs.gov/uspvdb/](https://eerscmap.usgs.gov/uspvdb/) and [https://eerscmap.usgs.gov/uswtdb/](https://eerscmap.usgs.gov/uswtdb/)
  - OpenStreetMap: [https://www.openstreetmap.org](https://www.openstreetmap.org)
- **Auxiliary caption datasets** (optional; check each license before use):
  - Change tasks: [LEVIR-CC](https://github.com/Chen-Yang-Liu/LEVIR-CC-Dataset); [Change-Agent](https://github.com/Chen-Yang-Liu/Change-Agent), which adds change masks; [SECOND-CC](https://github.com/ChangeCapsInRS/SecondCC); [RSCC](https://github.com/Bili-Sakura/RSCC), larger, but only a small subset may be human labeled.
  - Fixed tasks: [VRSBench](https://github.com/lx709/VRSBench); [RSICD_optimal](https://github.com/201528014227051/RSICD_optimal).
- Empty AWS sandbox; open-source repo created at kickoff.
