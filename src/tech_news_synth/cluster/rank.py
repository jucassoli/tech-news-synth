"""Cluster candidate ranking (D-09).

Plan 05-01 Task 1 scaffold — Task 3 implements ``rank_candidates``.
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
    """Stub — real implementation in Task 3."""
    raise NotImplementedError("cluster.rank.rank_candidates implemented in Task 3")
