"""Unit tests for SelectionResult extension (Phase 6 Plan 06-01).

Asserts ``winner_centroid: bytes | None`` field:
  (a) default None → backward compat for the fallback branch + pre-existing tests.
  (b) round-trips ``bytes`` intact.
"""

from __future__ import annotations

from tech_news_synth.cluster.models import SelectionResult


def _base_kwargs() -> dict:
    return dict(
        winner_cluster_id=None,
        winner_article_ids=None,
        fallback_article_id=None,
        rejected_by_antirepeat=[],
        all_cluster_ids=[],
        counts_patch={},
    )


def test_selection_result_winner_centroid_defaults_to_none():
    sr = SelectionResult(**_base_kwargs())
    assert sr.winner_centroid is None


def test_selection_result_winner_centroid_roundtrips_bytes():
    payload = b"\x00\x01\x02\x03"
    sr = SelectionResult(**_base_kwargs(), winner_centroid=payload)
    assert sr.winner_centroid == payload
    assert isinstance(sr.winner_centroid, bytes)


def test_selection_result_still_frozen():
    sr = SelectionResult(**_base_kwargs())
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        sr.winner_centroid = b"new"  # type: ignore[misc]
