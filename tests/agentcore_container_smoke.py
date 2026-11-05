"""Run inside the Batch Runtime image, offline, with no AWS credentials or mounted data."""

import importlib.util
import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from clayzer.agentcore.runtime import Handler, ToolboxCache
from clayzer.ontology import load


def main():
    assert load().claimable()
    for module in ("batch", "grounding", "answer_keys", "ui"):
        assert importlib.util.find_spec(f"clayzer.{module}") is None
    assert not Path("/app/fixtures").exists()
    Handler.client, Handler.cache = object(), ToolboxCache()
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}"
    try:
        with urllib.request.urlopen(url + "/ping", timeout=5) as response:
            assert json.load(response)["status"] == "Healthy"
        request = urllib.request.Request(
            url + "/invocations",
            data=b'{"unknown":"field"}',
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            assert json.load(response)["error"]["kind"] == "contract"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)
    print("Batch Runtime image: isolation, ontology, health, and contract checks passed")


if __name__ == "__main__":
    main()
