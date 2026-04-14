"""Phase 5 Plan 05-01 Task 3: rank_candidates."""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np

from tech_news_synth.cluster.rank import ClusterCandidate, rank_candidates


def _make(cluster_db_id, source_count, most_recent_ts, weight_sum):
    return ClusterCandidate(
        cluster_db_id=cluster_db_id,
        member_article_ids=[cluster_db_id * 10],
        source_count=source_count,
        most_recent_ts=most_recent_ts,
        weight_sum=weight_sum,
        centroid=np.zeros(1),
    )


def test_excludes_singletons():
    ts = datetime(2026, 4, 12, 9, 0, tzinfo=UTC)
    out = rank_candidates([_make(1, 1, ts, 1.0), _make(2, 2, ts, 2.0)])
    assert len(out) == 1
    assert out[0].cluster_db_id == 2


def test_primary_key_source_count_desc():
    ts = datetime(2026, 4, 12, 9, 0, tzinfo=UTC)
    out = rank_candidates([_make(1, 2, ts, 1.0), _make(2, 4, ts, 1.0), _make(3, 3, ts, 1.0)])
    assert [c.source_count for c in out] == [4, 3, 2]


def test_tiebreak_recency_desc():
    earlier = datetime(2026, 4, 12, 8, 0, tzinfo=UTC)
    later = datetime(2026, 4, 12, 10, 0, tzinfo=UTC)
    out = rank_candidates([_make(1, 3, earlier, 1.0), _make(2, 3, later, 1.0)])
    assert [c.cluster_db_id for c in out] == [2, 1]


def test_tiebreak2_weight_sum_desc():
    ts = datetime(2026, 4, 12, 9, 0, tzinfo=UTC)
    out = rank_candidates([_make(1, 3, ts, 1.0), _make(2, 3, ts, 5.0), _make(3, 3, ts, 3.0)])
    assert [c.weight_sum for c in out] == [5.0, 3.0, 1.0]


def test_empty_returns_empty():
    assert rank_candidates([]) == []


def test_stable_sort_preserves_insertion_order_on_full_tie():
    ts = datetime(2026, 4, 12, 9, 0, tzinfo=UTC)
    a = _make(1, 3, ts, 1.0)
    b = _make(2, 3, ts, 1.0)
    c = _make(3, 3, ts, 1.0)
    out = rank_candidates([a, b, c])
    assert [x.cluster_db_id for x in out] == [1, 2, 3]
