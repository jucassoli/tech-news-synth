"""Hacker News Firebase API fetcher (D-05, D-discretion).

Serial fetch: one GET for ``/topstories.json`` → slice to cap → one GET per
``/item/{id}.json``. At cap=30 with an httpx.Client reuse this is fast enough
(HTTP/2 multiplexing amortizes the per-request overhead) and avoids the
complexity of async for v1.

Filters:
  - only ``type == "story"`` (no ``job`` / ``poll`` / ``comment``)
  - only items with a non-empty ``url`` (skip text-only "Ask HN" in v1 —
    CONTEXT.md "Claude's Discretion")
  - older than ``config.max_article_age_hours`` → excluded

D-14: HN Firebase does NOT support conditional GET. The function signature
accepts ``state_etag`` / ``state_last_modified`` for uniformity with the
orchestrator but never sends them or echoes them back.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from tech_news_synth.ingest.http import fetch_with_retry
from tech_news_synth.ingest.models import ArticleRow
from tech_news_synth.ingest.normalize import build_article_row
from tech_news_synth.ingest.sources_config import HnFirebaseSource, SourcesConfig


def fetch(
    source: HnFirebaseSource,
    client: httpx.Client,
    state_etag: str | None,  # accepted for signature uniformity, ignored (D-14)
    state_last_modified: str | None,  # ignored
    config: SourcesConfig,
) -> tuple[list[ArticleRow], dict[str, Any]]:
    """Fetch top stories serially. Returns ``(rows, {"status":"ok", ...})``."""
    timeout = httpx.Timeout(source.timeout_sec, connect=5.0)
    cap = source.max_articles_per_fetch or config.max_articles_per_fetch

    base = str(source.url).rstrip("/")
    topstories_resp = fetch_with_retry(
        client, "GET", f"{base}/topstories.json", timeout=timeout,
    )
    topstories_resp.raise_for_status()
    ids = topstories_resp.json()[:cap]  # T-04-12: slice BEFORE iterating

    fetched_at = datetime.now(UTC)
    cutoff = fetched_at - timedelta(hours=config.max_article_age_hours)
    rows: list[ArticleRow] = []

    for item_id in ids:
        r = fetch_with_retry(
            client, "GET", f"{base}/item/{item_id}.json", timeout=timeout,
        )
        r.raise_for_status()
        item = r.json() or {}
        if item.get("type") != "story":
            continue
        url = item.get("url")
        if not url:
            # D-discretion: skip text-only stories in v1.
            continue
        title = item.get("title") or ""
        if not title:
            continue
        unix_ts = item.get("time")
        pub = datetime.fromtimestamp(unix_ts, tz=UTC) if unix_ts else None
        row = build_article_row(
            source_name=source.name,
            raw_title=title,
            raw_summary_or_html="",  # HN items carry no body worth synthesizing
            url=url,
            published_at=pub,
            fetched_at=fetched_at,
        )
        if row.published_at < cutoff:
            continue
        rows.append(row)

    rows.sort(key=lambda r: r.published_at, reverse=True)
    return rows, {"status": "ok", "etag": None, "last_modified": None}


__all__ = ["fetch"]
