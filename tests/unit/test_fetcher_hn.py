"""Unit tests for tech_news_synth.ingest.fetchers.hn_firebase (Plan 04-02 Task 2)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import respx
import time_machine

from tech_news_synth.ingest.fetchers.hn_firebase import fetch
from tech_news_synth.ingest.http import USER_AGENT
from tech_news_synth.ingest.sources_config import HnFirebaseSource, SourcesConfig

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "json"
HN_TOPSTORIES = json.loads((FIXTURES / "hn_topstories.json").read_text())
HN_ITEM_1 = json.loads((FIXTURES / "hn_item_1.json").read_text())  # story + url
HN_ITEM_2 = json.loads((FIXTURES / "hn_item_2.json").read_text())  # story, no url
HN_ITEM_3 = json.loads((FIXTURES / "hn_item_3.json").read_text())  # job

# Item 1 time=1776095400 = 2026-04-13 05:50:00 UTC. Freeze a couple hours after.
FROZEN_NOW = datetime(2026, 4, 13, 8, 0, tzinfo=UTC)
BASE_URL = "https://hacker-news.firebaseio.com/v0"


def _source(*, cap: int | None = None) -> HnFirebaseSource:
    return HnFirebaseSource(
        name="hacker_news",
        type="hn_firebase",
        url=BASE_URL,  # type: ignore[arg-type]
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
# Test 1 — happy path: only story+url items emitted.
# ---------------------------------------------------------------------------
@respx.mock
def test_hn_filters_type_and_url():
    respx.get(f"{BASE_URL}/topstories.json").mock(
        return_value=httpx.Response(200, json=[39000001, 39000002, 39000003])
    )
    respx.get(f"{BASE_URL}/item/39000001.json").mock(
        return_value=httpx.Response(200, json=HN_ITEM_1)
    )
    respx.get(f"{BASE_URL}/item/39000002.json").mock(
        return_value=httpx.Response(200, json=HN_ITEM_2)
    )
    respx.get(f"{BASE_URL}/item/39000003.json").mock(
        return_value=httpx.Response(200, json=HN_ITEM_3)
    )

    with _client() as client, time_machine.travel(FROZEN_NOW, tick=False):
        rows, meta = fetch(_source(cap=3), client, None, None, _config())

    assert len(rows) == 1
    assert rows[0].title.startswith("Rust 1.80")
    assert rows[0].url == "https://blog.rust-lang.org/2026/04/13/Rust-1.80.0.html"
    assert meta == {"status": "ok", "etag": None, "last_modified": None}


# ---------------------------------------------------------------------------
# Test 2 — cap respected: 50 IDs → only 30 item fetches.
# ---------------------------------------------------------------------------
@respx.mock
def test_hn_cap_slices_topstories_before_fetch():
    # 50 IDs.
    many_ids = list(range(40000001, 40000051))
    respx.get(f"{BASE_URL}/topstories.json").mock(return_value=httpx.Response(200, json=many_ids))
    item_route = respx.get(url__regex=rf"{BASE_URL}/item/\d+\.json").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": 1,
                "type": "story",
                "title": "t",
                "url": "https://example.com/a",
                "time": 1776095400,
            },
        )
    )
    with _client() as client, time_machine.travel(FROZEN_NOW, tick=False):
        rows, _ = fetch(_source(), client, None, None, _config())
    # cap=30 (global default) — item endpoint hit exactly 30 times.
    assert item_route.call_count == 30
    assert len(rows) == 30


# ---------------------------------------------------------------------------
# Test 3 — UA header on every request.
# ---------------------------------------------------------------------------
@respx.mock
def test_hn_ua_header_on_every_call():
    top_route = respx.get(f"{BASE_URL}/topstories.json").mock(
        return_value=httpx.Response(200, json=[39000001])
    )
    item_route = respx.get(f"{BASE_URL}/item/39000001.json").mock(
        return_value=httpx.Response(200, json=HN_ITEM_1)
    )
    with _client() as client, time_machine.travel(FROZEN_NOW, tick=False):
        fetch(_source(cap=5), client, None, None, _config())

    assert top_route.calls.last.request.headers["user-agent"] == USER_AGENT
    assert item_route.calls.last.request.headers["user-agent"] == USER_AGENT


# ---------------------------------------------------------------------------
# Test 4 — max_age filter excludes old items.
# ---------------------------------------------------------------------------
@respx.mock
def test_hn_max_age_filter():
    respx.get(f"{BASE_URL}/topstories.json").mock(return_value=httpx.Response(200, json=[39000001]))
    respx.get(f"{BASE_URL}/item/39000001.json").mock(
        return_value=httpx.Response(200, json=HN_ITEM_1)
    )
    # Freeze 2 days ahead of the item's time so it falls outside 24h.
    future = datetime.fromtimestamp(HN_ITEM_1["time"], tz=UTC) + timedelta(days=2)
    with _client() as client, time_machine.travel(future, tick=False):
        rows, _ = fetch(_source(), client, None, None, _config(max_article_age_hours=24))
    assert rows == []


# ---------------------------------------------------------------------------
# Test 5 — no conditional-GET headers even when state is present (D-14).
# ---------------------------------------------------------------------------
@respx.mock
def test_hn_never_sends_conditional_get_headers():
    top_route = respx.get(f"{BASE_URL}/topstories.json").mock(
        return_value=httpx.Response(200, json=[39000001])
    )
    respx.get(f"{BASE_URL}/item/39000001.json").mock(
        return_value=httpx.Response(200, json=HN_ITEM_1)
    )
    with _client() as client, time_machine.travel(FROZEN_NOW, tick=False):
        fetch(
            _source(),
            client,
            state_etag='W/"abc"',
            state_last_modified="Mon, 13 Apr 2026 00:00:00 GMT",
            config=_config(),
        )
    req = top_route.calls.last.request
    assert "if-none-match" not in req.headers
    assert "if-modified-since" not in req.headers
