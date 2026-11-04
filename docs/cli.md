# Clayzer CLI and configuration reference

Everything the `clayzer` command does, and the settings it reads. Start with the
[README](../README.md) to get set up; the terms are in the [glossary](../GLOSSARY.md), and the why
is in the [plan](caption-plan.md) and [design](caption-design.md).

`uv run clayzer --help` lists every command; `uv run clayzer <command> --help` shows its options.

## Storage

By default everything lives in local folders: `data/` (Chips and Cases) and `batches/`. To share
results across machines or host the web app, use an S3 bucket in your own AWS account. Each
teammate has their own account, so each uses their own bucket; git is the shared layer
(caption-plan.md §3).

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

`uv run clayzer push --from <dir>` copies a local `chips/` + `cases/` folder into your store;
`--from fixtures/caption` loads the team's committed development Cases.

## Build Cases

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

## The evaluation loop

A **Run** is one Harness execution on one Case; a **Batch** runs every Case several times
(**Repeats**) under one fixed configuration. Change one thing, run a Batch, compare it with the
**Baseline**, and let the regression gate decide whether to keep the change.

```sh
uv run clayzer batch --repeats 3 --label base          # every Case × 3 Repeats
uv run clayzer baseline accept <batch-id>              # writes baselines/default/ (commit it)

uv run clayzer batch --repeats 3 --label terse --prompt my-prompt.txt
uv run clayzer compare <baseline-batch-id> <candidate-batch-id>
uv run clayzer gate <candidate-batch-id>               # exit 0 pass, 1 fail, 2 inconclusive
```

Other options: `--caption-model`, `--only <case-id> ...`, `--no-judge`, `--no-narrate`.

| Command | What it does |
|---|---|
| `clayzer batches` | list Batches |
| `clayzer report <batch-id>` | rebuild a Batch's reports |
| `clayzer rescore <batch-id>` | score its stored Captions again with the current scorer, no model calls |
| `clayzer trace <batch-id> <case-id> --repeat 1` | one Run, Step by Step (`--json` for the raw Trace) |
| `clayzer summarize <batch-id>` | rebuild every Run's summary offline (`--narrate` writes missing narratives) |

Each Run ends `ok`, `harness_fault` (no usable Caption: scored 0), or `sandbox_failure` (Bedrock,
network, or credentials: no valid score, excluded). Results are saved after every Run. Expired
session credentials stop the Batch cleanly; refresh `.env` and finish it with
`uv run clayzer batch --resume <batch-id>`.

### What a Batch stores

A Batch writes `batches/<batch-id>/` in the store:

- `batch.json`: the configuration and its provenance: models, hashes of the prompt, Cases,
  Chips, Judge rubric, and ontology, Repeats, scorer version, and git commit
- `prompt.txt`, `judge-prompt.txt`: the caption prompt and the Judge's rubric
- `cases.jsonl`: the Cases, frozen at the start; `chips.json`: a SHA-256 of every Chip, checked
  before each Run
- `results.jsonl`, `captions.jsonl`, `retrieval.jsonl`, `summary.json` (per-Case mean and Spread)
- `report.md`, `report.html`: `report.html` is a single self-contained file with each Chip, its
  Claims and Reference Labels on the 3×3 grid, mean ± Spread per Case, and every Repeat's Caption
- `traces/`: one Trace per Run (`<case-id>--r<repeat>.jsonl`), with its summary and narrative
- `runs/`: one report per Run (`<case-id>--r<repeat>.html` and `.json`)

A **Trace** records every model and tool call as a Step: the full prompt and response, the image
by key and hash, wall time and Bedrock's latency, tokens, retries, and the error code of anything
that failed. Each failed Step is attributed (ADR-0003, `faults.py`): a Harness Fault (a bad
request, a missing `submit_caption` call, anything unrecognized), an Environment Fault
(throttling, timeouts, network, access), or a Sandbox Failure (the Judge).

Every Run gets a **summary** of its Trace: code writes the facts (`summarize.py`), and a model
writes a readable narrative from the Trace alone (`narrate.py`, `CLAYZER_SUMMARY_MODEL`). The
narrative is saved with a hash of its Trace, so replays never call a model.

### How it's scored

- **Grounding** is two numbers: **correctness** (of what the Caption claimed, how much is right)
  and **coverage** (how much of the Answer Key it mentions).
- **Fidelity:** an image-aware Judge (Opus 5.5) rates the Caption against the Chip.
- **Retrieval:** whether the Caption finds its own Chip by embedding search (Titan).
- **Workflow Score** (`workflow.py`, REQ-06): how well the Harness worked, from its Trace alone:
  finishing with a Caption, the tool plan, tool-call success, recovery after Harness Faults, turns
  against the budget, and tokens against `CLAYZER_TOKEN_BUDGET` if set. Environment Faults never
  lower it.

**The regression gate.** A Case's score regresses when its mean drops by more than max(0.05, the
Baseline's Spread). Any regression, or a Baseline Case missing from the candidate, fails the gate;
Sandbox Failures make it inconclusive. It warns when a measurement setting differs (Judge, Judge
rubric, embedding model, Cases, Chips, ontology, scorer version), when there are fewer than 3
Repeats, and when tokens per Caption rise more than 25% (`--max-token-increase 0.5` makes that
fail instead).

