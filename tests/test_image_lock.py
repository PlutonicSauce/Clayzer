"""The web app image installs from requirements.lock, so the lock must cover what it needs."""

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).parents[1]


def _name(requirement: str) -> str:
    return re.split(r"[<>=!~;\[ ]", requirement, maxsplit=1)[0].lower().replace("_", "-")


def test_the_image_lock_has_every_runtime_and_ui_dependency():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    needed = {_name(r) for r in project["dependencies"] + project["optional-dependencies"]["ui"]}
    lock = (ROOT / "requirements.lock").read_text()
    locked = {m.lower().replace("_", "-") for m in re.findall(r"(?m)^([A-Za-z0-9_.-]+)==", lock)}
    missing = sorted(needed - locked)
    assert not missing, (
        f"requirements.lock is missing {missing}: run "
        "`uv export --frozen --extra ui --no-dev --no-emit-project -o requirements.lock`"
    )
