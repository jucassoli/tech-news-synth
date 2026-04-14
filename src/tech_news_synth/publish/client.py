"""Phase 7 tweepy client factory + post_tweet wrapper (stub — implemented in Task 3)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class XCallOutcome:
    status: Literal["posted", "rate_limited", "publish_error"]
    tweet_id: str | None
    elapsed_ms: int
    error_detail: dict | None


def build_x_client(settings):  # noqa: ARG001
    raise NotImplementedError


def post_tweet(client, text):  # noqa: ARG001
    raise NotImplementedError


__all__ = ["XCallOutcome", "build_x_client", "post_tweet"]
