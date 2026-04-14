"""Unit tests for ``synth.charcount.weighted_len`` (SYNTH-04, D-04).

Proves the twitter-text-parser wrapper returns expected weights for
ASCII, accented PT, t.co URLs, emoji, CJK, ellipsis, and empty strings.
The ellipsis assertion is a gate (T-06-07): if the upstream lib changes
ellipsis weight, this test fails loudly so the truncator's budget logic
can be updated in lockstep.
"""

from __future__ import annotations

import pytest

from tech_news_synth.synth.charcount import ELLIPSIS, weighted_len


@pytest.mark.parametrize(
    "text,expected",
    [
        ("hello", 5),
        ("Olá mundo, ação já", 18),
        ("https://t.co/abcdefghij", 23),
        ("", 0),
    ],
)
def test_weighted_len_ascii_and_accented(text, expected):
    assert weighted_len(text) == expected


def test_weighted_len_emoji_weight_two():
    # Emoji weights 2 in the twitter-text-parser rules.
    assert weighted_len("😀") == 2


def test_weighted_len_cjk_weight_two_per_char():
    assert weighted_len("中文") == 4


def test_ellipsis_weighted_len_gate():
    """T-06-07 gate: truncator reserves ELLIPSIS weight; assert the real value."""
    # Observed with twitter-text-parser 3.x: U+2026 weighs 2.
    # If this changes, update truncate.word_boundary_truncate reservation.
    assert weighted_len(ELLIPSIS) == 2
