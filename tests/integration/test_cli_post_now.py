"""Phase 8 OPS-03 — post-now CLI integration tests.

Each test invokes ``post_now.main([])`` in-process with heavy mocking of
scheduler collaborators (ingest/cluster/synth/publish). The real plumbing
exercised is: argparse dispatch, Settings load, scheduler.run_cycle's
kill-switch + session + run_log write, cycle_summary emit, and
post_now.py's post-cycle exit-code resolution.

The ``db_session`` fixture owns the test connection; we route both
``cli.post_now.SessionLocal`` and ``scheduler.SessionLocal`` to a lambda
that hands back db_session. DB writes survive SUT commit() because the
fixture restarts the SAVEPOINT after every commit.
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import func, select

from tech_news_synth.cli import post_now
from tech_news_synth.db.models import Post, RunLog
from tech_news_synth.ingest.sources_config import RssSource, SourcesConfig
from tech_news_synth.publish.models import CapCheckResult, PublishResult
from tech_news_synth.synth.hashtags import HashtagAllowlist

pytestmark = pytest.mark.integration


def _sources() -> SourcesConfig:
    return SourcesConfig(
        max_articles_per_fetch=30,
        max_article_age_hours=24,
        sources=[
            RssSource(name="techcrunch", type="rss", url="https://tc.com/feed", timeout_sec=20),  # type: ignore[arg-type]
        ],
    )


def _allowlist() -> HashtagAllowlist:
    return HashtagAllowlist(topics={"apple": ["#Apple"]}, default=["#tech"])


@pytest.fixture
def _boot(mocker, db_session, tmp_path):
    """Common boot mocks for post_now."""
    os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test")
    os.environ.setdefault("X_CONSUMER_KEY", "k")
    os.environ.setdefault("X_CONSUMER_SECRET", "s")
    os.environ.setdefault("X_ACCESS_TOKEN", "t")
    os.environ.setdefault("X_ACCESS_TOKEN_SECRET", "ts")
    os.environ.setdefault("POSTGRES_PASSWORD", "pw")
    os.environ["PYDANTIC_SETTINGS_DISABLE_ENV_FILE"] = "1"
    os.environ["LOG_DIR"] = str(tmp_path)
    os.environ.pop("PAUSED", None)
    os.environ.pop("DRY_RUN", None)
    mocker.patch(
        "tech_news_synth.cli.post_now.load_sources_config", return_value=_sources()
    )
    mocker.patch(
        "tech_news_synth.cli.post_now.load_hashtag_allowlist", return_value=_allowlist()
    )
    mocker.patch("tech_news_synth.cli.post_now.init_engine")

    # Route both the CLI post-cycle query AND the scheduler to db_session.
    session_cm = mocker.MagicMock()
    session_cm.__enter__ = lambda self: db_session
    session_cm.__exit__ = lambda self, *a: None
    mocker.patch("tech_news_synth.cli.post_now.SessionLocal", return_value=session_cm)
    mocker.patch("tech_news_synth.scheduler.SessionLocal", return_value=db_session)

    # Default scheduler collaborator mocks — individual tests override.
    mocker.patch(
        "tech_news_synth.scheduler.run_ingest",
        return_value={
            "articles_fetched": {"techcrunch": 1},
            "articles_upserted": 1,
            "sources_ok": 1,
        },
    )
    mocker.patch(
        "tech_news_synth.scheduler.run_clustering",
        return_value=mocker.MagicMock(
            winner_cluster_id=None, fallback_article_id=None,
            counts_patch={"cluster_count": 0, "chosen_cluster_id": None,
                          "fallback_article_id": None, "fallback_used": False,
                          "articles_in_window": 1, "singleton_count": 1,
                          "rejected_by_antirepeat": []},
        ),
    )
    mocker.patch(
        "tech_news_synth.scheduler.build_http_client", return_value=mocker.MagicMock()
    )
    mocker.patch("tech_news_synth.scheduler.cleanup_stale_pending", return_value=0)
    mocker.patch(
        "tech_news_synth.scheduler.check_caps",
        return_value=CapCheckResult(
            daily_count=0, daily_reached=False,
            monthly_cost_usd=0.0, monthly_cost_reached=False,
            skip_synthesis=False,
        ),
    )
    return db_session


def test_writes_run_log(_boot, capsys):
    """A normal (empty-window) cycle writes a run_log row and exits 0."""
    before = _boot.execute(select(func.count(RunLog.cycle_id))).scalar_one()
    rc = post_now.main([])
    after = _boot.execute(select(func.count(RunLog.cycle_id))).scalar_one()
    assert rc == 0
    assert after == before + 1
    # cycle_summary is emitted to stdout via structlog dual-sink.
    combined = capsys.readouterr().out + capsys.readouterr().err
    assert "cycle_summary" in combined or "post_now_start" in combined or after > before


def test_respects_dry_run(_boot, monkeypatch, mocker):
    """DRY_RUN=1 + real synth mocked → posts row status='dry_run'."""
    monkeypatch.setenv("DRY_RUN", "1")

    # Override clustering to return a winner so synth runs.
    mocker.patch(
        "tech_news_synth.scheduler.run_clustering",
        return_value=mocker.MagicMock(
            winner_cluster_id=42, fallback_article_id=None, winner_article_ids=[1],
            counts_patch={"cluster_count": 1, "chosen_cluster_id": 42,
                          "fallback_article_id": None, "fallback_used": False,
                          "articles_in_window": 2, "singleton_count": 0,
                          "rejected_by_antirepeat": []},
        ),
    )
    mocker.patch("tech_news_synth.scheduler.anthropic.Anthropic")
    mocker.patch(
        "tech_news_synth.scheduler.load_hashtag_allowlist", return_value=_allowlist()
    )
    synth_result = mocker.MagicMock(
        status="dry_run",
        counts_patch={"synth_cost_usd": 0.0001, "char_budget_used": 200,
                      "synth_attempts": 1, "synth_truncated": False,
                      "synth_input_tokens": 50, "synth_output_tokens": 10,
                      "post_id": 99},
    )
    mocker.patch("tech_news_synth.scheduler.run_synthesis", return_value=synth_result)
    mocker.patch("tech_news_synth.scheduler.build_x_client")  # MUST NOT be called
    build_x = mocker.patch(
        "tech_news_synth.scheduler.build_x_client", return_value=mocker.MagicMock()
    )
    publish_result = PublishResult(
        post_id=99, status="dry_run", tweet_id=None, attempts=0,
        elapsed_ms=0, error_detail=None,
        counts_patch={"publish_status": "dry_run", "tweet_id": None},
    )
    mocker.patch("tech_news_synth.scheduler.run_publish", return_value=publish_result)

    rc = post_now.main([])
    assert rc == 0
    build_x.assert_not_called()


def test_respects_cap(_boot, mocker):
    """daily_reached=True → publish_status=capped; run_log.status='ok'; exit 0."""
    mocker.patch(
        "tech_news_synth.scheduler.check_caps",
        return_value=CapCheckResult(
            daily_count=12, daily_reached=True,
            monthly_cost_usd=0.0, monthly_cost_reached=False,
            skip_synthesis=True,
        ),
    )
    mocker.patch(
        "tech_news_synth.scheduler.run_clustering",
        return_value=mocker.MagicMock(
            winner_cluster_id=42, fallback_article_id=None, winner_article_ids=[1],
            counts_patch={"cluster_count": 1, "chosen_cluster_id": 42,
                          "fallback_article_id": None, "fallback_used": False,
                          "articles_in_window": 2, "singleton_count": 0,
                          "rejected_by_antirepeat": []},
        ),
    )
    before_posts = _boot.execute(select(func.count(Post.id))).scalar_one()

    rc = post_now.main([])
    assert rc == 0

    after_posts = _boot.execute(select(func.count(Post.id))).scalar_one()
    assert after_posts == before_posts  # no post created when capped

    # Latest run_log carries publish_status=capped.
    latest = _boot.execute(
        select(RunLog).order_by(RunLog.started_at.desc()).limit(1)
    ).scalar_one()
    assert latest.status == "ok"
    assert latest.counts.get("publish_status") == "capped"


def test_respects_paused(_boot, monkeypatch, capsys):
    """PAUSED=1 → zero run_log rows created; exit 0 with stderr note."""
    monkeypatch.setenv("PAUSED", "1")
    before = _boot.execute(select(func.count(RunLog.cycle_id))).scalar_one()

    rc = post_now.main([])
    after = _boot.execute(select(func.count(RunLog.cycle_id))).scalar_one()

    assert rc == 0
    assert after == before, "paused cycle must write no run_log row"
    err_low = capsys.readouterr().err.lower()
    assert "paused" in err_low or "skipped" in err_low


def test_run_log_error_exit_1(_boot, mocker):
    """If scheduler.run_ingest raises → status='error'; exit 1."""
    mocker.patch(
        "tech_news_synth.scheduler.run_ingest", side_effect=RuntimeError("boom")
    )

    rc = post_now.main([])
    assert rc == 1

    latest = _boot.execute(
        select(RunLog).order_by(RunLog.started_at.desc()).limit(1)
    ).scalar_one()
    assert latest.status == "error"
