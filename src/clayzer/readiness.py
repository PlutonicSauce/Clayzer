"""The readiness check: the repo keeps no credentials, and every bucket blocks public access.

This is the part of the readiness check AWS-13 needs. It has two halves:

- **Repo** (offline, always runs): no long-lived AWS keys or a committed `.env` in the tracked
  files, and `.env` is gitignored. Short-lived access only (AWS-13): nothing a public repo could
  leak.
- **Account** (needs AWS, skipped without it): every S3 bucket in the account blocks public
  access at the bucket level, so the store and anything beside it can't be read by the world.

Each check is a Finding (ok or not, with a line of why). `check()` gathers them; the CLI prints
them and exits non-zero if any failed. The wider readiness task (licenses, disallowed services,
the leak scan in full) is `readiness` in docs/tasks.toml; this closes the AWS-13 slice.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from clayzer.config import REPO

# A long-lived AWS access key id: AKIA (IAM user) or ASIA is short-lived, so only AKIA is a leak.
# AGPA/AIDA/etc. are other id types; AKIA is the one that pairs with a secret key.
ACCESS_KEY = re.compile(r"\bAKIA[0-9A-Z]{16}\b")
# A line that assigns a secret access key a literal 40-char value (not a reference or a blank).
SECRET_KEY = re.compile(r"AWS_SECRET_ACCESS_KEY\s*[=:]\s*['\"]?[A-Za-z0-9/+]{40}\b")


@dataclass(frozen=True)
class Finding:
    name: str
    ok: bool
    detail: str


def tracked_files(repo: Path = REPO) -> list[Path]:
    """Every file git tracks. Untracked and gitignored files (like a local .env) aren't the
    repo's problem: the check is about what a clone would contain."""
    out = subprocess.run(
        ["git", "-C", str(repo), "ls-files", "-z"],
        capture_output=True,
        text=True,
        check=True,
    )
    return [repo / name for name in out.stdout.split("\0") if name]


def _is_gitignored(path: str, repo: Path = REPO) -> bool:
    # check-ignore exits 0 when the path is ignored and 1 when it isn't; neither is an error.
    cmd = ["git", "-C", str(repo), "check-ignore", "-q", path]
    return subprocess.run(cmd, check=False).returncode == 0


def no_committed_credentials(repo: Path = REPO) -> list[Finding]:
    """No long-lived keys and no committed .env among the tracked files (AWS-13)."""
    findings: list[Finding] = []

    env_tracked = any(f.name == ".env" for f in tracked_files(repo))
    findings.append(
        Finding(
            ".env not committed",
            not env_tracked,
            "a .env is tracked by git" if env_tracked else "no .env is tracked",
        )
    )
    findings.append(
        Finding(
            ".env is gitignored",
            _is_gitignored(".env", repo),
            "add .env to .gitignore" if not _is_gitignored(".env", repo) else "gitignored",
        )
    )

    hits = []
    for f in tracked_files(repo):
        # This module names the patterns it looks for, so skip it to avoid flagging itself.
        if f.resolve() == Path(__file__).resolve():
            continue
        try:
            text = f.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue  # a binary or unreadable file holds no key we'd match
        if ACCESS_KEY.search(text) or SECRET_KEY.search(text):
            hits.append(f.relative_to(repo).as_posix())
    findings.append(
        Finding(
            "no long-lived AWS keys committed",
            not hits,
            f"possible keys in {', '.join(hits)}" if hits else "none found in tracked files",
        )
    )
    return findings


def buckets_block_public_access(s3=None) -> list[Finding]:
    """Every S3 bucket in the account blocks public access at the bucket level (AWS-13, AWS-03).

    One Finding per bucket. A bucket with no public-access-block configuration at all is a fail:
    AWS treats a missing block as "not blocked".
    """
    import boto3
    from botocore.exceptions import ClientError

    s3 = s3 or boto3.client("s3")
    findings: list[Finding] = []
    for b in s3.list_buckets().get("Buckets", []):
        name = b["Name"]
        try:
            cfg = s3.get_public_access_block(Bucket=name)["PublicAccessBlockConfiguration"]
            blocked = all(
                cfg.get(k)
                for k in (
                    "BlockPublicAcls",
                    "IgnorePublicAcls",
                    "BlockPublicPolicy",
                    "RestrictPublicBuckets",
                )
            )
            detail = "all four public-access blocks on" if blocked else f"gaps: {cfg}"
        except ClientError as e:
            code = e.response["Error"]["Code"]
            if code == "NoSuchPublicAccessBlockConfiguration":
                blocked, detail = False, "no public-access block set"
            elif code in ("AccessDenied", "AllAccessDisabled"):
                # A bucket in the account this role can't read: report it, don't claim it's safe.
                blocked, detail = False, "access denied reading its public-access block"
            else:
                raise
        findings.append(Finding(f"bucket {name} blocks public access", blocked, detail))
    return findings


def check(repo: Path = REPO, s3=None, with_account: bool = True) -> list[Finding]:
    """Every readiness Finding. The account checks are skipped when `with_account` is false or
    no AWS credentials are available, so the repo checks still run offline."""
    findings = list(no_committed_credentials(repo))
    if not with_account:
        return findings
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError

    if s3 is None and boto3.Session().get_credentials() is None:
        findings.append(Finding("buckets checked", True, "skipped: no AWS credentials"))
        return findings
    try:
        findings.extend(buckets_block_public_access(s3))
    except (BotoCoreError, ClientError) as e:
        findings.append(
            Finding("buckets checked", False, f"couldn't list buckets: {type(e).__name__}")
        )
    return findings


def render(findings: list[Finding]) -> str:
    lines = [f"  [{'ok' if f.ok else 'FAIL'}] {f.name}: {f.detail}" for f in findings]
    failed = sum(not f.ok for f in findings)
    head = "Readiness: all checks passed" if not failed else f"Readiness: {failed} check(s) failed"
    return head + "\n" + "\n".join(lines)
