"""Agglomerative clustering (D-06) on dense TF-IDF vectors.

Plan 05-01 Task 1 scaffold — Task 3 implements the real functions.
"""

from __future__ import annotations

import numpy as np


def run_agglomerative(X_current: np.ndarray, distance_threshold: float) -> np.ndarray:
    """Stub — real implementation in Task 3."""
    raise NotImplementedError("cluster.cluster.run_agglomerative implemented in Task 3")


def compute_centroid(X: np.ndarray, row_indices: list[int]) -> np.ndarray:
    """Stub — real implementation in Task 3."""
    raise NotImplementedError("cluster.cluster.compute_centroid implemented in Task 3")


__all__ = ["compute_centroid", "run_agglomerative"]
