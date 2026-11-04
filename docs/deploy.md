# Deploying the hosted web app

How the hosted copy of the web app was deployed by hand on 2026-11-03, and what each step becomes
in a CI job. The CI version is drafted in [.github/workflows/ci.yml](../.github/workflows/ci.yml)
(the `deploy` job) but has not deployed yet; [What's left](#whats-left) lists what it still needs.

## What gets deployed

One CDK app, [infra/app.py](../infra/app.py), builds the `Clayzer` stack: CloudFront → Application
Load Balancer → one ECS Fargate task (ARM64) running the read-only web app, which reads the store
bucket. App Runner was the first choice, but it is denied to the hackathon participant role. The
load balancer only accepts traffic from CloudFront, and the task role can only read the store
prefix.

## The manual deploy

Run from a laptop, in the account of whoever is hosting (one Workshop Studio account, us-west-2).
A full deploy takes about 4.5 minutes, most of it building and pushing the image.

### 1. Tools

- uv, with the `infra` group: `uv sync --group infra`
- Node 24, for the CDK CLI (`npx aws-cdk@2`). `.nvmrc` pins it for nvm (`nvm use`), fnm, and
  CI's `setup-node`.
- Docker or Podman, to build the image. With Podman, `export CDK_DOCKER=podman`.

### 2. Credentials

The Workshop Studio `WSParticipantRole` hands out temporary session keys (access key, secret, and
session token). They go in the gitignored `.env`, and expire, so they're refreshed from the
Workshop Studio page before each deploy.

```sh
set -a; . ./.env; set +a
unset AWS_PROFILE
export AWS_REGION=us-west-2 CDK_DEFAULT_REGION=us-west-2
```

Unset `AWS_PROFILE`, and set the region explicitly: a shell profile or `~/.aws/config` pointing at
another account or region otherwise wins, and CDK deploys there.

### 3. Bootstrap, once per account and region

```sh
cd infra
npx aws-cdk@2 bootstrap
```

This creates the `CDKToolkit` stack: the asset bucket, the image repository, and the
`cdk-hnb659fds-*` roles every later deploy uses.

### 4. Behind a corporate network only

On an open network, skip this step. Behind a private package mirror or a TLS-intercepting proxy,
the image build can't reach Docker Hub or PyPI directly, so three variables reroute it (see the
[Dockerfile](../Dockerfile)):

| Variable | What it holds |
|---|---|
| `CLAYZER_BUILD_BASE_IMAGE` | A mirrored `python:3.12-slim` |
| `CLAYZER_BUILD_PIP_INDEX` | Path to a file holding the package index URL |
| `CLAYZER_BUILD_CA_BUNDLE` | Path to the proxy's CA bundle (`.pem`) |

The CDK CLI and AWS SDK also need the CA bundle (`AWS_CA_BUNDLE`, `NODE_EXTRA_CA_CERTS`), and
Node may need a proxy agent. The URL and CA bundle reach the build as Docker build secrets, so
they never end up in an image layer. Keep their values out of the repo.

### 5. Deploy

```sh
npx aws-cdk@2 deploy -c store=s3://<bucket>/<prefix>
```

`store` points at the existing store bucket and prefix. The live deploy passes the bucket it
already uses. Leaving it out makes the stack create a new, empty bucket, and the app then
shows nothing.

The deploy prints `Url` (the CloudFront address), `StoreUrl`, and the generated `ClusterName`
and `ServiceName` for `aws ecs` commands. To check it: open `<Url>/api/config`, which is also the
load balancer's health check. (The `WebLoadBalancerDNS` and `WebServiceURL` outputs come from the
CDK pattern; the load balancer only accepts CloudFront, so use `Url`.)

Physical names are generated, not fixed, so the stack can replace resources and deploy more than
once per account. Find resources through these outputs, or by the `project=clayzer` tag on
everything both stacks create.

## The same steps in CI

