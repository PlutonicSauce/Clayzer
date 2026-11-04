"""Check the actual synthesized trust policy for canonical and fork deployments."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    ("context", "expected_prefixes"),
    [
        (
            {},
            {"repo:PlutonicSauce/Clayzer", "repo:PlutonicSauce@127466756/Clayzer@1444863531"},
        ),
        ({"repo": "example/fork"}, {"repo:example/fork"}),
        (
            {"repo": "example/fork", "sub_prefix": "repo:example@123/fork@456"},
            {"repo:example/fork", "repo:example@123/fork@456"},
        ),
    ],
)
def test_deploy_role_subjects(tmp_path, context, expected_prefixes):
    result = subprocess.run(
        [sys.executable, str(Path(__file__).resolve().parents[1] / "github_oidc.py")],
        cwd=tmp_path,
        env={
            **os.environ,
            "CDK_CONTEXT_JSON": json.dumps(context),
            "CDK_OUTDIR": str(tmp_path / "cdk.out"),
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    template = json.loads((tmp_path / "cdk.out/ClayzerGitHubDeploy.template.json").read_text())
    roles = [
        resource["Properties"]
        for resource in template["Resources"].values()
        if resource["Type"] == "AWS::IAM::Role"
    ]
    assert len(roles) == 1
    statements = roles[0]["AssumeRolePolicyDocument"]["Statement"]
    assert len(statements) == 1
    statement = statements[0]
    assert statement["Effect"] == "Allow"
    assert statement["Action"] == "sts:AssumeRoleWithWebIdentity"
    conditions = statement["Condition"]["StringEquals"]
    assert conditions["token.actions.githubusercontent.com:aud"] == "sts.amazonaws.com"
    subjects = conditions["token.actions.githubusercontent.com:sub"]
    if isinstance(subjects, str):
        subjects = [subjects]
    assert set(subjects) == {f"{prefix}:environment:aws" for prefix in expected_prefixes}
