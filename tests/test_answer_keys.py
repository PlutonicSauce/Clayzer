"""The Answer Key clients ride out the public APIs' bursts of 502s and timeouts."""

import httpx
import pytest

from clayzer import answer_keys as ak


@pytest.fixture
def calls(monkeypatch):
    monkeypatch.setattr(ak.time, "sleep", lambda s: None)
    seen, script = [], []

    def get(url, **kw):
        seen.append(url)
        step = script.pop(0)
        if isinstance(step, Exception):
            raise step
        return httpx.Response(step, json=[{"case_id": 1}], request=httpx.Request("GET", url))

    monkeypatch.setattr(ak.httpx, "get", get)
    return seen, script


def test_usgs_requests_retry_502s_and_timeouts(calls):
    seen, script = calls
    script += [502, httpx.ConnectTimeout("slow"), 200]
    assert ak._get(ak.USWTDB, []) == [{"case_id": 1}]
    assert len(seen) == 3


def test_usgs_requests_give_up_after_four_tries(calls):
    seen, script = calls
    script += [502] * 4
    with pytest.raises(httpx.HTTPStatusError):
        ak._get(ak.USWTDB, [])
    assert len(seen) == 4


def test_a_client_error_is_not_retried(calls):
    seen, script = calls
    script += [404]
    with pytest.raises(httpx.HTTPStatusError):
        ak._get(ak.USWTDB, [])
    assert len(seen) == 1
