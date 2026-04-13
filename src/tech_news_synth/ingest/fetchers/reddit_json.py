"""Reddit r/technology JSON fetcher (D-05, D-14).

RESEARCH A1 note: Reddit's unauthenticated ``.json`` endpoint posture is
uncertain in 2026. If live traffic returns 403/429 persistently, this fetcher
will accumulate failures and auto-disable per D-12 within ~40h (20 x 2h
interval). Operators can manually re-enable or wait for Phase 8 OPS-04.

Filters:
  - ``stickied == True`` → dropped (mod/pinned posts, not news)
  - ``is_self == True`` → dropped (self-posts have no external destination;
    their ``url`` field points back at the reddit thread itself)
  - empty/missing ``url`` or ``title`` → dropped
  - entries older than ``config.max_article_age_hours`` → excluded

D-14: no conditional GET.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from tech_news_synth.ingest.http import fetch_with_retry
from tech_news_synth.ingest.models import ArticleRow
from tech_news_synth.ingest.normalize import build_article_row
from tech_news_synth.ingest.sources_config import RedditJsonSource, SourcesConfig


def fetch(
    source: RedditJsonSource,
    client: httpx.Client,
    state_etag: str | None,  # ignored (D-14)
    state_last_modified: str | None,  # ignored
    config: SourcesConfig,
) -> tuple[list[ArticleRow], dict[str, Any]]:
    timeout = httpx.Timeout(source.timeout_sec, connect=5.0)
    cap = source.max_articles_per_fetch or config.max_articles_per_fetch

    response = fetch_with_retry(client, "GET", str(source.url), timeout=timeout)
    response.raise_for_status()
    payload = response.json()

    children = payload.get("data", {}).get("children", [])
    fetched_at = datetime.now(UTC)
    cutoff = fetched_at - timedelta(hours=config.max_article_age_hours)
    rows: list[ArticleRow] = []

    for ch in children:
        data = ch.get("data", {})
        if data.get("stickied"):
            continue
        if data.get("is_self"):
            # Self-posts have no external destination; their `url` points back
            # at the reddit thread itself.
            continue
        url = data.get("url") or ""
        if not url:
            continue
        title = data.get("title") or ""
        if not title:
            continue
        created_utc = data.get("created_utc")
        pub = datetime.fromtimestamp(created_utc, tz=UTC) if created_utc else None
        summary = data.get("selftext") or ""
        row = build_article_row(
            source_name=source.name,
            raw_title=title,
            raw_summary_or_html=summary,
            url=url,
            published_at=pub,
            fetched_at=fetched_at,
        )
        if row.published_at < cutoff:
            continue
        rows.append(row)

    rows.sort(key=lambda r: r.published_at, reverse=True)
    rows = rows[:cap]
    return rows, {"status": "ok", "etag": None, "last_modified": None}


__all__ = ["fetch"]
