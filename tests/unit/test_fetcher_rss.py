"""Unit tests for tech_news_synth.ingest.fetchers.rss.

Covers Plan 04-02 Task 1 behaviors:
  - happy path (200 + sort DESC + cap)
  - conditional GET (304 short-circuit with If-None-Match / If-Modified-Since)
  - malformed XML raises (orchestrator handles isolation)
  - missing pubDate falls back to fetched_at
  - max_article_age_hours filter
  - max_articles_per_fetch slice
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
import respx
import time_machine

from tech_news_synth.ingest.fetchers.rss import fetch
from tech_news_synth.ingest.http import USER_AGENT
from tech_news_synth.ingest.sources_config import RssSource, SourcesConfig

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "rss"
TECHCRUNCH_FIXTURE = (FIXTURES / "techcrunch.xml").read_bytes()
VERGE_FIXTURE = (FIXTURES / "verge.xml").read_bytes()

# Fixture pubDates are 2026-04-13 07:30..11:30 UTC — freeze shortly after so
# everything is within the 24h cutoff.
FROZEN_NOW = datetime(2026, 4, 13, 12, 30, tzinfo=UTC)


def _source(
    *,
    name: str = "techcrunch",
    url: str = "https://techcrunch.com/feed/",
    cap: int | None = None,
    timeout: float = 20.0,
) -> RssSource:
    return RssSource(
        name=name,
        type="rss",
        url=url,  # type: ignore[arg-type]
        timeout_sec=timeout,
        max_articles_per_fetch=cap,
    )


def _config(
    *,
    max_articles_per_fetch: int = 30,
    max_article_age_hours: int = 24,
) -> SourcesConfig:
    return SourcesConfig(
        max_articles_per_fetch=max_articles_per_fetch,
        max_article_age_hours=max_article_age_hours,
        sources=[_source()],
    )


def _client() -> httpx.Client:
    return httpx.Client(headers={"User-Agent": USER_AGENT}, follow_redirects=True)


# ---------------------------------------------------------------------------
# Test 1 — happy path: 200 returns rows sorted DESC, UA sent, ETag captured.
# ---------------------------------------------------------------------------
@respx.mock
def test_rss_happy_path():
    route = respx.get("https://techcrunch.com/feed/").mock(
        return_value=httpx.Response(
            200,
            content=TECHCRUNCH_FIXTURE,
            headers={"ETag": 'W/"abc123"', "Last-Modified": "Mon, 13 Apr 2026 11:30:00 GMT"},
        )
    )
    with _client() as client, time_machine.travel(FROZEN_NOW, tick=False):
        rows, meta = fetch(_source(), client, None, None, _config())

    assert len(rows) == 5
    # Sorted by published_at DESC
    assert rows[0].title.startswith("OpenAI")
    assert rows == sorted(rows, key=lambda r: r.published_at, reverse=True)
    assert meta == {
        "status": "ok",
        "etag": 'W/"abc123"',
        "last_modified": "Mon, 13 Apr 2026 11:30:00 GMT",
    }
    # UA header sent (httpx.Client defaults)
    req = route.calls.last.request
    assert req.headers["user-agent"] == USER_AGENT
    # No conditional-GET headers on a fresh state.
    assert "if-none-match" not in req.headers
    assert "if-modified-since" not in req.headers


# ---------------------------------------------------------------------------
# Test 2 — 304 short-circuit: conditional headers sent + empty return.
# ---------------------------------------------------------------------------
@respx.mock
def test_rss_304_short_circuits():
    route = respx.get("https://techcrunch.com/feed/").mock(return_value=httpx.Response(304))
    with _client() as client, time_machine.travel(FROZEN_NOW, tick=False):
        rows, meta = fetch(
            _source(),
            client,
            state_etag='W/"abc123"',
            state_last_modified="Mon, 13 Apr 2026 11:30:00 GMT",
            config=_config(),
        )
    assert rows == []
    assert meta["status"] == "skipped_304"
    req = route.calls.last.request
    assert req.headers["if-none-match"] == 'W/"abc123"'
    assert req.headers["if-modified-since"] == "Mon, 13 Apr 2026 11:30:00 GMT"


# ---------------------------------------------------------------------------
# Test 3 — malformed XML raises (isolated by orchestrator).
# ---------------------------------------------------------------------------
@respx.mock
def test_rss_malformed_raises():
    respx.get("https://techcrunch.com/feed/").mock(
        return_value=httpx.Response(200, content=b"\x00\xff not xml \x00")
    )
    with _client() as client, time_machine.travel(FROZEN_NOW, tick=False):
        with pytest.raises(RuntimeError, match="feedparser bozo"):
            fetch(_source(), client, None, None, _config())


# ---------------------------------------------------------------------------
# Test 4 — missing pubDate falls back to fetched_at.
# ---------------------------------------------------------------------------
@respx.mock
def test_rss_missing_pubdate_fallback():
    xml = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <title>X</title><link>https://x.example/</link><description>x</description>
  <item>
    <title>No pubdate article</title>
    <link>https://x.example/article-no-pubdate</link>
    <description>body</description>
  </item>
</channel></rss>"""
    respx.get("https://techcrunch.com/feed/").mock(return_value=httpx.Response(200, content=xml))
    with _client() as client, time_machine.travel(FROZEN_NOW, tick=False):
        rows, _ = fetch(_source(), client, None, None, _config())
    assert len(rows) == 1
    # Falls back to fetched_at (now frozen).
    assert rows[0].published_at == FROZEN_NOW
    assert rows[0].fetched_at == FROZEN_NOW


# ---------------------------------------------------------------------------
# Test 5 — max_article_age_hours filter excludes stale entries.
# ---------------------------------------------------------------------------
@respx.mock
def test_rss_max_age_filter():
    respx.get("https://techcrunch.com/feed/").mock(
        return_value=httpx.Response(200, content=TECHCRUNCH_FIXTURE)
    )
    # Freeze far enough ahead that all 5 fixture items fall outside the window.
    future = FROZEN_NOW + timedelta(days=2)
    with _client() as client, time_machine.travel(future, tick=False):
        rows, _ = fetch(_source(), client, None, None, _config(max_article_age_hours=24))
    assert rows == []


# ---------------------------------------------------------------------------
# Test 6 — max_articles_per_fetch slice caps output.
# ---------------------------------------------------------------------------
@respx.mock
def test_rss_cap_slice():
    respx.get("https://techcrunch.com/feed/").mock(
        return_value=httpx.Response(200, content=TECHCRUNCH_FIXTURE)
    )
    # Fixture has 5 entries; cap=2 ⇒ 2 returned.
    with _client() as client, time_machine.travel(FROZEN_NOW, tick=False):
        rows, _ = fetch(_source(cap=2), client, None, None, _config())
    assert len(rows) == 2
    # Still newest-first.
    assert rows[0].title.startswith("OpenAI")
    assert rows[1].title.startswith("Apple")
