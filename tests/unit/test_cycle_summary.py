"""Phase 8 OPS-01 / D-04-D-06 — cycle_summary structlog emit unit tests.

Exercises ``scheduler._emit_cycle_summary`` via ``run_cycle``, asserting the
durability invariant (Pitfall 1): the aggregated line appears iff
``session.commit()`` succeeded. All 10 D-06 fields are validated.

Capture pattern: attach an in-memory StreamHandler to the root logger (same
technique as ``test_scheduler.py::capture_logs``). Cannot use
``structlog.testing.capture_logs`` because the project pipeline uses
``wrap_for_formatter`` — ``capture_logs`` bypasses it and yields nothing once
``configure_logging`` has been called.
"""

from __future__ import annotations

import io
import json
import logging

import pytest

from tech_news_synth import scheduler as scheduler_mod
from tech_news_synth.config import Settings, load_settings
from tech_news_synth.logging import configure_logging
from tech_news_synth.publish.models import CapCheckResult, PublishResult
from tech_news_synth.scheduler import run_cycle


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def settings(monkeypatch_env) -> Settings:
    return load_settings()


@pytest.fixture
def captured_stream(settings):
    """In-memory log stream (JSON lines) — mirrors test_scheduler.capture_logs."""
    configure_logging(settings)
    root = logging.getLogger()
    stream = io.StringIO()
    formatter = root.handlers[0].formatter
    buf_handler = logging.StreamHandler(stream)
    buf_handler.setFormatter(formatter)
    root.addHandler(buf_handler)
    try:
        yield stream
    finally:
        root.removeHandler(buf_handler)


def _parse(stream: io.StringIO) -> list[dict]:
    return [json.loads(line) for line in stream.getvalue().strip().splitlines() if line.strip()]


def _canned_selection(mocker):
    return mocker.MagicMock(
        winner_cluster_id=42,
        winner_article_ids=[1],
        fallback_article_id=None,
        counts_patch={
            "articles_in_window": 10,
            "cluster_count": 3,
            "singleton_count": 1,
            "chosen_cluster_id": 42,
            "rejected_by_antirepeat": [],
            "fallback_used": False,
            "fallback_article_id": None,
        },
    )


def _patch_synth(mocker):
    mocker.patch("tech_news_synth.scheduler.anthropic.Anthropic")
    mocker.patch(
        "tech_news_synth.scheduler.load_hashtag_allowlist",
        return_value=mocker.MagicMock(name="allowlist"),
    )
    synth_result = mocker.MagicMock(
        status="pending",
        counts_patch={
            "synth_attempts": 1,
            "synth_truncated": False,
            "synth_input_tokens": 100,
            "synth_output_tokens": 40,
            "synth_cost_usd": 0.000038,
            "char_budget_used": 223,  # Phase 8 OPS-01
            "post_id": 7,
        },
    )
    return mocker.patch("tech_news_synth.scheduler.run_synthesis", return_value=synth_result)