## Tools

With `--tools`, the Harness becomes a tool-use loop: the captioning model may call MCP tools
before it submits its Caption, for up to 8 model turns. Only servers allowed for the caption
Harness are known (`src/clayzer/tools.py`; ADR-0006). Needs the `tools` extra and `uvx`:

```sh
uv sync --extra tools
uv run clayzer batch --tools roda --label roda
```

A server that reads an Answer Key (OpenStreetMap, Nominatim, Overture, USGS and the like) is
refused, by name, before the Batch writes anything: `refused to start the Batch: MCP server ...
would let the Harness read ... data, which holds the Answer Keys (ADR-0006)`. The check is one
function ([`allowlist.py`](../src/clayzer/allowlist.py)) used by the Toolbox, by Batches, and by
the AgentCore Runtime. Each Batch records every server's pin (`tool_servers`) and what each
reported on connecting (`tool_versions`) in `batch.json`, and Compare shows a change in either.

LGND Geo (`lgnd`) is remote and signs each person in through OAuth. Sign in once; the sign-in is
saved in `~/.clayzer/auth/` (or `CLAYZER_AUTH_DIR`), outside the repo. A Batch never opens a
browser: without a saved sign-in it stops and says to run `login`.

```sh
uv run clayzer login lgnd     # opens the browser once
uv run clayzer tools lgnd     # list its tools
uv run clayzer tools lgnd --call search_chip_lat_lon --args '{"index": "naip", "lat": 35.2294, "lon": -118.1930}'
```

**Verify, then write.** With `--verify`, the Harness checks each drafted Claim with LGND Geo
before the Caption commits (`src/clayzer/verify.py`): it looks up LGND's NAIP image at the centre
of the Claim's grid cell and asks LGND's image model whether the object is there. Claims it
confirms stay; the rest move to `uncertain`, and a text-only call rewrites the prose from what
is left. A Claim LGND couldn't check (an LGND failure) stays, marked unverified. The code, not
the model, makes these calls from the Chip's footprint, so the model still sees only the image
(ADR-0009). Every lookup and check is a `tool` Step with `role: verify`, and each Run result has
counts (`verification`). LGND's images are about 160 m across, bigger than a 102 m cell, so the
check catches wrong objects far better than a Claim one cell off.

```sh
uv run clayzer batch --repeats 3 --verify --label verify
```

## Running the Harness on AgentCore

