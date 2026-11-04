"""The repo half of the readiness check (the readiness task): what a public clone contains.

Licenses respected and nothing private committed. Credentials and buckets are `clayzer
readiness` (AWS-13); these cover the rest, over every file git tracks, so they also run in CI.
"""

import re
import subprocess

import pytest

from clayzer.config import REPO

TRACKED = [
    REPO / name
    for name in subprocess.run(
        ["git", "-C", str(REPO), "ls-files", "-z"], capture_output=True, text=True, check=True
    ).stdout.split("\0")
    if name
]
BINARY = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".zip", ".woff", ".woff2", ".parquet"}
# Lock files hold package hashes, and this file holds the patterns themselves.
SKIP = {"uv.lock", "requirements.lock", "test_repo_readiness.py"}


def _text_files():
    for path in TRACKED:
        if path.suffix.lower() in BINARY or path.name in SKIP or not path.is_file():
            continue
        try:
            yield path, path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue


def _hits(pattern: re.Pattern) -> list[str]:
    out = []
    for path, text in _text_files():
        for n, line in enumerate(text.splitlines(), 1):
            if m := pattern.search(_scan_line(path, line)):
                out.append(f"{path.relative_to(REPO)}:{n}: {m.group(0)}")
    return out


def _scan_line(path, line: str) -> str:
    # A numeric substring of a verified-format package digest isn't an account id.
    # Keep scanning the rest of the line/file, including index URLs and credentials.
    line = re.sub(r"--hash=sha256:[a-f0-9]{64}\b", "", line)
    relative = path.relative_to(REPO).parts
    if relative[:1] == ("tests",) or relative[:2] == ("infra", "tests"):
        # AWS's documented example account is used by isolated IAM/CDK unit fixtures.
        line = re.sub(r"(?<!\d)123456789012(?!\d)", "<example-account>", line)
    return line


def test_scan_exempts_only_hashes_and_the_test_fixture_account():
    digest = "--hash=sha256:" + "a" * 20 + "824191099700" + "b" * 32
    assert (
        _scan_line(REPO / "infra/requirements.txt", digest + " private-index") == " private-index"
    )
    assert _scan_line(REPO / "tests/example.py", "123456789012 987654321098") == (
        "<example-account> 987654321098"
    )
    assert _scan_line(REPO / "src/example.py", "123456789012") == "123456789012"


def test_the_repo_is_licensed_apache_2():
    text = (REPO / "LICENSE").read_text()
    assert "Apache License" in text and "Version 2.0, January 2004" in text


@pytest.mark.parametrize(
    "what,pattern",
    [
        # An AWS account id: twelve digits on their own (OSM and USGS ids are shorter).
        ("account id", r"(?<![\d.])\d{12}(?![\d.])"),
        ("ARN with an account", r"arn:aws[a-z-]*:[a-z0-9-]+:[a-z0-9-]*:\d{12}:"),
        ("deployment hostname", (r"\b[a-z0-9]{8,}\.cloudfront\.net|[a-z0-9-]+\.elb\.amazonaws\.com"
                                 r"|[a-z0-9]+\.execute-api\.[a-z0-9-]+\.amazonaws\.com"
                                 r"|[a-z0-9-]+\.awsapprunner\.com")),
        ("employer reference", r"(?i)lmco|lockheed"),
    ],
    ids=["account id", "arn", "hostname", "employer"],
)  # fmt: skip
def test_nothing_private_is_committed(what, pattern):
    hits = _hits(re.compile(pattern))
    assert not hits, f"{what} in tracked files:\n" + "\n".join(hits[:10])


def test_no_benchmark_data_is_committed():
    # RSICD, LEVIR, VRSBench (DOTA images), SkyScript, and MegaEarth are downloaded at run
    # time, never committed (caption-plan.md §3): code and docs may name them, data may not.
    names = re.compile(r"(?i)rsicd|levir|vrsbench|dota|skyscript|megaearth")
    code = {".py", ".md", ".toml", ".js", ".html", ".css", ".txt", ".yaml", ".yml"}
    data = [p for p in TRACKED if names.search(p.name) and p.suffix.lower() not in code]
    assert not data, [str(p.relative_to(REPO)) for p in data]


def test_osm_derived_files_carry_the_odbl_notice():
    derived = sorted({p.parent for p, text in _text_files()
                      if p.suffix == ".jsonl" and '"source": "osm' in text})  # fmt: skip
    assert derived, "no OSM-derived Case files found; has the label format changed?"
    for folder in derived:
        notice = folder / "NOTICE.md"
        assert notice.exists(), f"{folder.relative_to(REPO)} has OSM-derived data but no NOTICE.md"
        text = notice.read_text()
        assert "ODbL" in text and "OpenStreetMap contributors" in text, notice


def test_no_disallowed_aws_services():
    # caption-design.md §2.2 (AWS-12): no HyperPod, no Trainium clusters, no warehouse, and no
    # deployment into another account.
    pattern = re.compile(r"(?i)hyperpod|trainium|\btrn[12]\b|redshift|snowflake|cross[_-]?account")
    hits = [h for h in _hits(pattern) if h.split(":")[0].split("/")[0] in ("src", "infra")]
    assert not hits, "\n".join(hits)


def test_the_scan_sees_the_repo():
    # Guards the checks above against passing because they read nothing.
    assert len(TRACKED) > 100 and (REPO / "src" / "clayzer").is_dir()
    assert any(p.name == "caption-dev.jsonl" for p in TRACKED)
    assert REPO / "LICENSE" in TRACKED
