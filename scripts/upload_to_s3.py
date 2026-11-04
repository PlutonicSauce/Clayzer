#!/usr/bin/env python3
"""Upload a large local file to S3 with multipart + a progress bar, using boto3 (no aws CLI).

For staging the Clay checkpoint so an AWS WorkSpace can read it (ADR-0010 workflow). boto3 ships
with the clayzer package, so this needs no extra install; it resolves region and credentials the
normal boto3 way (env vars, AWS_PROFILE, ~/.aws, or an instance role). Works in both the
commercial and GovCloud partitions — the partition follows your credentials' account.

    # on a machine that HAS the file and valid creds for the target account:
    export AWS_ACCESS_KEY_ID=... AWS_SECRET_ACCESS_KEY=... AWS_SESSION_TOKEN=...   # your own creds
    export AWS_DEFAULT_REGION=us-west-2                                           # the bucket's region
    uv run python scripts/upload_to_s3.py ~/Downloads/clay-v1.5.ckpt \
        s3://<bucket>/models/clay-v1.5.ckpt

It does NOT change bucket policy or ACLs: the object stays private (AWS-13). Grant the WorkSpace
read access with IAM, not by making the bucket public — see the runbook the assistant gave you.
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path


class _Progress:
    def __init__(self, total: int):
        self.total, self.seen, self.lock = total, 0, threading.Lock()

    def __call__(self, n: int):
        with self.lock:
            self.seen += n
            pct = 100 * self.seen / self.total if self.total else 100
            mb = 1024 * 1024
            sys.stdout.write(f"\r  {self.seen / mb:,.0f} / {self.total / mb:,.0f} MiB ({pct:4.1f}%)")
            sys.stdout.flush()


def main(argv=None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 2 or not args[1].startswith("s3://"):
        print("usage: upload_to_s3.py <local-file> s3://<bucket>/<key>", file=sys.stderr)
        return 2
    local, url = Path(args[0]), args[1]
    if not local.is_file():
        print(f"not a file: {local}", file=sys.stderr)
        return 1
    bucket, _, key = url.removeprefix("s3://").partition("/")
    if not bucket or not key:
        print(f"bad S3 url (need s3://bucket/key): {url}", file=sys.stderr)
        return 1

    import boto3
    from boto3.s3.transfer import TransferConfig

    size = local.stat().st_size
    s3 = boto3.client("s3")
    print(f"uploading {local} ({size / (1024 * 1024):,.0f} MiB) -> {url}")
    # 64 MiB parts, a few in flight: robust for multi-GB files on an ordinary connection.
    cfg = TransferConfig(multipart_threshold=64 * 1024 * 1024, multipart_chunksize=64 * 1024 * 1024,
                         max_concurrency=4, use_threads=True)  # fmt: skip
    try:
        s3.upload_file(str(local), bucket, key, Config=cfg, Callback=_Progress(size))
    except Exception as e:  # noqa: BLE001 -- surface the AWS error plainly, no traceback spew
        print(f"\nupload failed: {type(e).__name__}: {str(e)[:300]}", file=sys.stderr)
        return 1
    print(f"\ndone. object: {url}")
    print("verify:  aws s3api head-object --bucket "
          f"{bucket} --key {key}  (or the console)")  # fmt: skip
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
