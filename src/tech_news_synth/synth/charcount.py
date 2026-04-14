"""Weighted char counting — stub for Plan 06-01 Task 1.

Task 2 implements ``weighted_len`` as a wrapper around twitter_text.parse_tweet.
"""

from __future__ import annotations

ELLIPSIS: str = "\u2026"


def weighted_len(text: str) -> int:  # noqa: ARG001
    raise NotImplementedError("Plan 06-01 Task 2 implements weighted_len")


__all__ = ["ELLIPSIS", "weighted_len"]
