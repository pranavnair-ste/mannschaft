import io
import socket
import urllib.error

import pytest

from pi_harness.observability import bridge


def _http_error(code):
    return urllib.error.HTTPError("u", code, "msg", {}, io.BytesIO(b""))


def test_is_retryable_classification():
    assert bridge._is_retryable(_http_error(503)) is True
    assert bridge._is_retryable(_http_error(429)) is True
    assert bridge._is_retryable(_http_error(400)) is False
    assert bridge._is_retryable(_http_error(401)) is False
    assert bridge._is_retryable(urllib.error.URLError("conn refused")) is True
    assert bridge._is_retryable(socket.timeout()) is True
    assert bridge._is_retryable(ValueError("x")) is False


def test_retry_succeeds_after_transient(monkeypatch):
    calls = {"n": 0}
    slept = []

    def fake_post(envs, url, token, *, timeout=15.0):
        calls["n"] += 1
        if calls["n"] < 3:
            raise urllib.error.URLError("refused")
        return {"ingested": len(envs), "rejected": []}

    monkeypatch.setattr(bridge, "post_events", fake_post)
    out = bridge.post_events_with_retry([{"event_id": "a"}], "http://x", "t",
                                        sleep=slept.append, base_delay=0.5, factor=2.0)
    assert out == {"ingested": 1, "rejected": []}
    assert calls["n"] == 3
    assert slept == [0.5, 1.0]


def test_retry_reraises_permanent_immediately(monkeypatch):
    calls = {"n": 0}

    def fake_post(envs, url, token, *, timeout=15.0):
        calls["n"] += 1
        raise _http_error(401)

    monkeypatch.setattr(bridge, "post_events", fake_post)
    with pytest.raises(urllib.error.HTTPError):
        bridge.post_events_with_retry([{}], "http://x", "t", sleep=lambda s: None)
    assert calls["n"] == 1


def test_retry_exhausts_and_reraises(monkeypatch):
    monkeypatch.setattr(bridge, "post_events",
                        lambda *a, **k: (_ for _ in ()).throw(urllib.error.URLError("x")))
    with pytest.raises(urllib.error.URLError):
        bridge.post_events_with_retry([{}], "http://x", "t", max_attempts=3, sleep=lambda s: None)
