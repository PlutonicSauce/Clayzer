import json

from fastapi.testclient import TestClient
from test_loop import env, run  # noqa: F401

from clayzer import batch
from clayzer.cases import to_jsonl
from clayzer.run_report import run_keys
from clayzer.trace import dumps, loads, trace_key
from clayzer.ui.app import create_app


def test_reports_escape_untrusted_caption_and_trace_and_redact_secrets(env):  # noqa: F811
    b = run(env, repeats=1)
    store = env[0]
    bid = b["config"].batch_id
    r = b["results"][0]
    cap = b["captions"][0]
    cap["text"] = "<img src=x onerror=alert(1)> API_KEY=private-value"
    store.put(f"batches/{bid}/captions.jsonl", to_jsonl(b["captions"]))
    key = trace_key(bid, r["case_id"], r["repeat"])
    info, steps = loads(store.get(key))
    steps[0].output = {
        "authorization": "private-value",
        "headers": {"Authorization": "Basic cHJpdmF0ZS12YWx1ZQ=="},
        "raw": "<script>attack()</script>",
        "url": "https://example.com/image?X-Amz-Signature=private-value",
    }
    store.put(key, dumps(info, steps))
    before = store.get(key)
    batch.write_reports(store, bid)
    hkey, jkey = run_keys(bid, r["case_id"], r["repeat"])
    for name in (hkey, jkey, f"batches/{bid}/report.html", f"batches/{bid}/report.md"):
        body = store.get(name).decode()
        assert "private-value" not in body
        if name.endswith(".html"):
            assert "<img src=x onerror=" not in body and "<script>attack()" not in body
    assert "&lt;script&gt;attack()" in store.get(hkey).decode()
    assert json.loads(store.get(jkey))["caption"]["text"].endswith("[REDACTED]")
    assert store.get(key) == before
    client = TestClient(create_app(env[1]))
    for path in (
        f"/api/batches/{bid}/traces/{r['case_id']}--r1.jsonl",
        f"/api/batches/{bid}/files/traces/{r['case_id']}--r1.jsonl",
    ):
        response = client.get(path)
        assert response.status_code == 200
        assert "private-value" not in response.text and "cHJpdmF0ZS12YWx1ZQ==" not in response.text
