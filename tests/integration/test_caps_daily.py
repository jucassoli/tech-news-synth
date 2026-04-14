"""Integration tests for check_caps daily cap (Phase 7 Plan 07-01 Task 4, PUBLISH-04)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import SecretStr
from sqlalchemy import update

from tech_news_synth.config import Settings
from tech_news_synth.db.models import Post, RunLog
from tech_news_synth.db.posts import insert_post
from tech_news_synth.publish.caps import check_caps

pytestmark = pytest.mark.integration


def _settings(**overrides) -> Settings:
    base = {
        "anthropic_api_key": SecretStr("sk-ant-test"),
        "x_consumer_key": SecretStr("ck"),
        "x_consumer_secret": SecretStr("cs"),
        "x_access_token": SecretStr("at"),
        "x_access_token_secret": SecretStr("ats"),
        "postgres_password": SecretStr("pw"),
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def _seed_run_log(session, cycle_id: str) -> None:
    session.add(RunLog(cycle_id=cycle_id, status="ok"))
    session.flush()


def _seed_posted(session, cycle_id: str, n: int, posted_at: datetime) -> list[int]:
    ids: list[int] = []
    for i in range(n):
        p = insert_post(
            session=session,
            cycle_id=cycle_id,
            cluster_id=None,
            status="posted",
            theme_centroid=None,
            synthesized_text=f"t-{i}",
            hashtags=[],
            cost_usd=0.0,
        )
        ids.append(p.id)
    session.execute(update(Post).where(Post.id.in_(ids)).values(posted_at=posted_at))
    session.flush()
    return ids


def test_seeded_12_posted_triggers_cap(db_session):
    cid = "cyc-cap-day-12"
    _seed_run_log(db_session, cid)
    _seed_posted(db_session, cid, 12, datetime.now(UTC))

    result = check_caps(db_session, _settings(max_posts_per_day=12))
    assert result.daily_count == 12
    assert result.daily_reached is True
    assert result.skip_synthesis is True


def test_11_posted_does_not_trigger(db_session):
    cid = "cyc-cap-day-11"
    _seed_run_log(db_session, cid)
    _seed_posted(db_session, cid, 11, datetime.now(UTC))

    result = check_caps(db_session, _settings(max_posts_per_day=12))
    assert result.daily_count == 11
    assert result.daily_reached is False
    assert result.skip_synthesis is False


def test_yesterday_posts_do_not_count(db_session):
    cid = "cyc-cap-day-yest"
    _seed_run_log(db_session, cid)
    yesterday = datetime.now(UTC) - timedelta(hours=30)
    _seed_posted(db_session, cid, 12, yesterday)

    result = check_caps(db_session, _settings(max_posts_per_day=12))
    assert result.daily_count == 0
    assert result.daily_reached is False


def test_pending_failed_dry_run_do_not_count(db_session):
    cid = "cyc-cap-day-statuses"
    _seed_run_log(db_session, cid)
    now = datetime.now(UTC)

    posted_ids = _seed_posted(db_session, cid, 10, now)
    assert len(posted_ids) == 10

    other_ids: list[int] = []
    for status in ("failed", "failed", "failed", "failed", "failed"):
        p = insert_post(
            session=db_session,
            cycle_id=cid,
            cluster_id=None,
            status=status,
            theme_centroid=None,
            synthesized_text="x",
            hashtags=[],
            cost_usd=0.0,
        )
        other_ids.append(p.id)
    for status in ("dry_run", "dry_run", "dry_run", "dry_run", "dry_run"):
        p = insert_post(
            session=db_session,
            cycle_id=cid,
            cluster_id=None,
            status=status,
            theme_centroid=None,
            synthesized_text="x",
            hashtags=[],
            cost_usd=0.0,
        )
        other_ids.append(p.id)
    for status in ("pending", "pending", "pending", "pending", "pending"):
        p = insert_post(
            session=db_session,
            cycle_id=cid,
            cluster_id=None,
            status=status,
            theme_centroid=None,
            synthesized_text="x",
            hashtags=[],
            cost_usd=0.0,
        )
        other_ids.append(p.id)

    db_session.execute(update(Post).where(Post.id.in_(other_ids)).values(posted_at=now))
    db_session.flush()

    result = check_caps(db_session, _settings(max_posts_per_day=12))
    assert result.daily_count == 10
    assert result.daily_reached is False
