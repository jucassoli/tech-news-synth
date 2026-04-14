"""D-02 stale-pending guard.

Runs at cycle start BEFORE new publish attempt. Any ``status='pending'``
row older than cutoff is presumed orphaned (container crashed mid-call
between ``create_tweet`` success and DB UPDATE) and transitions to
``failed`` with a structured ``error_detail`` JSON for operator
investigation.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from tech_news_synth.db.posts import get_stale_pending_posts, update_post_to_failed
from tech_news_synth.logging import get_logger

log = get_logger(__name__)


def cleanup_stale_pending(session: Session, cutoff_minutes: int) -> int:
    """Mark orphaned pending rows as failed. Returns count of rows cleaned.

    Operator runbook: ``docs/runbook-orphaned-pending.md`` — if a tweet was
    actually posted to @ByteRelevant despite this row being marked failed,
    operator manually runs::

        UPDATE posts SET status='posted', tweet_id='<id>', error_detail=NULL
        WHERE id=<row>;
    """
    now = datetime.now(UTC)
    cutoff = now - timedelta(minutes=cutoff_minutes)
    stale = get_stale_pending_posts(session, cutoff)
    for post in stale:
        error_detail = json.dumps(
            {
                "reason": "orphaned_pending_row",
                "detected_at": now.isoformat(),
                "original_created_at": (post.created_at.isoformat() if post.created_at else None),
            },
            ensure_ascii=False,
        )
        update_post_to_failed(session, post.id, error_detail)
        log.warning(
            "orphaned_pending",
            post_id=post.id,
            created_at=post.created_at.isoformat() if post.created_at else None,
            cutoff_minutes=cutoff_minutes,
        )
    return len(stale)


__all__ = ["cleanup_stale_pending"]
