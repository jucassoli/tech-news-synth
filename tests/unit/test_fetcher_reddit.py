"""Unit tests for tech_news_synth.ingest.fetchers.reddit_json (Plan 04-02 Task 3)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import respx
import time_machine

from tech_news_synth.ingest.fetchers.reddit_json import fetch
from tech_news_synth.ingest.http import USER_AGENT
from tech_news_synth.ingest.sources_config import RedditJsonSource, SourcesConfig


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "json"
REDDIT_FIXTURE = json.loads((FIXTURES / "reddit_technology.json").read_text())

FROZEN_NOW = datetime(2026, 4, 13, 8, 0, tzinfo=UTC)
URL = "https://www.reddit.com/r/technology/.json"


def _source(*, cap: int | None = None) -> RedditJsonSource:
    return RedditJsonSource(
        name="reddit_technology",
        type="reddit_json",
        url=URL,  # type: ignore[arg-type]
        timeout_sec=15.0,
        max_articles_per_fetch=cap,
    )


def _config(**kw) -> SourcesConfig:
    return SourcesConfig(
        max_articles_per_fetch=kw.get("max_articles_per_fetch", 30),
        max_article_age_hours=kw.get("max_article_age_hours", 24),
        sources=[_source()],
    )


def _client() -> httpx.Client:
    return httpx.Client(headers={"User-Agent": USER_AGENT}, follow_redirects=True)


# ---------------------------------------------------------------------------
# Test 1 — happy path: stickied + is_self-without-external-url filtered.
# ---------------------------------------------------------------------------
@respx.mock
def test_reddit_filters_stickied_and_selfposts():
    respx.get(URL).mock(return_value=httpx.Response(200, json=REDDIT_FIXTURE))
    with _client() as client, time_machine.travel(FROZEN_NOW, tick=False):
        rows, meta = fetch(_source(), client, None, None, _config())

    # Fixture has 4 children: abc001 stickied, abc002 ok, abc003 is_self+reddit url,
    # abc004 ok. Expect 2 rows.
    assert len(rows) == 2
    titles = {r.title for r in rows}
    assert titles == {
        "New EU AI Act ruling affects open-source models",
        "Intel layoffs hit 15,000 employees",
    }
    assert meta == {"status": "ok", "etag": None, "last_modified": None}


# ---------------------------------------------------------------------------
# Test 2 — cap respected on large listings.
# ---------------------------------------------------------------------------
@respx.mock
def test_reddit_cap_respected():
    big = {
        "data": {
            "children": [
                {
                    "kind": "t3",
                    "data": {
                        "id": f"id{i}",
                        "title": f"title {i}",
                        "url": f"https://example.com/a{i}",
                        "created_utc": 1776095000 + i,
                        "selftext": "",
                        "stickied": False,
                        "is_self": False,
                    },
                }
                for i in range(50)
            ]
        }
    }
    respx.get(URL).mock(return_value=httpx.Response(200, json=big))
    with _client() as client, time_machine.travel(FROZEN_NOW, tick=False):
        rows, _ = fetch(_source(), client, None, None, _config())
    assert len(rows) == 30


# ---------------------------------------------------------------------------
# Test 3 — UA header sent.
# ---------------------------------------------------------------------------
@respx.mock
def test_reddit_ua_header():
    route = respx.get(URL).mock(return_value=httpx.Response(200, json=REDDIT_FIXTURE))
    with _client() as client, time_machine.travel(FROZEN_NOW, tick=False):
        fetch(_source(), client, None, None, _config())
    assert route.calls.last.request.headers["user-agent"] == USER_AGENT


# ---------------------------------------------------------------------------
# Test 4 — no conditional-GET headers sent (D-14).
# ---------------------------------------------------------------------------
@respx.mock
def test_reddit_never_sends_conditional_get():
    route = respx.get(URL).mock(return_value=httpx.Response(200, json=REDDIT_FIXTURE))
    with _client() as client, time_machine.travel(FROZEN_NOW, tick=False):
        fetch(
            _source(),
            client,
            state_etag='W/"abc"',
            state_last_modified="Mon, 13 Apr 2026 00:00:00 GMT",
            config=_config(),
        )
    req = route.calls.last.request
    assert "if-none-match" not in req.headers
    assert "if-modified-since" not in req.headers


# ---------------------------------------------------------------------------
# Test 5 — old created_utc excluded by max_age.
# ---------------------------------------------------------------------------
@respx.mock
def test_reddit_max_age_filter():
    respx.get(URL).mock(return_value=httpx.Response(200, json=REDDIT_FIXTURE))
    # All fixture posts created around 1776092000..1776095000 UTC — freeze 2d later.
    future = datetime.fromtimestamp(1776095000, tz=UTC) + timedelta(days=2)
    with _client() as client, time_machine.travel(future, tick=False):
        rows, _ = fetch(_source(), client, None, None, _config(max_article_age_hours=24))
    assert rows == []
