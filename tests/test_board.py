"""The work board: every done task says where to see it and what code changed."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from clayzer.ui.app import load_tasks

ROOT = Path(__file__).parents[1]


def test_every_done_task_says_what_was_delivered():
    for t in load_tasks():
        if t["status"] != "done":
            continue
        assert t.get("see_it"), f"{t['id']} is done but has no see_it"
        assert t.get("changes"), f"{t['id']} is done but has no changes"
        for change in t["changes"]:
            path, sep, what = change.partition(": ")
            assert sep and what, f"{t['id']}: {change!r} should be '<path>: what changed'"
            assert (ROOT / path).exists(), f"{t['id']}: {path} doesn't exist"


def test_gate_completion_keeps_real_validation_and_the_proposer_open():
    tasks = {t["id"]: t for t in load_tasks()}
    gate = [t for t in tasks.values() if t["step"] == "gate"]
    implementation = [t for t in gate if t.get("completion_scope") != "follow-up"]
    assert {t["id"] for t in implementation} == {"prompt-loop", "gate-rule", "gate-policy"}
    assert all(t["status"] == "done" for t in implementation)
    for name in ("prompt-improvement-validation", "proposer"):
        assert tasks[name]["completion_scope"] == "follow-up"
        assert tasks[name]["status"] == "todo"
    assert tasks["batch-inference"]["after"] == ["prompt-improvement-validation"]
    assert all(
        t.get("completion_scope", "implementation") in {"implementation", "follow-up"}
        for t in tasks.values()
    )


def test_actual_step_rollup_does_not_hide_an_unfinished_implementation():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is needed to execute the browser's status calculation")
    script = r"""
const fs = require("node:fs");
const vm = require("node:vm");
const source = fs.readFileSync("src/clayzer/ui/static/app.js", "utf8");
const start = source.indexOf("function stepState(");
const end = source.indexOf("// ── Pages", start);
const tasks = JSON.parse(fs.readFileSync(0, "utf8"));
const context = vm.createContext({tasks});
vm.runInContext(source.slice(start, end), context);
const state = () => vm.runInContext('stepState({key:"gate"}, tasks)[0]', context);
const completed = state();
tasks.find(t => t.id === "gate-policy").status = "doing";
const pending = state();
tasks.filter(t => t.completion_scope === "follow-up").forEach(t => t.status = "done");
console.log(JSON.stringify([completed, pending, state()]));
"""
    result = subprocess.run(
        [node, "-e", script],
        input=json.dumps(load_tasks()),
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(result.stdout) == ["built", "partly built", "partly built"]
