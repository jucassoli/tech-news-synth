"""Agglomerative clustering (D-06) on dense TF-IDF vectors.

Research P-2: densify BEFORE fit (sklearn 1.8 rejects sparse).
Research P-3: ``n_clusters=None`` requires ``distance_threshold`` (and vice versa).
Research P-8: guard N<2 — sklearn raises on 0 or 1 samples.
"""

from __future__ import annotations

import numpy as np
from sklearn.cluster import AgglomerativeClustering


def run_agglomerative(X_current: np.ndarray, distance_threshold: float) -> np.ndarray:
    """Return int labels per row.

    Guards N<2 by returning all-zero labels; orchestrator should detect
    these degenerate cases via the article list and take the fallback path,
    but this guard prevents sklearn ValueError.
    """
    n = X_current.shape[0]
    if n == 0:
        return np.zeros(0, dtype=int)
    if n < 2:
        return np.zeros(n, dtype=int)
    model = AgglomerativeClustering(
        metric="cosine",
        linkage="average",
        distance_threshold=distance_threshold,
        n_clusters=None,
    )
    model.fit(X_current)
    return model.labels_


def compute_centroid(X: np.ndarray, row_indices: list[int]) -> np.ndarray:
    """Mean of the given rows -> 1D ndarray of shape (N_features,)."""
    if not row_indices:
        return np.zeros(X.shape[1], dtype=X.dtype)
    return X[row_indices].mean(axis=0)


__all__ = ["compute_centroid", "run_agglomerative"]
