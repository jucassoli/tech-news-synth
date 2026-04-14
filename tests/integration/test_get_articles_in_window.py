"""CLUSTER-01 — ``get_articles_in_window`` window semantics + determinism."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from tech_news_synth.db.articles import ArticleRow, get_articles_in_window, upsert_batch
from tech_news_synth.db.hashing import article_hash as hash_url
from tech_news_synth.db.hashing import canonicalize_url


def _row(url: str, published_at: datetime | None, title: str = "t") -> ArticleRow:
    return ArticleRow(
        source="techcrunch",
        url=url,
        canonical_url=canonicalize_url(url),
        title=title,
        summary=None,
        published_at=published_at,
        article_hash=hash_url(url),
        etag=None,
        last_modified=None,
    )


def test_returns_articles_in_window(db_session) -> None:
    now = datetime.now(UTC)
    rows = [
        _row("https://ex.com/a", now - timedelta(hours=1)),
        _row("https://ex.com/b", now - timedelta(hours=3)),
        _row("https://ex.com/c", now - timedelta(hours=5)),
        _row("https://ex.com/d", now - timedelta(hours=10)),
    ]
    upsert_batch(db_session, rows)

    got = get_articles_in_window(db_session, hours=6)
    assert len(got) == 3
    # ASC published_at order: 5h first, 1h last
    assert got[0].url.endswith("/c")
    assert got[1].url.endswith("/b")
    assert got[2].url.endswith("/a")


def test_excludes_null_published_at(db_session) -> None:
    now = datetime.now(UTC)
    rows = [
        _row("https://ex.com/p", now - timedelta(hours=1)),
        _row("https://ex.com/n", None),
    ]
    upsert_batch(db_session, rows)

    got = get_articles_in_window(db_session, hours=6)
    assert len(got) == 1
    assert got[0].published_at is not None


def test_deterministic_ordering_with_id_tiebreak(db_session) -> None:
    now = datetime.now(UTC)
    ts = now - timedelta(hours=2)
    # Insert in non-sorted order to prove DB sorts by id too.
    rows = [
        _row("https://ex.com/3", ts, "third"),
        _row("https://ex.com/1", ts, "first"),
        _row("https://ex.com/2", ts, "second"),
    ]
    upsert_batch(db_session, rows)

    got = get_articles_in_window(db_session, hours=6)
    assert len(got) == 3
    ids = [a.id for a in got]
    assert ids == sorted(ids)

    # Determinism: second call same sequence.
    again = get_articles_in_window(db_session, hours=6)
    assert [a.id for a in again] == ids


def test_empty_window(db_session) -> None:
    assert get_articles_in_window(db_session, hours=6) == []
