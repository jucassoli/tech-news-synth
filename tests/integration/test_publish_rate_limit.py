"""Integration test for PUBLISH-03 429 rate-limit structured error_detail."""

from __future__ import annotations

import json

import pytest
import responses
from pydantic import SecretStr

from tech_news_synth.config import Settings
from tech_news_synth.db.models import RunLog
from tech_news_synth.db.posts import insert_post
from tech_news_synth.publish import build_x_client, run_publish
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


def _synth(post_id: int) -> SynthesisResult:
    return SynthesisResult(
        text="hello world",
        body_text="hello world",
        hashtags=[],
        source_url="https://ex.com",
        attempts=1,
        final_method="completed",
        input_tokens=1,
        output_tokens=1,
        cost_usd=0.000038,
        post_id=post_id,
        status="pending",
        counts_patch={},
    )


def _seed_run_log(session, cycle_id: str) -> None:
    session.add(RunLog(cycle_id=cycle_id, status="ok"))
    session.flush()


@responses.activate
def test_429_writes_structured_error_detail(db_session):
    cid = "cyc-429"
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
        json={"title": "Too Many Requests", "status": 429},
        status=429,
        headers={
            "x-rate-limit-reset": "1700000000",
            "x-rate-limit-remaining": "0",
            "x-rate-limit-limit": "300",
        },
    )

    x_client = build_x_client(_settings())
    result = run_publish(db_session, cid, _synth(pid), _settings(), x_client)

    assert result.status == "failed"
    assert result.counts_patch["rate_limited"] is True

    db_session.refresh(post)
    assert post.status == "failed"
    assert post.tweet_id is None
    assert post.error_detail is not None
    parsed = json.loads(post.error_detail)
    assert parsed["reason"] == "rate_limited"
    assert parsed["x_rate_limit_reset"] == 1700000000
    assert parsed["x_rate_limit_remaining"] == "0"
    assert parsed["x_rate_limit_limit"] == "300"
    assert "retry_after_seconds" in parsed
