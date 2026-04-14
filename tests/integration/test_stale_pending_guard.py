"""Integration tests for cleanup_stale_pending (Phase 7 Plan 07-01 Task 5, D-02)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
import structlog
from sqlalchemy import select, update

from tech_news_synth.db.models import Post, RunLog
from tech_news_synth.db.posts import insert_post
from tech_news_synth.publish.idempotency import cleanup_stale_pending

pytestmark = pytest.mark.integration


def _seed_run_log(session, cycle_id: str) -> None:
    session.add(RunLog(cycle_id=cycle_id, status="ok"))
    session.flush()


def _mk(session, cycle_id: str, status: str, text: str = "x") -> Post:
    return insert_post(
        session=session,
        cycle_id=cycle_id,
        cluster_id=None,
        status=status,
        theme_centroid=None,
        synthesized_text=text,
        hashtags=[],
        cost_usd=0.0,
    )


def _backdate(session, post_id: int, minutes_ago: int) -> None:
    session.execute(
        update(Post)
        .where(Post.id == post_id)
        .values(created_at=datetime.now(UTC) - timedelta(minutes=minutes_ago))
    )
    session.flush()


def test_stale_pending_marked_failed(db_session):
    cid = "cyc-stale-1"
    _seed_run_log(db_session, cid)
    p = _mk(db_session, cid, "pending", "old")
    _backdate(db_session, p.id, 6)

    count = cleanup_stale_pending(db_session, cutoff_minutes=5)
    assert count == 1

    db_session.refresh(p)
    assert p.status == "failed"
    assert p.error_detail is not None
    detail = json.loads(p.error_detail)
    assert detail["reason"] == "orphaned_pending_row"
    assert "detected_at" in detail
    assert "original_created_at" in detail
    # ISO 8601 UTC
    datetime.fromisoformat(detail["detected_at"])
    datetime.fromisoformat(detail["original_created_at"])


def test_fresh_pending_not_touched(db_session):
    cid = "cyc-stale-fresh"
    _seed_run_log(db_session, cid)
    p = _mk(db_session, cid, "pending", "fresh")
    # Leave created_at at "now" — not backdated.

    count = cleanup_stale_pending(db_session, cutoff_minutes=5)
    assert count == 0

    db_session.refresh(p)
    assert p.status == "pending"
    assert p.error_detail is None


def test_only_pending_status_affected(db_session):
    cid = "cyc-stale-statuses"
    _seed_run_log(db_session, cid)
    old_pending = _mk(db_session, cid, "pending", "old-pending")
    fresh_pending = _mk(db_session, cid, "pending", "fresh-pending")
    posted = _mk(db_session, cid, "posted", "p")
    failed = _mk(db_session, cid, "failed", "f")
    dry = _mk(db_session, cid, "dry_run", "d")

    # Backdate all except fresh_pending to 6 minutes ago.
    for pid in (old_pending.id, posted.id, failed.id, dry.id):
        _backdate(db_session, pid, 6)

    count = cleanup_stale_pending(db_session, cutoff_minutes=5)
    assert count == 1

    db_session.refresh(old_pending)
    db_session.refresh(fresh_pending)
    db_session.refresh(posted)
    db_session.refresh(failed)
    db_session.refresh(dry)

    assert old_pending.status == "failed"
    assert fresh_pending.status == "pending"
    assert posted.status == "posted"
    assert failed.status == "failed"
    assert dry.status == "dry_run"


def test_multiple_stale_pending_all_cleaned(db_session):
    cid = "cyc-stale-many"
    _seed_run_log(db_session, cid)

    ids = []
    for _ in range(3):
        p = _mk(db_session, cid, "pending", "x")
        _backdate(db_session, p.id, 10)
        ids.append(p.id)

    count = cleanup_stale_pending(db_session, cutoff_minutes=5)
    assert count == 3

    rows = (
        db_session.execute(select(Post).where(Post.id.in_(ids)).order_by(Post.id.asc()))
        .scalars()
        .all()
    )
    details = [json.loads(r.error_detail) for r in rows]
    assert all(r.status == "failed" for r in rows)
    assert all(d["reason"] == "orphaned_pending_row" for d in details)
    # Each row records its own original_created_at.
    assert len({d["original_created_at"] for d in details}) >= 1


def test_cleanup_logs_orphaned_pending_warn(db_session):
    cid = "cyc-stale-log"
    _seed_run_log(db_session, cid)
    p = _mk(db_session, cid, "pending", "loggy")
    _backdate(db_session, p.id, 10)

    with structlog.testing.capture_logs() as logs:
        count = cleanup_stale_pending(db_session, cutoff_minutes=5)

    assert count == 1
    matched = [e for e in logs if e.get("event") == "orphaned_pending"]
    assert len(matched) == 1
    event = matched[0]
    assert event["log_level"] == "warning"
    assert event["post_id"] == p.id
    assert event["cutoff_minutes"] == 5
