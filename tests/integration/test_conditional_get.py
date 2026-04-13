"""Integration: conditional GET round-trip (INGEST-04, D-14)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import respx
import time_machine
from sqlalchemy import select

from tech_news_synth.config import Settings
from tech_news_synth.db.models import Article, SourceState
from tech_news_synth.ingest.http import USER_AGENT
from tech_news_synth.ingest.orchestrator import run_ingest
from tech_news_synth.ingest.sources_config import RssSource, SourcesConfig

pytestmark = pytest.mark.integration


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
TC_XML = (FIXTURES / "rss" / "techcrunch.xml").read_bytes()

FROZEN_NOW = datetime(2026, 4, 13, 12, 30, tzinfo=UTC)


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
            RssSource(
                name="techcrunch", type="rss", url="https://techcrunch.com/feed/", timeout_sec=20
            ),  # type: ignore[arg-type]
        ],
    )


def _client() -> httpx.Client:
    return httpx.Client(headers={"User-Agent": USER_AGENT}, follow_redirects=True)


@respx.mock
def test_second_cycle_304_zero_inserts(db_session):
    # First cycle: 200 + ETag.
    route = respx.get("https://techcrunch.com/feed/").mock(
        return_value=httpx.Response(
            200,
            content=TC_XML,
            headers={"ETag": 'W/"tc-v1"', "Last-Modified": "Mon, 13 Apr 2026 11:30:00 GMT"},
        ),
    )
    with _client() as client, time_machine.travel(FROZEN_NOW, tick=False):
        counts_1 = run_ingest(db_session, _config(), client, _settings())

    assert counts_1["sources_ok"] == 1
    assert counts_1["articles_upserted"] >= 1
    state = db_session.execute(
        select(SourceState).where(SourceState.name == "techcrunch")
    ).scalar_one()
    assert state.etag == 'W/"tc-v1"'
    assert state.last_status == "ok"

    # Second cycle: respx returns 304 if If-None-Match matches.
    def _match_304(request: httpx.Request) -> httpx.Response:
        if request.headers.get("if-none-match") == 'W/"tc-v1"':
            return httpx.Response(304)
        return httpx.Response(200, content=TC_XML)

    route.mock(side_effect=_match_304)

    articles_before = len(db_session.execute(select(Article)).scalars().all())

    with _client() as client, time_machine.travel(FROZEN_NOW, tick=False):
        counts_2 = run_ingest(db_session, _config(), client, _settings())

    assert counts_2["sources_ok"] == 1
    assert counts_2["articles_upserted"] == 0
    state2 = db_session.execute(
        select(SourceState).where(SourceState.name == "techcrunch")
    ).scalar_one()
    assert state2.last_status == "skipped_304"
    assert state2.consecutive_failures == 0

    articles_after = len(db_session.execute(select(Article)).scalars().all())
    assert articles_after == articles_before
