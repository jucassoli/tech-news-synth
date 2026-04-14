"""Phase 5 Plan 05-01 Task 4: check_antirepeat."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from tech_news_synth.cluster.antirepeat import check_antirepeat
from tech_news_synth.cluster.cluster import compute_centroid
from tech_news_synth.cluster.vectorize import fit_combined_corpus


def test_empty_past_returns_empty():
    fitted = fit_combined_corpus(["foo bar baz"], [])
    winner = fitted.X[0]
    assert check_antirepeat(winner, fitted, [], 0.5) == []


def test_all_below_threshold_returns_empty():
    current = ["quantum computing breakthrough error correction"]
    past = [
        SimpleNamespace(post_id=1, source_texts=["Apple iPhone launch M5 chip announcement"]),
        SimpleNamespace(post_id=2, source_texts=["Tesla robotaxi urban navigation update"]),
    ]
    fitted = fit_combined_corpus(current, past)
    winner = fitted.X[0]
    rejects = check_antirepeat(winner, fitted, past, 0.5)
    assert rejects == []


def test_single_hit_returns_post_id():
    current = ["intel foundry spinoff separate company"]
    past = [
        SimpleNamespace(
            post_id=42,
            source_texts=[
                "intel foundry spinoff separate company",
                "intel foundry spinoff company details",
            ],
        )
    ]
    fitted = fit_combined_corpus(current, past)
    # Winner = centroid of the current slice (single article)
    winner = compute_centroid(fitted.X, [0])
    rejects = check_antirepeat(winner, fitted, past, 0.5)
    assert rejects == [42]


def test_mixed_hit_and_miss():
    current = ["openai gpt5 release developers api"]
    past = [
        SimpleNamespace(post_id=100, source_texts=["linux kernel bpf verifier"]),
        SimpleNamespace(
            post_id=200,
            source_texts=[
                "openai gpt5 release developers api preview",
                "openai gpt5 release for developers",
            ],
        ),
        SimpleNamespace(post_id=300, source_texts=["nvidia flagship gaming gpu announcement"]),
    ]
    fitted = fit_combined_corpus(current, past)
    winner = compute_centroid(fitted.X, [0])
    rejects = check_antirepeat(winner, fitted, past, 0.5)
    assert rejects == [200]


def test_threshold_boundary_is_inclusive():
    """Inclusive >= boundary: winner cosine exactly at threshold is a hit."""
    current = ["apple iphone m5 chip announcement"]
    past = [SimpleNamespace(post_id=7, source_texts=["apple iphone m5 chip announcement"])]
    fitted = fit_combined_corpus(current, past)
    winner = compute_centroid(fitted.X, [0])
    # Identical text → cosine ≈ 1.0 (floating-point ~0.9999999999999998)
    # Verify >= semantics: threshold slightly below measured cosine is inclusive hit.
    from sklearn.metrics.pairwise import cosine_similarity

    past_centroid = fitted.X[1:2].mean(axis=0).reshape(1, -1)
    measured = float(cosine_similarity(winner.reshape(1, -1), past_centroid)[0, 0])
    # Exact-boundary test: using the measured value as threshold → inclusive hit.
    assert check_antirepeat(winner, fitted, past, measured) == [7]
    # Just-above-boundary → miss (strict > would fail to include; we want >=)
    eps = 1e-12
    assert check_antirepeat(winner, fitted, past, measured + eps) == []
    # And of course, low threshold → hit.
    assert check_antirepeat(winner, fitted, past, 0.5) == [7]


def test_uses_sklearn_cosine_similarity(mocker):
    current = ["foo bar"]
    past = [
        SimpleNamespace(post_id=1, source_texts=["baz qux"]),
        SimpleNamespace(post_id=2, source_texts=["quux"]),
    ]
    fitted = fit_combined_corpus(current, past)
    winner = fitted.X[0]
    spy = mocker.patch(
        "tech_news_synth.cluster.antirepeat.cosine_similarity",
        return_value=np.array([[0.0]]),
    )
    check_antirepeat(winner, fitted, past, 0.5)
    assert spy.call_count == 2


# ---------------------------------------------------------------------------
# Integration with the fixture file
# ---------------------------------------------------------------------------
def test_anti_repeat_hit_fixture_flags_collision():
    """anti_repeat_hit.json: current Intel-foundry cluster should collide with past post."""
    import json
    from pathlib import Path

    data = json.loads(
        (Path(__file__).parent.parent / "fixtures" / "cluster" / "anti_repeat_hit.json").read_text()
    )
    current = data["current_articles"]
    current = sorted(current, key=lambda a: (a["published_at"], a["id"]))
    texts = [f"{a['title']} {a['summary']}" for a in current]
    past = [
        SimpleNamespace(post_id=p["post_id"], source_texts=p["source_texts"])
        for p in data["past_posts"]
    ]
    fitted = fit_combined_corpus(texts, past)
    # The first 4 current articles are the Intel-foundry cluster
    intel_indices = [
        i
        for i, a in enumerate(current)
        if "intel" in a["title"].lower() or "chipmaker" in a["title"].lower()
    ]
    assert len(intel_indices) == 4
    winner_centroid = compute_centroid(fitted.X, intel_indices)
    rejects = check_antirepeat(winner_centroid, fitted, past, 0.5)
    assert 101 in rejects
