"""STORE-02 — articles repository.

Module-level functions (no class) following the Phase 1 pure-function style.
Caller owns the transaction (no commit/rollback inside).

Idempotent ingest is the contract: ``upsert_batch`` uses Postgres
``INSERT ... ON CONFLICT (article_hash) DO NOTHING`` so re-feeding the same
article hash never produces duplicate rows.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
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


__all__ = ["ArticleRow", "get_by_hash", "upsert_batch"]
