"""Experiment B: can an AgentCore Gateway hold the LGND Geo sign-in?

Throwaway, scripted experiment (issue #23, plan phase 2). It is meant to be replaced by CDK once
we know what works. Every resource is named `clayzer-probe` and tagged throwaway=true, and `down`
removes them all.

Steps (each is idempotent, so you can re-run after a failure):

    uv run python experiments/agentcore-gateway/lgnd_gateway.py up       # role, OAuth client, Gateway
    uv run python experiments/agentcore-gateway/lgnd_gateway.py target   # add LGND as a target (needs a browser sign-in)
    uv run python experiments/agentcore-gateway/lgnd_gateway.py status
    uv run python experiments/agentcore-gateway/lgnd_gateway.py down

State (ARNs and ids only, never secrets) is kept in ~/.clayzer/agentcore-probe.json, outside the repo.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

REGION = "us-west-2"
NAME = "clayzer-probe"
LGND_MCP = "https://geo.lgnd.ai/mcp"
# LGND's sign-in is run by WorkOS AuthKit; geo.lgnd.ai/.well-known/oauth-protected-resource/mcp names it.
AUTH_SERVER = "https://captivating-sparkle-03.authkit.app"
DISCOVERY_URL = f"{AUTH_SERVER}/.well-known/oauth-authorization-server"
SCOPES = ["openid", "profile", "email", "offline_access"]
TAGS = {"purpose": "clayzer-agentcore-probe", "throwaway": "true"}
STATE = Path.home() / ".clayzer" / "agentcore-probe.json"

sts = boto3.client("sts", region_name=REGION)
iam = boto3.client("iam", region_name=REGION)
ctl = boto3.client("bedrock-agentcore-control", region_name=REGION)
ACCOUNT = sts.get_caller_identity()["Account"]
ROLE_NAME = "AgentCoreGateway-clayzer-probe"
PROVIDER = "clayzer-probe-lgnd"
GATEWAY = "clayzer-probe-gateway"


def load() -> dict:
    return json.loads(STATE.read_text()) if STATE.exists() else {}


def save(**kv) -> dict:
    state = {**load(), **kv}
    STATE.parent.mkdir(mode=0o700, exist_ok=True)
    STATE.write_text(json.dumps(state, indent=2))
    STATE.chmod(0o600)
    return state


def say(msg: str) -> None:
    print(msg, flush=True)


# ── 1. The Gateway's IAM role ────────────────────────────────────────────────────────────

def ensure_role() -> str:
    trust = {
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Service": "bedrock-agentcore.amazonaws.com"},
            "Action": "sts:AssumeRole",
            "Condition": {
                "StringEquals": {"aws:SourceAccount": ACCOUNT},
                "ArnLike": {"aws:SourceArn": f"arn:aws:bedrock-agentcore:{REGION}:{ACCOUNT}:gateway/*"},
            },
        }],
    }
    perms = {
        "Version": "2012-10-17",
        "Statement": [
            {   # fetch the OAuth token the sign-in produced
                "Sid": "IdentityTokens", "Effect": "Allow",
                "Action": ["bedrock-agentcore:GetWorkloadAccessToken",
                           "bedrock-agentcore:GetWorkloadAccessTokenForUserId",
                           "bedrock-agentcore:GetResourceOauth2Token"],
                "Resource": [
                    f"arn:aws:bedrock-agentcore:{REGION}:{ACCOUNT}:workload-identity-directory/default",
                    f"arn:aws:bedrock-agentcore:{REGION}:{ACCOUNT}:workload-identity-directory/default/workload-identity/*",
                    f"arn:aws:bedrock-agentcore:{REGION}:{ACCOUNT}:token-vault/default",
                    f"arn:aws:bedrock-agentcore:{REGION}:{ACCOUNT}:token-vault/default/oauth2credentialprovider/{PROVIDER}",
                ],
            },
            {   # the OAuth client secret lives in a Secrets Manager secret that AgentCore Identity creates
                "Sid": "ClientSecret", "Effect": "Allow",
                "Action": "secretsmanager:GetSecretValue",
                "Resource": f"arn:aws:secretsmanager:{REGION}:{ACCOUNT}:secret:bedrock-agentcore-identity!default/oauth2/{PROVIDER}*",
            },
        ],
    }
    try:
        arn = iam.create_role(
            RoleName=ROLE_NAME, AssumeRolePolicyDocument=json.dumps(trust),
            Description="Throwaway role for the Clayzer AgentCore Gateway probe",
            Tags=[{"Key": k, "Value": v} for k, v in TAGS.items()],
        )["Role"]["Arn"]
        say(f"role created: {arn}")
    except ClientError as e:
        if e.response["Error"]["Code"] != "EntityAlreadyExists":
            raise
        arn = iam.get_role(RoleName=ROLE_NAME)["Role"]["Arn"]
        say(f"role exists: {arn}")
    iam.put_role_policy(RoleName=ROLE_NAME, PolicyName="gateway-permissions", PolicyDocument=json.dumps(perms))
    return arn


# ── 2. The OAuth client at LGND's sign-in server, registered the standard way (RFC 7591) ──

def register_client(redirect_uri: str) -> tuple[str, str | None]:
    """Dynamic client registration, the same mechanism `clayzer login lgnd` uses in src/clayzer/mcp_auth.py."""
    body = {
        "client_name": "Clayzer AgentCore probe",
        "redirect_uris": [redirect_uri],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "client_secret_post",
        "scope": " ".join(SCOPES),
    }
    req = urllib.request.Request(
        f"{AUTH_SERVER}/oauth2/register", data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            reg = json.loads(r.read())
    except urllib.error.HTTPError as e:
        sys.exit(f"client registration refused: HTTP {e.code} {e.read().decode()[:300]}")
    return reg["client_id"], reg.get("client_secret")


def provider_config(client_id: str, client_secret: str) -> dict:
    return {"customOauth2ProviderConfig": {
        "oauthDiscovery": {"discoveryUrl": DISCOVERY_URL},
        "clientId": client_id, "clientSecret": client_secret}}


def ensure_provider() -> dict:
    state = load()
    if state.get("provider_arn") and state.get("client_registered"):
        say(f"OAuth client ready: {state['provider_arn']}")
        return state
    if not state.get("provider_arn"):
        # The callback URL only exists once the provider does, and the sign-in server needs it
        # at registration, so: create with placeholders, register, then update with the real client.
        out = ctl.create_oauth2_credential_provider(
            name=PROVIDER, credentialProviderVendor="CustomOauth2",
            oauth2ProviderConfigInput=provider_config("placeholder", "placeholder"),
            tags=TAGS)
        state = save(provider_arn=out["credentialProviderArn"], callback_url=out["callbackUrl"])
        say(f"provider created, callback: {state['callback_url']}")
    client_id, client_secret = register_client(state["callback_url"])
    if not client_secret:
        sys.exit("the sign-in server issued a public client (no secret); AgentCore needs one. Stopping.")
    ctl.update_oauth2_credential_provider(
        name=PROVIDER, credentialProviderVendor="CustomOauth2",
        oauth2ProviderConfigInput=provider_config(client_id, client_secret))
    del client_secret  # never written anywhere by this script
    say(f"OAuth client registered with LGND's sign-in server (client id {client_id[:12]}...)")
    return save(client_registered=True, client_id=client_id)


# ── 3. The Gateway ───────────────────────────────────────────────────────────────────────

def wait(label: str, fetch, ok: set[str], bad: set[str], every: int = 5, tries: int = 60):
    for _ in range(tries):
        resp = fetch()
        status = resp["status"]
        say(f"  {label}: {status}")
        if status in ok:
            return resp
        if status in bad:
            sys.exit(f"{label} failed: {resp.get('statusReasons') or resp}")
        time.sleep(every)
    sys.exit(f"{label}: timed out")


def ensure_gateway(role_arn: str) -> dict:
    state = load()
    if state.get("gateway_id"):
        say(f"gateway exists: {state['gateway_id']}")
        return state
    time.sleep(10)  # let the new role propagate
    out = ctl.create_gateway(
        name=GATEWAY, roleArn=role_arn, protocolType="MCP",
        authorizerType="AWS_IAM",  # callers sign with SigV4, so scripts and runtimes need no JWT setup
        description="Throwaway Clayzer probe: can a Gateway hold the LGND sign-in?", tags=TAGS)
    gw = wait("gateway", lambda: ctl.get_gateway(gatewayIdentifier=out["gatewayId"]),
              {"READY"}, {"FAILED", "UPDATE_UNSUCCESSFUL"})
    return save(gateway_id=gw["gatewayId"], gateway_arn=gw["gatewayArn"], gateway_url=gw["gatewayUrl"],
                workload_identity_arn=gw["workloadIdentityDetails"]["workloadIdentityArn"])


def cmd_up(_args) -> None:
    say(f"account {ACCOUNT}, region {REGION}")
    role_arn = ensure_role()
    ensure_provider()
    state = ensure_gateway(role_arn)
    say(f"\nGateway ready: {state['gateway_url']}")
    say("Next: run the `target` step (it needs you to sign in to LGND in a browser).")


def cmd_status(_args) -> None:
    say(json.dumps(load(), indent=2))


# ── 4. LGND as a Gateway target (needs a human sign-in) ──────────────────────────────────

RETURN_URL = "http://localhost:8765/callback"  # nothing needs to listen here; you copy the address from the browser


def cmd_target(_args) -> None:
    state = load()
    if not state.get("gateway_id"):
        sys.exit("run `up` first")
    # The Gateway may only send a browser back to URLs its workload identity allows.
    identity = state["workload_identity_arn"].rsplit("/", 1)[-1]
    ctl.update_workload_identity(name=identity, allowedResourceOauth2ReturnUrls=[RETURN_URL])
    out = ctl.create_gateway_target(
        gatewayIdentifier=state["gateway_id"], name="lgnd-geo",
        description="LGND Geo MCP server (throwaway probe)",
        targetConfiguration={"mcp": {"mcpServer": {"endpoint": LGND_MCP}}},
        credentialProviderConfigurations=[{
            "credentialProviderType": "OAUTH",
            "credentialProvider": {"oauthCredentialProvider": {
                "providerArn": state["provider_arn"], "grantType": "AUTHORIZATION_CODE",
                "defaultReturnUrl": RETURN_URL, "scopes": SCOPES}}}])
    save(target_id=out["targetId"])
    say(f"target {out['targetId']}: {out['status']}")
    for r in out.get("statusReasons", []):
        say(f"  reason: {r}")
    auth = out.get("authorizationData")
    if auth:
        say("\nOpen this link in your own browser and sign in to LGND:\n")
        say(json.dumps(auth, indent=2, default=str))
        say("\nThe browser will then be sent to a localhost address that won't load. That's expected.")
        say("Copy the full address from the address bar and run:  finish --callback-url '<that address>'")


def cmd_finish(args) -> None:
    from urllib.parse import parse_qs, urlparse
    state = load()
    query = parse_qs(urlparse(args.callback_url).query)
    session_uri = (query.get("session_uri") or query.get("sessionUri") or [None])[0]
    if not session_uri:
        sys.exit(f"no session_uri in that address; it had: {sorted(query)}")
    data = boto3.client("bedrock-agentcore", region_name=REGION)
    user_id = args.user_id or sts.get_caller_identity()["Arn"]
    data.complete_resource_token_auth(userIdentifier={"userId": user_id}, sessionUri=session_uri)
    say(f"sign-in completed for user id {user_id!r}")
    wait("target", lambda: ctl.get_gateway_target(gatewayIdentifier=state["gateway_id"], targetId=state["target_id"]),
         {"READY"}, {"FAILED", "UPDATE_UNSUCCESSFUL", "SYNCHRONIZE_UNSUCCESSFUL"})


# FINDING (2026-11-04): `target` fails on this IAM-authorized Gateway with "3LO Auth is not supported
# when gateway authorizer type is AWS_IAM". A Gateway can only run a browser sign-in for callers that
# carry a JWT (so it knows which user signed in). The `identity` / `identity-finish` steps below test
# the alternative: AgentCore Identity holds the sign-in and our own Harness code asks it for the token.


# ── 5. Identity-only path: the token vault holds the LGND sign-in, no Gateway involved ───

WORKLOAD = "clayzer-probe-agent"
TEAM_USER = "clayzer-team"  # the one shared identity the sign-in is stored under


def workload_token() -> str:
    data = boto3.client("bedrock-agentcore", region_name=REGION)
    return data.get_workload_access_token_for_user_id(workloadName=WORKLOAD, userId=TEAM_USER)["workloadAccessToken"]


def get_lgnd_token(session_uri: str | None = None) -> dict:
    data = boto3.client("bedrock-agentcore", region_name=REGION)
    kw = dict(workloadIdentityToken=workload_token(), resourceCredentialProviderName=PROVIDER,
              scopes=SCOPES, oauth2Flow="USER_FEDERATION", resourceOauth2ReturnUrl=RETURN_URL)
    if session_uri:
        kw["sessionUri"] = session_uri
    return data.get_resource_oauth2_token(**kw)


def cmd_identity(_args) -> None:
    if not load().get("provider_arn"):
        sys.exit("run `up` first")
    try:
        ctl.create_workload_identity(name=WORKLOAD, allowedResourceOauth2ReturnUrls=[RETURN_URL], tags=TAGS)
        say(f"workload identity created: {WORKLOAD}")
    except ClientError as e:
        if e.response["Error"]["Code"] not in ("ConflictException", "ValidationException"):
            raise
        ctl.update_workload_identity(name=WORKLOAD, allowedResourceOauth2ReturnUrls=[RETURN_URL])
        say(f"workload identity exists: {WORKLOAD}")
    resp = get_lgnd_token()
    keys = sorted(k for k in resp if k not in ("ResponseMetadata",))
    say(f"response fields: {keys}")
    if resp.get("accessToken"):
        say("already signed in: a token is stored for this identity")
        return
    save(session_uri=resp.get("sessionUri"))
    say("\nOpen this link in your own browser and sign in to LGND:\n")
    say(str(resp.get("authorizationUrl")))
    say("\nYour browser will then be sent to a localhost address that won't load. That is expected.")
    say("Copy the full address from the address bar and run:  identity-finish --callback-url '<that address>'")


def cmd_identity_finish(args) -> None:
    import ssl  # noqa: F401  (stdlib TLS used by urllib below)
    from urllib.parse import parse_qs, urlparse
    state = load()
    query = parse_qs(urlparse(args.callback_url).query)
    # The redirect names the value `session_id`; the API calls the same value `sessionUri`.
    session_uri = (query.get("session_uri") or query.get("sessionUri") or query.get("session_id")
                   or [state.get("session_uri")])[0]
    if not session_uri:
        sys.exit(f"no session id found; the address had: {sorted(query)}")
    if state.get("session_uri") and session_uri != state["session_uri"]:
        sys.exit("the session in that address is not the one this script started; run `identity` again")
    data = boto3.client("bedrock-agentcore", region_name=REGION)
    data.complete_resource_token_auth(userIdentifier={"userId": TEAM_USER}, sessionUri=session_uri)
    say("sign-in completed; asking Identity for the stored token")
    resp = get_lgnd_token()
    token = resp.get("accessToken")
    if not token:
        sys.exit(f"no token yet; fields: {sorted(resp)}")
    # Prove the token works: MCP `initialize` against LGND. The token is never printed.
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2025-06-18", "capabilities": {},
        "clientInfo": {"name": "clayzer-agentcore-probe", "version": "0"}}}).encode()
    req = urllib.request.Request(LGND_MCP, data=body, method="POST", headers={
        "Authorization": f"Bearer {token}", "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            text = r.read().decode()[:400]
            say(f"LGND answered HTTP {r.status}: {text}")
    except urllib.error.HTTPError as e:
        sys.exit(f"LGND rejected the token: HTTP {e.code} {e.read().decode()[:300]}")


# ── 6. Clean up everything this script created ───────────────────────────────────────────

def cmd_down(_args) -> None:
    state = load()
    def attempt(label, fn):
        try:
            fn(); say(f"deleted {label}")
        except ClientError as e:
            say(f"skip {label}: {e.response['Error']['Code']}")
    if state.get("gateway_id"):
        for t in ctl.list_gateway_targets(gatewayIdentifier=state["gateway_id"]).get("items", []):
            attempt(f"target {t['targetId']}", lambda t=t: ctl.delete_gateway_target(gatewayIdentifier=state["gateway_id"], targetId=t["targetId"]))
        time.sleep(5)
        attempt("gateway", lambda: ctl.delete_gateway(gatewayIdentifier=state["gateway_id"]))
    attempt("workload identity", lambda: ctl.delete_workload_identity(name=WORKLOAD))
    attempt("OAuth client (Identity provider)", lambda: ctl.delete_oauth2_credential_provider(name=PROVIDER))
    attempt("role policy", lambda: iam.delete_role_policy(RoleName=ROLE_NAME, PolicyName="gateway-permissions"))
    attempt("role", lambda: iam.delete_role(RoleName=ROLE_NAME))
    STATE.unlink(missing_ok=True)
    say("note: the client registered at LGND's sign-in server cannot be removed from here; it is inert once the provider is gone.")


COMMANDS = {"up": cmd_up, "status": cmd_status, "target": cmd_target, "finish": cmd_finish,
            "identity": cmd_identity, "identity-finish": cmd_identity_finish, "down": cmd_down}

if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("command", choices=sorted(COMMANDS))
    p.add_argument("--callback-url", help="finish: the address your browser was sent to after signing in")
    p.add_argument("--user-id", help="finish: the user id to bind the sign-in to (default: the AWS caller ARN)")
    args = p.parse_args()
    COMMANDS[args.command](args)