| Manual step | In the `deploy` job |
|---|---|
| Install uv, Node, Docker | `setup-uv` and `setup-node`; the runner has Docker |
| Temporary keys from `.env` | GitHub's OIDC: the job assumes a role, so no keys are stored. Temporary keys in GitHub secrets would stop working when they expire. |
| Unset the profile, pin the region | The `AWS_REGION` environment variable feeds `aws-region` and `CDK_DEFAULT_REGION` |
| `cdk bootstrap` | Not repeated: done once by hand, and the job reuses its roles |
| Corporate mirror and proxy settings | Not needed: GitHub's runners reach Docker Hub and PyPI directly |
| ARM64 image | Built natively on `ubuntu-24.04-arm` (the default runners are x86) |
| `cdk deploy -c store=...` | `cdk deploy Clayzer --require-approval never -c store="$CLAYZER_STORE"`; fails if `CLAYZER_STORE` is unset, so it never creates a new bucket |
| Open `<Url>/api/config` | Polls it for up to 2 minutes, and fails the job if it never answers |

The job runs after lint, test, frontend, and infra pass. It runs on pushes to main, and on manual
runs (Actions → CI → Run workflow). Only one deploy runs at a time, and a deploy is never cancelled
partway.

## What's left

1. **Create the deploy role**, once, with the hosting account's `.env` loaded and the region set as
   in step 2:
   ```sh
   cd infra
   npx aws-cdk@2 --app "uv run --group infra python github_oidc.py" deploy
   ```
   [infra/github_oidc.py](../infra/github_oidc.py) registers GitHub as an identity provider and
   creates a role that only jobs in this repo's `aws` environment can assume. All the role can do
   is assume the `cdk-hnb659fds-*` bootstrap roles. Note the `RoleArn` output.
2. **Create the `aws` environment** (repo Settings → Environments; needs a repo admin). Limit it
   to `main` and any branch you want to deploy by hand, and add required reviewers for an approval
   step. Add:
   - secret `AWS_DEPLOY_ROLE_ARN`: the `RoleArn` output
   - variable `AWS_REGION`: `us-west-2`
   - variable `CLAYZER_STORE`: the live store, `s3://<bucket>/<prefix>`
3. **Run it once by hand** from a branch the environment allows, and check the job's URL.
4. **Mark `github-ci` and `cdk` done** in [docs/tasks.toml](tasks.toml) once main deploys on its
   own.

## Things to watch

- **Public logs.** The repo is public, and so are its Action logs. The job masks the account ID,
  which also hides it inside the bucket name and stack ARN. Don't echo credentials or `.env`
  values in a step.
- **Main is behind.** The live site was deployed from feature branches. Once this workflow is on
  main, every push to main redeploys from main's code, so merge the feature branches first.
- **Synth without an account.** The prefix-list lookup in `infra/app.py` needs an account. CI's
  credential-free `infra` job passes `-c cloudfront_prefix_list=pl-00000000` instead. Deploys
  don't pass it, so they do the real lookup.
- **One stack per account.** A teammate hosting in their own account bootstraps it and creates
  the deploy role there. Running CI against that account needs a second environment with its
  own role and store.
- **The token's `sub` claim.** This repo uses GitHub's immutable subjects, so its tokens say
  `repo:PlutonicSauce@<id>/Clayzer@<id>:environment:aws`, not `repo:PlutonicSauce/Clayzer:...`.
  The deploy role accepts both. If `configure-aws-credentials` says "Not authorized to perform
  sts:AssumeRoleWithWebIdentity", compare the role's trust policy with
  `gh api repos/PlutonicSauce/Clayzer/actions/oidc/customization/sub`.
- **`cdk destroy`** removes everything except the store bucket, which is retained.

## AgentCore captioner (#23)

The integrated package supports two deployment contracts:

