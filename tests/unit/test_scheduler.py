"""INFRA-05 — scheduler tests: BlockingScheduler PID 1, CronTrigger UTC,
first-tick-on-boot (D-07), kill-switch integration (INFRA-09), and
cycle_id/dry_run contextvar binding (INFRA-07/INFRA-10).

Tests do NOT start the scheduler (it blocks). They exercise ``build_scheduler``
by inspection and ``run_cycle`` as a pure function.
"""

from __future__ import annotations

import io
import json
import logging
from datetime import UTC, datetime, timedelta

import pytest
from apscheduler.triggers.cron import CronTrigger

from tech_news_synth import scheduler as scheduler_mod
from tech_news_synth.config import Settings, load_settings
from tech_news_synth.logging import configure_logging, get_logger
from tech_news_synth.scheduler import build_scheduler, run_cycle


@pytest.fixture
def settings(monkeypatch_env) -> Settings:
    return load_settings()


@pytest.fixture
def capture_logs(settings, monkeypatch):
    """Reconfigure logging with an in-memory stream handler."""
    configure_logging(settings)
    root = logging.getLogger()
    stream = io.StringIO()
    # Reuse an existing formatter so lines are JSON.
    formatter = root.handlers[0].formatter
    buf_handler = logging.StreamHandler(stream)
    buf_handler.setFormatter(formatter)
    root.addHandler(buf_handler)
    try:
        yield stream
    finally:
        root.removeHandler(buf_handler)


def _parse_json_lines(text: str) -> list[dict]:
    return [json.loads(line) for line in text.strip().splitlines() if line.strip()]


def test_build_scheduler_utc_and_single_job(settings: Settings) -> None:
    sched = build_scheduler(settings)
    assert str(sched.timezone) in ("UTC", "UTC+00:00", "utc")
    jobs = sched.get_jobs()
    assert len(jobs) == 1
    job = jobs[0]
    assert job.id == "run_cycle"
    assert isinstance(job.trigger, CronTrigger)
    hour_field = next(f for f in job.trigger.fields if f.name == "hour")
    assert "*/2" in str(hour_field)


def test_first_tick_on_boot(settings: Settings) -> None:
    """D-07: next_run_time is ~= now at registration."""
    before = datetime.now(UTC)
    sched = build_scheduler(settings)
    after = datetime.now(UTC)
    job = sched.get_jobs()[0]
    assert job.next_run_time is not None
    assert before - timedelta(seconds=1) <= job.next_run_time <= after + timedelta(seconds=1)


def test_interval_respected(monkeypatch_env, monkeypatch) -> None:
    monkeypatch.setenv("INTERVAL_HOURS", "6")
    s = load_settings()
    sched = build_scheduler(s)
    job = sched.get_jobs()[0]
    hour_field = next(f for f in job.trigger.fields if f.name == "hour")
    assert "*/6" in str(hour_field)


def test_cycle_skipped_when_paused(
    settings: Settings, capture_logs: io.StringIO, monkeypatch
) -> None:
    """INFRA-09 integration: when is_paused returns True, log a single
    cycle_skipped line with status=paused and paused_by set."""
    monkeypatch.setattr(scheduler_mod, "is_paused", lambda s: (True, "env"))

    run_cycle(settings)

    lines = _parse_json_lines(capture_logs.getvalue())
    skip_lines = [ln for ln in lines if ln.get("event") == "cycle_skipped"]
    assert len(skip_lines) == 1
    assert skip_lines[0]["status"] == "paused"
    assert skip_lines[0]["paused_by"] == "env"
    # No cycle_start/cycle_end when paused (zero I/O invariant).
    assert not any(ln.get("event") == "cycle_start" for ln in lines)
    assert not any(ln.get("event") == "cycle_end" for ln in lines)


def test_run_cycle_writes_run_log_on_success(settings: Settings, mock_db_in_scheduler) -> None:
    """STORE-05: run_cycle calls start_cycle + finish_cycle(status='ok') and
    closes the session on success."""
    session_factory, session, start, finish = mock_db_in_scheduler

    run_cycle(settings)

    session_factory.assert_called_once()
    start.assert_called_once()
    finish.assert_called_once()
    # finish_cycle invoked with status='ok' for a clean cycle.
    _, finish_kwargs = finish.call_args
    assert finish_kwargs.get("status") == "ok"
    # Session committed twice (start + finish) and closed once.
    assert session.commit.call_count == 2
    session.close.assert_called_once()


def test_run_cycle_writes_run_log_on_error(
    settings: Settings, mock_db_in_scheduler, monkeypatch
) -> None:
    """STORE-05 + INFRA-08: even when body raises, finish_cycle must run with
    status='error' and the session must close."""

    def _boom(_settings: Settings) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(scheduler_mod, "_run_cycle_body", _boom)
    _, session, start, finish = mock_db_in_scheduler

    run_cycle(settings)  # must not propagate

    start.assert_called_once()
    finish.assert_called_once()
    _, finish_kwargs = finish.call_args
    assert finish_kwargs.get("status") == "error"
    session.close.assert_called_once()


