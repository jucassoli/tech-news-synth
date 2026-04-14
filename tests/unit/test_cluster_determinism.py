"""Phase 5 Plan 05-01 Task 3: determinism across runs.

Given identical sorted input (D-10), the full vectorize -> cluster -> rank
pipeline must produce identical outputs.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np
import pytest

from tech_news_synth.cluster.cluster import compute_centroid, run_agglomerative
from tech_news_synth.cluster.rank import ClusterCandidate, rank_candidates
from tech_news_synth.cluster.vectorize import fit_combined_corpus

FIXTURES = Path(__file__).parent.parent / "fixtures" / "cluster"


def _pipeline(fixture: str) -> list[ClusterCandidate]:
    articles = json.loads((FIXTURES / fixture).read_text(encoding="utf-8"))
    articles = sorted(articles, key=lambda a: (a["published_at"], a["id"]))
    texts = [f"{a['title']} {a['summary']}" for a in articles]
    fitted = fit_combined_corpus(texts, [])
    labels = run_agglomerative(fitted.X, 0.35)

    groups: dict[int, list[int]] = defaultdict(list)
    for i, label in enumerate(labels.tolist()):
        groups[label].append(i)

    candidates: list[ClusterCandidate] = []
    for label, indices in groups.items():
        members = [articles[i] for i in indices]
        sources = {m["source"] for m in members}
        most_recent = max(datetime.fromisoformat(m["published_at"]) for m in members)
        weight_sum = sum(float(m["weight"]) for m in members)
        centroid = compute_centroid(fitted.X, indices)
        candidates.append(
            ClusterCandidate(
                cluster_db_id=int(label),
                member_article_ids=[m["id"] for m in members],
                source_count=len(sources),
                most_recent_ts=most_recent,
                weight_sum=weight_sum,
                centroid=centroid,
            )
        )
    return rank_candidates(candidates)


@pytest.mark.parametrize("fixture", ["hot_topic.json", "mixed.json", "tiebreak.json"])
def test_fit_cluster_rank_deterministic_across_runs(fixture):
    r1 = _pipeline(fixture)
    r2 = _pipeline(fixture)
    # Same order, same members, same scores
    assert [c.cluster_db_id for c in r1] == [c.cluster_db_id for c in r2]
    assert [c.member_article_ids for c in r1] == [c.member_article_ids for c in r2]
    assert [c.source_count for c in r1] == [c.source_count for c in r2]
    # Centroids bit-identical
    for a, b in zip(r1, r2, strict=True):
        assert np.array_equal(a.centroid, b.centroid)


def test_tiebreak_fixture_later_cluster_wins():
    """tiebreak.json: both clusters have source_count=3; later most_recent_ts wins."""
    ranked = _pipeline("tiebreak.json")
    assert len(ranked) == 2
    # Both clusters size 3; winner is the later one (Gemini 3, ts 10:00+)
    assert ranked[0].most_recent_ts > ranked[1].most_recent_ts
