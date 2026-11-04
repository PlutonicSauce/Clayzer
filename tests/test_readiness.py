"""The readiness check (AWS-13): no credentials in the repo, and every bucket blocks public
access. Offline: the bucket checks run against a fake S3 client, and the repo checks against a
throwaway git repo so a real .env or key on disk can't affect them."""

import subprocess
from pathlib import Path

from clayzer.readiness import (
    ACCESS_KEY,
    Finding,
    buckets_block_public_access,
    check,
    no_committed_credentials,
    render,
)

AKIA = "AKIA" + "IOSFODNN7EXAMPLE"[:16]  # a sample long-lived access key id, built so it isn't one


def git_repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "t@e.st"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "t"], check=True)
    return tmp_path


def commit(repo: Path, name: str, text: str):
    (repo / name).parent.mkdir(parents=True, exist_ok=True)
    (repo / name).write_text(text)
    subprocess.run(["git", "-C", str(repo), "add", name], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", name], check=True)


def test_a_clean_repo_passes(tmp_path):
    repo = git_repo(tmp_path)
    commit(repo, ".gitignore", ".env\n")
    commit(repo, "src/app.py", "print('hello')\n")
    findings = no_committed_credentials(repo)
    assert all(f.ok for f in findings)
    assert {f.name for f in findings} == {
        ".env not committed",
        ".env is gitignored",
        "no long-lived AWS keys committed",
    }


def test_a_committed_env_file_fails(tmp_path):
    repo = git_repo(tmp_path)
    commit(repo, ".env", "AWS_ACCESS_KEY_ID=x\n")  # no .gitignore either
    by_name = {f.name: f for f in no_committed_credentials(repo)}
    assert not by_name[".env not committed"].ok
    assert not by_name[".env is gitignored"].ok


def test_a_committed_access_key_is_caught(tmp_path):
    repo = git_repo(tmp_path)
    commit(repo, ".gitignore", ".env\n")
    commit(repo, "notes.md", f"old key {AKIA} left in a doc\n")
    f = next(f for f in no_committed_credentials(repo) if "long-lived" in f.name)
    assert not f.ok and "notes.md" in f.detail


def test_a_committed_secret_key_assignment_is_caught(tmp_path):
    repo = git_repo(tmp_path)
    commit(repo, ".gitignore", ".env\n")
    commit(repo, "config.sh", "AWS_SECRET_ACCESS_KEY='" + "a" * 40 + "'\n")
    f = next(f for f in no_committed_credentials(repo) if "long-lived" in f.name)
    assert not f.ok and "config.sh" in f.detail


def test_a_gitignored_env_on_disk_is_not_a_finding(tmp_path):
    # The real repo has a local .env; a clone wouldn't. An untracked, ignored .env must pass.
    repo = git_repo(tmp_path)
    commit(repo, ".gitignore", ".env\n")
    (repo / ".env").write_text(f"AWS_ACCESS_KEY_ID={AKIA}\n")
    assert all(f.ok for f in no_committed_credentials(repo))


def test_this_modules_own_patterns_do_not_flag_the_real_repo():
    # readiness.py names AKIA and the secret-key pattern; the scan must skip itself, so the real
    # tracked repo stays clean.
    f = next(f for f in no_committed_credentials() if "long-lived" in f.name)
    assert f.ok, f.detail


class FakeS3:
    def __init__(self, buckets: dict[str, dict | None]):
        # name -> the PublicAccessBlockConfiguration, or None for "no block set".
        self._buckets = buckets

    def list_buckets(self):
        return {"Buckets": [{"Name": n} for n in self._buckets]}

    def get_public_access_block(self, Bucket):
        from botocore.exceptions import ClientError

        cfg = self._buckets[Bucket]
        if cfg is None:
            raise ClientError(
                {"Error": {"Code": "NoSuchPublicAccessBlockConfiguration"}},
                "GetPublicAccessBlock",
            )
        return {"PublicAccessBlockConfiguration": cfg}


ALL_ON = {
    "BlockPublicAcls": True,
    "IgnorePublicAcls": True,
    "BlockPublicPolicy": True,
    "RestrictPublicBuckets": True,
}


def test_a_fully_blocked_bucket_passes():
    f = buckets_block_public_access(FakeS3({"store": ALL_ON}))
    assert len(f) == 1 and f[0].ok


def test_a_bucket_with_no_block_fails():
    f = buckets_block_public_access(FakeS3({"store": None}))
    assert not f[0].ok and "no public-access block" in f[0].detail


def test_a_bucket_with_a_gap_fails():
    f = buckets_block_public_access(FakeS3({"store": {**ALL_ON, "RestrictPublicBuckets": False}}))
    assert not f[0].ok and "gaps" in f[0].detail


def test_every_bucket_is_reported():
    f = buckets_block_public_access(FakeS3({"a": ALL_ON, "b": None}))
    assert len(f) == 2 and sum(x.ok for x in f) == 1


def test_access_denied_on_a_bucket_is_a_fail_not_a_pass():
    from botocore.exceptions import ClientError

    class Denied(FakeS3):
        def get_public_access_block(self, Bucket):
            raise ClientError({"Error": {"Code": "AccessDenied"}}, "GetPublicAccessBlock")

    f = buckets_block_public_access(Denied({"someone-elses": ALL_ON}))
    assert not f[0].ok and "denied" in f[0].detail


def test_check_skips_the_account_when_asked():
    findings = check(with_account=False)
    assert findings and not any("bucket" in f.name for f in findings)


def test_check_runs_the_account_with_a_client_given():
    findings = check(s3=FakeS3({"store": ALL_ON}))
    assert any(f.name == "bucket store blocks public access" and f.ok for f in findings)


def test_render_summarizes_pass_and_fail():
    assert "all checks passed" in render([Finding("x", True, "fine")])
    assert "1 check(s) failed" in render([Finding("x", False, "bad"), Finding("y", True, "ok")])


def test_the_command_exits_nonzero_when_a_check_fails(monkeypatch, capsys):
    from clayzer import cli

    monkeypatch.setattr(cli, "load_env", lambda: None)
    monkeypatch.setattr("clayzer.readiness.check", lambda **_: [Finding("x", False, "bad")])
    assert cli.main(["readiness", "--no-account"]) == 1
    assert "FAIL" in capsys.readouterr().out


def test_the_access_key_pattern_matches_only_akia():
    assert ACCESS_KEY.search(AKIA)
    assert not ACCESS_KEY.search("ASIA" + "IOSFODNN7EXAMPLE"[:16])  # short-lived, allowed
