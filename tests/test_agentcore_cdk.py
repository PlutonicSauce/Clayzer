"""The AgentCore CDK stack (task agentcore-cdk): what `cdk deploy` would create, checked from the
synthesised template, with no AWS account. Needs the infra group: uv run --group infra pytest."""

import importlib.util
import json
from pathlib import Path

import pytest

pytest.importorskip("aws_cdk", reason="needs the infra group: uv sync --group infra")

import aws_cdk as cdk
from aws_cdk.assertions import Match, Template

APP = Path(__file__).resolve().parents[1] / "infra" / "agentcore_app.py"
ENV = cdk.Environment(account="123456789012", region="us-west-2")


def load_app_module():
    spec = importlib.util.spec_from_file_location("agentcore_app", APP)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def synthesised(tmp_path_factory):
    module = load_app_module()
    app = cdk.App(outdir=str(tmp_path_factory.mktemp("cdk-out")))
    stack = module.AgentCoreStack(app, "T", build="abc123", env=ENV)
    return Template.from_stack(stack), app.synth(), module


def statements(template: Template) -> list[dict]:
    out = []
    for name, policy in template.find_resources("AWS::IAM::Policy").items():
        if name.startswith("RuntimeRole"):
            out += policy["Properties"]["PolicyDocument"]["Statement"]
    return out


def as_list(x):
    return x if isinstance(x, list) else [x]


def test_one_runtime_runs_the_image_publicly_with_the_sign_in_taken_from_identity(synthesised):
    template, _, module = synthesised
    template.resource_count_is("AWS::BedrockAgentCore::Runtime", 1)
    template.has_resource_properties("AWS::BedrockAgentCore::Runtime", {
        "AgentRuntimeName": module.RUNTIME_NAME,
        "NetworkConfiguration": {"NetworkMode": "PUBLIC"},
        "ProtocolConfiguration": "HTTP",
        "AgentRuntimeArtifact": {"ContainerConfiguration": {"ContainerUri": Match.any_value()}},
        "EnvironmentVariables": Match.object_like({
            "CLAYZER_TOKEN_SOURCE": "agentcore",
            "CLAYZER_AGENTCORE_WORKLOAD": "clayzer",
            "CLAYZER_AGENTCORE_USER_ID": "clayzer-team",
            "CLAYZER_AGENTCORE_PROVIDER": "clayzer-lgnd",
            "CLAYZER_BUILD": "abc123",
            "AWS_REGION": "us-west-2",
        }),
    })  # fmt: skip
    assert "-" not in module.RUNTIME_NAME  # AgentCore allows letters, digits and underscores


def test_the_workload_identity_allows_the_return_address_login_uses(synthesised):
    template, _, module = synthesised
    template.has_resource_properties("AWS::BedrockAgentCore::WorkloadIdentity", {
        "Name": "clayzer",
        "AllowedResourceOauth2ReturnUrls": [module.DEFAULT_RETURN_URL],
    })  # fmt: skip
    # `clayzer agentcore login` writes this same address by default, so it leaves CDK's alone.
    from clayzer.agentcore.identity import DEFAULT_RETURN_URL

    assert module.DEFAULT_RETURN_URL == DEFAULT_RETURN_URL


def test_only_agentcore_in_this_account_can_assume_the_role(synthesised):
    template, _, _ = synthesised
    template.has_resource_properties("AWS::IAM::Role", {"AssumeRolePolicyDocument": {
        "Statement": [Match.object_like({
            "Action": "sts:AssumeRole",
            "Principal": {"Service": "bedrock-agentcore.amazonaws.com"},
            "Condition": {
                "StringEquals": {"aws:SourceAccount": "123456789012"},
                "ArnLike": {"aws:SourceArn": "arn:aws:bedrock-agentcore:us-west-2:123456789012:runtime/clayzer_harness-*"},
            },
        })]
    }})  # fmt: skip


