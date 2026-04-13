"""HTML sanitization + ArticleRow factory (D-discretion, T-04-09).

``strip_html`` removes tags, kills ``<script>``/``<style>`` content, collapses
whitespace, and truncates to 1000 chars. ``build_article_row`` delegates
canonicalization + hashing to Phase 2 helpers (no re-implementation) and
guarantees UTC-aware datetimes.
"""

from __future__ import annotations

from datetime import UTC, datetime

from bs4 import BeautifulSoup

from tech_news_synth.db.hashing import article_hash, canonicalize_url
from tech_news_synth.ingest.models import ArticleRow

_SUMMARY_MAX_CHARS = 1000


def strip_html(html: str) -> str:
    """Strip tags, remove script/style content, collapse whitespace, truncate.

    Deterministic — uses lxml as the parser backend for speed + robustness
    against malformed RSS HTML. Returns an empty string for empty input.
    """
    if not html:
        return ""
    soup = BeautifulSoup(html, "lxml")
    for bad in soup(["script", "style"]):
        bad.decompose()
    text = soup.get_text(" ", strip=True)
    return text[:_SUMMARY_MAX_CHARS]


def build_article_row(
    *,
    source_name: str,
    raw_title: str,
    raw_summary_or_html: str,
    url: str,
    published_at: datetime | None,
    fetched_at: datetime,
) -> ArticleRow:
    """Construct an ArticleRow from raw fetcher inputs.

    - ``published_at=None`` → falls back to ``fetched_at``
    - naive ``published_at`` → treated as UTC
    - aware ``published_at`` in another tz → converted to UTC
    - canonical_url + article_hash delegated to Phase 2 helpers
    """
    if published_at is None:
        pub = fetched_at
    elif published_at.tzinfo is None:
        pub = published_at.replace(tzinfo=UTC)
    else:
        pub = published_at.astimezone(UTC)
    return ArticleRow(
        source=source_name,
        url=url,
        canonical_url=canonicalize_url(url),
        article_hash=article_hash(url),
        title=raw_title.strip(),
        summary=strip_html(raw_summary_or_html or ""),
        published_at=pub,
        fetched_at=fetched_at,
    )


__all__ = ["build_article_row", "strip_html"]