def _phase7_mocks(mocker):
    mocker.patch("tech_news_synth.scheduler.cleanup_stale_pending", return_value=0)
    mocker.patch(
        "tech_news_synth.scheduler.check_caps",
        return_value=CapCheckResult(
            daily_count=0,
            daily_reached=False,
            monthly_cost_usd=0.0,
            monthly_cost_reached=False,
            skip_synthesis=False,
        ),
    )
    mocker.patch(
        "tech_news_synth.scheduler.build_x_client",
        return_value=mocker.MagicMock(name="x_client"),
    )
    mocker.patch(
        "tech_news_synth.scheduler.run_publish",
        return_value=PublishResult(
            post_id=7,
            status="posted",
            tweet_id="X1",
            attempts=1,
            elapsed_ms=10,
            error_detail=None,
            counts_patch={"publish_status": "posted", "tweet_id": "X1"},
        ),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
def test_emits_one_line_with_10_fields(settings, captured_stream, mocker):
    """Happy path: exactly one cycle_summary event with all 10 D-06 fields."""
    mocker.patch(
        "tech_news_synth.scheduler.run_ingest",
        return_value={"articles_fetched": {"techcrunch": 8, "verge": 5}, "articles_upserted": 12},
    )
    mocker.patch(
        "tech_news_synth.scheduler.run_clustering",
        return_value=_canned_selection(mocker),
    )
    _patch_synth(mocker)
    _phase7_mocks(mocker)
    mocker.patch("tech_news_synth.scheduler.build_http_client", return_value=mocker.MagicMock())

    run_cycle(settings, sources_config=mocker.MagicMock())

    events = _parse(captured_stream)
    summaries = [e for e in events if e.get("event") == "cycle_summary"]
    assert len(summaries) == 1, f"expected 1 cycle_summary, got {len(summaries)}"
    s = summaries[0]
    # All 10 D-06 fields
    assert isinstance(s["cycle_id"], str) and len(s["cycle_id"]) == 26
    assert isinstance(s["duration_ms"], int) and s["duration_ms"] >= 0
    assert s["articles_fetched_per_source"] == {"techcrunch": 8, "verge": 5}
    assert s["cluster_count"] == 3
    assert s["chosen_cluster_id"] == 42
    assert s["char_budget_used"] == 223
    assert s["token_cost_usd"] == 0.000038
    assert s["post_status"] == "posted"
    assert s["status"] == "ok"
    assert s["dry_run"] is False


def test_paused_cycle_emits_no_summary(settings, captured_stream, monkeypatch, mocker):
    """Pitfall 1 durability invariant: paused cycles have NO run_log row, so
    NO cycle_summary line is emitted either."""
    monkeypatch.setattr(scheduler_mod, "is_paused", lambda s: (True, "env"))

    run_cycle(settings, sources_config=mocker.MagicMock())

    events = _parse(captured_stream)
    summaries = [e for e in events if e.get("event") == "cycle_summary"]
    assert summaries == []
    # Sanity: we DID get the cycle_skipped line.
    assert any(e.get("event") == "cycle_skipped" for e in events)


def test_no_emit_on_commit_failure(settings, captured_stream, mock_db_in_scheduler, mocker):
    """Commit failure on finish → cycle_summary NOT emitted (durability invariant).

    The run_log_finish_failed event IS emitted by the except branch.
    """
    _, session, _, _ = mock_db_in_scheduler
    # First commit (start_cycle) succeeds; second commit (finish) raises.
    session.commit.side_effect = [None, RuntimeError("commit boom")]

    mocker.patch(
        "tech_news_synth.scheduler.run_ingest",
        return_value={"articles_fetched": {"x": 1}},
    )
    mocker.patch(
        "tech_news_synth.scheduler.run_clustering",
        return_value=mocker.MagicMock(
            winner_cluster_id=None, fallback_article_id=None, counts_patch={}
        ),
    )
    mocker.patch("tech_news_synth.scheduler.build_http_client", return_value=mocker.MagicMock())
    _phase7_mocks(mocker)

    run_cycle(settings, sources_config=mocker.MagicMock())

    events = _parse(captured_stream)
    summaries = [e for e in events if e.get("event") == "cycle_summary"]
    assert summaries == [], f"commit failure MUST skip emit; got {summaries}"
    assert any(e.get("event") == "run_log_finish_failed" for e in events)


def test_emits_on_failed_cycle(settings, captured_stream, mocker):
    """run_ingest raises → status='error' + post_status='empty' in the summary.
    The emit still happens because finish_cycle commit succeeded.
    """
    mocker.patch(
        "tech_news_synth.scheduler.run_ingest",
        side_effect=RuntimeError("ingest boom"),
    )
    mocker.patch("tech_news_synth.scheduler.build_http_client", return_value=mocker.MagicMock())

    run_cycle(settings, sources_config=mocker.MagicMock())

    events = _parse(captured_stream)
    summaries = [e for e in events if e.get("event") == "cycle_summary"]
    assert len(summaries) == 1
    s = summaries[0]
    assert s["status"] == "error"
    assert s["post_status"] == "empty"
    # No synth ran → token/budget null
    assert s["char_budget_used"] is None
    assert s["token_cost_usd"] is None


def test_dry_run_flag_propagates(monkeypatch_env, monkeypatch, mocker):
    """DRY_RUN=1 → cycle_summary ``dry_run`` field is True."""
    monkeypatch.setenv("DRY_RUN", "1")
    s = load_settings()
    configure_logging(s)
    root = logging.getLogger()
    stream = io.StringIO()
    formatter = root.handlers[0].formatter
    buf_handler = logging.StreamHandler(stream)
    buf_handler.setFormatter(formatter)
    root.addHandler(buf_handler)

    try:
        mocker.patch(
            "tech_news_synth.scheduler.run_ingest",
            return_value={"articles_fetched": {"x": 1}},
        )
        mocker.patch(
            "tech_news_synth.scheduler.run_clustering",
            return_value=_canned_selection(mocker),
        )
        _patch_synth(mocker)
        _phase7_mocks(mocker)
        mocker.patch("tech_news_synth.scheduler.build_http_client", return_value=mocker.MagicMock())

        run_cycle(s, sources_config=mocker.MagicMock())

        events = _parse(stream)
        summaries = [e for e in events if e.get("event") == "cycle_summary"]
        assert len(summaries) == 1
        assert summaries[0]["dry_run"] is True
    finally:
        root.removeHandler(buf_handler)
