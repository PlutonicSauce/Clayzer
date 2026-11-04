"""Where Chips, Cases, and Runs live: local folders by default, or an S3 bucket.

Keys are the same either way (caption-plan.md §5.3):

    chips/<chip-id>.png, chips/<chip-id>.json
    cases/caption-<region>.jsonl            Reference Labels: never read by the Harness
    batches/<batch-id>/...

Set CLAYZER_STORE=s3://<bucket>/<prefix> to use S3. Locally, `batches/` maps to the batches
folder and everything else to the data folder.
"""

from pathlib import Path


class LocalStore:
    def __init__(self, data_dir: Path, batches_dir: Path):
        self.data_dir, self.batches_dir = data_dir, batches_dir

    def _path(self, key: str) -> Path:
        if key.startswith("batches/"):
            return self.batches_dir / key.removeprefix("batches/")
        return self.data_dir / key

    def list_dirs(self, prefix: str) -> list[str]:
        """Names of the immediate sub-folders under a key prefix such as `batches/`."""
        root = self._path(prefix)
        return [p.name for p in root.iterdir() if p.is_dir()] if root.exists() else []

    def url(self, key: str) -> str:
        return str(self._path(key))

    def exists(self, key: str) -> bool:
        return self._path(key).exists()

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def put(self, key: str, body: bytes, content_type: str | None = None) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)


class S3Store:
    def __init__(self, url: str, client=None):
        bucket, _, prefix = url.removeprefix("s3://").partition("/")
        self.bucket, self.prefix = bucket, prefix.strip("/")
        import boto3

        self.s3 = client if client is not None else boto3.client("s3")

    def _key(self, key: str) -> str:
        return f"{self.prefix}/{key}" if self.prefix else key

    def url(self, key: str) -> str:
        return f"s3://{self.bucket}/{self._key(key)}"

    def exists(self, key: str) -> bool:
        from botocore.exceptions import ClientError

        try:
            self.s3.head_object(Bucket=self.bucket, Key=self._key(key))
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] in ("404", "NoSuchKey", "NotFound"):
                return False
            raise

    def get(self, key: str) -> bytes:
        with self.s3.get_object(Bucket=self.bucket, Key=self._key(key))["Body"] as body:
            return body.read()

    def put(self, key: str, body: bytes, content_type: str | None = None) -> None:
        extra = {"ContentType": content_type} if content_type else {}
        self.s3.put_object(Bucket=self.bucket, Key=self._key(key), Body=body, **extra)

    def delete(self, key: str) -> None:
        self.s3.delete_object(Bucket=self.bucket, Key=self._key(key))

    def list_dirs(self, prefix: str) -> list[str]:
        pages = self.s3.get_paginator("list_objects_v2").paginate(
            Bucket=self.bucket, Prefix=self._key(prefix), Delimiter="/"
        )
        return [
            p["Prefix"].rstrip("/").rsplit("/", 1)[-1]
            for page in pages
            for p in page.get("CommonPrefixes", [])
        ]


Store = LocalStore | S3Store


def open_store(url: str | None, data_dir: Path, batches_dir: Path) -> Store:
    return S3Store(url) if url and url.startswith("s3://") else LocalStore(data_dir, batches_dir)
