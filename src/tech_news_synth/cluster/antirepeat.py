"""Anti-repetition check via cosine similarity to 48h post centroids (D-01, D-03).

Uses the same ``FittedCorpus`` vectorizer the winner was built from, so
vectors live in a single feature space (D-01 combined-corpus refit).
"""

from __future__ import annotations

from typing import Any

import numpy as np
from sklearn.metrics.pairwise import cosine_similarity

from tech_news_synth.cluster.vectorize import FittedCorpus


def check_antirepeat(
    winning_centroid: np.ndarray,
    fitted: FittedCorpus,
    past_posts: list[Any],
    threshold: float,
) -> list[int]:
    """Return list of past post_ids whose centroid cosine >= threshold.

    ``past_posts`` elements must have a ``post_id`` attribute that indexes
    into ``fitted.past_post_ranges``. The threshold comparison is inclusive
    (>=) per D-03.
    """
    if not past_posts:
        return []
    rejects: list[int] = []
    winner_2d = winning_centroid.reshape(1, -1)
    for p in past_posts:
        start, end = fitted.past_post_ranges[p.post_id]
        past_centroid = fitted.X[start:end].mean(axis=0).reshape(1, -1)
        sim = float(cosine_similarity(winner_2d, past_centroid)[0, 0])
        if sim >= threshold:
            rejects.append(p.post_id)
    return rejects


__all__ = ["check_antirepeat"]