def test_run_cycle_skips_run_log_when_paused(
    settings: Settings, monkeypatch, mock_db_in_scheduler
) -> None:
    """INFRA-09: paused cycles perform zero I/O — no SessionLocal, no run_log."""
    monkeypatch.setattr(scheduler_mod, "is_paused", lambda s: (True, "env"))
    session_factory, _, start, finish = mock_db_in_scheduler

    run_cycle(settings)

    session_factory.assert_not_called()
    start.assert_not_called()
    finish.assert_not_called()


# ---------------------------------------------------------------------------
# Phase 4 wiring: http_client + run_ingest + counts propagation
# ---------------------------------------------------------------------------
def test_run_cycle_calls_run_ingest_with_counts(
    settings: Settings, mock_db_in_scheduler, mocker
) -> None:
    """run_cycle builds http_client, invokes run_ingest, forwards counts to
    finish_cycle, and closes the client even on clean exit."""
    _, _, _, finish = mock_db_in_scheduler
    fake_counts = {
        "articles_fetched": {"x": 1},
        "articles_upserted": 1,
        "sources_ok": 1,
        "sources_error": 0,
        "sources_skipped_disabled": 0,
    }
    run_ingest = mocker.patch("tech_news_synth.scheduler.run_ingest", return_value=fake_counts)
    fake_client = mocker.MagicMock(name="http_client")
    build = mocker.patch("tech_news_synth.scheduler.build_http_client", return_value=fake_client)
    sources_config = mocker.MagicMock(name="sources_config")

    run_cycle(settings, sources_config=sources_config)

    build.assert_called_once()
    run_ingest.assert_called_once()
    # run_ingest(session, sources_config, client, settings)
    call_args = run_ingest.call_args
    assert call_args.args[1] is sources_config
    assert call_args.args[2] is fake_client
    assert call_args.args[3] is settings
    fake_client.close.assert_called_once()

    # Counts forwarded to finish_cycle.
    _, finish_kwargs = finish.call_args
    assert finish_kwargs["counts"] == fake_counts
    assert finish_kwargs["status"] == "ok"


def test_run_cycle_closes_http_client_on_error(
    settings: Settings, mock_db_in_scheduler, mocker
) -> None:
    """Even when run_ingest raises, http_client.close() must fire."""
    _, _, _, finish = mock_db_in_scheduler
    mocker.patch("tech_news_synth.scheduler.run_ingest", side_effect=RuntimeError("boom"))
    fake_client = mocker.MagicMock(name="http_client")
    mocker.patch("tech_news_synth.scheduler.build_http_client", return_value=fake_client)
    sources_config = mocker.MagicMock(name="sources_config")

    run_cycle(settings, sources_config=sources_config)  # must not propagate

    fake_client.close.assert_called_once()
    _, finish_kwargs = finish.call_args
    assert finish_kwargs["status"] == "error"
    # Counts default to {} on error (run_ingest didn't return).
    assert finish_kwargs["counts"] == {}


def test_paused_cycle_does_not_build_http_client(
    settings: Settings, mock_db_in_scheduler, mocker, monkeypatch
) -> None:
    """INFRA-09 regression: paused cycles build no http client, no session."""
    monkeypatch.setattr(scheduler_mod, "is_paused", lambda s: (True, "env"))
    build = mocker.patch("tech_news_synth.scheduler.build_http_client")
    run_ingest = mocker.patch("tech_news_synth.scheduler.run_ingest")
    sources_config = mocker.MagicMock(name="sources_config")

    run_cycle(settings, sources_config=sources_config)

    build.assert_not_called()
    run_ingest.assert_not_called()


def test_contextvars_bound_and_cleared(
    monkeypatch_env, monkeypatch, capture_logs: io.StringIO
) -> None:
    """INFRA-07 / INFRA-10: every log line during the cycle carries cycle_id
    and dry_run; after the cycle, contextvars are cleared."""
    monkeypatch.setenv("DRY_RUN", "1")
    s = load_settings()

    run_cycle(s)

    log = get_logger(__name__)
    log.info("post_cycle_line")

    lines = _parse_json_lines(capture_logs.getvalue())
    in_cycle = [ln for ln in lines if ln.get("event") in ("cycle_start", "cycle_end")]
    assert in_cycle, "expected cycle_start / cycle_end lines"
    for ln in in_cycle:
        assert "cycle_id" in ln
        assert len(ln["cycle_id"]) == 26
        assert ln["dry_run"] is True

    post = [ln for ln in lines if ln.get("event") == "post_cycle_line"]
    assert post, "expected post_cycle_line in captured output"
    # contextvars must have been cleared.
    assert "cycle_id" not in post[-1]
