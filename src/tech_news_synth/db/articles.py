"""STORE-02 — articles repository.

Module-level functions (no class) following the Phase 1 pure-function style.
Caller owns the transaction (no commit/rollback inside).

Idempotent ingest is the contract: ``upsert_batch`` uses Postgres
``INSERT ... ON CONFLICT (article_hash) DO NOTHING`` so re-feeding the same
article hash never produces duplicate rows.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import TypedDict

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from tech_news_synth.db.models import Article


class ArticleRow(TypedDict, total=False):
    """Row shape for ``upsert_batch``. Match column nullability of Article."""

    source: str
    url: str
    canonical_url: str
    title: str
    summary: str | None
    published_at: datetime | None
    article_hash: str
    etag: str | None
    last_modified: str | None


def upsert_batch(session: Session, rows: Sequence[ArticleRow]) -> int:
    """Insert ``rows`` ignoring conflicts on ``article_hash`` (STORE-02).

    Returns the number of rows actually inserted (Postgres ``rowcount`` for
    ``ON CONFLICT DO NOTHING``). Caller commits.
    """
    if not rows:
        return 0
    stmt = (
        pg_insert(Article)
        .values(list(rows))
        .on_conflict_do_nothing(index_elements=["article_hash"])
        .returning(Article.id)
    )
    result = session.execute(stmt)
    return len(result.scalars().all())


def get_by_hash(session: Session, article_hash: str) -> Article | None:
    return session.execute(
        select(Article).where(Article.article_hash == article_hash)
    ).scalar_one_or_none()


def get_articles_in_window(session: Session, hours: int) -> list[Article]:
    """Articles with ``published_at >= now() - hours``, deterministically ordered.

    Sort key is ``(published_at ASC, id ASC)`` — this ordering is the
    substrate of Phase 5's determinism contract (research P-5, D-10).
    Articles with ``published_at IS NULL`` are excluded (cannot place them
    in window).
    """
    cutoff = datetime.now(UTC) - timedelta(hours=hours)
    return list(
        session.execute(
            select(Article)
            .where(Article.published_at.is_not(None))
            .where(Article.published_at >= cutoff)
            .order_by(Article.published_at.asc(), Article.id.asc())
        ).scalars()
    )


__all__ = ["ArticleRow", "get_articles_in_window", "get_by_hash", "upsert_batch"]
