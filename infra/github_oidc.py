"""The role GitHub Actions assumes to deploy the Clayzer stack, with no stored AWS keys.

Deploy it once per account, from a laptop with that account's credentials, after `cdk bootstrap`:

    cd infra
    npx aws-cdk@2 --app "uv run --group infra python github_oidc.py" deploy

Only workflow jobs that run in this repo's `aws` environment can assume the role (set that
environment's branch and reviewer rules in the repo settings), and the role can do nothing but
assume the CDK bootstrap roles, the same ones a teammate's `cdk deploy` uses. Copy the RoleArn
output into the `aws` environment's AWS_DEPLOY_ROLE_ARN secret.

GitHub names the repo in the token's `sub` claim in one of two ways: by name
(`repo:<owner>/<name>`) or, with immutable subjects, by name and numeric id
(`repo:<owner>@<id>/<name>@<id>`). This repo uses the second. The role accepts both, so it keeps
working if the setting changes. For a fork, pass `-c repo=<owner>/<name>`; this trusts only
the fork's name-based subject by default. If the fork uses immutable subjects, also pass
`-c sub_prefix=<prefix>`, where the prefix is `sub_claim_prefix` from
`gh api repos/<owner>/<name>/actions/oidc/customization/sub`.
"""

import os

import aws_cdk as cdk
from aws_cdk import aws_iam as iam
from constructs import Construct

GITHUB = "token.actions.githubusercontent.com"
REPO = "PlutonicSauce/Clayzer"
# The ids are public: they are in the repo's OIDC settings and in every token it issues.
SUB_PREFIX = "repo:PlutonicSauce@127466756/Clayzer@1444863531"


class GitHubDeployStack(cdk.Stack):
    def __init__(self, scope: Construct, id: str, repo: str, sub_prefix: str, **kwargs) -> None:
        super().__init__(scope, id, **kwargs)

        provider = iam.OidcProviderNative(
            self, "GitHub", url=f"https://{GITHUB}", client_ids=["sts.amazonaws.com"]
        )
        role = iam.Role(
            self,
            "Deploy",
            assumed_by=iam.WebIdentityPrincipal(
                provider.oidc_provider_arn,
                conditions={
                    "StringEquals": {
                        f"{GITHUB}:aud": "sts.amazonaws.com",
                        f"{GITHUB}:sub": [
                            f"repo:{repo}:environment:aws",
                            f"{sub_prefix}:environment:aws",
                        ],
                    }
                },
            ),
            max_session_duration=cdk.Duration.hours(1),
        )
        role.add_to_policy(
            iam.PolicyStatement(
                actions=["sts:AssumeRole", "sts:TagSession"],
                resources=[f"arn:aws:iam::{self.account}:role/cdk-hnb659fds-*-role-*"],
            )
        )

        cdk.CfnOutput(self, "RoleArn", value=role.role_arn)


app = cdk.App()
cdk.Tags.of(app).add("project", "clayzer")
repo = app.node.try_get_context("repo") or REPO
sub_prefix = app.node.try_get_context("sub_prefix") or (
    SUB_PREFIX if repo == REPO else f"repo:{repo}"
)
GitHubDeployStack(
    app,
    "ClayzerGitHubDeploy",
    repo=repo,
    sub_prefix=sub_prefix,
    env=cdk.Environment(
        account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
        region=os.environ.get("CDK_DEFAULT_REGION", "us-west-2"),
    ),
)
app.synth()
