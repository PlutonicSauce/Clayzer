"""Publish complete Baseline directories with a local lock and recoverable replacement.

Readers share the lock with writers. A staged directory is fully written before the old one
is moved aside; an interrupted replacement is recovered on the next read or write. This is
local filesystem coordination, not a transaction spanning S3 and multiple teammates' clones.
"""

import fcntl
import hashlib
import os
import re
import shutil
import tempfile
from contextlib import contextmanager, suppress
from pathlib import Path


def baseline_name(name):
    if (
        not isinstance(name, str)
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,120}", name)
        or ".." in name
    ):
        raise ValueError(
            "Baseline name must be a single safe name, such as 'default' or 'gate-check'"
        )


@contextmanager
def directory(root: Path, name: str):
    baseline_name(name)
    root.mkdir(parents=True, exist_ok=True)
    with (root / ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        target, backup = root / name, root / f".{name}.backup"
        if target.is_symlink() or backup.is_symlink():
            raise ValueError("Baseline directories must not be symbolic links")
        if backup.exists():
            if target.exists():
                with suppress(OSError):
                    shutil.rmtree(backup)
            else:
                os.replace(backup, target)
        yield target


def snapshot(target: Path) -> str:
    digest = hashlib.sha256()
    for name in ("batch.json", "summary.json", "results.jsonl"):
        digest.update(name.encode() + b"\0" + (target / name).read_bytes() + b"\0")
    return digest.hexdigest()


def publish(root: Path, name: str, files: dict[str, str], expected_snapshot: str | None = None):
    baseline_name(name)
    with directory(root, name) as target:
        if expected_snapshot is not None and (
            not target.exists() or snapshot(target) != expected_snapshot
        ):
            raise ValueError("Baseline changed since this experiment was evaluated; evaluate again")
        stage = Path(tempfile.mkdtemp(prefix=f".{name}-", dir=root))
        backup = root / f".{name}.backup"
        try:
            for filename, text in files.items():
                path = stage / filename
                path.write_text(text)
                with path.open("rb") as stream:
                    os.fsync(stream.fileno())
            if target.exists():
                os.replace(target, backup)
            try:
                os.replace(stage, target)
            except BaseException:
                if backup.exists():
                    os.replace(backup, target)
                raise
            # The new directory is complete. If cleanup is interrupted, the next reader
            # recognizes the completed target and removes the backup.
            if backup.exists():
                with suppress(OSError):
                    shutil.rmtree(backup)
        finally:
            if stage.exists():
                shutil.rmtree(stage)
    return target
