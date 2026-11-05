"""The Harness on Amazon Bedrock AgentCore, deployable into a teammate's own account (AWS-07, AWS-11).

Creates the AgentCore Runtime that runs the Clayzer Harness, the ARM64 image it runs, an IAM role
with only what a Run needs, and the workload identity that names who asks AgentCore Identity for
the LGND sign-in. It is a separate CDK app from app.py (the web app), so neither's `cdk deploy`
changes the other.

Deployment and inbound Cognito credential setup are documented in docs/cli.md, "Running the
Harness on AgentCore". Install the pinned CLI with `npm ci` in infra, then invoke
`npx --no-install cdk --app "uv run --group infra python agentcore_app.py"`.
After an account owner enables CloudWatch Transaction Search, pass `-c traces=true` on every
deploy/redeploy that should export spans. Without it, only the Batch's JSONL Trace is kept.
LGND browser consent is separate from the Cognito credential the Batch uses to invoke. Consent
is per workload identity; destroying/recreating that identity requires a new approval.

Destroy removes the Runtime, its role, workload identity, Cognito resources and Runtime log group.
The KMS key is scheduled for deletion (30 days). Shared bootstrap/ECR assets, the OAuth provider
and its Identity-managed client secret, account Transaction Search settings, and CDK provider
Lambda diagnostic log groups survive. Provider diagnostic logs expire after seven days. A
resource policy written by AgentCore for span delivery is outside CloudFormation ownership;
inspect it after teardown before removing it. Never remove another workload's policy.

This stack is validated in us-west-2 and uses US inference profiles (`us.`); EU/APAC profiles
and other AWS partitions require adapting the model ARNs before deployment.

Options, as `-c name=value`: `workload` (the Identity workload name, default `clayzer`), `provider`
(the OAuth client name, default `clayzer-lgnd`), `user` (the shared team identity, default
`clayzer-team`), `models` (comma-separated Bedrock model ids the Runtime may call, default Nova
Pro and Opus 5.5), `return_url`, and `traces` (default false; requires Transaction Search). Behind a private package mirror or TLS-intercepting proxy, set
CLAYZER_BUILD_BASE_IMAGE, CLAYZER_BUILD_PIP_INDEX (a file holding the index URL) and
CLAYZER_BUILD_CA_BUNDLE (a .pem file), as for app.py.
"""

import os
import subprocess
from pathlib import Path

import aws_cdk as cdk
from aws_cdk import aws_bedrockagentcore as agentcore
from aws_cdk import aws_cognito as cognito
from aws_cdk import aws_ecr_assets as ecr_assets
from aws_cdk import aws_iam as iam
from aws_cdk import aws_kms as kms
from aws_cdk import aws_logs as logs
from aws_cdk import custom_resources as cr
from constructs import Construct

REPO = Path(__file__).resolve().parents[1]
DEFAULT_MODELS = ["amazon.nova-pro-v1:0", "anthropic.claude-opus-5-5"]
DEFAULT_RETURN_URL = "http://localhost:8765/callback"
RUNTIME_NAME = "clayzer_harness"  # letters, digits and underscores only


