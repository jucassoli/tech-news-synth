"""Anthropic error propagation — no partial posts row."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from tech_news_synth.cluster.models import SelectionResult
from tech_news_synth.synth.hashtags import HashtagAllowlist


class FakeAnthropicError(Exception):
    """Stand-in for anthropic.APIError."""


def _mk_article(id_=1):
    return SimpleNamespace(
        id=id_,
        source="techcrunch",
        title="t",
        url="https://tc.com/x",
        summary="s",
        published_at=datetime(2026, 4, 14, 9, 0, tzinfo=UTC),
    )


def _settings():
    s = MagicMock()
    s.dry_run = False
    s.synthesis_max_tokens = 150
    s.synthesis_char_budget = 225
    s.synthesis_max_retries = 2
    s.hashtag_budget_chars = 30
    return s


def _sources():
    sc = MagicMock()
    sc.sources = [SimpleNamespace(name="techcrunch", weight=1.0)]
    return sc


def test_anthropic_error_propagates_and_no_post_written(mocker):
    from tech_news_synth.synth import orchestrator as orch

    mocker.patch.object(orch, "get_articles_by_ids", return_value=[_mk_article()])
    insert_mock = mocker.patch.object(orch, "insert_post")
    mocker.patch.object(orch, "call_haiku", side_effect=FakeAnthropicError("api down"))

    selection = SelectionResult(
        winner_cluster_id=42,
        winner_article_ids=[1],
        fallback_article_id=None,
        rejected_by_antirepeat=[],
        all_cluster_ids=[42],
        counts_patch={},
        winner_centroid=b"x",
    )

    session = MagicMock()
    session.get = MagicMock(return_value=SimpleNamespace(id=42, centroid_terms={}))

    allowlist = HashtagAllowlist(topics={}, default=["#tech"])

    with pytest.raises(FakeAnthropicError):
        orch.run_synthesis(
            session, "cid", selection, _settings(), _sources(), MagicMock(), allowlist,
        )

    insert_mock.assert_not_called()
