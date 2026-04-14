"""Cluster candidate ranking (D-09).

Rank key: ``(-source_count, -most_recent_ts.timestamp(), -weight_sum)``.
Python's stable sort preserves insertion order for ties, giving
deterministic behavior when inputs are in a canonical order (D-10).
Singletons are excluded from the returned candidate list.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import numpy as np

from tech_news_synth.cluster.models import SelectionResult

__all__ = ["ClusterCandidate", "SelectionResult", "rank_candidates"]


@dataclass(frozen=True)
class ClusterCandidate:
    cluster_db_id: int
    member_article_ids: list[int]
    source_count: int
    most_recent_ts: datetime
    weight_sum: float
    centroid: np.ndarray = field(default_factory=lambda: np.zeros(0))


def rank_candidates(candidates: list[ClusterCandidate]) -> list[ClusterCandidate]:
    """Exclude singletons (source_count < 2) and sort by D-09 key."""
    multi = [c for c in candidates if c.source_count >= 2]
    return sorted(
        multi,
        key=lambda c: (
            -c.source_count,
            -c.most_recent_ts.timestamp(),
            -c.weight_sum,
        ),
    )
