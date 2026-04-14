"""Phase 5 Plan 05-01 Task 5: pick_fallback + SelectionResult."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from tech_news_synth.cluster.fallback import pick_fallback
from tech_news_synth.cluster.models import SelectionResult


@dataclass
class FakeArticle:
    id: int
    source: str
    published_at: datetime | None


TS = datetime(2026, 4, 12, 9, 0, tzinfo=UTC)
TS_LATER = datetime(2026, 4, 12, 10, 0, tzinfo=UTC)


def test_empty_returns_none():
    assert pick_fallback([], {}) is None


def test_highest_weight_wins():
    arts = [
        FakeArticle(id=1, source="a", published_at=TS),
        FakeArticle(id=2, source="b", published_at=TS),
        FakeArticle(id=3, source="c", published_at=TS),
    ]
    weights = {"a": 1.0, "b": 2.0, "c": 1.5}
    assert pick_fallback(arts, weights) == 2


def test_recency_breaks_weight_tie():
    arts = [
        FakeArticle(id=1, source="a", published_at=TS),
        FakeArticle(id=2, source="a", published_at=TS_LATER),
    ]
    assert pick_fallback(arts, {"a": 1.0}) == 2


def test_lowest_id_breaks_recency_tie():
    arts = [
        FakeArticle(id=5, source="a", published_at=TS),
        FakeArticle(id=2, source="a", published_at=TS),
    ]
    assert pick_fallback(arts, {"a": 1.0}) == 2


def test_missing_published_at_treated_as_oldest():
    arts = [
        FakeArticle(id=1, source="a", published_at=None),
        FakeArticle(id=2, source="a", published_at=TS),
    ]
    # id=2 is newer (non-None dated) → wins
    assert pick_fallback(arts, {"a": 1.0}) == 2


def test_missing_source_weight_defaults_to_1_0():
    arts = [
        FakeArticle(id=1, source="unknown_src", published_at=TS),
        FakeArticle(id=2, source="known_src", published_at=TS),
    ]
    # known_src weight=0.5 < default 1.0 → unknown_src wins
    assert pick_fallback(arts, {"known_src": 0.5}) == 1


def test_slow_day_fixture():
    data = json.loads(
        (
            Path(__file__).parent.parent / "fixtures" / "cluster" / "slow_day.json"
        ).read_text(encoding="utf-8")
    )
    arts = [
        FakeArticle(
            id=a["id"],
            source=a["source"],
            published_at=datetime.fromisoformat(a["published_at"]),
        )
        for a in data
    ]
    weights = {a.source: 1.0 for a in arts}
    chosen_id = pick_fallback(arts, weights)
    # All weights equal → most recent wins (id=6, Ubuntu 26.04 at 09:15)
    expected = max(arts, key=lambda a: (a.published_at.timestamp(), -a.id))
    assert chosen_id == expected.id


# ---------------------------------------------------------------------------
# SelectionResult
# ---------------------------------------------------------------------------
def test_selection_result_frozen():
    r = SelectionResult(
        winner_cluster_id=None,
        winner_article_ids=None,
        fallback_article_id=42,
        rejected_by_antirepeat=[],
        all_cluster_ids=[],
        counts_patch={},
    )
    with pytest.raises(ValidationError):
        r.winner_cluster_id = 5  # type: ignore[misc]


def test_selection_result_equatable():
    kw = dict(
        winner_cluster_id=7,
        winner_article_ids=[1, 2, 3],
        fallback_article_id=None,
        rejected_by_antirepeat=[9],
        all_cluster_ids=[7, 9, 11],
        counts_patch={"cluster_count": 3},
    )
    a = SelectionResult(**kw)
    b = SelectionResult(**kw)
    assert a == b
