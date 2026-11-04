# Technical Environment Document: Clay Earth Dataset Foundry

## Hackathon Approach and Expectations

Read this first. It sets expectations for how to use the rest of this document.

- **Build an evaluation sandbox, not a model.** The goal is to **observe, summarize, and score agentic geospatial workflows**. The agent runs a known task by calling geospatial tools via MCP; you capture its traces and score the run. Spend your time on the observe-summarize-score loop.
- **The tasks, pick one or more.** Teams should make progress on one or more of the the tasks below; the **ADB agentic eval** is the recommended starting point.
- **Keep the model and the tracing tool swappable.** Use Amazon Bedrock for the agent, behind an abstraction. The team **recommends** a tracing/observability tool but must keep it swappable—nothing hard-wired.
- **Greenfield, self-contained, migration-aware.** Build in an empty sandbox that mirrors the setup without integrating into Clay's systems; choose shapes that map cleanly back to Clay's account.
- **Data: public or synthetic only.** NAIP imagery, Vantor open data, LGND embeddings, openly licensed reference data (GRW, USGS, OSM), and synthetic prompts/captions. Mind NAIP's Requester-Pays billing.
- **Reliability: record traces.** Capture traces so a flaky live agent can be replaced by replaying recorded traces through the scoring sandbox for the demo.

## Project Technical Summary

- **Project Name**: Clay Earth Dataset Foundry (MVP — agentic-workflow evaluation sandbox)
- **Primary Runtime Environment**: Cloud
- **Cloud Provider**: AWS
- **Target Deployment Model**: Flexible (serverless / containers / K8s), single sandbox account.
- **Customer Team Experience**: Deep geospatial-ML practice—open Earth foundation model, 15.2B published embeddings (Apache-2.0), an existing evaluation harness, continental-scale inference; existing use of S3, SageMaker, Bedrock, Snowflake; maintains a catalog of ~99 MCP servers.

## The Tasks (input data & scoring)

