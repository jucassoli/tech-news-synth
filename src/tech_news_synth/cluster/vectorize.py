"""TfidfVectorizer factory + combined-corpus fit (D-01, D-08, research P-1/P-2).

ONE fit per cycle over the union of current_articles and 48h past posts' source_texts.
The same fitted vectorizer is used to compute cluster centroids (current
slice) AND past-post centroids (history slice) — guaranteeing the two
vectors live in the same feature space (required by D-01).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer

from tech_news_synth.cluster.preprocess import preprocess


def build_vectorizer(min_df: int = 1) -> TfidfVectorizer:
    """Returns a fresh TfidfVectorizer matching D-08.

    NOTE: CONTEXT D-08 specified ``stop_words=`` on the vectorizer; sklearn
    silently ignores this with ``analyzer='char_wb'`` (research P-1). We strip
    stopwords in :func:`preprocess` BEFORE text reaches the analyzer, so net
    behavior matches D-08 intent. Do NOT add ``stop_words=`` here.
    """
    return TfidfVectorizer(
        analyzer="char_wb",
        ngram_range=(3, 5),
        preprocessor=preprocess,
        lowercase=True,  # redundant (preprocess lowercases) but harmless
        min_df=min_df,
        # stop_words intentionally omitted — see research P-1
    )


@dataclass(frozen=True)
class FittedCorpus:
    """Bookkeeping for a single combined-corpus TF-IDF fit."""

    vectorizer: TfidfVectorizer
    X: np.ndarray  # dense (N_total, N_features)
    current_range: tuple[int, int]  # [0, N_current)
    past_post_ranges: dict[int, tuple[int, int]] = field(default_factory=dict)


def fit_combined_corpus(
    current_texts: list[str],
    past_posts: list[Any],
) -> FittedCorpus:
    """Fit ONE vectorizer over combined corpus and return slice bookkeeping.

    ``past_posts`` is duck-typed: each element must have ``post_id: int`` and
    ``source_texts: list[str]`` attributes (matches Plan 05-02's
    ``PostWithTexts``).

    P-2: densify for downstream AgglomerativeClustering. At N<=200 docs x
    ~5k features x 8 bytes = ~8MB — trivial.
    """
    corpus: list[str] = list(current_texts)
    past_ranges: dict[int, tuple[int, int]] = {}
    for p in past_posts:
        start = len(corpus)
        corpus.extend(p.source_texts)
        past_ranges[p.post_id] = (start, len(corpus))
    vec = build_vectorizer()
    X_sparse = vec.fit_transform(corpus)
    X = X_sparse.toarray()
    return FittedCorpus(
        vectorizer=vec,
        X=X,
        current_range=(0, len(current_texts)),
        past_post_ranges=past_ranges,
    )


def top_k_terms(centroid: np.ndarray, vectorizer: TfidfVectorizer, k: int = 20) -> dict[str, float]:
    """{term: weight_float} sorted by weight DESC, top k, excludes zeros."""
    feature_names = vectorizer.get_feature_names_out()
    top_idx = np.argsort(centroid)[::-1][:k]
    return {str(feature_names[i]): float(centroid[i]) for i in top_idx if centroid[i] > 0}


__all__ = ["FittedCorpus", "build_vectorizer", "fit_combined_corpus", "top_k_terms"]
