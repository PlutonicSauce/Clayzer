"""One CDK app that hosts the Clayzer web app in a teammate's own account (AWS-07, AWS-08).

CloudFront (HTTPS URL) -> Application Load Balancer -> one ECS Fargate task (ARM64) running the
read-only web app, which reads the store bucket. App Runner was the first choice, but it is denied
to the hackathon participant role. No NAT gateway: the task sits in a public subnet and only
accepts traffic from the load balancer, which only accepts traffic from CloudFront.

    cd infra
    npx aws-cdk@2 bootstrap            # once per account and region
    npx aws-cdk@2 deploy -c store=s3://<your bucket>/<prefix>

Without `store`, the stack creates a new bucket and uses its `caption/` prefix. Behind a private
package mirror or a TLS-intercepting proxy, set CLAYZER_BUILD_BASE_IMAGE, CLAYZER_BUILD_PIP_INDEX
(a file holding the index URL), and CLAYZER_BUILD_CA_BUNDLE (a .pem file) before deploying; they
reach the image build as a build argument and build secrets (see the Dockerfile).
"""

import os
from pathlib import Path

import aws_cdk as cdk
from aws_cdk import aws_cloudfront as cloudfront
from aws_cdk import aws_cloudfront_origins as origins
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_ecr_assets as ecr_assets
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_ecs_patterns as ecs_patterns
from aws_cdk import aws_iam as iam
from aws_cdk import aws_logs as logs
from aws_cdk import aws_s3 as s3
from constructs import Construct

REPO = Path(__file__).resolve().parents[1]
PORT = 8770

# The default models each service role may invoke (AWS-01, AWS-02). A deploy overrides these with
# -c caption_model=… / judge_model=… / embed_model=… to match the Batch's own configuration.
DEFAULT_CAPTION_MODEL = "us.amazon.nova-pro-v1:0"
DEFAULT_JUDGE_MODEL = "us.anthropic.claude-opus-5-5"
DEFAULT_EMBED_MODEL = "amazon.titan-embed-text-v2:0"


def _model_arns(region: str, account: str, model_id: str) -> list[str]:
    """Every ARN Bedrock checks for one model id. A cross-region inference profile (the `us.`
    prefix) is itself an ARN, and invoking it reaches the underlying foundation models in each
    region the profile spans, so those are granted too."""
    bare = model_id.removeprefix("us.").removeprefix("eu.").removeprefix("apac.")
    foundation = [
        f"arn:aws:bedrock:{r}::foundation-model/{bare}" for r in (region, "us-east-1", "us-west-2")
    ]
    if model_id == bare:
        return sorted(set(foundation))
    profile = f"arn:aws:bedrock:{region}:{account}:inference-profile/{model_id}"
    return sorted({profile, *foundation})


