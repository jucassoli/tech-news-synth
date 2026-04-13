"""STORE-04 — posts repo: status CHECK + theme_centroid BYTEA roundtrip."""

from __future__ import annotations

from decimal import Decimal

import numpy as np
import pytest
from sqlalchemy.exc import IntegrityError

from tech_news_synth.db.models import Post
from tech_news_synth.db.posts import (
    insert_pending,
    read_centroid,
    update_failed,
    update_posted,
)
from tech_news_synth.db.run_log import start_cycle


def _seed(db_session, cycle_id: str) -> str:
    start_cycle(db_session, cycle_id)
    return cycle_id


def test_insert_pending_sets_status_and_created_at(db_session) -> None:
    cid = _seed(db_session, "01PENDING00000000000000001")
    post = insert_pending(
        db_session,
        cycle_id=cid,
        cluster_id=None,
        synthesized_text="hello",
        hashtags=["ai", "tech"],
    )
    assert post.id is not None
    assert post.status == "pending"
    assert post.created_at is not None
    assert post.posted_at is None
    assert post.hashtags == ["ai", "tech"]


@pytest.mark.parametrize("status", ["pending", "posted", "failed", "dry_run"])
def test_all_four_statuses_accepted(db_session, status: str) -> None:
    suffix = status.upper().ljust(20, "0")[:20]
    cid = _seed(db_session, f"01CID{suffix}1")[:26]
    post = Post(cycle_id=cid, status=status)
    db_session.add(post)
    db_session.flush()
    assert post.id is not None


def test_invalid_status_raises_integrity_error(db_session) -> None:
    cid = _seed(db_session, "01BADSTATUS00000000000001")
    db_session.add(Post(cycle_id=cid, status="bogus"))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_centroid_bytes_roundtrip_through_db(db_session) -> None:
    """STORE-04 D-07: numpy float32 .tobytes() survives DB roundtrip."""
    cid = _seed(db_session, "01CENTROID0000000000000001")
    vec = np.asarray([0.1, -0.2, 0.3, 0.4, 0.5], dtype=np.float32)

    post = insert_pending(
        db_session,
        cycle_id=cid,
        cluster_id=None,
        synthesized_text="hello",
        hashtags=["tag"],
    )
    update_posted(
        db_session,
        post.id,
        tweet_id="1234567890",
        cost_usd=0.000042,
        centroid_bytes=vec.tobytes(),
    )

    db_session.flush()
    db_session.refresh(post)
    assert post.status == "posted"
    assert post.tweet_id == "1234567890"
    assert post.cost_usd == Decimal("0.000042")
    assert post.theme_centroid is not None

    restored = np.frombuffer(post.theme_centroid, dtype=np.float32)
    np.testing.assert_array_equal(vec, restored)

    assert post.posted_at is not None
    # created_at stamped at insert; posted_at stamped at update — distinct.
    assert post.created_at != post.posted_at


def test_read_centroid_helper(db_session) -> None:
    cid = _seed(db_session, "01READCENTROID000000000001")
    vec = np.asarray([1.0, 2.0, 3.0], dtype=np.float32)
    post = insert_pending(db_session, cycle_id=cid, cluster_id=None)
    update_posted(db_session, post.id, tweet_id="t", cost_usd=None, centroid_bytes=vec.tobytes())

    blob = read_centroid(db_session, post.id)
    assert blob is not None
    assert np.array_equal(np.frombuffer(blob, dtype=np.float32), vec)


def test_update_failed_sets_error_detail(db_session) -> None:
    cid = _seed(db_session, "01FAILED000000000000000001")
    post = insert_pending(db_session, cycle_id=cid, cluster_id=None)
    update_failed(db_session, post.id, error_detail="HTTP 429 from upstream")

    db_session.flush()
    db_session.refresh(post)
    assert post.status == "failed"
    assert post.error_detail == "HTTP 429 from upstream"
