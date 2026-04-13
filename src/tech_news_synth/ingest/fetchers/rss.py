"""RSS fetcher with conditional GET (D-14).

Uses feedparser to parse bytes returned by httpx (never ``feedparser.parse(url)``
which would bypass our client, timeout, and User-Agent). Honors ETag /
Last-Modified via ``If-None-Match`` / ``If-Modified-Since`` request headers
when the caller passes a previous ``state``. On 304 Not Modified, returns an
empty list and a ``skipped_304`` status for the orchestrator. On 200, reads
``ETag`` + ``Last-Modified`` from the response headers so the orchestrator can
persist them to ``source_state``.

Filtering (D-08, D-09):
  - entries with no ``link`` or no ``title`` are skipped
  - entries older than ``config.max_article_age_hours`` are excluded
  - the final list is sorted by ``published_at`` DESC and sliced to
    ``source.max_articles_per_fetch or config.max_articles_per_fetch``

Missing ``published_parsed`` falls back to ``fetched_at`` (plan guidance) so
the entry still passes the age cutoff and downstream ordering stays sane.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import feedparser
import httpx

from tech_news_synth.ingest.http import fetch_with_retry
from tech_news_synth.ingest.models import ArticleRow
from tech_news_synth.ingest.normalize import build_article_row
from tech_news_synth.ingest.sources_config import RssSource, SourcesConfig


def fetch(
    source: RssSource,
    client: httpx.Client,
    state_etag: str | None,
    state_last_modified: str | None,
    config: SourcesConfig,
) -> tuple[list[ArticleRow], dict[str, Any]]:
    """Fetch + parse an RSS/Atom feed. See module docstring for semantics."""
    headers: dict[str, str] = {}
    if state_etag:
        headers["If-None-Match"] = state_etag
    if state_last_modified:
        headers["If-Modified-Since"] = state_last_modified

    timeout = httpx.Timeout(source.timeout_sec, connect=5.0)
    response = fetch_with_retry(
        client,
        "GET",
        str(source.url),
        timeout=timeout,
        headers=headers,
    )
    if response.status_code == 304:
        return [], {"status": "skipped_304", "etag": None, "last_modified": None}
    response.raise_for_status()

    # CRITICAL: parse bytes, never the URL — feedparser.parse(url) ignores our
    # client / timeout / UA (RESEARCH §"Pattern 3", T-04-11 mitigation since the
    # bytes have already crossed our retry layer).
    parsed = feedparser.parse(response.content)
    if parsed.bozo and not parsed.entries:
        raise RuntimeError(f"feedparser bozo: {parsed.bozo_exception!r}")

    fetched_at = datetime.now(UTC)
    cutoff = fetched_at - timedelta(hours=config.max_article_age_hours)
    cap = source.max_articles_per_fetch or config.max_articles_per_fetch

    rows: list[ArticleRow] = []
    for entry in parsed.entries:
        url = entry.get("link") or ""
        title = entry.get("title") or ""
        if not url or not title:
            continue
        summary_html = entry.get("summary") or entry.get("description") or ""
        pub = _parse_entry_published(entry)
        row = build_article_row(
            source_name=source.name,
            raw_title=title,
            raw_summary_or_html=summary_html,
            url=url,
            published_at=pub,
            fetched_at=fetched_at,
        )
        if row.published_at < cutoff:
            continue
        rows.append(row)

    rows.sort(key=lambda r: r.published_at, reverse=True)
    rows = rows[:cap]

    meta: dict[str, Any] = {
        "status": "ok",
        "etag": response.headers.get("etag"),
        "last_modified": response.headers.get("last-modified"),
    }
    return rows, meta


def _parse_entry_published(entry: Any) -> datetime | None:
    """feedparser exposes ``published_parsed`` (time.struct_time, UTC) when
    available. Falls back to ``updated_parsed``. Returns None on absence or
    malformed values — caller substitutes ``fetched_at``."""
    st = entry.get("published_parsed") or entry.get("updated_parsed")
    if st is None:
        return None
    try:
        return datetime(*st[:6], tzinfo=UTC)
    except (TypeError, ValueError):
        return None


__all__ = ["fetch"]
