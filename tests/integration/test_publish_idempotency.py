"""Integration test for PUBLISH-02 idempotency: pending → posted full roundtrip,
and a mid-call crash simulation where the stale-pending guard cleans the
orphaned row so the NEXT cycle does not re-publish it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
import responses
from pydantic import SecretStr
from sqlalchemy import update

from tech_news_synth.config import Settings
from tech_news_synth.db.models import Post, RunLog
from tech_news_synth.db.posts import insert_post
from tech_news_synth.publish import build_x_client, cleanup_stale_pending, run_publish
from tech_news_synth.synth.models import SynthesisResult

pytestmark = pytest.mark.integration

X_TWEETS_URL = "https://api.twitter.com/2/tweets"


def _settings() -> Settings:
    return Settings(  # type: ignore[call-arg]
        anthropic_api_key=SecretStr("sk-ant-test"),
        x_consumer_key=SecretStr("ck"),
        x_consumer_secret=SecretStr("cs"),
        x_access_token=SecretStr("at"),
        x_access_token_secret=SecretStr("ats"),
        postgres_password=SecretStr("pw"),
    )


def _synth(post_id: int, status: str = "pending", text: str = "hello world") -> SynthesisResult:
    return SynthesisResult(
        text=text,
        body_text=text,
        hashtags=[],
        source_url="https://example.com",
        attempts=1,
        final_method="completed",
        input_tokens=10,
        output_tokens=5,
        cost_usd=0.000038,
        post_id=post_id,
        status=status,  # type: ignore[arg-type]
        counts_patch={},
    )


def _seed_run_log(session, cycle_id: str) -> None:
    session.add(RunLog(cycle_id=cycle_id, status="ok"))
    session.flush()


@responses.activate
def test_pending_to_posted_full_roundtrip(db_session):
    cid = "cyc-pub-happy"
    _seed_run_log(db_session, cid)

    post = insert_post(
        session=db_session,
        cycle_id=cid,
        cluster_id=None,
        status="pending",
        theme_centroid=None,
        synthesized_text="hello world",
        hashtags=[],
        cost_usd=0.000038,
    )
    pid = post.id

    responses.add(
        responses.POST,
        X_TWEETS_URL,
        json={"data": {"id": "X1", "text": "hello world"}},
        status=201,
    )

    x_client = build_x_client(_settings())
    result = run_publish(db_session, cid, _synth(pid), _settings(), x_client)

    assert result.status == "posted"
    assert result.tweet_id == "X1"

    # Verify DB state
    db_session.refresh(post)
    assert post.status == "posted"
    assert post.tweet_id == "X1"
    assert post.posted_at is not None
    assert post.error_detail is None
    # cost_usd preserved (not overwritten by publish transition)
    assert post.cost_usd == Decimal("0.000038")


def test_mid_call_crash_simulated_by_stale_guard(db_session):
    """A prior-cycle orphan (pending >5min) is marked failed by the
    stale-pending guard, and a NEW publish targets a different post_id —
    proving the old row is not re-published.
    """
    cid_old = "cyc-pub-orphan"
    _seed_run_log(db_session, cid_old)
    orphan = insert_post(
        session=db_session,
        cycle_id=cid_old,
        cluster_id=None,
        status="pending",
        theme_centroid=None,
        synthesized_text="orphaned",
        hashtags=[],
        cost_usd=0.000038,
    )
    orphan_id = orphan.id
    # Backdate to 6 min ago.
    db_session.execute(
        update(Post)
        .where(Post.id == orphan_id)
        .values(created_at=datetime.now(UTC) - timedelta(minutes=6))
    )
    db_session.flush()

    # Cleanup: should transition orphan -> failed.
    cleaned = cleanup_stale_pending(db_session, cutoff_minutes=5)
    assert cleaned == 1

    db_session.refresh(orphan)
    assert orphan.status == "failed"
    assert orphan.error_detail is not None
    assert "orphaned_pending_row" in orphan.error_detail

    # A new publish happens against a new post row — old one remains untouched.
    new_post = insert_post(
        session=db_session,
        cycle_id=cid_old,
        cluster_id=None,
        status="pending",
        theme_centroid=None,
        synthesized_text="fresh",
        hashtags=[],
        cost_usd=0.000038,
    )
    new_pid = new_post.id
    assert new_pid != orphan_id

    with responses.RequestsMock() as rsps:
        rsps.add(
            rsps.POST,
            X_TWEETS_URL,
            json={"data": {"id": "X2", "text": "fresh"}},
            status=201,
        )
        x_client = build_x_client(_settings())
        r = run_publish(db_session, cid_old, _synth(new_pid, text="fresh"), _settings(), x_client)
        assert r.status == "posted"
        assert r.post_id == new_pid

    db_session.refresh(orphan)
    # Orphan still failed, NOT accidentally re-posted
    assert orphan.status == "failed"
    assert orphan.tweet_id is None
    db_session.refresh(new_post)
    assert new_post.status == "posted"
    assert new_post.tweet_id == "X2"
