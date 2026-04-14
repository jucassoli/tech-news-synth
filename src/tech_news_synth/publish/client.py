"""Phase 7 tweepy client factory + post_tweet wrapper.

D-01: tweepy.Client with OAuth 1.0a 4-secret User Context and
``return_type=requests.Response`` (required for rate-limit header access per
Phase 3 research).
D-07/D-08: exception → structured ``error_detail`` mapping. post_tweet never
raises — callers get a typed ``XCallOutcome`` and persist accordingly.
Research §1, §9: tweepy 4.14 exposes no ``timeout`` kwarg; enforce via
``functools.partial`` monkey-wrap of ``client.session.request`` (T-07-08).
T-07-03: ``SecretStr.get_secret_value()`` called inline only; ``error_detail``
never embeds secret values (only exception type names, truncated messages,
api_codes/messages from X).
"""

from __future__ import annotations

import functools
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

import requests
import tweepy

if TYPE_CHECKING:
    from tech_news_synth.config import Settings


@dataclass(frozen=True)
class XCallOutcome:
    status: Literal["posted", "rate_limited", "publish_error"]
    tweet_id: str | None
    elapsed_ms: int
    error_detail: dict | None


def build_x_client(settings: "Settings") -> tweepy.Client:
    """Build a per-cycle tweepy.Client with enforced timeout.

    D-13: constructed once per cycle; no explicit close (tweepy wraps a
    ``requests.Session`` internally).
    """
    client = tweepy.Client(
        consumer_key=settings.x_consumer_key.get_secret_value(),
        consumer_secret=settings.x_consumer_secret.get_secret_value(),
        access_token=settings.x_access_token.get_secret_value(),
        access_token_secret=settings.x_access_token_secret.get_secret_value(),
        return_type=requests.Response,
        wait_on_rate_limit=False,
    )
    # tweepy.Client has no `timeout` kwarg; monkey-wrap session.request
    # so every HTTP call gets the configured timeout (T-07-08).
    _orig_request = client.session.request
    client.session.request = functools.partial(
        _orig_request, timeout=settings.x_api_timeout_sec
    )
    return client


def post_tweet(client: tweepy.Client, text: str) -> XCallOutcome:
    """Single ``create_tweet`` call with exception → error_detail mapping.

    Never raises — returns a structured outcome for the orchestrator.
    """
    start = time.monotonic()
    try:
        r = client.create_tweet(text=text)
        elapsed_ms = int((time.monotonic() - start) * 1000)
        tweet_id = r.json()["data"]["id"]
        return XCallOutcome("posted", str(tweet_id), elapsed_ms, None)
    except tweepy.TooManyRequests as e:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        headers = getattr(e.response, "headers", {}) or {}
        reset_str = headers.get("x-rate-limit-reset") or "0"
        try:
            reset_epoch = int(reset_str)
        except (TypeError, ValueError):
            reset_epoch = 0
        return XCallOutcome(
            "rate_limited",
            None,
            elapsed_ms,
            {
                "reason": "rate_limited",
                "status_code": 429,
                "x_rate_limit_reset": reset_epoch,
                "x_rate_limit_remaining": headers.get("x-rate-limit-remaining"),
                "x_rate_limit_limit": headers.get("x-rate-limit-limit"),
                "retry_after_seconds": max(0, reset_epoch - int(time.time())),
            },
        )
    except tweepy.HTTPException as e:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        resp = getattr(e, "response", None)
        headers = getattr(resp, "headers", {}) if resp is not None else {}
        status_code = getattr(resp, "status_code", None)
        api_messages = list(getattr(e, "api_messages", []) or [])
        is_duplicate = status_code == 422 and any(
            "duplicate" in str(m).lower() for m in api_messages
        )
        return XCallOutcome(
            "publish_error",
            None,
            elapsed_ms,
            {
                "reason": "duplicate_tweet" if is_duplicate else "publish_error",
                "status_code": status_code,
                "tweepy_error_type": type(e).__name__,
                "message": str(e)[:500],
                "api_codes": list(getattr(e, "api_codes", []) or []),
                "api_messages": api_messages,
                "x_rate_limit_reset": headers.get("x-rate-limit-reset"),
                "x_rate_limit_remaining": headers.get("x-rate-limit-remaining"),
            },
        )
    except Exception as e:  # network / timeout / unknown
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return XCallOutcome(
            "publish_error",
            None,
            elapsed_ms,
            {
                "reason": "publish_error",
                "status_code": None,
                "tweepy_error_type": type(e).__name__,
                "message": str(e)[:500],
            },
        )


__all__ = ["XCallOutcome", "build_x_client", "post_tweet"]
