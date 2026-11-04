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
from aws_cdk import aws_logs as logs
from aws_cdk import aws_s3 as s3
from constructs import Construct

REPO = Path(__file__).resolve().parents[1]
PORT = 8770


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

        # Only CloudFront reaches the load balancer. The lookup needs an account, so CI's
        # credential-free synth passes a placeholder as `-c cloudfront_prefix_list=pl-...`.
        cloudfront_prefixes = self.node.try_get_context("cloudfront_prefix_list") or (
            ec2.PrefixList.from_lookup(
                self,
                "CloudFrontOrigins",
                prefix_list_name="com.amazonaws.global.cloudfront.origin-facing",
            ).prefix_list_id
        )
        service.load_balancer.connections.allow_from(
            ec2.Peer.prefix_list(cloudfront_prefixes), ec2.Port.tcp(80)
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
        # Physical names stay generated; outputs are how people and scripts find them.
        cdk.CfnOutput(self, "ClusterName", value=cluster.cluster_name)
        cdk.CfnOutput(self, "ServiceName", value=service.service.service_name)


app = cdk.App()
# Groups the stack's resources in the console, Cost Explorer, and Resource Groups.
cdk.Tags.of(app).add("project", "clayzer")
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