`--harness agentcore` runs each Run's Harness (draft, tools, verify, rewrite) in an
[Amazon Bedrock AgentCore](https://aws.amazon.com/bedrock/agentcore/) Runtime instead of in your
terminal. The Batch still reads the Chip, checks its SHA-256, writes the Trace, and scores; the
Runtime only produces the Caption. Two reasons to use it: the LGND sign-in is held by AgentCore
Identity instead of one person's machine, and the Harness runs where the model and tools are.

```sh
# 1. Deploy the Runtime into your account (needs Node, Docker with ARM64 support, and a
#    bootstrapped account). The Runtime ARN is printed as the RuntimeArn output.
uv sync --group infra
cd infra
npx aws-cdk@2 bootstrap                                  # once per account and region
npx aws-cdk@2 --app "uv run --group infra python agentcore_app.py" deploy
cd ..

# 2. Keep the LGND sign-in in AgentCore Identity. Once per account; needs a browser.
uv run clayzer agentcore login lgnd

# 3. Run a Batch on it.
export CLAYZER_AGENTCORE_RUNTIME=<the RuntimeArn output>
uv run clayzer batch --harness agentcore --verify --repeats 3 --label agentcore
```

`login` prints a link. Open it, sign in to LGND, and approve. The browser then goes to a
`localhost:8765` address that won't load; that is expected. Paste the whole address from the
address bar back into the terminal. It sets up two things CDK can't (a person must be present):
an OAuth client for LGND, registered at LGND's sign-in server, and the stored approval. It is safe
to run again, and prints "already signed in" when there is nothing to do.

What to know:

- **One shared identity.** The approval is stored under a team user id (`clayzer-team`), so one
  approval serves everyone who deploys or runs against that account, and all of them draw on one
  LGND account's quota (the free tier is 150 calls a day, per [mcp.md](mcp.md)).
- **Answer Keys stay out.** A request carries the Chip, the prompt, the model, the tool list, and
  the Chip's footprint (for the verifier only), and has no field for a Case or its Reference
  Labels; an unknown field is refused ([`contract.py`](../src/clayzer/agentcore/contract.py)). The
  Runtime's role can't read the store either.
- **Same Trace.** The Runtime returns every Step and the Batch writes the Trace, so scoring,
  replay and the run reports work as before. Steps from the Runtime are marked `harness:
  agentcore`.
- **Recorded.** `batch.json` records `harness`, `runtime`, `runtime_build` (the git commit the
  image was built from), and the tool pins and versions. Compare and the gate show a change in
  any of them, and warn when a Baseline came from a different Harness.
- **Same code.** The Runtime runs `harness.caption`, the function a local Batch runs. Scores from
  the two paths agree within the noise of the model: 10 Repeats of 3 Cases showed no overall
  difference, and the local Harness differs from itself by about as much as it does from AgentCore
  at 3 Repeats. Use enough Repeats before reading a small difference as a regression.
- **Cost of a failed Run.** A Bedrock error inside the Runtime comes back as the same error
  code, so the Batch treats it as a Sandbox Failure (excluded, and run again by `--resume`). A
  model that never submits a Caption is a Harness Fault, scored 0.
- **Tear down.** `npx aws-cdk@2 --app "uv run --group infra python agentcore_app.py" destroy`
  removes the Runtime, its role, and its workload identity. The OAuth client and approval from
  `login` are kept in Identity; delete them in the AgentCore console.

Options for the stack are passed as `-c name=value`; see the docstring of
[`infra/agentcore_app.py`](../infra/agentcore_app.py). The token source is chosen by
`CLAYZER_TOKEN_SOURCE`: `file` (the default, what `clayzer login` saved) or `agentcore`. The stack
sets it for the Runtime; set it yourself to run `clayzer tools lgnd` or a local `--verify` Batch
on the Identity-held sign-in.

### Another captioning model

`--caption-model us.anthropic.claude-opus-5-5` runs the same Cases with Opus 5.5. It refuses a
forced tool choice, so the Harness asks for `submit_caption` in the prompt instead of forcing it
for models on that list ([`harness.py`](../src/clayzer/harness.py), `NO_FORCED_TOOL`). Opus is
also the default Judge, so a Batch it captions is **self-graded**: the report, Compare, the web
app and the gate all say so, and its Fidelity should not be compared with a Batch judged by a
different model.

## The team web app

```sh
uv run clayzer ui                  # http://127.0.0.1:8770, read-only
uv run clayzer ui --allow-launch   # also lets the browser run Batches
uv run clayzer ui --port 8800      # another port
```

It reads whatever store your settings point at and listens on localhost only.

## Settings

Put these in `.env` at the repo root (gitignored), or export them.

| Variable | Default |
|---|---|
| `CLAYZER_CAPTION_MODEL` | `us.amazon.nova-pro-v1:0` |
| `CLAYZER_JUDGE_MODEL` | `us.anthropic.claude-opus-5-5` |
| `CLAYZER_EMBED_MODEL` | `amazon.titan-embed-text-v2:0` |
| `CLAYZER_SUMMARY_MODEL` | `us.amazon.nova-pro-v1:0` (writes Run narratives) |
| `CLAYZER_TOKEN_BUDGET` | unset (the Workflow Score's cost part is left out) |
| `CLAYZER_BEDROCK_ENDPOINT_URL` | unset (a private Bedrock endpoint, if your network needs one) |
| `CLAYZER_OVERPASS_URL` | `https://overpass-api.de/api/interpreter` |
| `CLAYZER_STORE` | unset: local `data/` and `batches/`. `s3://<bucket>/<prefix>` for S3 |
| `CLAYZER_NAIP_SOURCE` | `pc` (Planetary Computer). `aws` reads `naip-visualization` (Requester-Pays, us-west-2) |
| `CLAYZER_DATA_DIR`, `CLAYZER_BATCHES_DIR` | `data/`, `batches/` |
| `CLAYZER_BASELINES_DIR` | `baselines/` (committed) |
| `CLAYZER_AUTH_DIR` | `~/.clayzer/auth/` (MCP sign-ins) |
| `CLAYZER_TOKEN_SOURCE` | `file` (the sign-in `clayzer login` saved). `agentcore` reads it from AgentCore Identity |
| `CLAYZER_AGENTCORE_RUNTIME` | unset. The Runtime ARN for `--harness agentcore` |
| `CLAYZER_AGENTCORE_REGION` | `AWS_REGION`, else `us-west-2` |
| `CLAYZER_AGENTCORE_WORKLOAD` | `clayzer` (the Identity workload the sign-in is stored under) |
| `CLAYZER_AGENTCORE_USER_ID` | `clayzer-team` (the shared identity) |
| `CLAYZER_AGENTCORE_PROVIDER` | `clayzer-lgnd` (the OAuth client's name in Identity) |
| `CLAYZER_AGENTCORE_RETURN_URL` | `http://localhost:8765/callback` |

Credentials in `.env` take precedence over a shell's AWS profile, region, or Bedrock bearer token.

Behind a TLS-intercepting proxy, set `SSL_CERT_FILE` to the proxy's CA bundle; it's passed to GDAL
for NAIP reads too. MCP servers that ignore it need `CLAYZER_MCP_SYSTEM_TRUST=1`.

## Hosting it on AWS

One CDK app ([`infra/app.py`](../infra/app.py)) puts the read-only web app in your own account
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
prefix. `npx aws-cdk@2 destroy` removes everything except the bucket. To build the image on its
own: `docker build -t clayzer .` (see the [Dockerfile](../Dockerfile)).
