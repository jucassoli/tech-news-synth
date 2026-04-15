"""Unit test for 422 duplicate-tweet handling (cross-cutting)."""

from __future__ import annotations

import json

import structlog
from pydantic import SecretStr

from tech_news_synth.config import Settings
from tech_news_synth.publish.client import XCallOutcome
from tech_news_synth.publish.orchestrator import run_publish
from tech_news_synth.synth.models import SynthesisResult


def _settings() -> Settings:
    return Settings(  # type: ignore[call-arg]
        anthropic_api_key=SecretStr("sk-ant-test"),
        x_consumer_key=SecretStr("ck"),
        x_consumer_secret=SecretStr("cs"),
        x_access_token=SecretStr("at"),
        x_access_token_secret=SecretStr("ats"),
        postgres_password=SecretStr("pw"),
    )


def _synth() -> SynthesisResult:
    return SynthesisResult(
        text="body url #tag",
        body_text="body",
        hashtags=["tag"],
        source_url="https://ex.com",
        attempts=1,
        final_method="completed",
        input_tokens=1,
        output_tokens=1,
        cost_usd=0.000038,
        post_id=7,
        status="pending",
        counts_patch={},
    )


def test_422_duplicate_tweet_flagged(mocker):
    session = mocker.MagicMock()
    x_client = mocker.MagicMock()
    mocker.patch("tech_news_synth.publish.orchestrator.get_post_tweets", return_value=[])
    mocker.patch("tech_news_synth.publish.orchestrator.insert_post_tweets")
    mocker.patch("tech_news_synth.publish.orchestrator.update_post_tweet_id")
    detail = {
        "reason": "duplicate_tweet",
        "status_code": 422,
        "tweepy_error_type": "HTTPException",
        "message": "duplicate content",
        "api_codes": [],
        "api_messages": ["You are not allowed to create a Tweet with duplicate content."],
    }
    mocker.patch(
        "tech_news_synth.publish.orchestrator.post_tweet",
        return_value=XCallOutcome("publish_error", None, 80, detail),
    )
    update_failed = mocker.patch("tech_news_synth.publish.orchestrator.update_post_to_failed")

    with structlog.testing.capture_logs() as captured:
        r = run_publish(session, "cyc-422", _synth(), _settings(), x_client)

    assert r.status == "failed"
    assert r.error_detail is not None
    assert r.error_detail["reason"] == "duplicate_tweet"
    assert r.counts_patch["publish_status"] == "failed"
    assert r.counts_patch.get("publish_error_reason") == "duplicate_tweet"
    assert r.counts_patch["thread_parts_planned"] == 1
    assert r.counts_patch["thread_parts_posted"] == 0
    # rate_limited flag MUST NOT be set on non-429 errors
    assert "rate_limited" not in r.counts_patch

    # Persisted JSON round-trips + preserves reason.
    json_arg = update_failed.call_args.args[2]
    parsed = json.loads(json_arg)
    assert parsed["reason"] == "duplicate_tweet"
    assert parsed["status_code"] == 422

    # publish_failed ERROR log emitted
    err_lines = [ln for ln in captured if ln.get("event") == "publish_failed"]
    assert err_lines, f"expected publish_failed log; got {captured!r}"
    assert err_lines[0]["reason"] == "duplicate_tweet"
    assert err_lines[0]["status_code"] == 422
