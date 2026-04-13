"""Integration: happy-path ingest cycle with all 5 sources succeeding."""

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
TC_XML = (FIXTURES / "rss" / "techcrunch.xml").read_bytes()
VERGE_XML = (FIXTURES / "rss" / "verge.xml").read_bytes()
ARS_XML = (FIXTURES / "rss" / "ars_technica.xml").read_bytes()
HN_TOP = json.loads((FIXTURES / "json" / "hn_topstories.json").read_text())
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


def _five_source_config() -> SourcesConfig:
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
    return httpx.Client(headers={"User-Agent": USER_AGENT}, follow_redirects=True)


@respx.mock
def test_all_sources_ok(db_session):
    respx.get("https://techcrunch.com/feed/").mock(
        return_value=httpx.Response(200, content=TC_XML, headers={"ETag": '"tc1"'}),
    )
    respx.get("https://www.theverge.com/rss/index.xml").mock(
        return_value=httpx.Response(200, content=VERGE_XML, headers={"ETag": '"vg1"'}),
    )
    respx.get("https://feeds.arstechnica.com/arstechnica/index").mock(
        return_value=httpx.Response(200, content=ARS_XML, headers={"ETag": '"ars1"'}),
    )
    # HN: 1 id → item 1 (story + url)
    respx.get("https://hacker-news.firebaseio.com/v0/topstories.json").mock(
        return_value=httpx.Response(200, json=[39000001]),
    )
    respx.get("https://hacker-news.firebaseio.com/v0/item/39000001.json").mock(
        return_value=httpx.Response(200, json=HN_ITEM_1),
    )
    respx.get("https://www.reddit.com/r/technology/.json").mock(
        return_value=httpx.Response(200, json=REDDIT),
    )

    config = _five_source_config()
    settings = _settings()

    with _client() as client, time_machine.travel(FROZEN_NOW, tick=False):
        counts = run_ingest(db_session, config, client, settings)

    assert counts["sources_ok"] == 5
    assert counts["sources_error"] == 0
    assert counts["sources_skipped_disabled"] == 0
    assert counts["articles_upserted"] > 0

    # Every source has a source_state row with last_status='ok'.
    states = db_session.execute(select(SourceState)).scalars().all()
    assert {s.name for s in states} == {
        "techcrunch",
        "verge",
        "ars_technica",
        "hacker_news",
        "reddit_technology",
    }
    for s in states:
        assert s.last_status == "ok", f"{s.name}: {s.last_status}"
        assert s.consecutive_failures == 0
        assert s.disabled_at is None

    # articles table populated.
    article_count = db_session.execute(select(Article)).scalars().all()
    assert len(article_count) == counts["articles_upserted"]
