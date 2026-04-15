"""Unit tests for tech_news_synth.publish.orchestrator.run_publish (Plan 07-02 Task 1).

Covers the happy-path 'posted' branch, log contextvar binding, JSON
serializability of error_detail, and the no-cost_usd regression guard
against T-07-07.
"""

from __future__ import annotations

import json

import structlog
from pydantic import SecretStr

from tech_news_synth.config import Settings
from tech_news_synth.publish.client import XCallOutcome
from tech_news_synth.publish.models import PublishResult
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


def _synth(
    status: str = "pending", post_id: int | None = 42, text: str = "hello world"
) -> SynthesisResult:
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
        counts_patch={"post_id": post_id},
    )


def _patch_thread_repo(mocker):
    mocker.patch("tech_news_synth.publish.orchestrator.get_post_tweets", return_value=[])
    mocker.patch("tech_news_synth.publish.orchestrator.insert_post_tweets")
    return mocker.patch("tech_news_synth.publish.orchestrator.update_post_tweet_id")


def test_posted_happy_path(mocker):
    session = mocker.MagicMock(name="session")
    x_client = mocker.MagicMock(name="x_client")
    update_thread_tweet = _patch_thread_repo(mocker)
    mocker.patch(
        "tech_news_synth.publish.orchestrator.post_tweet",
        return_value=XCallOutcome("posted", "999", 120, None),
    )
    update_posted = mocker.patch("tech_news_synth.publish.orchestrator.update_post_to_posted")
    update_failed = mocker.patch("tech_news_synth.publish.orchestrator.update_post_to_failed")

    result = run_publish(session, "cyc-1", _synth(), _settings(), x_client)

    assert isinstance(result, PublishResult)
    assert result.status == "posted"
    assert result.post_id == 42
    assert result.tweet_id == "999"
    assert result.attempts == 1
    assert result.elapsed_ms == 120
    assert result.error_detail is None
    assert result.counts_patch == {
        "publish_status": "posted",
        "tweet_id": "999",
        "publish_elapsed_ms": 120,
        "thread_parts_planned": 1,
        "thread_parts_posted": 1,
    }

    update_posted.assert_called_once()
    update_thread_tweet.assert_called_once()
    args = update_posted.call_args.args
    assert args[0] is session
    assert args[1] == 42
    assert args[2] == "999"
    # posted_at arg is a UTC datetime
    update_failed.assert_not_called()


def test_posted_does_not_touch_cost_usd(mocker):
    """T-07-07 regression guard: orchestrator calls update_post_to_posted
    (which never writes cost_usd), not the legacy update_posted helper.
    """
    session = mocker.MagicMock(name="session")
    x_client = mocker.MagicMock(name="x_client")
    _patch_thread_repo(mocker)
    mocker.patch(
        "tech_news_synth.publish.orchestrator.post_tweet",
        return_value=XCallOutcome("posted", "1", 5, None),
    )
    # legacy update_posted MUST NOT be referenced by the orchestrator:
    legacy = mocker.patch("tech_news_synth.db.posts.update_posted")
    mocker.patch("tech_news_synth.publish.orchestrator.update_post_to_posted")

    run_publish(session, "cyc", _synth(), _settings(), x_client)

    legacy.assert_not_called()


def test_binds_phase_publish_log_context(mocker):
    """PUBLISH: every orchestrator log line carries phase='publish'."""
    session = mocker.MagicMock(name="session")
    x_client = mocker.MagicMock(name="x_client")
    _patch_thread_repo(mocker)
    mocker.patch(
        "tech_news_synth.publish.orchestrator.post_tweet",
        return_value=XCallOutcome("posted", "999", 10, None),
    )
    mocker.patch("tech_news_synth.publish.orchestrator.update_post_to_posted")

    with structlog.testing.capture_logs() as captured:
        run_publish(session, "cyc-log", _synth(), _settings(), x_client)

    assert any(ln.get("phase") == "publish" for ln in captured), (
        f"expected at least one log line with phase='publish'; got {captured!r}"
    )


def test_error_detail_is_json_serializable(mocker):
    """The string passed to update_post_to_failed must round-trip JSON."""
    session = mocker.MagicMock(name="session")
    x_client = mocker.MagicMock(name="x_client")
    _patch_thread_repo(mocker)
    complex_detail = {
        "reason": "publish_error",
        "status_code": 500,
        "tweepy_error_type": "HTTPException",
        "message": "boom",
        "api_codes": [42],
        "api_messages": ["a", "b"],
    }
    mocker.patch(
        "tech_news_synth.publish.orchestrator.post_tweet",
        return_value=XCallOutcome("publish_error", None, 33, complex_detail),
    )
    update_failed = mocker.patch("tech_news_synth.publish.orchestrator.update_post_to_failed")
    mocker.patch("tech_news_synth.publish.orchestrator.update_post_to_posted")

    run_publish(session, "cyc-err", _synth(), _settings(), x_client)

    assert update_failed.called
    json_arg = update_failed.call_args.args[2]
    parsed = json.loads(json_arg)  # must round-trip
    assert parsed["reason"] == "publish_error"
    assert parsed["status_code"] == 500


