"""CloudWatch Transaction Search for one account and region, as a stack of its own.

The AgentCore Runtime exports OpenTelemetry spans only once Transaction Search is on
(`-c traces=true` in agentcore_app.py). Turning it on is account-wide: X-Ray then sends every
trace segment in this account and region to CloudWatch Logs (the `aws/spans` group) and indexes a
sample of them. That is why it lives here and not in the Runtime stack: destroying the Runtime
must not change trace routing for everything else in the account, and the account owner should
agree to it once, separately.

    cd infra
    npx aws-cdk@2 --app "uv run --group infra python transaction_search_app.py" deploy

Destroying this stack turns Transaction Search off again (X-Ray goes back to sending segments to
X-Ray) and removes the log resource policy. The `aws/spans` log group X-Ray created stays.

If the account already has Transaction Search on (enabled by hand or by another tool), creating
the stack fails because the setting already exists. Adopt it instead, with no change to the
account; docs/cli.md, "Running the Harness on AgentCore", has the `cdk import` command.

Options, as `-c name=value`: `indexing` (the percentage of spans indexed as trace summaries,
default 1; X-Ray indexes 1% at no extra charge) and `policy_name` (the log resource policy's
name, default ClayzerAgentCoreTransactionSearch).
"""

import os

import aws_cdk as cdk
from aws_cdk import aws_logs as logs
from aws_cdk import aws_xray as xray
from constructs import Construct

DEFAULT_POLICY_NAME = "ClayzerAgentCoreTransactionSearch"


def spans_policy(region: str, account: str) -> dict:
    """What X-Ray needs to write spans into CloudWatch Logs, and only from this account."""
    groups = f"arn:aws:logs:{region}:{account}:log-group"
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "XRayTransactionSearch",
                "Effect": "Allow",
                "Principal": {"Service": "xray.amazonaws.com"},
                "Action": "logs:PutLogEvents",
                "Resource": [
                    f"{groups}:aws/spans:*",
                    f"{groups}:/aws/application-signals/data:*",
                ],
                "Condition": {
                    "StringEquals": {"aws:SourceAccount": account},
                    "ArnLike": {"aws:SourceArn": f"arn:aws:xray:{region}:{account}:*"},
                },
            }
        ],
    }


def indexing_percentage(value) -> float:
    try:
        percent = float(value if value is not None else 1)
    except ValueError:
        raise SystemExit(f"indexing must be a number from 0 to 100, not {value!r}") from None
    if not 0 <= percent <= 100:
        raise SystemExit(f"indexing must be from 0 to 100, not {percent}")
    return percent


class TransactionSearchStack(cdk.Stack):
    def __init__(
        self,
        scope: Construct,
        id: str,
        *,
        indexing: float = 1,
        policy_name: str = DEFAULT_POLICY_NAME,
        **kwargs,
    ) -> None:
        super().__init__(scope, id, **kwargs)
        # The policy must exist before X-Ray switches its destination, or the switch fails.
        policy = logs.CfnResourcePolicy(
            self,
            "SpansPolicy",
            policy_name=policy_name,
            policy_document=cdk.Stack.of(self).to_json_string(
                spans_policy(self.region, self.account)
            ),
        )
        config = xray.CfnTransactionSearchConfig(
            self, "TransactionSearch", indexing_percentage=indexing
        )
        config.node.add_dependency(policy)
        # `cdk import` needs an explicit deletion policy on every resource it adopts.
        for resource in (policy, config):
            resource.apply_removal_policy(cdk.RemovalPolicy.DESTROY)
        cdk.CfnOutput(self, "IndexingPercentage", value=str(indexing))


def main() -> None:
    app = cdk.App()
    cdk.Tags.of(app).add("project", "clayzer")
    ctx = app.node.try_get_context
    TransactionSearchStack(
        app,
        "ClayzerTransactionSearch",
        indexing=indexing_percentage(ctx("indexing")),
        policy_name=ctx("policy_name") or DEFAULT_POLICY_NAME,
        env=cdk.Environment(
            account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
            region=os.environ.get("CDK_DEFAULT_REGION", "us-west-2"),
        ),
    )
    app.synth()


if __name__ == "__main__":
    main()
