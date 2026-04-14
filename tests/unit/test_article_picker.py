"""Unit tests for ``synth.article_picker.pick_articles_for_synthesis`` (D-01)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from tech_news_synth.synth.article_picker import pick_articles_for_synthesis


@dataclass
class _A:
    """Duck-typed Article stand-in — picker only reads id/source/published_at."""

    id: int
    source: str
    published_at: datetime
    title: str = "t"
    summary: str = "s"
    url: str = "u"


def _base(ts: datetime = None) -> datetime:  # type: ignore[assignment]
    return ts or datetime(2026, 4, 14, tzinfo=UTC)


def test_two_article_cluster_returns_both():
    base = _base()
    articles = [
        _A(1, "techcrunch", base),
        _A(2, "techcrunch", base + timedelta(minutes=10)),
    ]
    result = pick_articles_for_synthesis(articles, max_articles=5)
    assert len(result) == 2
    # Same source, most recent first after round 2 fill.
    assert result[0].id == 2


def test_eight_articles_three_sources():
    base = _base()
    # A:4, B:3, C:1 — expect round-1 A1/B1/C1 then round-2 A2/B2 → 5 total.
    articles = [
        _A(1, "A", base + timedelta(minutes=10)),
        _A(2, "A", base + timedelta(minutes=20)),
        _A(3, "A", base + timedelta(minutes=30)),
        _A(4, "A", base + timedelta(minutes=40)),
        _A(5, "B", base + timedelta(minutes=15)),
        _A(6, "B", base + timedelta(minutes=25)),
        _A(7, "B", base + timedelta(minutes=35)),
        _A(8, "C", base + timedelta(minutes=5)),
    ]
    result = pick_articles_for_synthesis(articles, max_articles=5)
    assert len(result) == 5
    ids = [a.id for a in result]
    # Round 1: most recent from A, B, C.
    assert set(ids[:3]) == {4, 7, 8}
    # Round 2: two next-most-recent overall (A:3 @30 and B:6 @25).
    assert set(ids[3:]) == {3, 6}


def test_three_articles_same_source():
    base = _base()
    articles = [
        _A(1, "A", base),
        _A(2, "A", base + timedelta(minutes=5)),
        _A(3, "A", base + timedelta(minutes=10)),
    ]
    result = pick_articles_for_synthesis(articles, max_articles=5)
    assert len(result) == 3
    ids = [a.id for a in result]
    # Most-recent-first ordering for the single-source case.
    assert ids[0] == 3


def test_five_distinct_sources_returns_one_each():
    base = _base()
    articles = [
        _A(1, "A", base),
        _A(2, "B", base),
        _A(3, "C", base),
        _A(4, "D", base),
        _A(5, "E", base),
    ]
    result = pick_articles_for_synthesis(articles, max_articles=5)
    assert len(result) == 5
    assert {a.source for a in result} == {"A", "B", "C", "D", "E"}


def test_ten_articles_across_seven_sources_caps_at_five():
    base = _base()
    articles = [_A(i, f"S{i % 7}", base + timedelta(minutes=i)) for i in range(10)]
    result = pick_articles_for_synthesis(articles, max_articles=5)
    assert len(result) == 5
    # All distinct sources (since 7 sources > 5 slots → no filler).
    assert len({a.source for a in result}) == 5


def test_deterministic_same_input_same_order():
    base = _base()
    articles = [
        _A(1, "A", base + timedelta(minutes=10)),
        _A(2, "B", base + timedelta(minutes=20)),
        _A(3, "A", base + timedelta(minutes=30)),
    ]
    r1 = [a.id for a in pick_articles_for_synthesis(articles, 5)]
    r2 = [a.id for a in pick_articles_for_synthesis(articles, 5)]
    assert r1 == r2


def test_empty_input():
    assert pick_articles_for_synthesis([], 5) == []
