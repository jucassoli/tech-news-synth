"""INFRA-08 — unhandled exceptions inside run_cycle do NOT propagate and do
NOT stop the scheduler. The EVENT_JOB_ERROR listener logs as a safety net."""

from __future__ import annotations

import io
import json
import logging
from unittest.mock import MagicMock

import pytest

from tech_news_synth import scheduler as scheduler_mod
from tech_news_synth.config import Settings, load_settings
from tech_news_synth.logging import configure_logging
from tech_news_synth.scheduler import _job_error_listener, run_cycle


@pytest.fixture
def settings(monkeypatch_env) -> Settings:
    return load_settings()


@pytest.fixture
def capture_logs(settings):
    configure_logging(settings)
    root = logging.getLogger()
    stream = io.StringIO()
    formatter = root.handlers[0].formatter
    h = logging.StreamHandler(stream)
    h.setFormatter(formatter)
    root.addHandler(h)
    try:
        yield stream
    finally:
        root.removeHandler(h)


def _parse(text: str) -> list[dict]:
    return [json.loads(line) for line in text.strip().splitlines() if line.strip()]


def test_cycle_body_exception_isolated(
    settings: Settings, capture_logs: io.StringIO, monkeypatch
) -> None:
    """Inject a raising cycle body via _run_cycle_body; run_cycle must not propagate."""

    def _boom(_settings: Settings) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(scheduler_mod, "_run_cycle_body", _boom)

    # Must not raise.
    run_cycle(settings)

    lines = _parse(capture_logs.getvalue())
    errs = [ln for ln in lines if ln.get("event") == "cycle_error"]
    assert len(errs) >= 1
    # Stacktrace + exception info should be present.
    dumped = json.dumps(errs[0])
    assert "boom" in dumped
    assert "Traceback" in dumped or "RuntimeError" in dumped


def test_scheduler_keeps_ticking_after_error(settings: Settings, monkeypatch) -> None:
    """After a raising body, a subsequent invocation runs normally."""
    calls = {"n": 0}

    def _maybe_boom(_settings: Settings) -> None:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("first-only")
        # second+ run is a no-op

    monkeypatch.setattr(scheduler_mod, "_run_cycle_body", _maybe_boom)

    run_cycle(settings)
    run_cycle(settings)

    assert calls["n"] == 2  # second tick fired despite first-tick exception


def test_job_error_listener_logs(capture_logs: io.StringIO) -> None:
    """Belt-and-suspenders EVENT_JOB_ERROR listener logs the failure."""
    event = MagicMock()
    event.exception = RuntimeError("listener-path")
    event.traceback = "Traceback (most recent call last):\n  ...\nRuntimeError: listener-path"
    event.job_id = "run_cycle"

    _job_error_listener(event)

    lines = _parse(capture_logs.getvalue())
    matches = [ln for ln in lines if ln.get("event") == "scheduler_job_error"]
    assert len(matches) == 1
    assert "listener-path" in matches[0].get("exception", "")
    assert matches[0].get("job_id") == "run_cycle"
