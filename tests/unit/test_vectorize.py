"""Phase 5 Plan 05-01 Task 2: vectorize + preprocess + stopwords."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from tech_news_synth.cluster.preprocess import preprocess
from tech_news_synth.cluster.stopwords_pt import PT_EN_STOPWORDS, PT_STOPWORDS
from tech_news_synth.cluster.vectorize import (
    build_vectorizer,
    fit_combined_corpus,
    top_k_terms,
)


# ---------------------------------------------------------------------------
# preprocess
# ---------------------------------------------------------------------------
def test_preprocess_strips_pt_stopwords():
    assert preprocess("uma nova API de IA") == "nova api ia"


def test_preprocess_strips_en_stopwords():
    # "the" and "new" both in ENGLISH_STOP_WORDS
    out = preprocess("the new GPT release")
    tokens = out.split()
    assert "the" not in tokens
    assert "gpt" in tokens
    assert "release" in tokens


def test_preprocess_unidecode_then_strip():
    # "não" -> "nao" (stopword), "é" -> "e" (stopword), "só" -> "so" (stopword)
    assert preprocess("não é só produto") == "produto"


def test_preprocess_emoji_survives():
    # Emoji folds to nothing; word chars unchanged.
    out = preprocess("🚀 rocket launches")
    assert "rocket" in out.split()
    assert "launches" in out.split()


def test_preprocess_empty():
    assert preprocess("") == ""


# ---------------------------------------------------------------------------
# build_vectorizer — research P-1 CRITICAL assertion
# ---------------------------------------------------------------------------
def test_build_vectorizer_config():
    v = build_vectorizer()
    assert v.analyzer == "char_wb"
    assert v.ngram_range == (3, 5)
    assert v.preprocessor is preprocess
    # CRITICAL: sklearn silently ignores stop_words with char_wb (research P-1).
    # We assert it's None on the vectorizer to codify that stopword stripping
    # happens in preprocess(), not here.
    assert v.stop_words is None
    assert v.min_df == 1


# ---------------------------------------------------------------------------
# fit_combined_corpus
# ---------------------------------------------------------------------------
def test_fit_combined_empty_past():
    fitted = fit_combined_corpus(["foo bar baz", "qux quux quuux"], [])
    assert fitted.current_range == (0, 2)
    assert fitted.past_post_ranges == {}
    assert fitted.X.shape[0] == 2


def test_fit_combined_with_past():
    current = ["apple iphone m5", "openai gpt5 release"]
    past = [
        SimpleNamespace(post_id=1, source_texts=["a b c", "d e f", "g h i"]),
        SimpleNamespace(post_id=2, source_texts=["foo bar", "baz qux"]),
    ]
    fitted = fit_combined_corpus(current, past)
    n_curr = len(current)
    assert fitted.current_range == (0, n_curr)
    assert fitted.past_post_ranges == {
        1: (n_curr, n_curr + 3),
        2: (n_curr + 3, n_curr + 5),
    }
    assert fitted.X.shape[0] == n_curr + 5


def test_fit_combined_determinism():
    current = ["apple m5 chip", "openai gpt5 api"]
    past = [SimpleNamespace(post_id=10, source_texts=["intel foundry spinoff"])]
    f1 = fit_combined_corpus(current, past)
    f2 = fit_combined_corpus(current, past)
    assert np.array_equal(f1.X, f2.X)
    assert list(f1.vectorizer.get_feature_names_out()) == list(
        f2.vectorizer.get_feature_names_out()
    )


# ---------------------------------------------------------------------------
# top_k_terms
# ---------------------------------------------------------------------------
def test_top_k_terms_sorted_desc():
    centroid = np.array([0.1, 0.5, 0.3, 0.0, 0.8])

    class _FakeVec:
        @staticmethod
        def get_feature_names_out():
            return np.array(["aa", "bb", "cc", "dd", "ee"])

    out = top_k_terms(centroid, _FakeVec(), k=10)
    # Zero-weight excluded; sorted DESC
    assert list(out.keys()) == ["ee", "bb", "cc", "aa"]
    assert "dd" not in out
    # k respected
    out2 = top_k_terms(centroid, _FakeVec(), k=2)
    assert list(out2.keys()) == ["ee", "bb"]


# ---------------------------------------------------------------------------
# stopwords sanity
# ---------------------------------------------------------------------------
def test_stopwords_pt_union_has_english():
    assert "the" in PT_EN_STOPWORDS
    assert "de" in PT_EN_STOPWORDS
    assert "nao" in PT_EN_STOPWORDS
    # PT seed has ~80 unique tokens after unidecode dedup; assert non-trivial size
    assert len(PT_STOPWORDS) >= 75
    assert len(PT_EN_STOPWORDS) > len(PT_STOPWORDS)
