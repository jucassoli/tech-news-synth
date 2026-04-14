"""When selection is empty (no winner, no fallback), run_synthesis must raise.

Caller (scheduler) is responsible for short-circuiting; this test guards the
defensive invariant inside the orchestrator.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from tech_news_synth.cluster.models import SelectionResult
from tech_news_synth.synth.hashtags import HashtagAllowlist


def test_empty_selection_raises_value_error():
    from tech_news_synth.synth.orchestrator import run_synthesis

    selection = SelectionResult(
        winner_cluster_id=None,
        winner_article_ids=None,
        fallback_article_id=None,
        rejected_by_antirepeat=[],
        all_cluster_ids=[],
        counts_patch={},
    )
    settings = MagicMock()
    settings.dry_run = False
    settings.synthesis_max_retries = 2
    settings.synthesis_char_budget = 225
    settings.synthesis_max_tokens = 150
    settings.hashtag_budget_chars = 30

    allowlist = HashtagAllowlist(topics={}, default=["#tech"])

    with pytest.raises(ValueError, match="empty selection"):
        run_synthesis(
            MagicMock(),
            "cid",
            selection,
            settings,
            MagicMock(),
            MagicMock(),
            allowlist,
        )
