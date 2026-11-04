"""Spoken summaries of a Batch (listen.py), offline: fake Bedrock and a fake Polly."""

import io
import json

from fastapi.testclient import TestClient
from test_loop import env, run  # noqa: F401

from clayzer.gate import accept_baseline, load_baseline
from clayzer.listen import (
    audio_key,
    code_script,
    facts,
    listen,
    script_key,
    spoken_case,
    unsupported_numbers,
)
from clayzer.ui.app import create_app


class FakePolly:
    def __init__(self):
        self.calls = []

    def synthesize_speech(self, **kw):
        self.calls.append(kw)
        return {"AudioStream": io.BytesIO(b"ID3 fake mp3 of: " + kw["Text"].encode())}


class FakeWriter:
    """Bedrock for the script only: returns `text`, or raises when it's an exception."""

    def __init__(self, text):
        self.text, self.calls = text, 0

    def converse(self, **kw):
        self.calls += 1
        if isinstance(self.text, Exception):
            raise self.text
        return {"output": {"message": {"content": [{"text": self.text}]}}, "usage": {}}


def test_case_ids_are_read_as_words():
    assert spoken_case("fixed-dev-uspvdb-400117") == "the solar site number 400117"
    assert spoken_case("fixed-test-uswtdb-3072695") == "the wind site number 3072695"
    assert spoken_case("fixed-dev-neg-4") == "the negative site number 4"
    assert spoken_case("change-dev-uspvdb-9") == "the solar site image pair number 9"
    assert spoken_case("fixed-dev-solar") == "the solar site"


def test_a_batch_without_a_baseline_is_summarized_without_a_verdict(env):  # noqa: F811
    store, _, _ = env
    b = run(env, "base")
    polly = FakePolly()
    rec = listen(store, b["config"].batch_id, None, None, polly, progress=lambda _: None)
    assert rec["source"] == "code" and rec["verdict"] is None
    assert "2 places, 3 times each" in rec["text"]
    assert "no Baseline" in rec["text"]
    assert store.get(audio_key(b["config"].batch_id)).startswith(b"ID3")
    assert polly.calls[0]["OutputFormat"] == "mp3"


def test_a_failed_gate_is_spoken_with_the_places_that_dropped(env):  # noqa: F811
    store, settings, _ = env
    accept_baseline(run(env, "base"), settings.baselines_dir)
    cand = run(env, "worse", wrong=True)
    rec = listen(store, cand["config"].batch_id, load_baseline(settings.baselines_dir), None,
                 FakePolly(), progress=lambda _: None)  # fmt: skip
    assert rec["verdict"] == "fail"
    assert "failed the regression gate" in rec["text"]
    assert "dropped at the solar site" in rec["text"]
    assert "fixed-dev" not in rec["text"]  # no ids read aloud
    assert "down" in rec["text"]


def test_the_saved_summary_is_replayed_until_the_facts_change(env):  # noqa: F811
    store, settings, _ = env
    b = run(env, "base")
    bid = b["config"].batch_id
    polly = FakePolly()
    first = listen(store, bid, None, None, polly, progress=lambda _: None)
    again = listen(store, bid, None, None, polly, progress=lambda _: None)
    assert first["written"] and not again["written"]
    assert len(polly.calls) == 1
    # A Baseline changes what can be said, so it's made again.
    accept_baseline(b, settings.baselines_dir)
    third = listen(store, bid, load_baseline(settings.baselines_dir), None, polly,
                   progress=lambda _: None)  # fmt: skip
    assert third["written"] and len(polly.calls) == 2
    assert "is the current Baseline" in third["text"]
    assert third["verdict"] is None


def test_the_model_script_is_used_only_when_its_numbers_are_in_the_facts(env):  # noqa: F811
    store, _, _ = env
    bid = run(env, "base")["config"].batch_id
    good = FakeWriter("We tested 2 places 3 times each. Correctness was 100 out of 100.")
    rec = listen(store, bid, None, good, FakePolly(), force=True, progress=lambda _: None)
    assert rec["source"] == "model" and rec["text"].startswith("We tested 2 places")

    said = []
    invented = FakeWriter("We tested 2 places. Correctness was 87 out of 100.")
    rec = listen(store, bid, None, invented, FakePolly(), force=True, progress=said.append)
    assert rec["source"] == "code"
    assert "87" in said[0]

    down = FakeWriter(RuntimeError("no Bedrock"))
    rec = listen(store, bid, None, down, FakePolly(), force=True, progress=lambda _: None)
    assert rec["source"] == "code"


def test_the_code_script_only_states_numbers_from_the_facts(env):  # noqa: F811
    _, settings, _ = env
    accept_baseline(run(env, "base"), settings.baselines_dir)
    cand = run(env, "worse", wrong=True)
    f = facts(cand, load_baseline(settings.baselines_dir))
    assert unsupported_numbers(code_script(f), f) == []


def test_the_web_app_plays_the_saved_summary(env):  # noqa: F811
    store, settings, _ = env
    bid = run(env, "base")["config"].batch_id
    c = TestClient(create_app(settings))
    assert c.get(f"/api/batches/{bid}/listen").status_code == 404
    listen(store, bid, None, None, FakePolly(), progress=lambda _: None)
    body = c.get(f"/api/batches/{bid}/listen").json()
    assert body["text"] == json.loads(store.get(script_key(bid)))["text"]
    audio = c.get(f"/api/batches/{bid}/listen.mp3")
    assert audio.headers["content-type"] == "audio/mpeg"
    assert audio.content.startswith(b"ID3")


def test_a_failed_summary_after_a_batch_is_reported_not_raised(env, monkeypatch):  # noqa: F811
    from clayzer import listen as listen_mod

    store, settings, _ = env
    bid = run(env, "base")["config"].batch_id

    def no_polly():
        raise RuntimeError("Polly is denied")

    monkeypatch.setattr(listen_mod, "polly", no_polly)
    said = []
    assert listen_mod.after_batch(store, settings, bid, progress=said.append) is None
    assert "spoken summary skipped" in said[0] and f"clayzer listen {bid}" in said[0]
    assert not store.exists(audio_key(bid))
