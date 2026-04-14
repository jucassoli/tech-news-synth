"""Unit tests for dry_run short-circuit composition (PUBLISH-06)."""

from __future__ import annotations

import structlog
from pydantic import SecretStr

from tech_news_synth.config import Settings
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


def _dry_synth(post_id: int = 7) -> SynthesisResult:
    return SynthesisResult(
        text="draft",
        body_text="draft",
        hashtags=[],
        source_url="https://ex.com",
        attempts=1,
        final_method="completed",
        input_tokens=1,
        output_tokens=1,
        cost_usd=0.0,
        post_id=post_id,
        status="dry_run",
        counts_patch={},
    )


def test_dry_run_short_circuits(mocker):
    session = mocker.MagicMock()
    post_tweet = mocker.patch("tech_news_synth.publish.orchestrator.post_tweet")
    update_posted = mocker.patch("tech_news_synth.publish.orchestrator.update_post_to_posted")
    update_failed = mocker.patch("tech_news_synth.publish.orchestrator.update_post_to_failed")

    with structlog.testing.capture_logs() as captured:
        r = run_publish(session, "cyc-dr", _dry_synth(post_id=7), _settings(), None)

    assert r.status == "dry_run"
    assert r.post_id == 7
    assert r.tweet_id is None
    assert r.attempts == 0
    assert r.elapsed_ms == 0
    assert r.error_detail is None
    assert r.counts_patch == {"publish_status": "dry_run", "tweet_id": None}

    post_tweet.assert_not_called()
    update_posted.assert_not_called()
    update_failed.assert_not_called()

    skip_lines = [ln for ln in captured if ln.get("event") == "publish_skipped_dry_run"]
    assert skip_lines, f"expected publish_skipped_dry_run log; got {captured!r}"
    assert skip_lines[0]["post_id"] == 7


def test_dry_run_tolerates_no_x_client(mocker):
    """x_client=None must not raise in dry_run path."""
    session = mocker.MagicMock()
    mocker.patch("tech_news_synth.publish.orchestrator.post_tweet")

    # Should not raise
    r = run_publish(session, "cyc", _dry_synth(), _settings(), x_client=None)
    assert r.status == "dry_run"
