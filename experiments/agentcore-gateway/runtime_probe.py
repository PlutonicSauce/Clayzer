"""Experiment B, part 2: can a Runtime use the LGND sign-in that AgentCore Identity holds?

Run `lgnd_gateway.py up` and `lgnd_gateway.py identity` (plus the one browser sign-in) first.

    uv run python experiments/agentcore-gateway/runtime_probe.py deploy   # ECR repo, role, image, runtime
    uv run python experiments/agentcore-gateway/runtime_probe.py invoke   # one LGND call from inside the runtime
    uv run python experiments/agentcore-gateway/runtime_probe.py down     # delete all of it (takes ~5 minutes)

Needs Docker. On an x86 machine, register ARM64 emulation first:
    docker run --privileged --rm tonistiigi/binfmt --install arm64
"""

from __future__ import annotations

import argparse
import base64
import json
import subprocess
import sys
import time
import uuid
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

# Reuse names and helpers from the first script (it sits next to this one).
from lgnd_gateway import (ACCOUNT, LGND_MCP, PROVIDER, REGION, RETURN_URL, SCOPES, TAGS, TEAM_USER, WORKLOAD,
                          ctl, iam, load, save, say, wait)

HERE = Path(__file__).parent
REPO = "clayzer-agentcore-lgnd-probe"
ROLE = "AgentCoreRuntime-clayzer-probe-lgnd"
RUNTIME = "clayzer_probe_lgnd"
REGISTRY = f"{ACCOUNT}.dkr.ecr.{REGION}.amazonaws.com"
IMAGE = f"{REGISTRY}/{REPO}:v1"
ecr = boto3.client("ecr", region_name=REGION)
logs = boto3.client("logs", region_name=REGION)
data = boto3.client("bedrock-agentcore", region_name=REGION)


def sh(*cmd: str, stdin: str | None = None) -> None:
    subprocess.run(cmd, check=True, input=stdin, text=True)


def ensure_role() -> str:
    arn_base = f"arn:aws:bedrock-agentcore:{REGION}:{ACCOUNT}"
    trust = {"Version": "2012-10-17", "Statement": [{
        "Effect": "Allow", "Principal": {"Service": "bedrock-agentcore.amazonaws.com"}, "Action": "sts:AssumeRole",
        "Condition": {"StringEquals": {"aws:SourceAccount": ACCOUNT},
                      "ArnLike": {"aws:SourceArn": f"{arn_base}:*"}}}]}
    perms = {"Version": "2012-10-17", "Statement": [
        {"Sid": "EcrAuth", "Effect": "Allow", "Action": "ecr:GetAuthorizationToken", "Resource": "*"},
        {"Sid": "EcrPull", "Effect": "Allow", "Action": ["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"],
         "Resource": f"arn:aws:ecr:{REGION}:{ACCOUNT}:repository/{REPO}"},
        {"Sid": "Logs", "Effect": "Allow",
         "Action": ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents", "logs:DescribeLogStreams"],
         "Resource": f"arn:aws:logs:{REGION}:{ACCOUNT}:log-group:/aws/bedrock-agentcore/runtimes/*"},
        {"Sid": "LgndToken", "Effect": "Allow",
         "Action": ["bedrock-agentcore:GetWorkloadAccessTokenForUserId", "bedrock-agentcore:GetResourceOauth2Token"],
         "Resource": [f"{arn_base}:workload-identity-directory/default",
                      f"{arn_base}:workload-identity-directory/default/workload-identity/{WORKLOAD}",
                      f"{arn_base}:token-vault/default",
                      f"{arn_base}:token-vault/default/oauth2credentialprovider/{PROVIDER}"]},
        {"Sid": "ClientSecret", "Effect": "Allow", "Action": "secretsmanager:GetSecretValue",
         "Resource": f"arn:aws:secretsmanager:{REGION}:{ACCOUNT}:secret:bedrock-agentcore-identity!default/oauth2/{PROVIDER}*"},
    ]}
    try:
        arn = iam.create_role(RoleName=ROLE, AssumeRolePolicyDocument=json.dumps(trust),
                              Description="Throwaway runtime role for the Clayzer LGND probe",
                              Tags=[{"Key": k, "Value": v} for k, v in TAGS.items()])["Role"]["Arn"]
        say(f"role created: {arn}")
    except ClientError as e:
        if e.response["Error"]["Code"] != "EntityAlreadyExists":
            raise
        arn = iam.get_role(RoleName=ROLE)["Role"]["Arn"]
    iam.put_role_policy(RoleName=ROLE, PolicyName="runtime-permissions", PolicyDocument=json.dumps(perms))
    return arn


