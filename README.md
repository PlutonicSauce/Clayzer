# Clayzer

Caption generation and evaluation for the text-native Clay v2 model, built for the Clay Earth
Dataset Foundry hackathon. The plan is [docs/caption-plan.md](docs/caption-plan.md); terms are
in [GLOSSARY.md](GLOSSARY.md).

## Walking skeleton

One path end to end, with crude parts (caption-plan.md §7, Day 1):

```
USGS site ──► NAIP Chip (Planetary Computer) ──► Case with USGS + OSM Reference Labels
                                                   │
                       Chip only (ADR-0006) ◄──────┘
                              │
                        Nova Pro Caption ──► grounding · fidelity (Opus 5.5) · retrieval (Titan)
                                              ──► batches/<batch-id>/report.html
```

### Set up

Needs Python 3.12 and [uv](https://docs.astral.sh/uv/).

```sh
uv sync
```

Put AWS credentials for an account with Bedrock access to Nova Pro, Opus 5.5, and Titan Text
Embeddings v2 in `.env` at the repo root (gitignored). `export` lines are fine:

```sh
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_SESSION_TOKEN=...
AWS_DEFAULT_REGION=us-west-2
```

Credentials in `.env` take precedence over a shell's AWS profile, region, or Bedrock bearer
token.

### Storage

Each teammate has their own hackathon AWS account, so each uses their own bucket; git is the
shared layer (caption-plan.md §3). In your account:

```sh
# one-time: a private bucket (public access blocked, encrypted by default)
aws s3api create-bucket --bucket clayzer-<account-id>-us-west-2 --region us-west-2 \
  --create-bucket-configuration LocationConstraint=us-west-2
aws s3api put-public-access-block --bucket clayzer-<account-id>-us-west-2 \
  --public-access-block-configuration \
  BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
```

Then add to `.env`:

```sh
CLAYZER_STORE=s3://clayzer-<account-id>-us-west-2/caption
CLAYZER_NAIP_SOURCE=aws
```

`uv run clayzer push --from <dir>` copies a local `chips/` + `cases/` folder (such as the
committed fixtures) into your bucket.

### Build Cases

Each command cuts a 512 × 512 Chip, fetches Reference Labels, and adds the Case to
`cases/caption-dev.jsonl` in the store:

```sh
uv run clayzer case uspvdb 400117              # solar: USPVDB site id
uv run clayzer case uswtdb 3025453             # wind: USWTDB turbine id
uv run clayzer case neg -119.20 35.45 --n 1    # negative: lon lat; refused if USGS is nearby
```

Positives use the latest NAIP image taken after the site was built. Site and turbine ids come
from the USGS APIs (`https://energy.usgs.gov/api/uspvdb/v1/projects`,
`https://energy.usgs.gov/api/uswtdb/v1/turbines`).

### The evaluation loop

A **Run** is one Harness execution on one Case; a **Batch** runs every Case several times
(**Repeats**) under one fixed configuration. Change one thing, run a Batch, compare it with
the **Baseline**, and let the regression gate decide whether to keep the change.

```sh
uv run clayzer batch --repeats 3 --label base         # every Case × 3 Repeats
uv run clayzer baseline accept <batch-id>              # writes baselines/default/ (commit it)

uv run clayzer batch --repeats 3 --label terse --prompt prompts/terse.txt
uv run clayzer compare <baseline-batch-id> <candidate-batch-id>
uv run clayzer gate <candidate-batch-id>               # exit 0 pass, 1 fail, 2 inconclusive
```

Other options: `--caption-model`, `--only <case-id> ...`, `--no-judge`. `clayzer batches`
lists Batches; `clayzer report <batch-id>` rebuilds a Batch's reports; `clayzer rescore
<batch-id>` scores its stored Captions again with the current scorer, without calling a model.

Each Run ends `ok`, `harness_fault` (no usable Caption: scored 0), or `sandbox_failure`
(Bedrock, network, or credentials: no valid score, excluded). Results are saved after every Run.
Expired session credentials stop the Batch cleanly; refresh `.env` and finish it with:

```sh
uv run clayzer batch --resume <batch-id>
```

**Tools.** With `--tools`, the Harness becomes a tool-use loop: the captioning model may call
MCP tools before it submits its Caption, for up to 8 model turns. Each tool call is a `tool`
Step in the Run's Trace, and `batch.json` records the servers. Only servers allowed for the
caption Harness are known (`src/clayzer/tools.py`; ADR-0006). Needs the `tools` extra and `uvx`:

```sh
uv sync --extra tools
uv run clayzer batch --tools roda --label roda
```

A Batch writes `batches/<batch-id>/` in the store: `batch.json` (models, prompt hash, Cases
hash, Repeats, scorer version), `prompt.txt`, `cases.jsonl` (frozen at the start),
`results.jsonl`, `captions.jsonl`, `retrieval.jsonl`, `summary.json` (per-Case mean and
Spread), `report.md`, `report.html`, and `traces/`: one Trace per Run
(`<case-id>--r<repeat>.jsonl`). A Trace records every model call as a Step, with the full
prompt and response, the image by key and hash, wall time and Bedrock's own latency, tokens,
retries, and the error code of anything that failed; Judge calls are marked as scoring. Each
failed Step is attributed (ADR-0003, `faults.py`): a Harness Fault (a bad request, a missing
`submit_caption` call, anything unrecognized), an Environment Fault (throttling, timeouts,
network, access), or a Sandbox Failure (the Judge). Runs and Batch summaries carry the counts.

```sh
uv run clayzer trace <batch-id> <case-id> --repeat 1          # one Run, Step by Step
uv run clayzer trace <batch-id> <case-id> --repeat 1 --json   # the raw Trace
```

`report.html` is the one to open: a single self-contained file (no server, no network) with
each Chip, its Claims and Reference Labels drawn on the 3×3 grid, mean ± Spread per Case, and
every Repeat's Caption, Claims, and Judge notes.

**Grounding** is two numbers: **correctness** (of what the Caption claimed, how much is right:
precision, count, position, attributes, relations) and **coverage** (how much of the Answer Key
it mentions). A terse Caption scores high on the first and low on the second.

**The regression gate.** A Case's grounding correctness, grounding coverage, or fidelity, or
the Batch's retrieval, regresses when its mean drops by more than max(0.05, the Baseline's
Spread), Spread being the run-to-run standard deviation across Repeats. Any regression, or a
Baseline Case missing from the candidate, fails the gate. A Case whose Spread grows sharply
gets a warning: the captioner became erratic there. Sandbox Failures make it inconclusive. It warns when a measurement
setting differs (Judge, embedding model, Cases, scorer version), when there are fewer than 3
Repeats, and when tokens per Caption rise more than 25% (`--max-token-increase 0.5` makes that
fail instead).

### The team web app

```sh
uv sync --extra ui
uv run clayzer ui                  # http://127.0.0.1:8770, read-only
uv run clayzer ui --allow-launch   # also lets the browser run Batches
```

- **Overview:** the workflow, step by step (what each step is, why it's there, where it lives,
  and whether it's built), plus the latest Batch next to the Baseline.
- **Tasks:** the work board from [`docs/tasks.toml`](docs/tasks.toml), by functional area. Each
  task has a **Brief** (context, the requirements it closes, what done means, what to read first)
  and a **Copy brief for your agent** button that puts all of it, plus the repo rules, on the
  clipboard as Markdown. `#/tasks/<task-id>` links straight to one. To take a task, put your
  name in its `owner` field and open a PR.
- **Cases:** every Chip in the store with its Reference Labels.
- **Batches:** every Batch, its report, its regression gate against the Baseline, and
  Compare between any two.
- **Concepts:** the glossary.

It reads whatever store your settings point at (your bucket, or local folders) and listens on
localhost only.

### Settings

| Variable | Default |
|---|---|
| `CLAYZER_CAPTION_MODEL` | `us.amazon.nova-pro-v1:0` |
| `CLAYZER_JUDGE_MODEL` | `us.anthropic.claude-opus-5-5` |
| `CLAYZER_EMBED_MODEL` | `amazon.titan-embed-text-v2:0` |
| `CLAYZER_BEDROCK_ENDPOINT_URL` | unset (a private Bedrock endpoint, if your network needs one) |
| `CLAYZER_OVERPASS_URL` | `https://overpass-api.de/api/interpreter` |
| `CLAYZER_STORE` | unset: local `data/` and `batches/`. `s3://<bucket>/<prefix>` for S3 |
| `CLAYZER_NAIP_SOURCE` | `pc` (Planetary Computer). `aws` reads `naip-visualization` (Requester-Pays, us-west-2) |
| `CLAYZER_DATA_DIR`, `CLAYZER_BATCHES_DIR` | `data/`, `batches/` (local store, and local copies of reports) |
| `CLAYZER_BASELINES_DIR` | `baselines/` (committed) |

Behind a TLS-intercepting proxy, set `SSL_CERT_FILE` to the proxy's CA bundle; it's passed to
GDAL for NAIP reads too. MCP servers that ignore it (RODA does) need `CLAYZER_MCP_SYSTEM_TRUST=1`,
which starts them with the OS trust store.

### Hosting it on AWS

One CDK app ([`infra/app.py`](infra/app.py)) puts the read-only web app in your own account
behind an HTTPS CloudFront URL: CloudFront → Application Load Balancer → one ECS Fargate task
(ARM64) that reads your store bucket. It needs Node (for the CDK CLI) and Docker or Podman.

```sh
uv sync --group infra
cd infra
npx aws-cdk@2 bootstrap                                   # once per account and region
npx aws-cdk@2 deploy -c store=s3://<your bucket>/<prefix>  # prints the Url output
```

Leave out `-c store=...` to have the stack create a new bucket. With Podman, set
`CDK_DOCKER=podman`. The hosted app never starts Batches, and its role can only read the store
prefix. `npx aws-cdk@2 destroy` removes everything except the bucket.

To build the image on its own: `docker build -t clayzer .` (see the
[Dockerfile](Dockerfile) for mirror and proxy options).

### Tests

```sh
uv run pytest
```

### Not built yet

- Verify-then-write and the LGND Geo sign-in; the tool-use loop has only RODA so far.
- Workflow Score and Trace summaries (REQ-05, REQ-06 in
  [caption-design.md §2.3](docs/caption-design.md#23-evaluation-loop-requirements)).
- Change Cases and the RSICD and VRSBench benchmarks.
- The open work, by area, is on the Tasks page (`docs/tasks.toml`).
- USGS positions use site centroids, not polygons.
