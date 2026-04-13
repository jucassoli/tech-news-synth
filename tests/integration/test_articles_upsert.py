"""STORE-02 — articles upsert idempotency (ON CONFLICT DO NOTHING)."""

from __future__ import annotations

from tech_news_synth.db.articles import ArticleRow, get_by_hash, upsert_batch
from tech_news_synth.db.hashing import article_hash as hash_url
from tech_news_synth.db.hashing import canonicalize_url
from tech_news_synth.db.models import Article


def _row(url: str, title: str = "t", source: str = "src") -> ArticleRow:
    return ArticleRow(
        source=source,
        url=url,
        canonical_url=canonicalize_url(url),
        title=title,
        summary=None,
        published_at=None,
        article_hash=hash_url(url),
        etag=None,
        last_modified=None,
    )


def test_upsert_batch_inserts_and_is_idempotent(db_session) -> None:
    rows = [_row("https://ex.com/a"), _row("https://ex.com/b")]
    first = upsert_batch(db_session, rows)
    assert first == 2

    second = upsert_batch(db_session, rows)
    assert second == 0  # ON CONFLICT DO NOTHING

    # Final table state unchanged.
    assert db_session.query(Article).count() == 2


def test_upsert_collapses_canonical_dupes(db_session) -> None:
    """Two URLs that canonicalize to the same form share a hash → one row."""
    r1 = _row("https://EX.com/a?utm_source=x")
    r2 = _row("https://ex.com/a")
    assert r1["article_hash"] == r2["article_hash"], "canonicalize must collapse these"

    upsert_batch(db_session, [r1, r2])
    assert db_session.query(Article).count() == 1


def test_get_by_hash_returns_row_or_none(db_session) -> None:
    r = _row("https://ex.com/z")
    upsert_batch(db_session, [r])

    fetched = get_by_hash(db_session, r["article_hash"])
    assert fetched is not None
    assert fetched.url == "https://ex.com/z"

    assert get_by_hash(db_session, "0" * 64) is None


def test_upsert_empty_batch_returns_zero(db_session) -> None:
    assert upsert_batch(db_session, []) == 0