def _invoke_models(
    scope: Construct, name: str, region: str, account: str, *model_ids: str
) -> iam.Role:
    """A service role that may invoke only the named Bedrock models, and nothing else (AWS-13)."""
    arns = sorted({a for m in model_ids for a in _model_arns(region, account, m)})
    role = iam.Role(
        scope,
        name,
        assumed_by=iam.ServicePrincipal("bedrock.amazonaws.com"),
        description=f"Clayzer {name}: invoke only its Bedrock models (AWS-13)",
    )
    role.add_to_policy(
        iam.PolicyStatement(
            actions=["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
            resources=arns,
        )
    )
    return role


def build_options() -> dict:
    args, secrets = {}, {}
    if base := os.environ.get("CLAYZER_BUILD_BASE_IMAGE"):
        args["BASE_IMAGE"] = base
    if index := os.environ.get("CLAYZER_BUILD_PIP_INDEX"):
        secrets["pip_index"] = cdk.DockerBuildSecret.from_src(index)
    if ca := os.environ.get("CLAYZER_BUILD_CA_BUNDLE"):
        secrets["ca_bundle"] = cdk.DockerBuildSecret.from_src(ca)
    return {"build_args": args or None, "build_secrets": secrets or None}


class ClayzerStack(cdk.Stack):
    def __init__(self, scope: Construct, id: str, store: str | None, **kwargs) -> None:
        super().__init__(scope, id, **kwargs)

        caption_model = self.node.try_get_context("caption_model") or DEFAULT_CAPTION_MODEL
        judge_model = self.node.try_get_context("judge_model") or DEFAULT_JUDGE_MODEL
        embed_model = self.node.try_get_context("embed_model") or DEFAULT_EMBED_MODEL

        if store:
            bucket_name, _, prefix = store.removeprefix("s3://").partition("/")
            bucket = s3.Bucket.from_bucket_name(self, "Store", bucket_name)
        else:
            bucket = s3.Bucket(
                self,
                "Store",
                block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
                encryption=s3.BucketEncryption.S3_MANAGED,
                enforce_ssl=True,
                removal_policy=cdk.RemovalPolicy.RETAIN,
            )
            prefix = "caption"
        prefix = prefix.strip("/")

        # A role per service (AWS-13), each with only what it needs. The captioner writes Chips,
        # Captions, and Traces; the Judge reads a Chip and a Caption and writes its verdict; both
        # invoke only their own model. The web app role is defined below, with the Fargate task.
        captioner = _invoke_models(
            self, "CaptionerRole", self.region, self.account, caption_model, embed_model
        )
        bucket.grant_read_write(captioner, f"{prefix}/*")
        judge = _invoke_models(self, "JudgeRole", self.region, self.account, judge_model)
        bucket.grant_read_write(judge, f"{prefix}/*")

        vpc = ec2.Vpc(
            self,
            "Vpc",
            max_azs=2,
            nat_gateways=0,
            subnet_configuration=[
                ec2.SubnetConfiguration(name="public", subnet_type=ec2.SubnetType.PUBLIC)
            ],
        )
        cluster = ecs.Cluster(self, "Cluster", vpc=vpc)

        service = ecs_patterns.ApplicationLoadBalancedFargateService(
            self,
            "Web",
            cluster=cluster,
            cpu=512,
            memory_limit_mib=1024,
            desired_count=1,
            # One task: start the new one before stopping the old, and roll back a failed deploy.
            min_healthy_percent=100,
            circuit_breaker=ecs.DeploymentCircuitBreaker(rollback=True),
            assign_public_ip=True,
            task_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
            public_load_balancer=True,
            open_listener=False,
            runtime_platform=ecs.RuntimePlatform(
                cpu_architecture=ecs.CpuArchitecture.ARM64,
                operating_system_family=ecs.OperatingSystemFamily.LINUX,
            ),
            task_image_options=ecs_patterns.ApplicationLoadBalancedTaskImageOptions(
                image=ecs.ContainerImage.from_asset(
                    str(REPO), platform=ecr_assets.Platform.LINUX_ARM64, **build_options()
                ),
                container_port=PORT,
                environment={
                    "AWS_REGION": self.region,
                    "CLAYZER_STORE": f"s3://{bucket.bucket_name}/{prefix}",
                },
                log_driver=ecs.LogDrivers.aws_logs(
                    stream_prefix="clayzer", log_retention=logs.RetentionDays.ONE_WEEK
                ),
            ),
        )
        service.target_group.configure_health_check(path="/api/config")

        # Least privilege (AWS-13): the read-only app only reads its own prefix of the store.
        bucket.grant_read(service.task_definition.task_role, f"{prefix}/*")

        # Only CloudFront reaches the load balancer.
        cloudfront_prefixes = ec2.PrefixList.from_lookup(
            self,
            "CloudFrontOrigins",
            prefix_list_name="com.amazonaws.global.cloudfront.origin-facing",
        )
        service.load_balancer.connections.allow_from(
            ec2.Peer.prefix_list(cloudfront_prefixes.prefix_list_id), ec2.Port.tcp(80)
        )

        distribution = cloudfront.Distribution(
            self,
            "Cdn",
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.LoadBalancerV2Origin(
                    service.load_balancer,
                    protocol_policy=cloudfront.OriginProtocolPolicy.HTTP_ONLY,
                ),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                allowed_methods=cloudfront.AllowedMethods.ALLOW_ALL,
                cache_policy=cloudfront.CachePolicy.CACHING_DISABLED,
                origin_request_policy=cloudfront.OriginRequestPolicy.ALL_VIEWER,
            ),
        )

        cdk.CfnOutput(self, "Url", value=f"https://{distribution.distribution_domain_name}")
        cdk.CfnOutput(self, "StoreUrl", value=f"s3://{bucket.bucket_name}/{prefix}")
        cdk.CfnOutput(self, "CaptionerRoleArn", value=captioner.role_arn)
        cdk.CfnOutput(self, "JudgeRoleArn", value=judge.role_arn)


def main() -> None:
    app = cdk.App()
    ClayzerStack(
        app,
        "Clayzer",
        store=app.node.try_get_context("store"),
        env=cdk.Environment(
            account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
            region=os.environ.get("CDK_DEFAULT_REGION", "us-west-2"),
        ),
    )
    app.synth()


if __name__ == "__main__":
    main()
