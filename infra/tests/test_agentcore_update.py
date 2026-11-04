"""Deployment guards must fail before mutation; readiness must cover the live endpoint."""

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest


@pytest.fixture
def updater(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1]))
    spec = importlib.util.spec_from_file_location(
        "agentcore_update", Path(__file__).parents[1] / "update_agentcore.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_waits_for_the_requested_live_version(updater, monkeypatch):
    control = Mock()
    control.get_agent_runtime.return_value = {"status": "READY"}
    control.get_agent_runtime_endpoint.side_effect = [
        {"status": "READY", "liveVersion": "4"},
        {"status": "READY", "liveVersion": "5"},
    ]
    sleep = Mock()
    monkeypatch.setattr(updater.time, "sleep", sleep)
    updater.wait_ready(control, "runtime", "5")
    sleep.assert_called_once_with(5)


def test_failed_endpoint_does_not_count_as_ready(updater):
    control = Mock()
    control.get_agent_runtime.return_value = {"status": "READY"}
    control.get_agent_runtime_endpoint.return_value = {"status": "FAILED"}
    with pytest.raises(RuntimeError, match="deployment failed"):
        updater.wait_ready(control, "runtime", "5")


@pytest.mark.parametrize("dirty,matched", [(True, True), (False, False)])
def test_invalid_artifacts_fail_before_aws_access(updater, monkeypatch, tmp_path, dirty, matched):
    archive = tmp_path / "runtime.zip"
    archive.write_bytes(b"package")
    archive.with_suffix(".manifest.json").write_text(
        json.dumps(
            {
                "dirty": dirty,
                "zip_sha256": hashlib.sha256(b"package" if matched else b"other").hexdigest(),
            }
        )
    )
    state = tmp_path / "state.json"
    state.write_text("{}")
    session = Mock()
    monkeypatch.setattr(updater.boto3, "Session", session)
    monkeypatch.setattr(sys, "argv", ["update", str(state), str(archive)])
    with pytest.raises(ValueError):
        updater.main()
    session.assert_not_called()
