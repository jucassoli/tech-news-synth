"""Integration: auto-disable at cycle start (INGEST-07, D-12)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import respx
from sqlalchemy import select

from tech_news_synth.config import Settings
from tech_news_synth.db.models import SourceState
from tech_news_synth.db.source_state import get_state, upsert_source
from tech_news_synth.ingest.http import USER_AGENT
from tech_news_synth.ingest.orchestrator import run_ingest
from tech_news_synth.ingest.sources_config import RssSource, SourcesConfig

pytestmark = pytest.mark.integration


def _settings() -> Settings:
    import os

    os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test")
    os.environ.setdefault("X_CONSUMER_KEY", "k")
    os.environ.setdefault("X_CONSUMER_SECRET", "s")
    os.environ.setdefault("X_ACCESS_TOKEN", "t")
    os.environ.setdefault("X_ACCESS_TOKEN_SECRET", "ts")
    os.environ.setdefault("POSTGRES_PASSWORD", "pw")
    os.environ["PYDANTIC_SETTINGS_DISABLE_ENV_FILE"] = "1"
    return Settings()  # type: ignore[call-arg]


def _config() -> SourcesConfig:
    return SourcesConfig(
        max_articles_per_fetch=30,
        max_article_age_hours=24,
        sources=[
            RssSource(name="techcrunch", type="rss", url="https://techcrunch.com/feed/", timeout_sec=20),  # type: ignore[arg-type]
        ],
    )


def _client() -> httpx.Client:
    return httpx.Client(headers={"User-Agent": USER_AGENT}, follow_redirects=True)


@respx.mock
def test_source_disabled_when_counter_ge_threshold(db_session):
    # Seed state with consecutive_failures=20 (default threshold).
    upsert_source(db_session, "techcrunch")
    row = get_state(db_session, "techcrunch")
    assert row is not None
    row.consecutive_failures = 20
    db_session.flush()

    # respx: if the fetcher hits this URL, fail the test by returning 418.
    # assert_all_called defaults True — we invert with .respond pattern.
    route = respx.get("https://techcrunch.com/feed/").mock(
        return_value=httpx.Response(418),  # teapot — would surface as error if called
    )

    with _client() as client:
        counts = run_ingest(db_session, _config(), client, _settings())

    # Fetcher must NOT have been called.
    assert route.call_count == 0
    assert counts["sources_skipped_disabled"] == 1
    assert counts["sources_ok"] == 0
    assert counts["sources_error"] == 0
    assert counts["articles_upserted"] == 0

    # disabled_at populated.
    state = db_session.execute(
        select(SourceState).where(SourceState.name == "techcrunch")
    ).scalar_one()
    assert state.disabled_at is not None
    assert state.disabled_at.tzinfo is not None


@respx.mock
def test_source_skipped_when_disabled_at_set(db_session):
    upsert_source(db_session, "techcrunch")
    row = get_state(db_session, "techcrunch")
    assert row is not None
    row.consecutive_failures = 3  # below threshold
    row.disabled_at = datetime(2026, 4, 12, 0, 0, tzinfo=UTC)  # but explicitly disabled
    db_session.flush()

    route = respx.get("https://techcrunch.com/feed/").mock(
        return_value=httpx.Response(418),
    )

    with _client() as client:
        counts = run_ingest(db_session, _config(), client, _settings())

    assert route.call_count == 0
    assert counts["sources_skipped_disabled"] == 1