def cmd_deploy(_a) -> None:
    if not load().get("provider_arn"):
        sys.exit("run lgnd_gateway.py up and identity first")
    try:
        ecr.create_repository(repositoryName=REPO, imageScanningConfiguration={"scanOnPush": True},
                              tags=[{"Key": k, "Value": v} for k, v in TAGS.items()])
        say(f"ECR repo created: {REPO}")
    except ClientError as e:
        if e.response["Error"]["Code"] != "RepositoryAlreadyExistsException":
            raise
    role_arn = ensure_role()
    user, password = base64.b64decode(
        ecr.get_authorization_token()["authorizationData"][0]["authorizationToken"]).decode().split(":", 1)
    sh("docker", "login", "--username", user, "--password-stdin", REGISTRY, stdin=password)
    sh("docker", "buildx", "build", "--platform", "linux/arm64", "-t", IMAGE, "--push", str(HERE / "runtime_probe"))
    time.sleep(10)  # let the new role propagate
    env = {"LGND_WORKLOAD": WORKLOAD, "LGND_USER_ID": TEAM_USER, "LGND_PROVIDER": PROVIDER,
           "LGND_RETURN_URL": RETURN_URL, "LGND_SCOPES": " ".join(SCOPES), "LGND_MCP": LGND_MCP}
    try:
        out = ctl.create_agent_runtime(
            agentRuntimeName=RUNTIME, description="Throwaway: can a runtime use the LGND sign-in held by Identity?",
            agentRuntimeArtifact={"containerConfiguration": {"containerUri": IMAGE}}, roleArn=role_arn,
            networkConfiguration={"networkMode": "PUBLIC"}, protocolConfiguration={"serverProtocol": "HTTP"},
            environmentVariables=env, tags=TAGS)
    except ClientError as e:
        if e.response["Error"]["Code"] != "ConflictException":
            raise
        rid = next(r["agentRuntimeId"] for r in ctl.list_agent_runtimes()["agentRuntimes"]
                   if r["agentRuntimeName"] == RUNTIME)
        out = ctl.update_agent_runtime(
            agentRuntimeId=rid, agentRuntimeArtifact={"containerConfiguration": {"containerUri": IMAGE}},
            roleArn=role_arn, networkConfiguration={"networkMode": "PUBLIC"},
            protocolConfiguration={"serverProtocol": "HTTP"}, environmentVariables=env)
    rt = wait("runtime", lambda: ctl.get_agent_runtime(agentRuntimeId=out["agentRuntimeId"]),
              {"READY"}, {"CREATE_FAILED", "UPDATE_FAILED"}, every=10)
    save(runtime_id=rt["agentRuntimeId"], runtime_arn=rt["agentRuntimeArn"])
    say(f"runtime ready: {rt['agentRuntimeArn']}")


def cmd_invoke(args) -> None:
    arn = load().get("runtime_arn") or sys.exit("run `deploy` first")
    resp = data.invoke_agent_runtime(
        agentRuntimeArn=arn, runtimeSessionId=f"clayzer-probe-{uuid.uuid4().hex}-{uuid.uuid4().hex[:8]}",
        contentType="application/json", accept="application/json",
        payload=json.dumps({"lat": args.lat, "lon": args.lon}).encode())
    say(f"HTTP {resp['ResponseMetadata']['HTTPStatusCode']}")
    say(json.dumps(json.loads(resp["response"].read()), indent=2))


def cmd_down(_a) -> None:
    state = load()

    def attempt(label, fn):
        try:
            fn()
            say(f"deleted {label}")
        except ClientError as e:
            say(f"skip {label}: {e.response['Error']['Code']}")

    rid = state.get("runtime_id")
    if rid:
        attempt("runtime", lambda: ctl.delete_agent_runtime(agentRuntimeId=rid))
        for _ in range(60):  # deletion takes about five minutes
            if not any(r["agentRuntimeId"] == rid for r in ctl.list_agent_runtimes()["agentRuntimes"]):
                break
            time.sleep(10)
    attempt("ECR repo", lambda: ecr.delete_repository(repositoryName=REPO, force=True))
    attempt("role policy", lambda: iam.delete_role_policy(RoleName=ROLE, PolicyName="runtime-permissions"))
    attempt("role", lambda: iam.delete_role(RoleName=ROLE))
    if rid:
        for g in logs.describe_log_groups(logGroupNamePrefix=f"/aws/bedrock-agentcore/runtimes/{rid}")["logGroups"]:
            attempt(f"log group {g['logGroupName']}", lambda g=g: logs.delete_log_group(logGroupName=g["logGroupName"]))
    subprocess.run(["docker", "logout", REGISTRY], check=False, capture_output=True)
    save(runtime_id=None, runtime_arn=None)


COMMANDS = {"deploy": cmd_deploy, "invoke": cmd_invoke, "down": cmd_down}

if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("command", choices=sorted(COMMANDS))
    p.add_argument("--lat", type=float, default=35.55, help="invoke: latitude (default: Ivanpah solar plant, CA)")
    p.add_argument("--lon", type=float, default=-115.47)
    a = p.parse_args()
    COMMANDS[a.command](a)
