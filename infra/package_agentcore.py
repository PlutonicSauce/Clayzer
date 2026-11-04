"""Build an ARM64 Python 3.12 ZIP for AgentCore code deployment."""

import argparse
import hashlib
import json
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "infra/agentcore-requirements.lock"
SKIP = {"__pycache__", "bin"}
INSTALL_METADATA = {"RECORD", "INSTALLER", "REQUESTED", "uv_cache.json", "direct_url.json"}


def write_archive(package: Path, output: Path) -> None:
    """Use stable names, ordering, permissions and timestamps; omit installer-local metadata."""
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(package.rglob("*")):
            relative = path.relative_to(package)
            if not path.is_file() or SKIP.intersection(relative.parts):
                continue
            if path.parent.name.endswith(".dist-info") and path.name in INSTALL_METADATA:
                continue
            info = zipfile.ZipInfo(relative.as_posix(), date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, path.read_bytes(), compresslevel=9)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="clayzer-agentcore-") as directory:
        package = Path(directory)
        subprocess.run(
            [
                "uv",
                "pip",
                "install",
                "--target",
                directory,
                "--python-platform",
                "aarch64-manylinux2014",
                "--python-version",
                "3.12",
                "--only-binary",
                ":all:",
                "--require-hashes",
                "-r",
                str(LOCK),
            ],
            check=True,
        )
        shutil.copytree(
            ROOT / "src/clayzer",
            package / "clayzer",
            ignore=shutil.ignore_patterns("__pycache__", "ui"),
        )
        # AgentCore's code entryPoint accepts at most two elements.
        (package / "entrypoint.py").write_text(
            "import uvicorn\nfrom clayzer.agentcore import create_app\n"
            'if __name__ == "__main__":\n'
            '    uvicorn.run(create_app(), host="0.0.0.0", port=8080)\n'
        )
        source_hashes = {
            str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted((ROOT / "src/clayzer").rglob("*.py"))
            if "ui" not in path.relative_to(ROOT / "src/clayzer").parts
        }
        build = {
            "git_commit": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
            ).strip(),
            "dirty": bool(
                subprocess.check_output(
                    ["git", "status", "--porcelain"], cwd=ROOT, text=True
                ).strip()
            ),
            "source_sha256": source_hashes,
            "lock_sha256": hashlib.sha256(LOCK.read_bytes()).hexdigest(),
        }
        (package / "clayzer/agentcore_build.json").write_text(
            json.dumps(build, sort_keys=True, indent=2) + "\n"
        )
        write_archive(package, args.output)
        args.output.with_suffix(".manifest.json").write_text(
            json.dumps(
                {
                    **build,
                    "zip_sha256": hashlib.sha256(args.output.read_bytes()).hexdigest(),
                },
                sort_keys=True,
                indent=2,
            )
            + "\n"
        )
    print(f"{args.output}: sha256={hashlib.sha256(args.output.read_bytes()).hexdigest()}")


if __name__ == "__main__":
    main()
