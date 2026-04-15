"""Unit tests for run_publish rate-limit (429) handling (PUBLISH-03)."""

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
        post_id=42,
        status="pending",
        counts_patch={},
    )


def _rl_detail() -> dict:
    return {
        "reason": "rate_limited",
        "status_code": 429,
        "x_rate_limit_reset": 1700000000,
        "x_rate_limit_remaining": "0",
        "x_rate_limit_limit": "300",
        "retry_after_seconds": 42,
    }


def test_429_maps_to_failed(mocker):
    session = mocker.MagicMock()
    x_client = mocker.MagicMock()
    mocker.patch("tech_news_synth.publish.orchestrator.get_post_tweets", return_value=[])
    mocker.patch("tech_news_synth.publish.orchestrator.insert_post_tweets")
    mocker.patch("tech_news_synth.publish.orchestrator.update_post_tweet_id")
    mocker.patch(
        "tech_news_synth.publish.orchestrator.post_tweet",
        return_value=XCallOutcome("rate_limited", None, 50, _rl_detail()),
    )
    update_failed = mocker.patch("tech_news_synth.publish.orchestrator.update_post_to_failed")
    mocker.patch("tech_news_synth.publish.orchestrator.update_post_to_posted")

    r = run_publish(session, "cyc", _synth(), _settings(), x_client)

    assert r.status == "failed"
    assert r.tweet_id is None
    assert r.post_id == 42
    assert r.attempts == 1
    assert r.elapsed_ms == 50
    assert r.error_detail is not None
    assert r.error_detail["reason"] == "rate_limited"
    assert r.counts_patch["publish_status"] == "failed"
    assert r.counts_patch["rate_limited"] is True
    assert r.counts_patch["tweet_id"] is None
    assert r.counts_patch["thread_parts_planned"] == 1
    assert r.counts_patch["thread_parts_posted"] == 0

    update_failed.assert_called_once()
    json_arg = update_failed.call_args.args[2]
    parsed = json.loads(json_arg)
    assert parsed["reason"] == "rate_limited"
    assert parsed["x_rate_limit_reset"] == 1700000000
    assert parsed["x_rate_limit_remaining"] == "0"
    assert parsed["x_rate_limit_limit"] == "300"
    assert parsed["retry_after_seconds"] == 42


def test_429_warn_log_emitted(mocker):
    session = mocker.MagicMock()
    x_client = mocker.MagicMock()
    mocker.patch("tech_news_synth.publish.orchestrator.get_post_tweets", return_value=[])
    mocker.patch("tech_news_synth.publish.orchestrator.insert_post_tweets")
    mocker.patch("tech_news_synth.publish.orchestrator.update_post_tweet_id")
    mocker.patch(
        "tech_news_synth.publish.orchestrator.post_tweet",
        return_value=XCallOutcome("rate_limited", None, 50, _rl_detail()),
    )
    mocker.patch("tech_news_synth.publish.orchestrator.update_post_to_failed")

    with structlog.testing.capture_logs() as captured:
        run_publish(session, "cyc", _synth(), _settings(), x_client)

    rl_lines = [
        ln
        for ln in captured
        if ln.get("event") == "rate_limit_hit" and ln.get("log_level") == "warning"
    ]
    assert rl_lines, f"expected rate_limit_hit warning; got {captured!r}"
    assert rl_lines[0]["reset_at"] is not None
    assert rl_lines[0]["retry_after_seconds"] == 42
