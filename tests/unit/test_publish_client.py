"""Unit tests for tech_news_synth.publish.client (Phase 7 Plan 07-01 Task 3).

Uses the ``responses`` library (tweepy uses ``requests`` internally; respx
is httpx-only and cannot intercept those calls).
"""

from __future__ import annotations

import json

import pytest
import requests
import responses
import tweepy
from pydantic import SecretStr

from tech_news_synth.config import Settings
from tech_news_synth.publish.client import XCallOutcome, build_x_client, post_tweet

X_TWEETS_URL = "https://api.twitter.com/2/tweets"


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


def test_build_x_client_constructor():
    s = _settings()
    c = build_x_client(s)
    assert isinstance(c, tweepy.Client)
    assert c.consumer_key == "ck"
    assert c.consumer_secret == "cs"
    assert c.access_token == "at"
    assert c.access_token_secret == "ats"
    # return_type set via constructor kwarg
    assert c.return_type is requests.Response


def test_timeout_enforced():
    """T-07-08: session.request wrapped with functools.partial(timeout=30)."""
    import functools as ft

    s = _settings()
    c = build_x_client(s)
    assert isinstance(c.session.request, ft.partial)
    assert c.session.request.keywords == {"timeout": 30}


def test_timeout_custom_value():
    s = _settings(x_api_timeout_sec=15)
    c = build_x_client(s)
    assert c.session.request.keywords == {"timeout": 15}  # type: ignore[union-attr]


@responses.activate
def test_post_tweet_success_parses_id():
    s = _settings()
    c = build_x_client(s)
    responses.add(
        responses.POST,
        X_TWEETS_URL,
        json={"data": {"id": "1234567890", "text": "hi"}},
        status=201,
    )
    out = post_tweet(c, "hi")
    assert isinstance(out, XCallOutcome)
    assert out.status == "posted"
    assert out.tweet_id == "1234567890"
    assert out.elapsed_ms >= 0
    assert out.error_detail is None


@responses.activate
def test_post_tweet_429_captures_headers():
    s = _settings()
    c = build_x_client(s)
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
    out = post_tweet(c, "hi")
    assert out.status == "rate_limited"
    assert out.tweet_id is None
    assert out.error_detail is not None
    assert out.error_detail["reason"] == "rate_limited"
    assert out.error_detail["status_code"] == 429
    assert out.error_detail["x_rate_limit_reset"] == 1700000000
    assert out.error_detail["x_rate_limit_remaining"] == "0"
    assert out.error_detail["x_rate_limit_limit"] == "300"
    assert "retry_after_seconds" in out.error_detail


@responses.activate
def test_post_tweet_422_duplicate():
    s = _settings()
    c = build_x_client(s)
    responses.add(
        responses.POST,
        X_TWEETS_URL,
        json={
            "title": "Forbidden",
            "detail": "You are not allowed to create a Tweet with duplicate content.",
            "type": "about:blank",
            "status": 422,
            "errors": [
                {"message": "You are not allowed to create a Tweet with duplicate content."}
            ],
        },
        status=422,
    )
    out = post_tweet(c, "hi")
    assert out.status == "publish_error"
    assert out.error_detail is not None
    assert out.error_detail["status_code"] == 422
    assert out.error_detail["reason"] == "duplicate_tweet"
    # tweepy raises Forbidden subclass for 403; for 422 it raises HTTPException directly
    assert out.error_detail["tweepy_error_type"] in {"HTTPException", "BadRequest", "Forbidden"}


@responses.activate
def test_post_tweet_500_generic():
    s = _settings()
    c = build_x_client(s)
    responses.add(
        responses.POST,
        X_TWEETS_URL,
        json={"title": "Internal", "status": 500},
        status=500,
    )
    out = post_tweet(c, "hi")
    assert out.status == "publish_error"
    assert out.error_detail is not None
    assert out.error_detail["status_code"] == 500
    assert out.error_detail["reason"] == "publish_error"


def test_post_tweet_timeout_caught(mocker):
    s = _settings()
    c = build_x_client(s)

    def boom(*args, **kwargs):
        raise requests.exceptions.ReadTimeout("read timed out")

    mocker.patch.object(c, "session", mocker.MagicMock())
    c.session.request = boom

    out = post_tweet(c, "hi")
    assert out.status == "publish_error"
    assert out.error_detail is not None
    assert out.error_detail["reason"] == "publish_error"
    assert out.error_detail["tweepy_error_type"] == "ReadTimeout"


@responses.activate
def test_post_tweet_secrets_not_in_error_detail():
    """T-07-03: no OAuth secret value appears in error_detail."""
    s = _settings()
    c = build_x_client(s)
    responses.add(
        responses.POST,
        X_TWEETS_URL,
        json={"title": "Unauthorized", "status": 401, "errors": [{"message": "bad auth"}]},
        status=401,
    )
    out = post_tweet(c, "hi")
    payload = json.dumps(out.error_detail)
    for secret in ("ck", "cs", "at", "ats"):
        # Check the literal secret does not appear as a substring.
        assert f'"{secret}"' not in payload
        assert f"={secret}" not in payload
