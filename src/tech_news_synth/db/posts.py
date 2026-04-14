"""STORE-04 — posts repository.

Status flows: ``pending`` (insert) → ``posted`` | ``failed`` | ``dry_run``.
``theme_centroid`` BYTEA holds numpy float32 ``.tobytes()`` (D-07); caller
serializes / deserializes — repo just persists raw bytes.

Caller owns the transaction.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from tech_news_synth.db.models import Article, Cluster, Post


@dataclass(frozen=True)
class PostWithTexts:
    """A posted tweet paired with the cluster member articles' source texts.

    Used by Phase 5 anti-repeat to build a combined TF-IDF corpus (D-01).
    Each text is ``f"{title} {summary or ''}"`` — matches the current-cycle
    vectorization input.
    """

    post_id: int
    source_texts: list[str]


def insert_pending(
    session: Session,
    cycle_id: str,
    cluster_id: int | None,
    synthesized_text: str | None = None,
    hashtags: Sequence[str] | None = None,
) -> Post:
    """Insert a row in ``status='pending'`` (created_at = server now())."""
    post = Post(
        cycle_id=cycle_id,
        cluster_id=cluster_id,
        status="pending",
        synthesized_text=synthesized_text,
        hashtags=list(hashtags) if hashtags is not None else [],
    )
    session.add(post)
    session.flush()
    return post


def update_posted(
    session: Session,
    post_id: int,
    tweet_id: str,
    cost_usd: float | Decimal | None,
    centroid_bytes: bytes | None = None,
) -> Post:
    """Mark a post ``status='posted'``; sets tweet_id, cost, posted_at, centroid."""
    post = session.execute(select(Post).where(Post.id == post_id)).scalar_one()
    post.status = "posted"
    post.tweet_id = tweet_id
    post.cost_usd = Decimal(str(cost_usd)) if cost_usd is not None else None
    post.posted_at = datetime.now(UTC)
    if centroid_bytes is not None:
        post.theme_centroid = centroid_bytes
    session.flush()
    return post


def update_failed(session: Session, post_id: int, error_detail: str) -> Post:
    """Mark a post ``status='failed'`` and store error message."""
    post = session.execute(select(Post).where(Post.id == post_id)).scalar_one()
    post.status = "failed"
    post.error_detail = error_detail
    session.flush()
    return post


def read_centroid(session: Session, post_id: int) -> bytes | None:
    """Return the raw centroid bytes (or None if unset)."""
    return session.execute(
        select(Post.theme_centroid).where(Post.id == post_id)
    ).scalar_one_or_none()


def get_recent_posts_with_source_texts(
    session: Session, within_hours: int
) -> list[PostWithTexts]:
    """Posts with ``status='posted'`` AND ``posted_at > now - hours``, joined
    to their cluster's article texts (research P-9).

    We filter ``status='posted'`` explicitly — pending/failed/dry_run tweets
    never reached the timeline and must not block reposts of the same topic.
    Posts whose ``cluster_id`` is NULL are also excluded (no source texts to
    compare against).
    """
    cutoff = datetime.now(UTC) - timedelta(hours=within_hours)
    post_rows = session.execute(
        select(Post.id, Post.cluster_id)
        .where(Post.status == "posted")
        .where(Post.posted_at.is_not(None))
        .where(Post.posted_at > cutoff)
        .where(Post.cluster_id.is_not(None))
        .order_by(Post.id.asc())
    ).all()

    if not post_rows:
        return []

    results: list[PostWithTexts] = []
    for post_id, cluster_id in post_rows:
        cluster = session.execute(
            select(Cluster).where(Cluster.id == cluster_id)
        ).scalar_one_or_none()
        if cluster is None or not cluster.member_article_ids:
            continue
        rows = list(
            session.execute(
                select(Article.title, Article.summary)
                .where(Article.id.in_(cluster.member_article_ids))
                .order_by(Article.id.asc())
            ).all()
        )
        texts = [f"{title} {summary or ''}".strip() for title, summary in rows]
        if texts:
            results.append(PostWithTexts(post_id=post_id, source_texts=texts))
    return results


__all__ = [
    "PostWithTexts",
    "get_recent_posts_with_source_texts",
    "insert_pending",
    "read_centroid",
    "update_failed",
    "update_posted",
]
