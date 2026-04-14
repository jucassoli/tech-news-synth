"""Weighted char counting — SYNTH-04 (D-04).

Wraps ``twitter_text.parse_tweet(text).weightedLength`` so the rest of the
codebase never imports twitter_text directly. Future library swap costs one
edit here.

Pitfall notes (twitter-text-parser 3.x, verified 2026-04-13):
  - U+2026 ellipsis weighs 2 (unit-test gate in test_charcount).
  - CJK chars weigh 2 each; t.co URLs collapse to 23 regardless of length.
  - Accented Latin chars (PT-BR "ação", "não") weigh 1 per char.
"""

from __future__ import annotations

from twitter_text import parse_tweet

# Literal ellipsis used by the truncator (SYNTH-04). test_charcount asserts
# its real weighted length so the truncator's reservation stays in sync.
ELLIPSIS: str = "\u2026"


def weighted_len(text: str) -> int:
    """Return X's weighted character length for ``text`` per tweet-counting spec."""
    return int(parse_tweet(text).weightedLength)


__all__ = ["ELLIPSIS", "weighted_len"]
