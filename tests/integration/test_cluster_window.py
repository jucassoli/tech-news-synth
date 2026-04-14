"""CLUSTER-01 end-to-end — helper respects ``cluster_window_hours`` cutoff."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from tech_news_synth.db.articles import ArticleRow, get_articles_in_window, upsert_batch
from tech_news_synth.db.hashing import article_hash as hash_url
from tech_news_synth.db.hashing import canonicalize_url


def _row(url: str, published_at: datetime) -> ArticleRow:
    return ArticleRow(
        source="techcrunch",
        url=url,
        canonical_url=canonicalize_url(url),
        title=url,
        summary=None,
        published_at=published_at,
        article_hash=hash_url(url),
        etag=None,
        last_modified=None,
    )


def test_cluster_window_hours_respected(db_session) -> None:
    """Seed articles across a 24h span; only last-6h subset returns."""
    now = datetime.now(UTC)
    rows = [_row(f"https://ex.com/{i}", now - timedelta(hours=i)) for i in range(24)]
    upsert_batch(db_session, rows)

    got = get_articles_in_window(db_session, hours=6)
    # Hours 0..5 → 6 rows (strictly > now-6h given tiny offsets, and we use >=)
    assert 5 <= len(got) <= 6  # floating inclusive boundary allows ~5 or 6
    for a in got:
        assert (now - a.published_at) <= timedelta(hours=6, minutes=1)
