"""Integration: orchestrator counts dict shape locked + JSONB roundtrip."""

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
from tech_news_synth.db.models import RunLog
from tech_news_synth.db.run_log import finish_cycle, start_cycle
from tech_news_synth.ingest.http import USER_AGENT
from tech_news_synth.ingest.orchestrator import run_ingest
from tech_news_synth.ingest.sources_config import (
    HnFirebaseSource,
    RssSource,
    SourcesConfig,
)

pytestmark = pytest.mark.integration


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
TC_XML = (FIXTURES / "rss" / "techcrunch.xml").read_bytes()
HN_ITEM_1 = json.loads((FIXTURES / "json" / "hn_item_1.json").read_text())

FROZEN_NOW = datetime(2026, 4, 13, 12, 30, tzinfo=UTC)

EXPECTED_KEYS = {
    "articles_fetched",
    "articles_upserted",
    "sources_ok",
    "sources_error",
    "sources_skipped_disabled",
}


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
            HnFirebaseSource(
                name="hacker_news",
                type="hn_firebase",
                url="https://hacker-news.firebaseio.com/v0",
                timeout_sec=15,
            ),  # type: ignore[arg-type]
        ],
    )


def _client() -> httpx.Client:
    return httpx.Client(headers={"User-Agent": USER_AGENT}, follow_redirects=True)


@respx.mock
def test_counts_dict_shape_and_jsonb_roundtrip(db_session):
    respx.get("https://techcrunch.com/feed/").mock(
        return_value=httpx.Response(200, content=TC_XML),
    )
    respx.get("https://hacker-news.firebaseio.com/v0/topstories.json").mock(
        return_value=httpx.Response(200, json=[39000001]),
    )
    respx.get("https://hacker-news.firebaseio.com/v0/item/39000001.json").mock(
        return_value=httpx.Response(200, json=HN_ITEM_1),
    )

    with _client() as client, time_machine.travel(FROZEN_NOW, tick=False):
        counts = run_ingest(db_session, _config(), client, _settings())

    # Key set locked.
    assert set(counts.keys()) == EXPECTED_KEYS, counts.keys()

    # articles_fetched is dict[str,int].
    assert isinstance(counts["articles_fetched"], dict)
    for k, v in counts["articles_fetched"].items():
        assert isinstance(k, str)
        assert isinstance(v, int)

    # Roundtrip through run_log.counts JSONB.
    cycle_id = "01JTEST000000000000000TEST"
    start_cycle(db_session, cycle_id)
    finish_cycle(db_session, cycle_id, "ok", counts=counts)
    db_session.flush()

    row = db_session.execute(select(RunLog).where(RunLog.cycle_id == cycle_id)).scalar_one()
    assert set(row.counts.keys()) == EXPECTED_KEYS
    assert row.counts["articles_upserted"] == counts["articles_upserted"]