def git_build() -> str:
    """Which commit the image was built from, so a Batch records which Harness answered."""
    try:
        sha = subprocess.run(["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, check=True, timeout=10).stdout.strip()  # fmt: skip
        dirty = subprocess.run(["git", "-C", str(REPO), "status", "--porcelain",
                                "--untracked-files=no"], capture_output=True, text=True,
                               check=True, timeout=10).stdout.strip()  # fmt: skip
        return sha + ("-dirty" if dirty else "")
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def build_options() -> dict:
    args, secrets = {}, {}
    if base := os.environ.get("CLAYZER_BUILD_BASE_IMAGE"):
        args["BASE_IMAGE"] = base
    if index := os.environ.get("CLAYZER_BUILD_PIP_INDEX"):
        secrets["pip_index"] = cdk.DockerBuildSecret.from_src(index)
    if ca := os.environ.get("CLAYZER_BUILD_CA_BUNDLE"):
        secrets["ca_bundle"] = cdk.DockerBuildSecret.from_src(ca)
    return {"build_args": args, "build_secrets": secrets or None}


class AgentCoreStack(cdk.Stack):
    def __init__(
        self,
        scope: Construct,
        id: str,
        *,
        workload: str = "clayzer",
        provider: str = "clayzer-lgnd",
        user: str = "clayzer-team",
        models: list[str] | None = None,
        return_url: str = DEFAULT_RETURN_URL,
        traces: bool = False,
        build: str = "unknown",
        **kwargs,
    ) -> None:
        super().__init__(scope, id, **kwargs)
        models = models or DEFAULT_MODELS
        options = build_options()

        # The image: only the Harness, built for ARM64 (infra/agentcore/Dockerfile).
        image = ecr_assets.DockerImageAsset(
            self, "RuntimeImage", directory=str(REPO), file="infra/agentcore/Dockerfile",
            platform=ecr_assets.Platform.LINUX_ARM64,
            build_args={**options["build_args"], "BUILD": build},
            build_secrets=options["build_secrets"],
        )  # fmt: skip

        # Who is asking Identity for the sign-in, and where the browser may be sent afterwards.
        # `clayzer agentcore login` leaves this alone when the return address is already allowed.
        identity = agentcore.CfnWorkloadIdentity(
            self, "Workload", name=workload,
            allowed_resource_oauth2_return_urls=[return_url],
        )  # fmt: skip

        arn = f"arn:aws:bedrock-agentcore:{self.region}:{self.account}"
        role = iam.Role(
            self, "RuntimeRole",
            description="Runs the Clayzer Harness in AgentCore: Bedrock models, the LGND sign-in, logs",
            assumed_by=iam.ServicePrincipal(
                "bedrock-agentcore.amazonaws.com",
                conditions={
                    "StringEquals": {"aws:SourceAccount": self.account},
                    "ArnLike": {"aws:SourceArn": f"{arn}:runtime/{RUNTIME_NAME}-*"},
                },
            ),
        )  # fmt: skip
        image.repository.grant_pull(role)
        # Models the Harness (and its rewrite) may call. Cross-region profiles route to other
        # regions, so the foundation-model ARN is region-wildcarded; the profile's is not.
        role.add_to_policy(iam.PolicyStatement(
            sid="Models", actions=["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
            resources=[
                *[f"arn:aws:bedrock:*::foundation-model/{m}" for m in models],
                *[f"arn:aws:bedrock:{self.region}:{self.account}:inference-profile/us.{m}"
                  for m in models],
            ],
        ))  # fmt: skip
        role.add_to_policy(iam.PolicyStatement(
            sid="Logs",
            actions=["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents",
                     "logs:DescribeLogStreams"],
            resources=[f"arn:aws:logs:{self.region}:{self.account}:log-group:/aws/bedrock-agentcore/runtimes/{RUNTIME_NAME}-*"],
        ))  # fmt: skip
        # These X-Ray APIs have no resource-level scope. Keep the account's existing
        # destination; enabling Transaction Search is a separate account-wide decision.
        role.add_to_policy(
            iam.PolicyStatement(
                sid="RuntimeTraces",
                actions=[
                    "xray:PutTraceSegments",
                    "xray:PutTelemetryRecords",
                    "xray:GetSamplingRules",
                    "xray:GetSamplingTargets",
                ],
                resources=["*"],
            )
        )
        if traces:
            role.add_to_policy(
                iam.PolicyStatement(
                    sid="UnifiedTraceLogPolicy",
                    actions=["logs:PutResourcePolicy"],
                    resources=[
                        (
                            f"arn:aws:logs:{self.region}:{self.account}:log-group:"
                            f"/aws/bedrock-agentcore/runtimes/{RUNTIME_NAME}-*"
                        )
                    ],
                )
            )
        role.add_to_policy(
            iam.PolicyStatement(
                sid="RuntimeMetrics",
                actions=["cloudwatch:PutMetricData"],
                resources=["*"],
                conditions={"StringEquals": {"cloudwatch:namespace": "bedrock-agentcore"}},
            )
        )
        # Fetch the LGND token held in Identity: this workload, this OAuth client, nothing else.
        role.add_to_policy(iam.PolicyStatement(
            sid="LgndSignIn",
            actions=["bedrock-agentcore:GetWorkloadAccessTokenForUserId",
                     "bedrock-agentcore:GetResourceOauth2Token"],
            resources=[
                f"{arn}:workload-identity-directory/default",
                f"{arn}:workload-identity-directory/default/workload-identity/{workload}",
                f"{arn}:token-vault/default",
                f"{arn}:token-vault/default/oauth2credentialprovider/{provider}",
            ],
        ))  # fmt: skip
        # Identity keeps the OAuth client's secret in a Secrets Manager secret it creates.
        client_secret = (
            f"arn:aws:secretsmanager:{self.region}:{self.account}:secret:"
            f"bedrock-agentcore-identity!default/oauth2/{provider}*"
        )
        role.add_to_policy(iam.PolicyStatement(
            sid="OAuthClientSecret", actions=["secretsmanager:GetSecretValue"],
            resources=[client_secret],
        ))  # fmt: skip

        # Inbound OAuth on the endpoint: AgentCore Identity validates a JWT before the agent runs.
        # The provider is a Cognito user pool with a client-credentials app client, since a Batch
        # is a machine caller and LGND's user-login provider can't mint machine tokens.
        pool = cognito.UserPool(self, "InboundPool", removal_policy=cdk.RemovalPolicy.DESTROY)
        domain = pool.add_domain(
            "InboundDomain",
            cognito_domain=cognito.CognitoDomainOptions(
                domain_prefix=f"clayzer-{self.account}-{self.region}"
            ),
        )
        scope = cognito.ResourceServerScope(
            scope_name="invoke", scope_description="Invoke the Harness"
        )
        resource_server = pool.add_resource_server(
            "InboundResourceServer", identifier="clayzer-runtime", scopes=[scope]
        )
        client = pool.add_client(
            "InboundClient",
            generate_secret=True,
            o_auth=cognito.OAuthSettings(
                flows=cognito.OAuthFlows(client_credentials=True),
                scopes=[cognito.OAuthScope.resource_server(resource_server, scope)],
            ),
        )
        pool_url = f"https://cognito-idp.{self.region}.amazonaws.com/{pool.user_pool_id}"

        runtime = agentcore.CfnRuntime(
            self, "Runtime", agent_runtime_name=RUNTIME_NAME,
            description="The Clayzer caption Harness (draft, verify, rewrite) and its tools",
            role_arn=role.role_arn,
            agent_runtime_artifact=agentcore.CfnRuntime.AgentRuntimeArtifactProperty(
                container_configuration=agentcore.CfnRuntime.ContainerConfigurationProperty(
                    container_uri=image.image_uri
                )
            ),
            network_configuration=agentcore.CfnRuntime.NetworkConfigurationProperty(
                network_mode="PUBLIC"
            ),
            protocol_configuration="HTTP",
            authorizer_configuration=agentcore.CfnRuntime.AuthorizerConfigurationProperty(
                custom_jwt_authorizer=agentcore.CfnRuntime.CustomJWTAuthorizerConfigurationProperty(
                    discovery_url=f"{pool_url}/.well-known/openid-configuration",
                    allowed_clients=[client.user_pool_client_id],
                )
            ),
            environment_variables={
                "AWS_REGION": self.region,
                "CLAYZER_TOKEN_SOURCE": "agentcore",  # the LGND sign-in comes from Identity
                "CLAYZER_AGENTCORE_WORKLOAD": workload,
                "CLAYZER_AGENTCORE_USER_ID": user,
                "CLAYZER_AGENTCORE_PROVIDER": provider,
                "CLAYZER_AGENTCORE_RETURN_URL": return_url,
                "CLAYZER_BUILD": build,
                "UNIFIED_TRACES_DESTINATION_ENABLED": str(traces).lower(),
                "OTEL_TRACES_EXPORTER": "otlp" if traces else "none",
            },
        )  # fmt: skip
        runtime.node.add_dependency(role)  # the role's policy must exist before the first Run
        runtime.node.add_dependency(identity)

        # AgentCore creates this group during Runtime creation. Configure it instead of
        # declaring a competing AWS::Logs::LogGroup resource (which fails AlreadyExists).
        log_prefix = (
            f"arn:aws:logs:{self.region}:{self.account}:log-group:"
            f"/aws/bedrock-agentcore/runtimes/{RUNTIME_NAME}-*"
        )
        log_key = kms.Key(
            self,
            "RuntimeLogKey",
            enable_key_rotation=True,
            removal_policy=cdk.RemovalPolicy.DESTROY,
        )
        log_key.add_to_resource_policy(
            iam.PolicyStatement(
                principals=[iam.ServicePrincipal(f"logs.{self.region}.amazonaws.com")],
                actions=[
                    "kms:Encrypt",
                    "kms:Decrypt",
                    "kms:ReEncrypt*",
                    "kms:GenerateDataKey*",
                    "kms:DescribeKey",
                ],
                resources=["*"],
                conditions={"ArnLike": {"kms:EncryptionContext:aws:logs:arn": log_prefix}},
            )
        )
        log_group_name = f"/aws/bedrock-agentcore/runtimes/{runtime.attr_agent_runtime_id}-DEFAULT"
        log_group_arn = f"arn:aws:logs:{self.region}:{self.account}:log-group:{log_group_name}"
        sdk_policy = cr.AwsCustomResourcePolicy.from_sdk_calls(
            resources=[log_group_arn, log_group_arn + ":*"]
        )
        encryption_call = cr.AwsSdkCall(
            service="CloudWatchLogs",
            action="associateKmsKey",
            parameters={"logGroupName": log_group_name, "kmsKeyId": log_key.key_arn},
            physical_resource_id=cr.PhysicalResourceId.of(log_group_name + "-encryption"),
        )
        encryption = cr.AwsCustomResource(
            self,
            "RuntimeLogEncryption",
            on_create=encryption_call,
            on_update=encryption_call,
            policy=sdk_policy,
            install_latest_aws_sdk=False,
            log_retention=logs.RetentionDays.ONE_WEEK,
        )
        log_key.grant(encryption, "kms:DescribeKey")
        retention_call = cr.AwsSdkCall(
            service="CloudWatchLogs",
            action="putRetentionPolicy",
            parameters={"logGroupName": log_group_name, "retentionInDays": 7},
            physical_resource_id=cr.PhysicalResourceId.of(log_group_name),
        )
        retention = cr.AwsCustomResource(
            self,
            "RuntimeLogRetention",
            on_create=retention_call,
            on_update=retention_call,
            on_delete=cr.AwsSdkCall(
                service="CloudWatchLogs",
                action="deleteLogGroup",
                parameters={"logGroupName": log_group_name},
                ignore_error_codes_matching="ResourceNotFoundException",
            ),
            policy=sdk_policy,
            install_latest_aws_sdk=False,
            log_retention=logs.RetentionDays.ONE_WEEK,
        )
        retention.node.add_dependency(encryption)
        cdk.CfnOutput(self, "RuntimeLogGroup", value=log_group_name)

        cdk.CfnOutput(self, "RuntimeArn", value=runtime.attr_agent_runtime_arn,
                      description="Set CLAYZER_AGENTCORE_RUNTIME to this")  # fmt: skip
        cdk.CfnOutput(self, "RuntimeRoleArn", value=role.role_arn)
        cdk.CfnOutput(self, "Build", value=build)
        # Inbound OAuth: what a Batch needs to mint a token. The client secret is not an output
        # (CloudFormation won't expose it); read it with the printed command.
        cdk.CfnOutput(self, "InboundTokenUrl", value=f"{domain.base_url()}/oauth2/token",
                      description="CLAYZER_AGENTCORE_INBOUND_TOKEN_URL")  # fmt: skip
        cdk.CfnOutput(self, "InboundClientId", value=client.user_pool_client_id,
                      description="CLAYZER_AGENTCORE_INBOUND_CLIENT_ID")  # fmt: skip
        cdk.CfnOutput(self, "InboundUserPoolId", value=pool.user_pool_id,
                      description="Use with describe-user-pool-client to retrieve the secret")  # fmt: skip
        cdk.CfnOutput(self, "InboundScope", value="clayzer-runtime/invoke",
                      description="CLAYZER_AGENTCORE_INBOUND_SCOPE")  # fmt: skip
        cdk.CfnOutput(self, "InboundClientSecretCommand", value=(
            f"aws cognito-idp describe-user-pool-client --user-pool-id {pool.user_pool_id} "
            f"--client-id {client.user_pool_client_id} --region {self.region} "
            "--query UserPoolClient.ClientSecret --output text"),
            description="Prints the inbound client secret for CLAYZER_AGENTCORE_INBOUND_CLIENT_SECRET")  # fmt: skip


def traces_flag(value) -> bool:
    """Read `-c traces=...`, refusing anything that is not clearly on or off: a typo must not
    silently deploy with span export turned off."""
    text = str(value if value is not None else "false").strip().lower()
    if text in {"true", "1", "yes", "on"}:
        return True
    if text in {"false", "0", "no", "off", ""}:
        return False
    raise SystemExit(f"traces must be true or false, not {value!r}")


def main() -> None:
    app = cdk.App()
    ctx = app.node.try_get_context
    models = ctx("models")
    AgentCoreStack(
        app,
        "ClayzerAgentCore",
        workload=ctx("workload") or os.environ.get("CLAYZER_AGENTCORE_WORKLOAD", "clayzer"),
        provider=ctx("provider") or os.environ.get("CLAYZER_AGENTCORE_PROVIDER", "clayzer-lgnd"),
        user=ctx("user") or os.environ.get("CLAYZER_AGENTCORE_USER_ID", "clayzer-team"),
        models=[m.strip() for m in models.split(",") if m.strip()] if models else None,
        return_url=ctx("return_url") or DEFAULT_RETURN_URL,
        traces=traces_flag(ctx("traces")),
        build=ctx("build") or git_build(),
        env=cdk.Environment(
            account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
            region=os.environ.get("CDK_DEFAULT_REGION", "us-west-2"),
        ),
    )
    app.synth()


if __name__ == "__main__":
    main()
