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
