"""Running the Harness on Amazon Bedrock AgentCore (issue #23, AWS-11).

    identity   AgentCore Identity holds the LGND Geo sign-in, so no laptop has to
    contract   what a Batch sends a Runtime and what comes back: the Run contract
    remote     the Batch side: invoke the Runtime once per Run
    runtime    the Runtime side: the app inside the container

Needs only boto3, which the project already requires; the MCP tools extra is needed inside the
Runtime, where the Harness's tools run.
"""
