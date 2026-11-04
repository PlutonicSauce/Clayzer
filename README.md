# Clayzer

[![CI](https://github.com/PlutonicSauce/Clayzer/actions/workflows/ci.yml/badge.svg)](https://github.com/PlutonicSauce/Clayzer/actions/workflows/ci.yml)

Caption generation and evaluation for the text-native Clay v2 model, built for the Clay Earth
Dataset Foundry hackathon.

Clayzer cuts aerial images (NAIP) around places whose contents are known from public data (USGS
solar and wind sites, OpenStreetMap). An AI model captions each image without seeing those
answers, and every caption is scored against them. Each experiment runs every image several
times and is compared with the current best, so a change to the captioner is kept only when the
scores show it helps.

```
USGS site ──► NAIP Chip ──► Case (Chip + Reference Labels)
                               │
          Chip only ◄──────────┘
              │
        Caption (Nova Pro) ──► grounding · fidelity (Opus 5.5) · retrieval (Titan) · Workflow Score
                                 ──► report, Compare, regression gate
```

## Getting started

### 1. Install

You need Python 3.12+, [uv](https://docs.astral.sh/uv/), and git.

```sh
git clone https://github.com/PlutonicSauce/Clayzer.git
cd Clayzer
uv sync --extra ui --extra tools
```

### 2. Start the web app

```sh
uv run clayzer push --from fixtures/caption   # load the team's 63 Cases, no AWS needed
uv run clayzer ui
```

Open <http://127.0.0.1:8770>. It runs locally and is read-only. The first command copies the
committed [development Cases](fixtures/caption/README.md) into your store (the local `data/`
folder, or your bucket once `CLAYZER_STORE` is set), so the **Cases** page shows them. Batches
appear once you run one, which needs AWS (step 3).

| Page | What's there |
|---|---|
| Overview | the latest scores against the Baseline, and a sample caption on its image |
| How it works | the ten steps from image to kept change, each linked to its plan and design sections |
| Cases | every image with its Reference Labels |
| Batches | every experiment: its report, provenance, regression gate, and Compare |
| For Dev Team | Tasks, Data sources, Concepts (the glossary), and the pitch deck |

### 3. Connect your AWS account

Building Cases and running Batches call Amazon Bedrock. Use your own hackathon account with access
to Nova Pro, Claude Opus 5.5, and Titan Text Embeddings v2. Put its credentials in `.env` at the
repo root; it's gitignored, so never commit it.

```sh
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_SESSION_TOKEN=...
AWS_DEFAULT_REGION=us-west-2
```

Results stay in local folders unless you point `CLAYZER_STORE` at an S3 bucket in your account
([Storage](docs/cli.md#storage)). If you set it, run `clayzer push --from fixtures/caption` again
to load the Cases into the bucket.

### 4. Run your first Batch

A Batch captions every Case several times, and all 63 cost real Bedrock time, so start with two:

```sh
uv run clayzer batch --repeats 1 --label first --only fixed-dev-uspvdb-400117 fixed-dev-neg-1
```

Refresh the web app's **Batches** page to see the result, or open the `report.html` the command
prints. To add a Case of your own, see [Build Cases](docs/cli.md#build-cases).

## Using the CLI

Every command reads from and writes to the store. `uv run clayzer --help` lists them all.

| Command | What it does |
|---|---|
| `clayzer case uspvdb <id>` / `uswtdb <id>` / `neg <lon> <lat>` | build a Case |
| `clayzer batch --repeats 3 --label <name>` | run every Case 3 times under one configuration |
| `clayzer batch --resume <batch-id>` | finish a stopped Batch |
| `clayzer compare <batch-a> <batch-b>` | what changed between two Batches, and by how much |
| `clayzer baseline accept <batch-id>` | make a Batch the Baseline |
| `clayzer gate <batch-id>` | keep or reject a change: exit 0 pass, 1 fail, 2 inconclusive |
| `clayzer trace <batch-id> <case-id> -r 1` | one Run's summary and Trace, Step by Step |
| `clayzer login lgnd` / `clayzer tools lgnd` | sign in to LGND Geo, and list or call its tools |
| `clayzer ui [--allow-launch]` | the web app; `--allow-launch` lets the browser start Batches |

Options, what a Batch stores, how scoring works, settings, and AWS hosting are in the
[CLI and configuration reference](docs/cli.md).

## Find your way around

| Looking for | Go to |
|---|---|
| Something to work on | the web app's **For Dev Team → Tasks**, or [docs/tasks.toml](docs/tasks.toml). Each task has a brief you can paste into your coding agent. |
| How it fits together | the web app's **How it works** page |
| The plan: what we build and why | [docs/caption-plan.md](docs/caption-plan.md) |
| The design: requirements and architecture | [docs/caption-design.md](docs/caption-design.md) |
| What a term means (Case, Chip, Run, Trace…) | [GLOSSARY.md](GLOSSARY.md) |
| Why a decision was made | [docs/adr/](docs/adr/) |
| The hackathon briefs | [technical](docs/tech-hackathon.md), [vision](docs/vision-hackathon.md) |
| Every command and setting | [docs/cli.md](docs/cli.md) |

## Project layout

```
src/clayzer/        the package: Cases, Harness, scoring, Batches, Traces, CLI
src/clayzer/ui/     the web app (FastAPI and a no-build front end)
docs/               plan, design, ADRs, tasks, data sources, CLI reference
ontology/           the object classes a Claim can name
baselines/          the accepted Baseline (committed)
infra/              the CDK app that hosts the web app on AWS
tests/              offline tests: no AWS needed
```

## Contributing

1. Pick a task, put your name in its `owner` field in [docs/tasks.toml](docs/tasks.toml), and work
   on a branch for that task.
2. Before opening a PR, run the checks CI ([.github/workflows/ci.yml](.github/workflows/ci.yml))
   runs on every PR and every push to main:

   ```sh
   uv run ruff check src tests
   uv run ruff format --check src tests
   uv run vulture
   uv run --extra ui --extra tools pytest --cov
   node tests/deck_smoke.mjs
   npx --yes jscpd@5.4.2 src --min-tokens 50 --threshold 3 --ignore "**/vendor/**"
   ```

   Ruff also caps function complexity at 15. Vulture flags dead code, coverage must stay at or
   above 75%, and duplicated code must stay under 3%.

3. In the PR, update the task's `status`. Done tasks also get `see_it` and `changes`.

**This repo is public.** Never commit `.env`, AWS keys or account ids, `data/`, `batches/`,
downloaded datasets or benchmark images, or private hostnames and package indexes. Use the
[glossary](GLOSSARY.md)'s terms, and record decisions as ADRs.
