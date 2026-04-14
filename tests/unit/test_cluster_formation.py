"""Phase 5 Plan 05-01 Task 3: cluster formation on fixtures."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import numpy as np
import pytest

from tech_news_synth.cluster.cluster import compute_centroid, run_agglomerative
from tech_news_synth.cluster.vectorize import fit_combined_corpus

FIXTURES = Path(__file__).parent.parent / "fixtures" / "cluster"


def _load_articles(filename: str) -> list[dict]:
    """Load a fixture (expects a top-level list)."""
    return json.loads((FIXTURES / filename).read_text(encoding="utf-8"))


def _vectorize(articles: list[dict]) -> np.ndarray:
    """Fit + densify on fixture text (title + summary)."""
    # Deterministic input order (D-10)
    articles = sorted(articles, key=lambda a: (a["published_at"], a["id"]))
    texts = [f"{a['title']} {a['summary']}" for a in articles]
    fitted = fit_combined_corpus(texts, [])
    return fitted.X


# ---------------------------------------------------------------------------
# Fixture-driven cluster-count expectations
# ---------------------------------------------------------------------------
def test_hot_topic_yields_3_clusters():
    articles = _load_articles("hot_topic.json")
    X = _vectorize(articles)
    labels = run_agglomerative(X, 0.35)
    assert len(set(labels)) == 3


def test_slow_day_yields_all_singletons():
    articles = _load_articles("slow_day.json")
    X = _vectorize(articles)
    labels = run_agglomerative(X, 0.35)
    # All unrelated topics → each article is its own cluster
    assert len(set(labels)) == len(articles)


def test_mixed_yields_one_multi_plus_singletons():
    articles = _load_articles("mixed.json")
    X = _vectorize(articles)
    labels = run_agglomerative(X, 0.35)
    counts = Counter(labels.tolist())
    top_count = counts.most_common(1)[0][1]
    assert top_count == 4  # the EU AI Act cluster


# ---------------------------------------------------------------------------
# N guard cases (research P-8)
# ---------------------------------------------------------------------------
def test_run_agglomerative_n_zero():
    X = np.zeros((0, 5))
    labels = run_agglomerative(X, 0.35)
    assert labels.shape == (0,)


def test_run_agglomerative_n_one():
    X = np.array([[1.0, 0.0, 0.0]])
    labels = run_agglomerative(X, 0.35)
    assert labels.tolist() == [0]


# ---------------------------------------------------------------------------
# compute_centroid
# ---------------------------------------------------------------------------
def test_compute_centroid_matches_mean():
    X = np.array(
        [
            [1.0, 2.0, 3.0],
            [4.0, 5.0, 6.0],
            [7.0, 8.0, 9.0],
            [10.0, 11.0, 12.0],
            [13.0, 14.0, 15.0],
        ]
    )
    c = compute_centroid(X, [0, 2, 4])
    expected = X[[0, 2, 4]].mean(axis=0)
    assert np.allclose(c, expected)


def test_compute_centroid_empty_indices():
    X = np.array([[1.0, 2.0], [3.0, 4.0]])
    c = compute_centroid(X, [])
    assert c.shape == (2,)
    assert np.allclose(c, 0.0)


# Parametrized sanity: distance_threshold extremes
@pytest.mark.parametrize("threshold,expected_labels", [(0.001, "all-singletons"), (2.0, "one-big")])
def test_threshold_extremes(threshold, expected_labels):
    articles = _load_articles("hot_topic.json")
    X = _vectorize(articles)
    labels = run_agglomerative(X, threshold)
    n_clusters = len(set(labels))
    if expected_labels == "all-singletons":
        assert n_clusters == len(articles)
    else:
        # threshold >= max cosine distance (1.0) collapses everything
        assert n_clusters == 1
