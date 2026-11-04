"""The work board: every done task says where to see it and what code changed."""

from pathlib import Path

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
