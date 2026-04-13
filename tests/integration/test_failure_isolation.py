"""Integration: one source errors (500 loop) — others still succeed (INGEST-05)."""

from __future__ import annotations

import json
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
from tech_news_synth.ingest.sources_config import (
    HnFirebaseSource,
    RedditJsonSource,
    RssSource,
    SourcesConfig,
)

pytestmark = pytest.mark.integration


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
VERGE_XML = (FIXTURES / "rss" / "verge.xml").read_bytes()
ARS_XML = (FIXTURES / "rss" / "ars_technica.xml").read_bytes()
HN_ITEM_1 = json.loads((FIXTURES / "json" / "hn_item_1.json").read_text())
REDDIT = json.loads((FIXTURES / "json" / "reddit_technology.json").read_text())

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
            RssSource(
                name="verge",
                type="rss",
                url="https://www.theverge.com/rss/index.xml",
                timeout_sec=20,
            ),  # type: ignore[arg-type]
            RssSource(
                name="ars_technica",
                type="rss",
                url="https://feeds.arstechnica.com/arstechnica/index",
                timeout_sec=20,
            ),  # type: ignore[arg-type]
            HnFirebaseSource(
                name="hacker_news",
                type="hn_firebase",
                url="https://hacker-news.firebaseio.com/v0",
                timeout_sec=15,
            ),  # type: ignore[arg-type]
            RedditJsonSource(
                name="reddit_technology",
                type="reddit_json",
                url="https://www.reddit.com/r/technology/.json",
                timeout_sec=15,
            ),  # type: ignore[arg-type]
        ],
    )


def _client() -> httpx.Client:
    # Use minimal timeout/backoff equivalence — tenacity default retries 3x.
    return httpx.Client(headers={"User-Agent": USER_AGENT}, follow_redirects=True)


@respx.mock
def test_one_source_500_others_succeed(db_session, monkeypatch):
    # Short-circuit tenacity backoff for test speed (keeps retries but 0 wait).
    import tenacity

    from tech_news_synth.ingest import http as http_mod

    monkeypatch.setattr(http_mod.fetch_with_retry.retry, "wait", tenacity.wait_none())

    # techcrunch always 500 (will exhaust retries → raise)
    respx.get("https://techcrunch.com/feed/").mock(
        return_value=httpx.Response(500, content=b"server error"),
    )
    respx.get("https://www.theverge.com/rss/index.xml").mock(
        return_value=httpx.Response(200, content=VERGE_XML),
    )
    respx.get("https://feeds.arstechnica.com/arstechnica/index").mock(
        return_value=httpx.Response(200, content=ARS_XML),
    )
    respx.get("https://hacker-news.firebaseio.com/v0/topstories.json").mock(
        return_value=httpx.Response(200, json=[39000001]),
    )
    respx.get("https://hacker-news.firebaseio.com/v0/item/39000001.json").mock(
        return_value=httpx.Response(200, json=HN_ITEM_1),
    )
    respx.get("https://www.reddit.com/r/technology/.json").mock(
        return_value=httpx.Response(200, json=REDDIT),
    )

    with _client() as client, time_machine.travel(FROZEN_NOW, tick=False):
        counts = run_ingest(db_session, _config(), client, _settings())

    assert counts["sources_ok"] == 4
    assert counts["sources_error"] == 1
    assert counts["articles_upserted"] > 0

    # techcrunch row shows error state.
    tc = db_session.execute(
        select(SourceState).where(SourceState.name == "techcrunch")
    ).scalar_one()
    assert tc.consecutive_failures == 1
    assert tc.last_status is not None
    assert tc.last_status.startswith("error:")
    assert tc.disabled_at is None  # not yet at threshold

    # Others inserted articles (at least one non-techcrunch article exists).
    other_articles = (
        db_session.execute(select(Article).where(Article.source != "techcrunch")).scalars().all()
    )
    assert len(other_articles) > 0