| Mode | Entry point | Request and Trace owner |
|---|---|---|
| Scored Batch Harness | `clayzer batch --harness agentcore`; container runs `clayzer.agentcore.runtime` | Batch sends image bytes and validated Run settings; Runtime returns Steps; Batch scores and writes the Trace. Identity, inbound OAuth and OTEL support are preserved from the remote implementation. See [CLI guide](cli.md#running-the-harness-on-agentcore). |
| Standalone Gateway captioner | `python -m clayzer.agentcore`; ZIP runs `clayzer.agentcore.gateway_runtime` | Caller sends only a Chip id; Runtime reads that PNG and checkpoints standalone output under `runs/agentcore/`. |

Their Runtime ARNs are not interchangeable: the request contracts and IAM policies differ.
The CDK container path remains in `infra/agentcore_app.py` and `infra/agentcore/`; the reviewed
Gateway updater below manages the separately validated ZIP deployment. Both share the same
caption Harness, Trace format, fault attribution and MCP client. Change Case Chip Pairs now
round-trip through the Batch Runtime contract with both image hashes and ordered image keys.
Fixed Cases retain contract v1 compatibility; Chip Pairs use v2 and require the integrated
container Runtime, so an older Runtime refuses them instead of silently misreading an image.
Integration validation: 508 application and infrastructure tests passed, two skipped, with
84.29% coverage. Ruff, formatting, dead-code and deck smoke checks passed. These local checks
cover both contracts; the hosted validation below exercises the standalone Gateway deployment.

**Validation (2026-11-04):** the reviewed runtime completed both an LGND tool call and a Nova
Pro caption inside AgentCore in `us-west-2`. The S3 Trace contains a successful
`lgnd___toolbox_classifier_list` Step (`role: setup`) and an `llm` Step. The same runtime role
was denied a HEAD request against a provisioned, harmless Cases canary
(`case_read_denied: true` in the Trace). AgentCore Identity retains the LGND consent.
The readiness call validates authentication before paying for inference; the model still
chooses whether to call additional tools. Keep #23 open until the PR and CI are complete.

The separate HTTP adapter in `src/clayzer/agentcore/gateway_runtime.py` runs the existing agentic Harness on
AgentCore Runtime. Its request is only `{"chip_id": "..."}`. Deployment fixes the model, S3
store, and Gateway; callers cannot supply prompts, Case labels, tool servers, or store paths.
The runtime role reads Chip PNGs and writes under `runs/agentcore/`; its reviewed policy
explicitly denies reads under `cases/` and `labels/`. Each invocation creates a new Run.

The runtime uses IAM authentication. Gateway needs **JWT authentication** for LGND's
authorization-code OAuth: AWS rejects a 3LO target on an `AWS_IAM` gateway, and a gateway's
authorizer type cannot be changed after creation. A confidential Cognito client supplies the
runtime's Gateway JWT. Its credential is in Secrets Manager; the environment contains only its
secret ARN. AgentCore Identity holds the separate LGND client credential and consent.
Configure Gateway's MCP `supportedVersions` as `["2025-11-25"]`: its default older protocol
cannot initiate URL elicitation for OAuth.
The captioner exposes 15 exact geospatial tool names. It excludes account-management tools,
classifier creation, and any future names until they are explicitly reviewed. The filter
runs before Bedrock name validation, so an unrelated long tool name cannot break connection.
All Runtime callers share this deployment's consenting LGND identity; restrict
`InvokeAgentRuntime` access accordingly. This is a single-participant deployment.

### Invoke and inspect

With local AWS credentials in `.env` and an authorized LGND target:

```sh
uv run --extra ui --extra tools python -m clayzer.agentcore invoke \
  "$RUNTIME_ARN" "$CHIP_ID"
```

The response contains the Caption, call summary, and `trace_key`. The complete JSONL Trace is
written to `runs/agentcore/agentcore-<uuid>/trace.jsonl` in the configured S3 store.
`caption.json` next to it contains the candidate Caption and Trace locator. The Trace's
`run_end` is the sole completion authority: S3 cannot atomically update both objects.
The artifact itself does not claim a successful status. These standalone Runs do not run
the Judge or feed the regression gate. `batch_id` remains in the response/Trace for format
compatibility; it is not a scored Batch. Batch discovery ignores legacy directories lacking
`batch.json`, including the initial validation's old `batches/agentcore-*` output.

The runtime checkpoints `run_start` before work and every completed Step. A graceful failure
writes `run_end` with `stopped` or `harness_fault`. An abrupt VM termination leaves the last
readable `running` snapshot, without a fabricated completion event. Storage outages can still
prevent a checkpoint; the failure response reports `trace_saved: false`.

Failed Runs return a JSON domain outcome with `status`, `run_id`, `trace_key`, and
`trace_saved`. This uses HTTP 200 because AgentCore replaces non-2xx bodies with a generic
`RuntimeClientError`, discarding the locator. The local invoke command prints that outcome
and exits nonzero for failure. Input-validation and startup errors remain HTTP errors.

A 600-second cooperative deadline stops new calls with a 100-second reserve. Runtime Bedrock
calls use two total attempts, a five-second connection timeout, and a 35-second read timeout;
MCP calls are bounded to 30 seconds and connection setup to 45 seconds. The platform's
900-second limit remains the hard stop. Retry attempts are recorded in the Trace.

### Package and runtime settings

```sh
uv run python infra/package_agentcore.py /tmp/clayzer-agentcore.zip
```

The builder installs the hashed `infra/agentcore-requirements.lock` for Linux ARM64 Python 3.12 and
packages Git-tracked first-party source files and an HTTP bootstrap. Ignored local files cannot
enter the archive; every packaged first-party file is hashed. It excludes `.env`, local sign-ins, images,
Cases, the UI, and installer-local metadata. ZIP ordering, timestamps and permissions are
fixed. The embedded build record and sibling `.manifest.json` contain the source commit,
dirty flag, source hashes, lock hash, and ZIP hash. CI tests against this lock on ARM64,
extracts the built ZIP, and imports the deployed entry point and request-time dependencies
under Python 3.12 with `-I -S`, isolated from development site-packages.

Regenerate the lock deliberately when upgrading dependencies:

```sh
uv pip compile infra/agentcore-requirements.in --python-version 3.12 \
  --python-platform aarch64-manylinux2014 --generate-hashes \
  --no-emit-index-url --no-emit-index-annotation -o infra/agentcore-requirements.lock
```

The AgentCore code configuration is:

```json
{
  "codeConfiguration": {
    "code": {"s3": {"bucket": "<artifact-bucket>", "prefix": "<zip-key>"}},
    "runtime": "PYTHON_3_12",
    "entryPoint": ["entrypoint.py"]
  }
}
```

Use protocol `HTTP`, port 8080, and IAM inbound authentication (the default). The bootstrap
serves `GET /ping` and `POST /invocations`. For a participant-account validation, `PUBLIC`
network mode reaches Cognito, Bedrock, S3, and LGND through Gateway; it does not make
invocations anonymous. The validated session limits are 60 seconds idle and 900 seconds total.
Wait for both the runtime and its endpoint to be `READY`.

| Runtime environment setting | Value |
|---|---|
| `CLAYZER_STORE` | `s3://<store-bucket>/<prefix>` |
| `CLAYZER_CAPTION_MODEL` | `us.amazon.nova-pro-v1:0` |
| `CLAYZER_AGENTCORE_GATEWAY` | The JWT gateway's HTTPS `/mcp` URL |
| `CLAYZER_AGENTCORE_GATEWAY_SECRET` | ARN of the Cognito client secret |

The Cognito secret is a JSON object with `token_endpoint`, `client_id`, `client_secret`, and
`scope` (`caption/invoke`). Tokens are cached within an invocation and refreshed once on a 401.
Never put either the client secret or an access token in runtime environment variables.

### LGND consent and permissions

Create a custom OAuth provider in AgentCore Identity first, obtain its generated `callbackUrl`,
register that exact URL with LGND, and update the provider with the registered confidential
client. LGND supports `client_secret_post`. In AgentCore use
`clientAuthenticationMethod: CLIENT_SECRET_POST`; also sending the deprecated
`tokenEndpointAuthMethods` field is rejected.

The Gateway target must be named `lgnd`, point at `https://geo.lgnd.ai/mcp`, use
`AUTHORIZATION_CODE`, and request `openid profile email offline_access`. Initial discovery
can enter `CREATE_PENDING_AUTH`. For a target configured with
`defaultReturnUrl: http://localhost:33418/callback`, start the local consent helper:

```sh
uv run --extra ui --extra tools python -m clayzer.agentcore authorize \
  "$GATEWAY_ID" "$TARGET_ID"
```

Open the printed localhost link in a browser. The helper binds the start and callback with a
random HttpOnly cookie and completes AgentCore's resource-token authorization. A local
`clayzer login lgnd` signs in a different client and does not authorize the Gateway.
Discovery consent alone does not prove that tool invocation works: test an actual tool call.
The runtime's Cognito caller has its own consent, completed once with:

```sh
uv run --extra ui --extra tools python -m clayzer.agentcore authorize-caller \
  "$GATEWAY_ID" "$GATEWAY_SECRET_ARN"
```

This reads the configured confidential client, requests a Gateway tool, and handles MCP's
`-32042` URL-elicitation response. Browser completion uses the exact JWT from that tool
request (`userToken`); the discovery flow instead uses its returned `userId`.
Use `--force` to replace an expired consent session. Consent URLs stay out of model inputs and Trace text.
An expired or revoked consent is an Environment Fault, not a Harness Fault.

Use separate runtime and Gateway roles, with service trust restricted by account and source
ARN. Scope runtime permissions to Chip PNG reads, its artifact ZIP, its new Trace directories,
Nova Pro invocation, its Cognito credential, and its log group. Scope Gateway OAuth access to
its workload identity and directory, token vault, LGND credential provider, and the provider's
Secrets Manager ARN. Check the current
[AgentCore service authorization reference](https://docs.aws.amazon.com/service-authorization/latest/reference/list_amazonbedrockagentcore.html)
when creating these policies.

The exact parameterized policies are in [infra/agentcore_policies.py](../infra/agentcore_policies.py).
For an existing deployment, the checked-in updater applies those policies and publishes an
immutable ZIP key (its SHA-256), manifest, and deployment receipt:

```sh
uv run python infra/update_agentcore.py /private/path/state.json /tmp/clayzer-agentcore.zip
```

The private state file contains non-secret resource identifiers: `agentRuntimeId`, `gatewayId`,
`storeUrl`, `assetBucket`, `gatewaySecretArn`, and `logGroup`. Obtain these from the existing
runtime/Gateway and stack outputs. No credential values belong in it. The updater checks
the account and ownership tags before modifying the two roles. It rejects dirty builds unless
`--allow-dirty` is explicitly selected for development validation.

The updater enables `CLAYZER_AGENTCORE_VALIDATE_IAM=1` and provisions a harmless object at
`cases/agentcore-access-canary.json`. The runtime checks denial with HEAD, which requires the
same S3 GetObject permission without reading any labels. Unexpected access stops the Run.
The receipt records runtime version, artifact URI, commit, source hashes, both permissions
and trust policies, and the non-secret environment. It is marked READY only after the runtime
and DEFAULT endpoint become READY. Artifact read permission covers only this deployment's
content-addressed ZIP prefix, preserving rollback and earlier-version cold starts.
Retain the receipt with validation results. Initial Cognito/Identity registration and human consent remain
the setup steps above; updating code does not recreate or revoke those identities.

The account validation created resources tagged `project=clayzer`, `issue=23` separately from
the `Clayzer` CDK stack: runtime, Gateway, two execution roles, OAuth provider, Cognito pool and
client, Secrets Manager credential, and a KMS key for runtime logs with seven-day retention.
They are not removed by `cdk destroy`. Keep them while using the captioner; remove this
separate deployment explicitly when it is no longer needed.

References:
[direct Python deployment](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-get-started-code-deploy-python.html),
[MCP Gateway targets](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-target-MCPservers.html),
[OAuth session binding](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/oauth2-authorization-url-session-binding.html).
