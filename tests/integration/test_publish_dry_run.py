"""Integration test for PUBLISH-06 DRY_RUN=1 — no X API call, row unchanged."""

from __future__ import annotations

import pytest
import responses
from pydantic import SecretStr

from tech_news_synth.config import Settings
from tech_news_synth.db.models import RunLog
from tech_news_synth.db.posts import insert_post
from tech_news_synth.publish import run_publish
from tech_news_synth.synth.models import SynthesisResult

pytestmark = pytest.mark.integration


def _settings(dry_run: bool = True) -> Settings:
    return Settings(  # type: ignore[call-arg]
        anthropic_api_key=SecretStr("sk-ant-test"),
        x_consumer_key=SecretStr("ck"),
        x_consumer_secret=SecretStr("cs"),
        x_access_token=SecretStr("at"),
        x_access_token_secret=SecretStr("ats"),
        postgres_password=SecretStr("pw"),
        dry_run=dry_run,
    )


def _dry_synth(post_id: int, text: str) -> SynthesisResult:
    return SynthesisResult(
        text=text,
        body_text=text,
        hashtags=[],
        source_url="https://ex.com",
        attempts=1,
        final_method="completed",
        input_tokens=1,
        output_tokens=1,
        cost_usd=0.000038,
        post_id=post_id,
        status="dry_run",
        counts_patch={},
    )


def _seed_run_log(session, cycle_id: str) -> None:
    session.add(RunLog(cycle_id=cycle_id, status="ok"))
    session.flush()


def test_dry_run_no_api_call(db_session):
    """DRY_RUN path: no HTTP request made; posts row unchanged."""
    cid = "cyc-dry"
    _seed_run_log(db_session, cid)

    post = insert_post(
        session=db_session,
        cycle_id=cid,
        cluster_id=None,
        status="dry_run",
        theme_centroid=None,
        synthesized_text="dry-run body",
        hashtags=[],
        cost_usd=0.000038,
    )
    pid = post.id
    original_text = post.synthesized_text
    original_cost = post.cost_usd

    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        # No mock registered — any HTTP call would explode with ConnectionError.
        r = run_publish(
            db_session,
            cid,
            _dry_synth(pid, text=original_text),
            _settings(),
            x_client=None,
        )
        assert len(rsps.calls) == 0, f"dry_run must not call X API; got {len(rsps.calls)} calls"

    assert r.status == "dry_run"
    assert r.post_id == pid
    assert r.tweet_id is None
    assert r.counts_patch == {"publish_status": "dry_run", "tweet_id": None}

    db_session.refresh(post)
    assert post.status == "dry_run"
    assert post.tweet_id is None
    assert post.posted_at is None
    assert post.synthesized_text == original_text
    assert post.cost_usd == original_cost
