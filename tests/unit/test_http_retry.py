"""Unit tests for tech_news_synth.ingest.http (D-06, INGEST-03, T-04-03/04).

Uses respx to mock httpx calls. Patches ``time.sleep`` to no-op so the
3-retry exponential backoff doesn't add real wall-clock time to the test.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from tech_news_synth.ingest.http import (
    USER_AGENT,
    build_http_client,
    fetch_with_retry,
)


@pytest.fixture(autouse=True)
def _no_sleep(mocker):
    """Patch tenacity's sleep + stdlib time.sleep so retries are instant."""
    mocker.patch("tenacity.nap.time.sleep", return_value=None)


# ---------------------------------------------------------------------------
# Test 1 — UA + client config
# ---------------------------------------------------------------------------
def test_build_http_client_sets_user_agent():
    client = build_http_client()
    try:
        assert client.headers["User-Agent"] == USER_AGENT
        assert USER_AGENT == "ByteRelevant/0.1 (+https://x.com/ByteRelevant)"
        assert client.follow_redirects is True
    finally:
        client.close()


# ---------------------------------------------------------------------------
# Test 2 — 5xx retry: exactly 3 attempts
# ---------------------------------------------------------------------------
def test_5xx_retries_exactly_three_times():
    with respx.mock() as router:
        route = router.get("https://example.com/feed").mock(
            return_value=httpx.Response(500, text="boom")
        )
        client = build_http_client()
        try:
            with pytest.raises(httpx.HTTPStatusError):
                fetch_with_retry(client, "GET", "https://example.com/feed")
        finally:
            client.close()
        assert route.call_count == 3


# ---------------------------------------------------------------------------
# Test 3 — 4xx does NOT retry and does NOT raise (caller decides)
# ---------------------------------------------------------------------------
def test_4xx_no_retry_returns_response():
    with respx.mock() as router:
        route = router.get("https://example.com/feed").mock(
            return_value=httpx.Response(404, text="nope")
        )
        client = build_http_client()
        try:
            resp = fetch_with_retry(client, "GET", "https://example.com/feed")
        finally:
            client.close()
        assert resp.status_code == 404
        assert route.call_count == 1


# ---------------------------------------------------------------------------
# Test 4 — 304 returned unchanged, no retry (conditional GET semantics)
# ---------------------------------------------------------------------------
def test_304_returned_unchanged():
    with respx.mock() as router:
        route = router.get("https://example.com/feed").mock(return_value=httpx.Response(304))
        client = build_http_client()
        try:
            resp = fetch_with_retry(client, "GET", "https://example.com/feed")
        finally:
            client.close()
        assert resp.status_code == 304
        assert route.call_count == 1


# ---------------------------------------------------------------------------
# Test 5 — 200 happy path
# ---------------------------------------------------------------------------
def test_200_happy_path():
    with respx.mock() as router:
        route = router.get("https://example.com/feed").mock(
            return_value=httpx.Response(200, text="ok")
        )
        client = build_http_client()
        try:
            resp = fetch_with_retry(client, "GET", "https://example.com/feed")
        finally:
            client.close()
        assert resp.status_code == 200
        assert route.call_count == 1


# ---------------------------------------------------------------------------
# Test 6 — eventual success: 503 → 503 → 200
# ---------------------------------------------------------------------------
def test_eventual_success_after_two_5xx():
    with respx.mock() as router:
        route = router.get("https://example.com/feed").mock(
            side_effect=[
                httpx.Response(503),
                httpx.Response(503),
                httpx.Response(200, text="ok"),
            ]
        )
        client = build_http_client()
        try:
            resp = fetch_with_retry(client, "GET", "https://example.com/feed")
        finally:
            client.close()
        assert resp.status_code == 200
        assert route.call_count == 3


# ---------------------------------------------------------------------------
# Test 7 — timeout / transport errors retry too
# ---------------------------------------------------------------------------
def test_transport_error_retries_three_times():
    with respx.mock() as router:
        route = router.get("https://example.com/feed").mock(side_effect=httpx.ReadTimeout("slow"))
        client = build_http_client()
        try:
            with pytest.raises(httpx.TransportError):
                fetch_with_retry(client, "GET", "https://example.com/feed")
        finally:
            client.close()
        assert route.call_count == 3


# ---------------------------------------------------------------------------
# Test 8 — 429 treated as retryable (rate-limit)
# ---------------------------------------------------------------------------
def test_429_retries_like_5xx():
    with respx.mock() as router:
        route = router.get("https://example.com/feed").mock(return_value=httpx.Response(429))
        client = build_http_client()
        try:
            with pytest.raises(httpx.HTTPStatusError):
                fetch_with_retry(client, "GET", "https://example.com/feed")
        finally:
            client.close()
        assert route.call_count == 3


# ---------------------------------------------------------------------------
# Test 9 — UA header present on EVERY request (belt-and-suspenders)
# ---------------------------------------------------------------------------
def test_user_agent_sent_on_every_request():
    with respx.mock() as router:
        route = router.get("https://example.com/feed").mock(
            return_value=httpx.Response(200, text="ok")
        )
        client = build_http_client()
        try:
            fetch_with_retry(client, "GET", "https://example.com/feed")
        finally:
            client.close()
        assert route.calls[0].request.headers["user-agent"] == USER_AGENT