def test_status_capped_and_empty_constructable():
    """PublishResult model accepts scheduler-level status values
    ('capped', 'empty') even though run_publish itself does not emit them.
    """
    for status in ("capped", "empty"):
        r = PublishResult(
            post_id=None,
            status=status,  # type: ignore[arg-type]
            tweet_id=None,
            attempts=0,
            elapsed_ms=0,
            error_detail=None,
            counts_patch={"publish_status": status},
        )
        assert r.status == status


def test_generic_error_branch_counts_patch(mocker):
    """publish_error → counts_patch contains publish_error_reason, not rate_limited."""
    session = mocker.MagicMock(name="session")
    x_client = mocker.MagicMock(name="x_client")
    _patch_thread_repo(mocker)
    mocker.patch(
        "tech_news_synth.publish.orchestrator.post_tweet",
        return_value=XCallOutcome(
            "publish_error",
            None,
            80,
            {"reason": "duplicate_tweet", "status_code": 422, "tweepy_error_type": "HTTPException"},
        ),
    )
    mocker.patch("tech_news_synth.publish.orchestrator.update_post_to_failed")
    mocker.patch("tech_news_synth.publish.orchestrator.update_post_to_posted")

    r = run_publish(session, "cyc-422", _synth(), _settings(), x_client)

    assert r.status == "failed"
    assert r.counts_patch["publish_status"] == "failed"
    assert r.counts_patch["publish_error_reason"] == "duplicate_tweet"
    assert r.counts_patch["thread_parts_planned"] == 1
    assert r.counts_patch["thread_parts_posted"] == 0
    assert "rate_limited" not in r.counts_patch


def test_multi_part_thread_posts_sequentially(mocker):
    session = mocker.MagicMock(name="session")
    x_client = mocker.MagicMock(name="x_client")
    mocker.patch("tech_news_synth.publish.orchestrator.get_post_tweets", return_value=[])
    insert_parts = mocker.patch("tech_news_synth.publish.orchestrator.insert_post_tweets")
    update_thread = mocker.patch("tech_news_synth.publish.orchestrator.update_post_tweet_id")
    update_posted = mocker.patch("tech_news_synth.publish.orchestrator.update_post_to_posted")
    mocker.patch("tech_news_synth.publish.orchestrator.update_post_to_failed")
    post_call = mocker.patch(
        "tech_news_synth.publish.orchestrator.post_tweet",
        side_effect=[
            XCallOutcome("posted", "r1", 20, None),
            XCallOutcome("posted", "r2", 30, None),
            XCallOutcome("posted", "r3", 40, None),
        ],
    )

    synth = _synth()
    synth = synth.model_copy(
        update={
            "thread_texts": ["root", "reply 1", "reply 2"],
            "reply_texts": ["reply 1", "reply 2"],
        }
    )

    result = run_publish(session, "cyc-thread", synth, _settings(), x_client)

    assert result.status == "posted"
    assert result.tweet_id == "r1"
    assert result.tweet_ids == ["r1", "r2", "r3"]
    assert result.parts_posted == 3
    assert result.elapsed_ms == 90
    assert result.counts_patch["thread_parts_planned"] == 3
    assert result.counts_patch["thread_parts_posted"] == 3
    insert_parts.assert_called_once_with(session, 42, ["root", "reply 1", "reply 2"])
    assert [
        call.kwargs["in_reply_to_tweet_id"] for call in post_call.call_args_list
    ] == [None, "r1", "r2"]
    assert [call.args[2] for call in update_thread.call_args_list] == [1, 2, 3]
    update_posted.assert_called_once()


def test_thread_failure_midway_preserves_posted_prefix(mocker):
    session = mocker.MagicMock(name="session")
    x_client = mocker.MagicMock(name="x_client")
    mocker.patch("tech_news_synth.publish.orchestrator.get_post_tweets", return_value=[])
    mocker.patch("tech_news_synth.publish.orchestrator.insert_post_tweets")
    update_thread = mocker.patch("tech_news_synth.publish.orchestrator.update_post_tweet_id")
    update_failed = mocker.patch("tech_news_synth.publish.orchestrator.update_post_to_failed")
    mocker.patch("tech_news_synth.publish.orchestrator.update_post_to_posted")
    mocker.patch(
        "tech_news_synth.publish.orchestrator.post_tweet",
        side_effect=[
            XCallOutcome("posted", "r1", 20, None),
            XCallOutcome(
                "publish_error",
                None,
                30,
                {"reason": "publish_error", "status_code": 500},
            ),
        ],
    )

    synth = _synth()
    synth = synth.model_copy(update={"thread_texts": ["root", "reply 1"]})

    result = run_publish(session, "cyc-thread", synth, _settings(), x_client)

    assert result.status == "failed"
    assert result.tweet_id == "r1"
    assert result.tweet_ids == ["r1"]
    assert result.parts_posted == 1
    assert result.failed_part == 2
    assert result.counts_patch["thread_parts_planned"] == 2
    assert result.counts_patch["thread_parts_posted"] == 1
    assert result.counts_patch["thread_failed_part"] == 2
    update_thread.assert_called_once()
    update_failed.assert_called_once()
