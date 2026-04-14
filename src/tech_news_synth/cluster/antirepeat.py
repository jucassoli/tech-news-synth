"""Anti-repetition check via cosine similarity to 48h post centroids (D-01, D-03).

Plan 05-01 Task 1 scaffold — Task 4 implements the real function.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from tech_news_synth.cluster.vectorize import FittedCorpus


def check_antirepeat(
    winning_centroid: np.ndarray,
    fitted: FittedCorpus,
    past_posts: list[Any],
    threshold: float,
) -> list[int]:
    """Stub — real implementation in Task 4."""
    raise NotImplementedError("cluster.antirepeat.check_antirepeat implemented in Task 4")


__all__ = ["check_antirepeat"]
