"""Phase 8 OPS-01 — end-to-end cycle_summary emit against a real DB.

Runs ``scheduler.run_cycle`` with:
  * real DB (db_session fixture via SessionLocal patch)
  * mocked Anthropic (``call_haiku`` returns canned text)
  * mocked tweepy (``create_tweet`` returns fake tweet id)
  * mocked ingest (returns canned articles)

Verifies: exactly one ``cycle_summary`` JSON line is emitted to stdout with
all 10 D-06 fields populated, AFTER the run_log row is durably committed.
"""

from __future__ import annotations

import io
import json
import logging
import os
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from tech_news_synth.config import Settings
from tech_news_synth.db.articles import upsert_batch
from tech_news_synth.db.models import RunLog
from tech_news_synth.ingest.sources_config import RssSource, SourcesConfig
from tech_news_synth.logging import configure_logging
from tech_news_synth.publish.models import CapCheckResult, PublishResult
from tech_news_synth.scheduler import run_cycle
from tech_news_synth.synth.hashtags import HashtagAllowlist

pytestmark = pytest.mark.integration


def _settings(tmp_log_dir) -> Settings:
    for k, v in {
        "ANTHROPIC_API_KEY": "sk-ant-test",
        "X_CONSUMER_KEY": "k",
        "X_CONSUMER_SECRET": "s",
        "X_ACCESS_TOKEN": "t",
        "X_ACCESS_TOKEN_SECRET": "ts",
        "POSTGRES_PASSWORD": "pw",
    }.items():
        os.environ.setdefault(k, v)
    os.environ["PYDANTIC_SETTINGS_DISABLE_ENV_FILE"] = "1"
    os.environ["LOG_DIR"] = str(tmp_log_dir)
    return Settings()  # type: ignore[call-arg]


def _sources() -> SourcesConfig:
    return SourcesConfig(
        max_articles_per_fetch=30,
        max_article_age_hours=24,
        sources=[
            RssSource(name="techcrunch", type="rss", url="https://tc.com/feed", timeout_sec=20),  # type: ignore[arg-type]
            RssSource(name="verge", type="rss", url="https://verge.com/feed", timeout_sec=20),  # type: ignore[arg-type]
        ],
    )


def _allowlist() -> HashtagAllowlist:
    return HashtagAllowlist(topics={"apple": ["#Apple"]}, default=["#tech"])


def test_real_cycle_emits_summary(db_session, mocker, tmp_path):
    """Full cycle against real DB: one cycle_summary line with all 10 fields
    lands AFTER run_log.finished_at is written."""
    settings = _settings(tmp_path)
    configure_logging(settings)
    root = logging.getLogger()
    stream = io.StringIO()
    formatter = root.handlers[0].formatter
    buf_handler = logging.StreamHandler(stream)
    buf_handler.setFormatter(formatter)
    root.addHandler(buf_handler)

    # Seed two articles — enough for clustering to find a real winner OR fall
    # back. Either way cycle_summary must be emitted.
    upsert_batch(
        db_session,
        [
            {
                "source": "techcrunch",
                "url": "https://tc.com/a",
                "canonical_url": "https://tc.com/a",
                "title": "Apple unveils new M5 chip",
                "summary": "Apple chip.",
                "published_at": datetime.now(UTC),
                "article_hash": "a" * 64,
            },
            {
                "source": "verge",
                "url": "https://verge.com/b",
                "canonical_url": "https://verge.com/b",
                "title": "Apple M5 chip revealed",
                "summary": "Apple silicon.",
                "published_at": datetime.now(UTC),
                "article_hash": "b" * 64,
            },
        ],
    )
    db_session.flush()

    # Route SessionLocal() in scheduler to our test session.
    mocker.patch("tech_news_synth.scheduler.SessionLocal", return_value=db_session)
    # db_session inherits outer transaction → commits become SAVEPOINT releases.

    # Mock ingest (we already have articles seeded) — return per-source counts.
    mocker.patch(
        "tech_news_synth.scheduler.run_ingest",
        return_value={
            "articles_fetched": {"techcrunch": 1, "verge": 1},
            "articles_upserted": 0,
            "sources_ok": 2,
            "sources_error": 0,
        },
    )
    mocker.patch("tech_news_synth.scheduler.build_http_client", return_value=mocker.MagicMock())

    # Mock Anthropic
    mocker.patch(
        "tech_news_synth.synth.orchestrator.call_haiku",
        return_value=("Apple apresentou o chip M5 com aceleração de IA.", 50, 20),
    )

    # Phase 7 mocks
    mocker.patch("tech_news_synth.scheduler.cleanup_stale_pending", return_value=0)
    mocker.patch(
        "tech_news_synth.scheduler.check_caps",
        return_value=CapCheckResult(
            daily_count=0, daily_reached=False,
            monthly_cost_usd=0.0, monthly_cost_reached=False,
            skip_synthesis=False,
        ),
    )
    mocker.patch("tech_news_synth.scheduler.build_x_client", return_value=mocker.MagicMock())
    mocker.patch(
        "tech_news_synth.scheduler.run_publish",
        return_value=PublishResult(
            post_id=7, status="posted", tweet_id="X1", attempts=1,
            elapsed_ms=10, error_detail=None,
            counts_patch={"publish_status": "posted", "tweet_id": "X1"},
        ),
    )

    try:
        run_cycle(settings, sources_config=_sources(), hashtag_allowlist=_allowlist())
    finally:
        root.removeHandler(buf_handler)

    events = [
        json.loads(ln) for ln in stream.getvalue().splitlines() if ln.strip()
    ]
    summaries = [e for e in events if e.get("event") == "cycle_summary"]
    assert len(summaries) == 1, f"expected 1 cycle_summary, got {len(summaries)}"
    s = summaries[0]
    # All 10 fields present
    for key in (
        "cycle_id", "duration_ms", "articles_fetched_per_source",
        "cluster_count", "chosen_cluster_id", "char_budget_used",
        "token_cost_usd", "post_status", "status", "dry_run",
    ):
        assert key in s, f"missing field {key} in cycle_summary"
    assert s["articles_fetched_per_source"] == {"techcrunch": 1, "verge": 1}
    assert s["status"] == "ok"
    assert isinstance(s["dry_run"], bool)

    # Durability invariant: run_log row for this cycle_id exists with status=ok.
    rl = db_session.execute(
        select(RunLog).where(RunLog.cycle_id == s["cycle_id"])
    ).scalar_one()
    assert rl.status == "ok"
    assert rl.finished_at is not None
