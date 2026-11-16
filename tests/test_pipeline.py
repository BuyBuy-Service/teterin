"""Часть A: ретраи HTTP на 429/таймауты и демо-режим сбоев."""
import pytest
import requests

import pipeline


class FakeResp:
    def __init__(self, status, headers=None):
        self.status_code, self.headers = status, headers or {}

    def raise_for_status(self):
        raise requests.HTTPError(f"HTTP {self.status_code}")


def test_retry_after_429_then_success(monkeypatch):
    answers = iter([FakeResp(429, {"Retry-After": "1"}), FakeResp(503), FakeResp(200)])
    monkeypatch.setattr(requests, "get", lambda *a, **k: next(answers))
    run = pipeline.Run("t", "t", {}, "manual")
    assert pipeline.http_get("http://x", run).status_code == 200
    assert run.stats["http_calls"] == 3 and run.stats["retries"] == 2


def test_timeout_gives_up_with_clear_error(monkeypatch):
    def boom(*a, **k):
        raise requests.Timeout()
    monkeypatch.setattr(requests, "get", boom)
    with pytest.raises(pipeline.SourceError, match="попыток"):
        pipeline.http_get("http://x")


def test_client_error_not_retried(monkeypatch):
    calls = []
    monkeypatch.setattr(requests, "get", lambda *a, **k: calls.append(1) or FakeResp(400))
    with pytest.raises(requests.HTTPError):
        pipeline.http_get("http://x")
    assert len(calls) == 1


def test_failed_job_is_logged_and_does_not_raise(monkeypatch):
    monkeypatch.setenv("AERO_FAULT", "timeout")
    from sources import openmeteo
    r = openmeteo.ingest()
    assert r.status == "failed" and "Timeout" in r.error
    from db import connect
    with connect() as con:
        row = con.execute("SELECT status, retries FROM load_log WHERE id = ?", (r.id,)).fetchone()
    assert row["status"] == "failed" and row["retries"] == 3
