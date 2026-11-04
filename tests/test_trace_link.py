import json

import pytest
from test_loop import env, run  # noqa: F401

from clayzer import batch
from clayzer.replay import replay
from clayzer.trace import dumps, loads, trace_key
from clayzer.trace_link import xray_link

CONTEXT = {
    "otel": {
        "trace_id": "0123456789abcdef0123456789abcdef",
        "aws_region": "us-west-2",
        "exported_to": "xray",
    }
}


def test_exported_trace_link_requires_context_and_valid_id():
    nav = xray_link(CONTEXT)
    assert nav["url"].endswith("/traces/1-01234567-89abcdef0123456789abcdef")
    assert nav["url"].startswith("https://us-west-2.console.aws.amazon.com/")


@pytest.mark.parametrize(
    "context",
    [
        {},
        {"trace_id": "0" * 32, "aws_region": "us-west-2", "exported_to": "xray"},
        {"trace_id": "<script>", "aws_region": "us-west-2", "exported_to": "xray"},
        {"trace_id": "0123456789abcdef0123456789abcdef", "exported_to": "xray"},
        {
            "trace_id": "0123456789abcdef0123456789abcdef",
            "aws_region": 'us-west-2" onclick="bad',
            "exported_to": "xray",
        },
    ],
)
def test_missing_or_malformed_export_is_unavailable(context):
    assert xray_link({"otel": context})["url"] is None


def test_trace_context_survives_reports_and_replay_without_aws(env, tmp_path):  # noqa: F811
    from pathlib import Path

    b = run(env, repeats=1)
    store = env[0]
    bid = b["config"].batch_id
    r = b["results"][0]
    key = trace_key(bid, r["case_id"], 1)
    info, steps = loads(store.get(key))
    info.metadata.update(CONTEXT)
    store.put(key, dumps(info, steps))
    batch.write_reports(store, bid)
    target = replay(
        Path(store.url(f"batches/{bid}")), data=store.data_dir, output=tmp_path / "replay"
    )
    page = target / "batches" / bid / "runs" / f"{r['case_id']}--r1.html"
    record = json.loads(page.with_suffix(".json").read_text())
    assert record["trace_navigation"] == xray_link(CONTEXT)
    assert xray_link(CONTEXT)["url"] in page.read_text()
    assert (
        "no recorded X-Ray export context"
        in (page.parent / f"{b['results'][1]['case_id']}--r1.html").read_text()
    )
