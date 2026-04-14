"""Unit tests for ``synth.url_picker.pick_source_url`` (D-02)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from tech_news_synth.synth.url_picker import pick_source_url


@dataclass
class _A:
    id: int
    source: str
    url: str
    published_at: datetime


def _t() -> datetime:
    return datetime(2026, 4, 14, tzinfo=UTC)


def test_equal_weights_recency_wins():
    base = _t()
    articles = [
        _A(1, "A", "u_a_old", base),
        _A(2, "B", "u_b_new", base + timedelta(minutes=10)),
    ]
    assert pick_source_url(articles, {"A": 1.0, "B": 1.0}) == "u_b_new"


def test_higher_weight_beats_recency():
    base = _t()
    articles = [
        _A(1, "A", "u_a_old", base),
        _A(2, "B", "u_b_new", base + timedelta(minutes=10)),
    ]
    # A has double weight → wins despite being older.
    assert pick_source_url(articles, {"A": 2.0, "B": 1.0}) == "u_a_old"


def test_tiebreak_lowest_id_when_all_equal():
    base = _t()
    articles = [
        _A(5, "A", "u5", base),
        _A(2, "A", "u2", base),
        _A(9, "A", "u9", base),
    ]
    assert pick_source_url(articles, {"A": 1.0}) == "u2"


def test_empty_source_weights_defaults_to_one():
    base = _t()
    articles = [
        _A(1, "A", "u_a", base),
        _A(2, "B", "u_b_newer", base + timedelta(minutes=5)),
    ]
    # No weights dict → defaults to 1.0 → newest wins.
    assert pick_source_url(articles, {}) == "u_b_newer"


def test_deterministic_on_repeat_call():
    base = _t()
    articles = [
        _A(1, "A", "u1", base),
        _A(2, "B", "u2", base + timedelta(minutes=5)),
    ]
    w = {"A": 1.0, "B": 1.0}
    assert pick_source_url(articles, w) == pick_source_url(articles, w)
