"""Unit tests for ``synth.truncate.word_boundary_truncate`` (SYNTH-04, D-06).

Invariant: ``weighted_len(result) <= max_weighted`` for any input.
"""

from __future__ import annotations

import pytest

from tech_news_synth.synth.charcount import ELLIPSIS, weighted_len
from tech_news_synth.synth.truncate import word_boundary_truncate


def test_ellipsis_weight_gate():
    """Confirms the truncator's reservation assumption holds."""
    assert weighted_len(ELLIPSIS) == 2


def test_passthrough_when_under_budget():
    assert word_boundary_truncate("hello world", 20) == "hello world"


def test_cuts_at_whitespace_and_appends_ellipsis():
    result = word_boundary_truncate("one two three four five", 12)
    # Result must end in ellipsis and be within budget.
    assert result.endswith(ELLIPSIS)
    assert weighted_len(result) <= 12
    # Word-boundary: no partial word at the end (excluding the ellipsis).
    head = result[: -len(ELLIPSIS)]
    assert not head.endswith(" ")
    # The body must be a prefix of the original text (up to a whitespace).
    assert "one two three four five".startswith(head.rstrip())


def test_char_level_fallback_when_no_whitespace():
    result = word_boundary_truncate("abcdefghij", 6)
    assert result.endswith(ELLIPSIS)
    assert weighted_len(result) <= 6


def test_long_repeating_input_respects_budget():
    text = "word " * 50
    result = word_boundary_truncate(text, 30)
    assert weighted_len(result) <= 30
    assert result.endswith(ELLIPSIS)


@pytest.mark.parametrize(
    "text,budget",
    [
        ("hello world this is a test", 10),
        ("a b c d e f g h i j k l m n o p q r", 14),
        ("ação não é só um acento, também um símbolo cultural", 20),
        ("kubernetes sidecar containers GA release notes", 25),
        ("中文 测试 budget truncation path", 12),
    ],
)
def test_invariant_always_within_budget(text, budget):
    result = word_boundary_truncate(text, budget)
    assert weighted_len(result) <= budget
