"""The reviewed runtime policy cannot read Answer Keys or write scored Batches."""

import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "agentcore_policies", Path(__file__).parents[1] / "agentcore_policies.py"
)
policies = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policies)


def test_runtime_access_is_scoped_to_images_and_standalone_outputs():
    policy = policies.runtime_policy(
        "us-west-2",
        "123456789012",
        "store",
        "caption",
        "assets",
        "sha.zip",
        "arn:secret",
        "/aws/bedrock-agentcore/runtimes/example-DEFAULT",
    )
    statements = {s["Sid"]: s for s in policy["Statement"]}
    assert statements["ChipImagesAndCode"]["Resource"] == [
        "arn:aws:s3:::store/caption/chips/*.png",
        "arn:aws:s3:::assets/sha.zip",
    ]
    assert (
        statements["StandaloneTraces"]["Resource"] == "arn:aws:s3:::store/caption/runs/agentcore/*"
    )
    assert statements["NoAnswerKeys"]["Effect"] == "Deny"
    assert "arn:aws:s3:::store/caption/cases/*" in statements["NoAnswerKeys"]["Resource"]


def test_trust_checks_source_account_and_resource():
    statement = policies.trust("123456789012", "arn:runtime")["Statement"][0]
    assert statement["Condition"] == {
        "StringEquals": {"aws:SourceAccount": "123456789012"},
        "ArnLike": {"aws:SourceArn": "arn:runtime"},
    }
