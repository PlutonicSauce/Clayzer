"""Apply the reviewed policy and immutable ZIP to an existing Clayzer AgentCore deployment.

Reads the account's non-secret state file, validates resource ownership, and records a
deployment receipt. Initial OAuth provider registration and human consent are separate;
this command never reads the client secrets or changes those registrations.
"""

import argparse
import hashlib
import json
from pathlib import Path

import boto3
from agentcore_policies import gateway_policy, runtime_policy, trust

from clayzer.config import load_env


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("state", type=Path, help="private deployment state JSON")
    parser.add_argument("package", type=Path)
    parser.add_argument("--provider", default="clayzer-lgnd-23")
    parser.add_argument("--allow-dirty", action="store_true", help="development validation only")
    args = parser.parse_args()
    state = json.loads(args.state.read_text())
    manifest = json.loads(args.package.with_suffix(".manifest.json").read_text())
    digest = hashlib.sha256(args.package.read_bytes()).hexdigest()
    if digest != manifest["zip_sha256"]:
        raise ValueError("ZIP does not match its manifest")
    if manifest["dirty"] and not args.allow_dirty:
        raise ValueError(
            "Commit the source before deploying (or use --allow-dirty for development)"
        )
    load_env()
    session = boto3.Session()
    account = session.client("sts").get_caller_identity()["Account"]
    control, iam, s3 = (
        session.client("bedrock-agentcore-control"),
        session.client("iam"),
        session.client("s3"),
    )
    runtime = control.get_agent_runtime(agentRuntimeId=state["agentRuntimeId"])
    gateway = control.get_gateway(gatewayIdentifier=state["gatewayId"])
    provider = control.get_oauth2_credential_provider(name=args.provider)
    for arn in (
        runtime["agentRuntimeArn"],
        gateway["gatewayArn"],
        provider["credentialProviderArn"],
    ):
        if arn.split(":")[4] != account:
            raise ValueError("This updater only operates in the current participant account")
    bucket, _, prefix = state["storeUrl"].removeprefix("s3://").partition("/")
    key = f"clayzer-agentcore/23/{digest}.zip"
    role = runtime["roleArn"].rsplit("/", 1)[-1]
    gateway_role = gateway["roleArn"].rsplit("/", 1)[-1]
    for name in (role, gateway_role):
        tags = {t["Key"]: t["Value"] for t in iam.get_role(RoleName=name)["Role"].get("Tags", [])}
        if tags.get("project") != "clayzer" or tags.get("issue") != "23":
            raise ValueError("Refusing to modify a role not owned by this deployment")
    policy = runtime_policy(
        session.region_name,
        account,
        bucket,
        prefix,
        state["assetBucket"],
        key,
        state["gatewaySecretArn"],
        state["logGroup"],
    )
    iam.put_role_policy(
        RoleName=role, PolicyName="CaptionRuntime", PolicyDocument=json.dumps(policy)
    )
    iam.update_assume_role_policy(
        RoleName=role,
        PolicyDocument=json.dumps(trust(account, runtime["agentRuntimeArn"] + "*")),
    )
    iam.put_role_policy(
        RoleName=gateway_role,
        PolicyName="LgndOAuth",
        PolicyDocument=json.dumps(
            gateway_policy(
                gateway["workloadIdentityDetails"]["workloadIdentityArn"],
                provider["credentialProviderArn"],
                provider["clientSecretArn"]["secretArn"],
            )
        ),
    )
    iam.update_assume_role_policy(
        RoleName=gateway_role,
        PolicyDocument=json.dumps(trust(account, gateway["gatewayArn"])),
    )
    s3.upload_file(str(args.package), state["assetBucket"], key)
    s3.put_object(
        Bucket=state["assetBucket"],
        Key=key + ".manifest.json",
        Body=json.dumps(manifest).encode(),
        ContentType="application/json",
    )
    # A harmless, existing object makes the hosted HEAD check distinguish denial from absence.
    canary = (
        prefix.strip("/") + "/" if prefix.strip("/") else ""
    ) + "cases/agentcore-access-canary.json"
    s3.put_object(Bucket=bucket, Key=canary, Body=b'{"purpose":"permission-test; no answer keys"}')
    updated = control.update_agent_runtime(
        agentRuntimeId=state["agentRuntimeId"],
        agentRuntimeArtifact={
            "codeConfiguration": {
                "code": {"s3": {"bucket": state["assetBucket"], "prefix": key}},
                "runtime": "PYTHON_3_12",
                "entryPoint": ["entrypoint.py"],
            }
        },
        roleArn=runtime["roleArn"],
        networkConfiguration=runtime["networkConfiguration"],
        protocolConfiguration=runtime["protocolConfiguration"],
        lifecycleConfiguration=runtime["lifecycleConfiguration"],
        environmentVariables=runtime["environmentVariables"]
        | {"CLAYZER_AGENTCORE_VALIDATE_IAM": "1"},
    )
    receipt = {
        **manifest,
        "runtime_arn": runtime["agentRuntimeArn"],
        "runtime_version": updated["agentRuntimeVersion"],
        "artifact_uri": f"s3://{state['assetBucket']}/{key}",
        "runtime_policy": policy,
    }
    args.package.with_suffix(".deployment.json").write_text(json.dumps(receipt, indent=2) + "\n")
    state.update(assetKey=key, agentRuntimeVersion=updated["agentRuntimeVersion"])
    args.state.write_text(json.dumps(state, indent=2) + "\n")
    print(f"Updating runtime to version {updated['agentRuntimeVersion']}; ZIP SHA-256 {digest}")


if __name__ == "__main__":
    main()
