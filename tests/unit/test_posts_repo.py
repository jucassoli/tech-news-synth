"""Unit tests for tech_news_synth.db.posts (Phase 7 Plan 07-01 Task 2).

The actual DB-backed tests live in tests/integration/test_posts_repo_phase7.py
(ARRAY + JSONB columns require a real Postgres backend). This file exists so
the contract in PLAN.md (tests/unit/test_posts_repo.py) is not empty and
verifies the new symbols are importable.
"""

from __future__ import annotations


def test_phase7_helpers_importable():
    from tech_news_synth.db.posts import (
        count_posted_today,
        get_post_tweets,
        get_stale_pending_posts,
        insert_post_tweets,
        sum_monthly_cost_usd,
        update_post_to_failed,
        update_post_to_posted,
        update_post_tweet_id,
    )

    # All helpers must be callable attributes.
    for fn in (
        update_post_to_posted,
        update_post_to_failed,
        get_stale_pending_posts,
        count_posted_today,
        sum_monthly_cost_usd,
        insert_post_tweets,
        update_post_tweet_id,
        get_post_tweets,
    ):
        assert callable(fn)
