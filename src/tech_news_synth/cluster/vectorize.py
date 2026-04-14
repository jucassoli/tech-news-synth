"""TfidfVectorizer factory + combined-corpus fit (D-01, D-08).

Plan 05-01 Task 1 scaffold — Task 2 implements the real functions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:
    from sklearn.feature_extraction.text import TfidfVectorizer


@dataclass(frozen=True)
class FittedCorpus:
    """Bookkeeping for a single combined-corpus TF-IDF fit."""

    vectorizer: Any  # sklearn TfidfVectorizer
    X: np.ndarray
    current_range: tuple[int, int]
    past_post_ranges: dict[int, tuple[int, int]] = field(default_factory=dict)


def build_vectorizer(min_df: int = 1) -> TfidfVectorizer:
    """Stub — real implementation in Task 2."""
    raise NotImplementedError("cluster.vectorize.build_vectorizer implemented in Task 2")


def fit_combined_corpus(
    current_texts: list[str],
    past_posts: list[Any],
) -> FittedCorpus:
    """Stub — real implementation in Task 2."""
    raise NotImplementedError("cluster.vectorize.fit_combined_corpus implemented in Task 2")


def top_k_terms(centroid: np.ndarray, vectorizer: TfidfVectorizer, k: int = 20) -> dict[str, float]:
    """Stub — real implementation in Task 2."""
    raise NotImplementedError("cluster.vectorize.top_k_terms implemented in Task 2")


__all__ = ["FittedCorpus", "build_vectorizer", "fit_combined_corpus", "top_k_terms"]
