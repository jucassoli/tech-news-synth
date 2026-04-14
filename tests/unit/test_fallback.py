"""Phase 5 Plan 05-01 Task 5: pick_fallback + SelectionResult."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.skip(reason="implemented in Plan 05-01 Task 5")


def test_empty_returns_none():
    pass


def test_highest_weight_wins():
    pass


def test_recency_breaks_weight_tie():
    pass


def test_lowest_id_breaks_recency_tie():
    pass


def test_missing_published_at_treated_as_oldest():
    pass


def test_missing_source_weight_defaults_to_1_0():
    pass


def test_slow_day_fixture():
    pass


def test_selection_result_frozen():
    pass


def test_selection_result_equatable():
    pass
