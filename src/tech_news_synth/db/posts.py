"""STORE-04 — posts repository.

Status flows: ``pending`` (insert) → ``posted`` | ``failed`` | ``dry_run``.
``theme_centroid`` BYTEA holds numpy float32 ``.tobytes()`` (D-07); caller
serializes / deserializes — repo just persists raw bytes.

Caller owns the transaction.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from tech_news_synth.db.models import Post


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


__all__ = ["insert_pending", "read_centroid", "update_failed", "update_posted"]
