"""Integration tests for check_caps monthly cost cap (Phase 7 Plan 07-01 Task 4, PUBLISH-05)."""

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


def test_sum_over_budget_triggers(db_session):
    cid = "cyc-cap-mo-over"
    _seed_run_log(db_session, cid)

    insert_post(
        session=db_session,
        cycle_id=cid,
        cluster_id=None,
        status="posted",
        theme_centroid=None,
        synthesized_text="a",
        hashtags=[],
        cost_usd=20.0,
    )
    insert_post(
        session=db_session,
        cycle_id=cid,
        cluster_id=None,
        status="failed",
        theme_centroid=None,
        synthesized_text="b",
        hashtags=[],
        cost_usd=11.0,
    )

    result = check_caps(db_session, _settings(max_monthly_cost_usd=30.0))
    assert result.monthly_cost_usd == pytest.approx(31.0)
    assert result.monthly_cost_reached is True
    assert result.skip_synthesis is True


def test_dry_run_excluded_from_monthly(db_session):
    cid = "cyc-cap-mo-dry"
    _seed_run_log(db_session, cid)

    insert_post(
        session=db_session,
        cycle_id=cid,
        cluster_id=None,
        status="posted",
        theme_centroid=None,
        synthesized_text="a",
        hashtags=[],
        cost_usd=5.0,
    )
    insert_post(
        session=db_session,
        cycle_id=cid,
        cluster_id=None,
        status="dry_run",
        theme_centroid=None,
        synthesized_text="b",
        hashtags=[],
        cost_usd=100.0,
    )

    result = check_caps(db_session, _settings(max_monthly_cost_usd=30.0))
    assert result.monthly_cost_usd == pytest.approx(5.0)
    assert result.monthly_cost_reached is False


def test_last_month_posts_excluded(db_session):
    cid = "cyc-cap-mo-prev"
    _seed_run_log(db_session, cid)

    p = insert_post(
        session=db_session,
        cycle_id=cid,
        cluster_id=None,
        status="posted",
        theme_centroid=None,
        synthesized_text="a",
        hashtags=[],
        cost_usd=100.0,
    )
    # Backdate created_at to 40 days ago (previous month guaranteed).
    db_session.execute(
        update(Post)
        .where(Post.id == p.id)
        .values(created_at=datetime.now(UTC) - timedelta(days=40))
    )
    db_session.flush()

    result = check_caps(db_session, _settings(max_monthly_cost_usd=30.0))
    assert result.monthly_cost_usd == 0.0
    assert result.monthly_cost_reached is False


def test_failed_rows_counted_in_monthly(db_session):
    cid = "cyc-cap-mo-failed"
    _seed_run_log(db_session, cid)

    insert_post(
        session=db_session,
        cycle_id=cid,
        cluster_id=None,
        status="failed",
        theme_centroid=None,
        synthesized_text="a",
        hashtags=[],
        cost_usd=15.0,
    )

    result = check_caps(db_session, _settings(max_monthly_cost_usd=30.0))
    assert result.monthly_cost_usd == pytest.approx(15.0)
    assert result.monthly_cost_reached is False
