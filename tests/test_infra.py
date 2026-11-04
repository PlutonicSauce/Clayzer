"""The CDK app's IAM (AWS-13): a role per service, each able to invoke only its own Bedrock
models, and the store bucket blocks public access. Synthesized offline with a fixed account and
region, so no AWS call is made."""

import importlib.util
from pathlib import Path

import pytest

cdk = pytest.importorskip("aws_cdk", reason="needs the infra group: uv sync --group infra")
from aws_cdk.assertions import Template

REPO = Path(__file__).resolve().parents[1]


def _stack_module():
    spec = importlib.util.spec_from_file_location("infra_app", REPO / "infra" / "app.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def template():
    infra = _stack_module()
    app = cdk.App(
        # A real prefix list id, so PrefixList.from_lookup resolves without an AWS call.
        context={
            "availability-zones:account=111111111111:region=us-west-2": [
                "us-west-2a",
                "us-west-2b",
            ],
            "prefixlist:account=111111111111:filter.prefix-list-name="
            "com.amazonaws.global.cloudfront.origin-facing:region=us-west-2": "pl-0123456789abcdef0",
        }
    )
    stack = infra.ClayzerStack(
        app, "Clayzer", store=None, env=cdk.Environment(account="111111111111", region="us-west-2")
    )
    return Template.from_stack(stack)


def test_there_is_a_role_per_service(template):
    # Captioner, Judge, and the Fargate task role and its execution role.
    roles = template.find_resources("AWS::IAM::Role")
    principals = [
        r["Properties"]["AssumeRolePolicyDocument"]["Statement"][0]["Principal"]["Service"]
        for r in roles.values()
    ]
    assert principals.count("bedrock.amazonaws.com") == 2  # captioner and Judge
    assert "ecs-tasks.amazonaws.com" in principals  # the web app task


def test_the_captioner_and_judge_invoke_only_their_models(template):
    policies = template.find_resources("AWS::IAM::Policy")
    bedrock_resources = []
    for p in policies.values():
        for st in p["Properties"]["PolicyDocument"]["Statement"]:
            actions = st["Action"] if isinstance(st["Action"], list) else [st["Action"]]
            if any("bedrock" in a for a in actions):
                assert set(actions) <= {
                    "bedrock:InvokeModel",
                    "bedrock:InvokeModelWithResponseStream",
                }, "a Bedrock role has more than invoke"
                res = st["Resource"]
                bedrock_resources.extend(res if isinstance(res, list) else [res])
    blob = str(bedrock_resources)
    assert "nova-pro" in blob and "claude-opus" in blob and "titan-embed" in blob
    # Never a wildcard over all models.
    assert "*" not in blob.replace("foundation-model/", "")


def test_a_model_override_narrows_the_grant(template):
    infra = _stack_module()
    app = cdk.App(
        context={
            "caption_model": "us.anthropic.claude-3-5-sonnet-20240620-v1:0",
            "availability-zones:account=222222222222:region=us-west-2": [
                "us-west-2a",
                "us-west-2b",
            ],
            "prefixlist:account=222222222222:filter.prefix-list-name="
            "com.amazonaws.global.cloudfront.origin-facing:region=us-west-2": "pl-0123456789abcdef0",
        }
    )
    stack = infra.ClayzerStack(
        app, "C", store=None, env=cdk.Environment(account="222222222222", region="us-west-2")
    )
    blob = str(Template.from_stack(stack).find_resources("AWS::IAM::Policy"))
    assert "claude-3-5-sonnet" in blob and "nova-pro" not in blob


def test_the_store_bucket_blocks_public_access(template):
    template.has_resource_properties(
        "AWS::S3::Bucket",
        {
            "PublicAccessBlockConfiguration": {
                "BlockPublicAcls": True,
                "IgnorePublicAcls": True,
                "BlockPublicPolicy": True,
                "RestrictPublicBuckets": True,
            }
        },
    )


def test_no_long_lived_keys_in_the_template(template):
    # The stack grants roles, never an access key; the synthesized template has no AKIA id.
    import json

    assert "AKIA" not in json.dumps(template.to_json())
