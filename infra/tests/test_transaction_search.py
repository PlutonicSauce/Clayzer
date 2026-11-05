"""The Transaction Search stack: account-wide span routing, owned by its own stack."""

import importlib.util
import json
from pathlib import Path

import pytest

pytest.importorskip("aws_cdk", reason="needs the infra group: uv sync --group infra")

import aws_cdk as cdk
from aws_cdk.assertions import Template

spec = importlib.util.spec_from_file_location(
    "transaction_search_app", Path(__file__).parents[1] / "transaction_search_app.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
ENV = cdk.Environment(account="123456789012", region="us-west-2")


def synth(**kwargs) -> Template:
    stack = module.TransactionSearchStack(cdk.App(), "T", env=ENV, **kwargs)
    return Template.from_stack(stack)


def test_it_turns_on_transaction_search_at_one_percent_after_the_policy_exists():
    template = synth()
    template.has_resource("AWS::XRay::TransactionSearchConfig", {
        "Properties": {"IndexingPercentage": 1},
        "DependsOn": [next(iter(template.find_resources("AWS::Logs::ResourcePolicy")))],
        "DeletionPolicy": "Delete",
    })  # fmt: skip


def test_only_xray_from_this_account_may_write_only_the_span_groups():
    policy = next(iter(synth().find_resources("AWS::Logs::ResourcePolicy").values()))
    assert policy["Properties"]["PolicyName"] == "ClayzerAgentCoreTransactionSearch"
    assert policy["DeletionPolicy"] == "Delete"  # cdk import needs it explicit
    (statement,) = json.loads(policy["Properties"]["PolicyDocument"])["Statement"]
    assert statement["Principal"] == {"Service": "xray.amazonaws.com"}
    assert statement["Action"] == "logs:PutLogEvents"
    assert statement["Resource"] == [
        "arn:aws:logs:us-west-2:123456789012:log-group:aws/spans:*",
        "arn:aws:logs:us-west-2:123456789012:log-group:/aws/application-signals/data:*",
    ]
    assert statement["Condition"]["StringEquals"] == {"aws:SourceAccount": "123456789012"}


def test_options_change_the_percentage_and_policy_name():
    template = synth(indexing=5, policy_name="Other")
    template.has_resource_properties(
        "AWS::XRay::TransactionSearchConfig", {"IndexingPercentage": 5}
    )
    template.has_resource_properties("AWS::Logs::ResourcePolicy", {"PolicyName": "Other"})


@pytest.mark.parametrize("value", ["lots", "-1", "101"])
def test_the_indexing_option_refuses_nonsense(value):
    with pytest.raises(SystemExit):
        module.indexing_percentage(value)


def test_the_indexing_option_defaults_to_one_percent():
    assert module.indexing_percentage(None) == 1
    assert module.indexing_percentage("2.5") == 2.5