| **Task** | **Agent does** | **Input data (public/synthetic)** | **Score against** |
|---|---|---|---|
| **ADB agentic eval** *(start here)* | Performs an ADB-style AI/dataset-build task under test | Input dataset + harness(es) under test + **synthetic prompts** (teams bring) | **Scoring rubric**; output is the **traces** gathered from observing the system |
| **Caption generation** (Clay v2) | Imagery → training captions for fixed (one date) and change (two dates) tasks, each covering position, counts and relationality; enable retrieval (e.g., "find railroads") | **NAIP** high-res imagery + **sample Vantor data** (s3://vantor-opendata); optional auxiliary caption datasets | **Five-criterion caption rubric** + **example captions** (Clay has them) + retrieval **evaluation datasets**; GRW, USGS or OSM as retrieval answer keys |

**Getting started (Day 1):** Start with the **ADB agentic eval**. Stand up the LLM harness on Bedrock, wire in the **RODA MCP server** (uvx awslabs.roda-mcp-server@latest) plus one or two from Clay's priority MCP shortlist, and get a single trace captured end to end before adding scoring. Prove the observe → summarize → score loop on one task before touching a second.

## Caption Track: Tasks, Rubric and Answer Key

### Task types

| **Task type** | **Input** | **What the caption must get right** |
|---|---|---|
| Fixed | One image of a place at one date | Position, counts and relationality (how objects sit relative to each other) in the image |
| Change | Two images of the same place at different dates | Changes in position, counts and relationality between the two dates |

### Rubric and how to measure it

Five criteria. Weighting is still to be decided, so score and report each criterion on its own and apply weights later.

| **Criterion** | **What it checks** | **How to measure** |
|---|---|---|
| Retrieval quality | A caption can be found from a text query alone, with no image | Embed captions and queries with any off-the-shelf text model; record how often the right caption is in the top results |
| Grounding (most important) | The caption matches what is on the ground: objects, attributes and counts | Compare caption claims with reference labels (GRW, USGS, OSM, Vantor vectors or human-labeled datasets) |
| Fidelity | The caption represents the image accurately overall | An LLM judge compares caption and image and gives a score |
| Cost | Throughput and time to output across VLMs | Same images and prompt for each VLM; record GPU time and number or size of GPUs, not token cost |
| Label preparation time | How long labels take to prepare | Record the time taken to prepare each label set |

### Retrieval answer key (ADB suggestion)

Train on one region of Global Renewables Watch v1.0 or USGS USPVDB/USWTDB, then test on another region that already has an LGND collection, using GRW, USGS or OSM there as the answer key.

## Programming Languages

### Required Languages

| **Language** | **Version** | **Purpose** | **Rationale** |
|---|---|---|---|
| Python | 3.12+ | Agent/harness, MCP wiring, trace capture/scoring, geospatial processing | Geospatial + agent/MCP ecosystems live in Python; matches Clay |
| TypeScript / JavaScript | 5.x / Node 20+ | Thin UI; MCP servers if authored in TS | Standard thin front end; strong MCP support |

### Permitted Languages

SQL (lightweight trace/metadata store), Bash (sandbox scripting).

## Frameworks and Libraries

### Required / Expected

| **Framework/Library** | **Domain** | **Rationale** |
|---|---|---|
| An agent framework (kept swappable) | LLM harness: plan → tool-call → task | The agentic workflow under evaluation; framework not prescribed |
| MCP SDK + geospatial MCP server(s) | Expose geospatial tools to the agent | RODA MCP server + Clay's free/priority shortlist from 99 |
| A tracing/observability tool (team recommends, swappable) | Capture + summarize agent traces | Confirmed: team chooses, must stay swappable (an OpenTelemetry-based LLM trace approach is a reasonable default) |
| Geospatial stack (rasterio / GDAL / xarray / pystac) | Imagery handling, STAC assets | Standard toolkit for NAIP/public archives |
| AWS SDK for Python (boto3) | S3, Bedrock access | Native AWS integration |

### Preferred Libraries

| **Library** | **Purpose** | **Use When** |
|---|---|---|
| Clay / LGND embeddings (Apache-2.0) | Imagery embeddings for captioning/retrieval | Reuse rather than train |
| scikit-learn / numpy | Scoring metrics (output vs. reference) | Scoring the task output |
| An off-the-shelf text embedding model | Caption retrieval-quality score (text query to caption, no image) | Scoring the caption task |
| FastAPI | Thin API behind the UI | Launching runs, serving reports |

## Models and AI Services

- **Provider**: Amazon Bedrock for the agent's reasoning, behind an abstraction so the model is easy to swap.
- **Embeddings**: Clay / LGND embeddings for the caption/retrieval task.
- **Caption VLMs**: Run the caption task on more than one VLM with the same images and prompt, so cost can be compared in GPU time and GPU count and size.
- **MCP**: The agent reaches geospatial capabilities through MCP servers. Start with the **RODA MCP server** (AWS, Apache-2.0) and Clay's **free/priority shortlist** from its 99 servers.

## Observability and Evaluation (the heart of the build)

- **Capture**: record every agent step—tool calls, arguments, sequence, failures/retries, latency, cost. For caption runs, record cost as GPU time and GPU count and size rather than tokens.
- **Summarize**: turn raw traces into a readable summary of what the agent did and where it struggled (Clay's explicit ask: "summarize traces from agentic activity").
- **Score — two dimensions**:
  - **Workflow (from traces)**: tool-call correctness and sequencing, error recovery, steps/cost.
  - **Output**: quality vs. the task's reference—**rubric** (ADB) or **example captions + retrieval eval set** (captions), scored on the five-criterion **caption rubric**.
- **Report**: a per-run evaluation report combining the summary and the scores.
- **Swappable tooling**: the tracing/observability tool is the team's recommendation but must sit behind an abstraction; same for the model.
- **Fallback**: persist traces so recorded runs can be replayed through scoring if the live agent misbehaves.

## Cloud Environment

### Cloud Provider

- **Primary Provider**: AWS
- **Account Structure**: Single empty hackathon sandbox account (greenfield). No connection to Clay's production account.
- **Regions**: Note **NAIP is in us-west-2 and Requester-Pays**—account for region and billing (pre-stage a small sample if helpful).

### Confirmed Data Sources

| **Source** | **What** | **Access notes** |
|---|---|---|
| NAIP on AWS | High-res (0.3–1 m) 4-band US aerial imagery | s3://naip-analytic (MRF), naip-source (GeoTIFF), naip-visualization (RGB COG); **Requester-Pays**, **us-west-2** |
| Vantor open data | Sample vector data for captioning | s3://vantor-opendata |
| LGND embeddings | Clay/LGND embeddings | [https://source.coop/clay/lgnd-embeddings](https://source.coop/clay/lgnd-embeddings) |
| RODA MCP server | AWS Apache-2.0 MCP server for Registry of Open Data discovery/sampling | uvx awslabs.roda-mcp-server@latest |
| MCP server catalog | Clay's ~99 MCP servers | Clay to share **free + priority** shortlist |
| Global Renewables Watch v1.0 | Solar and wind sites worldwide; retrieval answer key | MIT license; [https://github.com/microsoft/global-renewables-watch/releases/tag/v1.0](https://github.com/microsoft/global-renewables-watch/releases/tag/v1.0) |
| USGS USPVDB / USWTDB | US solar and wind sites; retrieval answer key | Public domain; [https://eerscmap.usgs.gov/uspvdb/](https://eerscmap.usgs.gov/uspvdb/) and [https://eerscmap.usgs.gov/uswtdb/](https://eerscmap.usgs.gov/uswtdb/) |
| OpenStreetMap | Map features; retrieval answer key | ODbL license; [https://www.openstreetmap.org](https://www.openstreetmap.org) |
| LGND Geo MCP server | Provides access to easy search of Earth data for LLMs and LLM tools. | This is a commercial product. You will be whitelisted to use it for the purposes of the hackathon. [https://lgnd.ai/geo](https://lgnd.ai/geo) |
| SkyScript | “A Large and Semantically Diverse Vision-Language Dataset for Remote Sensing" | [https://github.com/wangzhecheng/skyscript](https://github.com/wangzhecheng/skyscript) |
| MegaEarth | MegaEarth pairs Sentinel-2 windows with OpenStreetMap labels for 485 classes, grouped into families and split by geography, testing whether image features transfer to unseen categories.  | [https://huggingface.co/datasets/Mead0w1ark/megaearth-osm-sentinel2](https://huggingface.co/datasets/Mead0w1ark/megaearth-osm-sentinel2) |

### Auxiliary Caption Datasets (optional)

Check each license before use.

| **Dataset** | **Task type** | **Notes** |
|---|---|---|
| [LEVIR-CC](https://github.com/Chen-Yang-Liu/LEVIR-CC-Dataset) | Change | Change captioning and detection |
| [Change-Agent](https://github.com/Chen-Yang-Liu/Change-Agent) | Change | Adds change masks |
| [SECOND-CC](https://github.com/ChangeCapsInRS/SecondCC) | Change | Change captioning |
| [RSCC](https://github.com/Bili-Sakura/RSCC) | Change | Larger set; only a small subset may be human labeled |
| [VRSBench](https://github.com/lx709/VRSBench) | Fixed | Single-image descriptions |
| [RSICD_optimal](https://github.com/201528014227051/RSICD_optimal) | Fixed | Single-image captions |

### Service Disallow List

| **Service** | **Reason** | **Alternative** |
|---|---|---|
| SageMaker HyperPod / large Trainium clusters | Overkill for a sandbox eval slice | Modest instance / managed endpoint / mocked inference |
| Multi-account / cross-account deployment | Out of MVP scope | Single sandbox account |
| Full Snowflake/Iceberg/Athena warehouse | Heavy; not needed to prove the loop | Lightweight trace/metadata store |
| Any customer-private/sensitive data | Sandbox is public/synthetic only | NAIP, Vantor, LGND embeddings, open reference data (GRW, USGS, OSM), synthetic prompts/captions |

## Preferred Technologies and Patterns

| **Pattern** | **When to Use** | **When Not to Use** |
|---|---|---|
| Observe → summarize → score the agent | Default: every run is traced, summarized, and scored | Never evaluate on final output alone with no trace |
| Model + tracing tool behind abstractions | Keep both swappable | Never hard-wire a specific model or tracing vendor |
| Recorded-trace replay | Demo reliability and offline scoring | — |
| Read data at the source via MCP | Stream NAIP/Vantor through MCP tools | When a tiny pre-staged sample is faster/cheaper (Requester-Pays) |
| Greenfield, migration-aware | Self-contained sandbox, shapes that map to Clay's account | When a shortcut makes migration harder |

## Stretch Goals (if the team moves fast)

- Evaluate a **second (or third) task** to show the loop generalizes.
- **Multi-agent** (planner/executor/checker) traces.
- **Dynamic MCP tool discovery** across Clay's 99-server catalog.
- A richer **trace-summary dashboard**.
- **Sensitivity analysis** — vary inputs, prompts, tool selection, or model and measure how much the output and the trace/scores change (robustness of the workflow and the eval).
