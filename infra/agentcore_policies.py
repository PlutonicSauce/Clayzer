"""Reviewable AgentCore execution policies, parameterized for one participant account."""


def trust(account: str, resource_arn: str) -> dict:
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"Service": "bedrock-agentcore.amazonaws.com"},
                "Action": "sts:AssumeRole",
                "Condition": {
                    "StringEquals": {"aws:SourceAccount": account},
                    "ArnLike": {"aws:SourceArn": resource_arn},
                },
            }
        ],
    }


def runtime_policy(
    region: str,
    account: str,
    bucket: str,
    prefix: str,
    artifact_bucket: str,
    artifact_key: str,
    credential_arn: str,
    log_group: str,
) -> dict:
    root = f"arn:aws:s3:::{bucket}/" + (prefix.strip("/") + "/" if prefix.strip("/") else "")
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "ChipImagesAndCode",
                "Effect": "Allow",
                "Action": "s3:GetObject",
                "Resource": [
                    root + "chips/*.png",
                    f"arn:aws:s3:::{artifact_bucket}/{artifact_key}",
                ],
            },
            {
                "Sid": "StandaloneTraces",
                "Effect": "Allow",
                "Action": "s3:PutObject",
                "Resource": root + "runs/agentcore/*",
            },
            {
                "Sid": "NoAnswerKeys",
                "Effect": "Deny",
                "Action": ["s3:GetObject", "s3:GetObjectVersion"],
                "Resource": [root + "cases/*", root + "labels/*"],
            },
            {
                "Sid": "CaptionModel",
                "Effect": "Allow",
                "Action": "bedrock:InvokeModel",
                "Resource": [
                    f"arn:aws:bedrock:{region}:{account}:inference-profile/us.amazon.nova-pro-v1:0",
                    "arn:aws:bedrock:*::foundation-model/amazon.nova-pro-v1:0",
                ],
            },
            {
                "Sid": "GatewayClient",
                "Effect": "Allow",
                "Action": "secretsmanager:GetSecretValue",
                "Resource": credential_arn,
            },
            {
                "Sid": "RuntimeLogs",
                "Effect": "Allow",
                "Action": [
                    "logs:CreateLogGroup",
                    "logs:CreateLogStream",
                    "logs:PutLogEvents",
                    "logs:DescribeLogStreams",
                ],
                "Resource": f"arn:aws:logs:{region}:{account}:log-group:{log_group}:*",
            },
        ],
    }


def gateway_policy(workload_arn: str, provider_arn: str, secret_arn: str) -> dict:
    directory = workload_arn.rsplit("/workload-identity/", 1)[0]
    vault = provider_arn.rsplit("/oauth2credentialprovider/", 1)[0]
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "GatewayWorkload",
                "Effect": "Allow",
                "Action": [
                    "bedrock-agentcore:GetWorkloadAccessToken",
                    "bedrock-agentcore:GetWorkloadAccessTokenForUserId",
                    "bedrock-agentcore:GetWorkloadAccessTokenForJWT",
                ],
                "Resource": [directory, workload_arn],
            },
            {
                "Sid": "LgndToken",
                "Effect": "Allow",
                "Action": "bedrock-agentcore:GetResourceOauth2Token",
                "Resource": [provider_arn, vault, directory, workload_arn],
            },
            {
                "Sid": "LgndCredential",
                "Effect": "Allow",
                "Action": "secretsmanager:GetSecretValue",
                "Resource": secret_arn,
            },
        ],
    }
