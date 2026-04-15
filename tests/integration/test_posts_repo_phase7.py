"""Integration tests for Phase 7 Plan 07-01 Task 2 posts-repo extensions.

Covers:
- update_posted cost_usd preservation bug fix (T-07-07 regression).
- update_post_to_posted / update_post_to_failed (D-10 transitions).
- get_stale_pending_posts (D-02).
- count_posted_today (D-05).
- sum_monthly_cost_usd (D-06).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import update

from tech_news_synth.db.models import Post, RunLog
from tech_news_synth.db.posts import (
    count_posted_today,
    get_post_tweets,
    get_stale_pending_posts,
    insert_post,
    insert_post_tweets,
    sum_monthly_cost_usd,
    update_post_to_failed,
    update_post_to_posted,
    update_post_tweet_id,
    update_posted,
)

pytestmark = pytest.mark.integration


def _seed_run_log(session, cycle_id: str) -> None:
    """Insert a run_log row so posts FK is satisfied."""
    session.add(RunLog(cycle_id=cycle_id, status="ok"))
    session.flush()


# ---------------------------------------------------------------------------
# Regression: update_posted preserves cost_usd when None is passed (T-07-07)
# ---------------------------------------------------------------------------
def test_update_posted_preserves_cost_usd(db_session) -> None:
    """update_posted(..., cost_usd=None) MUST NOT overwrite existing cost."""
    cid = "cyc-t07-07-regression"
    _seed_run_log(db_session, cid)

    post = insert_post(
        session=db_session,
        cycle_id=cid,
        cluster_id=None,
        status="pending",
        theme_centroid=None,
        synthesized_text="t",
        hashtags=[],
        cost_usd=0.000038,
    )
    assert post.cost_usd == Decimal("0.000038")

    update_posted(db_session, post.id, tweet_id="123", cost_usd=None)
    db_session.refresh(post)
    assert post.cost_usd == Decimal("0.000038"), "cost_usd must be preserved when None is passed"
    assert post.status == "posted"
    assert post.tweet_id == "123"


# ---------------------------------------------------------------------------
# update_post_to_posted
# ---------------------------------------------------------------------------
def test_update_post_to_posted_happy(db_session) -> None:
    cid = "cyc-p2p-happy"
    _seed_run_log(db_session, cid)

    post = insert_post(
        session=db_session,
        cycle_id=cid,
        cluster_id=None,
        status="pending",
        theme_centroid=None,
        synthesized_text="hello",
        hashtags=["ai"],
        cost_usd=0.00005,
        error_detail="prior attempt note",
    )
    pid = post.id
    t0 = datetime.now(UTC).replace(microsecond=0)

    update_post_to_posted(db_session, pid, tweet_id="9999", posted_at=t0)
    db_session.refresh(post)

    assert post.status == "posted"
    assert post.tweet_id == "9999"
    assert post.posted_at == t0
    assert post.error_detail is None
    assert post.cost_usd == Decimal("0.00005"), "cost_usd must be untouched"


# ---------------------------------------------------------------------------
# update_post_to_failed
# ---------------------------------------------------------------------------
def test_update_post_to_failed_preserves_cost(db_session) -> None:
    cid = "cyc-p2f-cost"
    _seed_run_log(db_session, cid)

    post = insert_post(
        session=db_session,
        cycle_id=cid,
        cluster_id=None,
        status="pending",
        theme_centroid=None,
        synthesized_text="hello",
        hashtags=[],
        cost_usd=0.00005,
    )
    pid = post.id

    update_post_to_failed(db_session, pid, error_detail_json='{"reason": "publish_error"}')
    db_session.refresh(post)

    assert post.status == "failed"
    assert post.error_detail == '{"reason": "publish_error"}'
    assert post.cost_usd == Decimal("0.00005")


def test_post_tweets_roundtrip(db_session) -> None:
    cid = "cyc-thread-roundtrip"
    _seed_run_log(db_session, cid)

    post = insert_post(
        session=db_session,
        cycle_id=cid,
        cluster_id=None,
        status="pending",
        theme_centroid=None,
        synthesized_text="root",
        hashtags=[],
        cost_usd=0.00005,
    )

    insert_post_tweets(db_session, post.id, ["root", "reply 1", "reply 2"])
    update_post_tweet_id(db_session, post.id, 1, "r1")
    update_post_tweet_id(db_session, post.id, 2, "r2")

    rows = get_post_tweets(db_session, post.id)
    assert [(row.position, row.text, row.tweet_id) for row in rows] == [
        (1, "root", "r1"),
        (2, "reply 1", "r2"),
        (3, "reply 2", None),
    ]


# ---------------------------------------------------------------------------
# get_stale_pending_posts
# ---------------------------------------------------------------------------
def test_get_stale_pending_posts_respects_cutoff(db_session) -> None:
    cid = "cyc-stale-cutoff"
    _seed_run_log(db_session, cid)

    old = insert_post(
        session=db_session,
        cycle_id=cid,
        cluster_id=None,
        status="pending",
        theme_centroid=None,
        synthesized_text="old",
        hashtags=[],
        cost_usd=0.0,
    )
    _fresh = insert_post(
        session=db_session,
        cycle_id=cid,
        cluster_id=None,
        status="pending",
        theme_centroid=None,
        synthesized_text="fresh",
        hashtags=[],
        cost_usd=0.0,
    )
    # Backdate `old` to 10 minutes ago.
    ten_min_ago = datetime.now(UTC) - timedelta(minutes=10)
    db_session.execute(update(Post).where(Post.id == old.id).values(created_at=ten_min_ago))
    db_session.flush()

    cutoff = datetime.now(UTC) - timedelta(minutes=5)
    stale = get_stale_pending_posts(db_session, cutoff)
    ids = {p.id for p in stale}
    assert old.id in ids
    assert _fresh.id not in ids


# ---------------------------------------------------------------------------
# count_posted_today
# ---------------------------------------------------------------------------
def test_count_posted_today_excludes_yesterday(db_session) -> None:
    cid = "cyc-cnt-yest"
    _seed_run_log(db_session, cid)

    now = datetime.now(UTC)
    yesterday = now - timedelta(hours=30)

    ids_today = []
    for i in range(3):
        p = insert_post(
            session=db_session,
            cycle_id=cid,
            cluster_id=None,
            status="posted",
            theme_centroid=None,
            synthesized_text=f"today-{i}",
            hashtags=[],
            cost_usd=0.0,
        )
        ids_today.append(p.id)
    ids_yest = []
    for i in range(2):
        p = insert_post(
            session=db_session,
            cycle_id=cid,
            cluster_id=None,
            status="posted",
            theme_centroid=None,
            synthesized_text=f"yest-{i}",
            hashtags=[],
            cost_usd=0.0,
        )
        ids_yest.append(p.id)

    # Set posted_at for today rows = now; yesterday rows = 30h ago.
    db_session.execute(update(Post).where(Post.id.in_(ids_today)).values(posted_at=now))
    db_session.execute(update(Post).where(Post.id.in_(ids_yest)).values(posted_at=yesterday))
    db_session.flush()

    assert count_posted_today(db_session) == 3


def test_count_posted_today_excludes_non_posted(db_session) -> None:
    cid = "cyc-cnt-status"
    _seed_run_log(db_session, cid)

    now = datetime.now(UTC)

    def mk(status: str) -> int:
        p = insert_post(
            session=db_session,
            cycle_id=cid,
            cluster_id=None,
            status=status,
            theme_centroid=None,
            synthesized_text=status,
            hashtags=[],
            cost_usd=0.0,
        )
        return p.id

    posted_id = mk("posted")
    failed_id = mk("failed")
    dry_id = mk("dry_run")
    pending_id = mk("pending")

    # All get posted_at=now so only status filter rules them out.
    db_session.execute(
        update(Post)
        .where(Post.id.in_([posted_id, failed_id, dry_id, pending_id]))
        .values(posted_at=now)
    )
    db_session.flush()

    assert count_posted_today(db_session) == 1


# ---------------------------------------------------------------------------
# sum_monthly_cost_usd
# ---------------------------------------------------------------------------
def test_sum_monthly_cost_usd_includes_posted_and_failed_excludes_dry_run(db_session) -> None:
    cid = "cyc-sum-mix"
    _seed_run_log(db_session, cid)

    def mk(status: str, cost: float) -> None:
        insert_post(
            session=db_session,
            cycle_id=cid,
            cluster_id=None,
            status=status,
            theme_centroid=None,
            synthesized_text=status,
            hashtags=[],
            cost_usd=cost,
        )

    mk("posted", 1.0)
    mk("failed", 2.0)
    mk("dry_run", 10.0)
    mk("pending", 5.0)

    total = sum_monthly_cost_usd(db_session)
    assert total == pytest.approx(3.0)


def test_sum_monthly_cost_usd_null_returns_zero(db_session) -> None:
    """Empty window → COALESCE(NULL, 0) → 0.0."""
    assert sum_monthly_cost_usd(db_session) == 0.0