def test_the_role_cannot_reach_the_store_or_anything_broad(synthesised):
    template, _, _ = synthesised
    actions = {a for s in statements(template) for a in as_list(s["Action"])}
    # ADR-0006: the Runtime never touches the store, where Cases and Reference Labels live.
    assert not {a for a in actions if a.startswith("s3:")}
    assert not {a for a in actions if a.endswith("*")}  # no wildcard actions at all
    # These APIs lack resource-level permissions. Metrics are additionally namespace-scoped.
    unscoped = {
        "ecr:GetAuthorizationToken",
        "xray:PutTraceSegments",
        "xray:PutTelemetryRecords",
        "xray:GetSamplingRules",
        "xray:GetSamplingTargets",
        "cloudwatch:PutMetricData",
    }
    for s in statements(template):
        if "*" in as_list(s["Resource"]):
            assert set(as_list(s["Action"])) <= unscoped
        if "cloudwatch:PutMetricData" in as_list(s["Action"]):
            assert s["Condition"] == {"StringEquals": {"cloudwatch:namespace": "bedrock-agentcore"}}


def test_the_role_may_call_only_the_named_models_and_fetch_only_the_lgnd_token(synthesised):
    template, _, _ = synthesised
    blob = json.dumps(statements(template))
    for model in ("amazon.nova-pro-v1:0", "anthropic.claude-opus-5-5"):
        assert f"foundation-model/{model}" in blob and f"inference-profile/us.{model}" in blob
    assert "foundation-model/*" not in blob  # not every model
    assert "workload-identity/clayzer" in blob
    assert "oauth2credentialprovider/clayzer-lgnd" in blob
    assert "bedrock-agentcore-identity!default/oauth2/clayzer-lgnd" in blob


def test_the_image_is_built_for_arm64_from_the_agentcore_dockerfile(synthesised):
    _, assembly, _ = synthesised
    assets = json.loads(next(Path(assembly.directory).glob("*.assets.json")).read_text())
    sources = [d["source"] for d in assets["dockerImages"].values()]
    assert [s["dockerFile"] for s in sources] == ["infra/agentcore/Dockerfile"]
    assert sources[0]["platform"] == "linux/arm64"
    assert sources[0]["dockerBuildArgs"]["BUILD"] == "abc123"


def test_the_outputs_name_the_runtime_to_set(synthesised):
    template, _, _ = synthesised
    outputs = template.to_json()["Outputs"]
    assert "CLAYZER_AGENTCORE_RUNTIME" in outputs["RuntimeArn"]["Description"]
    assert {"RuntimeArn", "RuntimeRoleArn", "Build"} <= set(outputs)


def test_runtime_logs_are_encrypted_retained_and_owned_by_the_stack(synthesised):
    template, _, _ = synthesised
    # AgentCore owns creation; two idempotent SDK calls configure the existing group.
    custom = json.dumps(template.find_resources("Custom::AWS"))
    assert all(
        action in custom for action in ("associateKmsKey", "putRetentionPolicy", "deleteLogGroup")
    )
    assert "retentionInDays" in custom and "kmsKeyId" in custom
    assert "ResourceNotFoundException" in custom
    assert not template.find_resources("AWS::Logs::LogGroup")
    template.has_resource_properties("AWS::KMS::Key", {"EnableKeyRotation": True})
    assert "RuntimeLogGroup" in template.to_json()["Outputs"]


def test_options_change_the_names_and_models(tmp_path):
    module = load_app_module()
    app = cdk.App(outdir=str(tmp_path))
    stack = module.AgentCoreStack(app, "T2", workload="team-b", provider="team-b-lgnd",
                                  user="team-b-user", models=["amazon.nova-lite-v1:0"],
                                  build="x", env=ENV)  # fmt: skip
    template = Template.from_stack(stack)
    template.has_resource_properties("AWS::BedrockAgentCore::WorkloadIdentity", {"Name": "team-b"})
    template.has_resource_properties("AWS::BedrockAgentCore::Runtime", {
        "EnvironmentVariables": Match.object_like({
            "CLAYZER_AGENTCORE_PROVIDER": "team-b-lgnd", "CLAYZER_AGENTCORE_USER_ID": "team-b-user"}),
    })  # fmt: skip
    blob = json.dumps(statements(template))
    assert "nova-lite" in blob and "nova-pro" not in blob
