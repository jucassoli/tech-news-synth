"""Unit tests for ``synth.orchestrator.run_synthesis`` composition (Plan 06-02).

Mocks ``call_haiku`` at the module boundary; uses MagicMock Session + stub ORM
objects rather than a live DB. Integration-level coverage (real DB roundtrip)
lives in ``tests/integration/test_synth_*``.
"""

from __future__ import annotations

import json
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from tech_news_synth.cluster.models import SelectionResult
from tech_news_synth.synth.hashtags import HashtagAllowlist


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_article(
    *,
    id: int,
    source: str,
    title: str,
    url: str,
    summary: str = "sum",
    ts: str = "2026-04-14T09:00:00+00:00",
):
    return SimpleNamespace(
        id=id,
        source=source,
        title=title,
        url=url,
        summary=summary,
        published_at=datetime.fromisoformat(ts),
    )


def _settings(dry_run: bool = False, max_retries: int = 2, char_budget: int = 225):
    s = MagicMock(name="Settings")
    s.dry_run = dry_run
    s.synthesis_max_tokens = 150
    s.synthesis_char_budget = char_budget
    s.synthesis_max_retries = max_retries
    s.hashtag_budget_chars = 30
    return s


def _sources_config():
    sc = MagicMock(name="SourcesConfig")
    sc.sources = [
        SimpleNamespace(name="techcrunch", weight=1.0),
        SimpleNamespace(name="verge", weight=1.0),
        SimpleNamespace(name="ars_technica", weight=1.0),
    ]
    return sc


def _allowlist() -> HashtagAllowlist:
    return HashtagAllowlist(
        topics={"apple": ["#Apple"], "ai": ["#IA"]},
        default=["#tech"],
    )


def _mock_session_with_cluster(cluster_terms: dict):
    """MagicMock Session where session.get(Cluster, ...) returns centroid_terms."""
    session = MagicMock(name="Session")
    cluster_row = SimpleNamespace(id=42, centroid_terms=cluster_terms)
    # session.get receives (Model, id). Ignore Model argument for simplicity.
    session.get = MagicMock(return_value=cluster_row)
    # insert_post patched by mocker — session.add/flush no-op.
    session.flush = MagicMock(return_value=None)
    session.add = MagicMock(return_value=None)
    return session


def _patch_thread_dependencies(mocker, orch):
    mocker.patch.object(
        orch,
        "probe_source_card",
        return_value={"probable_card": True, "twitter_card": "summary_large_image"},
    )
    mocker.patch.object(
        orch,
        "generate_thread_replies",
        side_effect=lambda **kwargs: (
            [f"Reply {i}" for i in range(1, kwargs["parts"])],
            12,
            6,
        ),
    )
    mocker.patch.object(orch, "insert_post_tweets")


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------
def test_run_synthesis_completed_on_first_attempt(mocker):
    """Winner path, LLM returns under-budget immediately → attempts=1."""
    from tech_news_synth.synth import orchestrator as orch
    _patch_thread_dependencies(mocker, orch)

    articles = [
        _make_article(id=1, source="techcrunch", title="Apple M5", url="https://tc.com/a"),
        _make_article(id=2, source="verge", title="M5 event", url="https://verge.com/b"),
    ]
    mocker.patch.object(orch, "get_articles_by_ids", return_value=articles)

    inserted_post = SimpleNamespace(id=999)
    mocker.patch.object(orch, "insert_post", return_value=inserted_post)

    mocker.patch.object(orch, "call_haiku", return_value=("Apple anuncia o chip M5.", 50, 10))

    selection = SelectionResult(
        winner_cluster_id=42,
        winner_article_ids=[1, 2],
        fallback_article_id=None,
        rejected_by_antirepeat=[],
        all_cluster_ids=[42],
        counts_patch={},
        winner_centroid=b"\x00\x01\x02",
    )
    session = _mock_session_with_cluster({"apple": 0.9, "m5": 0.5})

    result = orch.run_synthesis(
        session,
        "01TESTCYCLE0000000000000001",
        selection,
        _settings(),
        _sources_config(),
        MagicMock(name="anthropic_client"),
        _allowlist(),
    )

    assert result.attempts == 1
    assert result.final_method == "completed"
    assert result.post_id == 999
    assert result.status == "pending"
    assert result.cost_usd > 0
    assert result.hashtags == ["#Apple"]
    assert "https://" in result.text
    assert "Siga a thread" in result.text
    assert result.reply_texts[-1].endswith("#Apple")
    assert len(result.thread_texts) == 3
    assert result.counts_patch["synth_attempts"] == 1
    assert result.counts_patch["synth_truncated"] is False
    assert result.counts_patch["post_id"] == 999
    # Phase 8 OPS-01: char_budget_used is weighted_len of final text
    from tech_news_synth.synth.charcount import weighted_len
    assert result.counts_patch["char_budget_used"] == weighted_len(result.text)


def test_run_synthesis_completed_on_second_attempt(mocker):
    """Over budget attempt 1, under budget attempt 2."""
    from tech_news_synth.synth import orchestrator as orch
    _patch_thread_dependencies(mocker, orch)

    articles = [_make_article(id=1, source="techcrunch", title="T", url="https://tc.com/a")]
    mocker.patch.object(orch, "get_articles_by_ids", return_value=articles)
    mocker.patch.object(orch, "insert_post", return_value=SimpleNamespace(id=1))

    over = "X" * 260  # over 280 with URL + hashtags
    under = "Texto curto."
    mocker.patch.object(
        orch,
        "call_haiku",
        side_effect=[(over, 100, 80), (under, 60, 20)],
    )

    selection = SelectionResult(
        winner_cluster_id=42,
        winner_article_ids=[1],
        fallback_article_id=None,
        rejected_by_antirepeat=[],
        all_cluster_ids=[42],
        counts_patch={},
        winner_centroid=b"x",
    )
    session = _mock_session_with_cluster({"apple": 0.9})

    result = orch.run_synthesis(
        session, "cid", selection, _settings(),
        _sources_config(), MagicMock(), _allowlist(),
    )
    assert result.attempts == 2
    assert result.final_method == "completed"
    assert result.input_tokens == 172
    assert result.output_tokens == 106


def test_run_synthesis_truncated_after_all_attempts(mocker):
    """All 3 attempts over budget → truncation path; error_detail populated."""
    from tech_news_synth.synth import orchestrator as orch
    _patch_thread_dependencies(mocker, orch)

    articles = [_make_article(id=1, source="techcrunch", title="T", url="https://tc.com/a")]
    mocker.patch.object(orch, "get_articles_by_ids", return_value=articles)

    captured_kwargs: dict = {}

    def fake_insert_post(session, **kwargs):
        captured_kwargs.update(kwargs)
        return SimpleNamespace(id=77)

    mocker.patch.object(orch, "insert_post", side_effect=fake_insert_post)
    over = "Y" * 260
    mocker.patch.object(orch, "call_haiku", return_value=(over, 100, 80))

    selection = SelectionResult(
        winner_cluster_id=42,
        winner_article_ids=[1],
        fallback_article_id=None,
        rejected_by_antirepeat=[],
        all_cluster_ids=[42],
        counts_patch={},
        winner_centroid=b"x",
    )
    session = _mock_session_with_cluster({"apple": 0.9})

    result = orch.run_synthesis(
        session, "cid", selection, _settings(max_retries=2),
        _sources_config(), MagicMock(), _allowlist(),
    )
    assert result.attempts == 3
    assert result.final_method == "truncated"
    # error_detail is JSON list of attempt log entries
    detail = captured_kwargs["error_detail"]
    assert detail is not None
    # dict or str
    if isinstance(detail, str):
        parsed = json.loads(detail)
    else:
        parsed = detail
    assert len(parsed) == 3
    # Invariant: final text <= 280 weighted
    from tech_news_synth.synth.charcount import weighted_len
    assert weighted_len(result.text) <= 280


def test_run_synthesis_fallback_path(mocker):
    """Fallback branch: single article, no cluster, default hashtag."""
    from tech_news_synth.synth import orchestrator as orch
    _patch_thread_dependencies(mocker, orch)

    article = _make_article(id=99, source="verge", title="Fallback news", url="https://verge.com/f")
    mocker.patch.object(orch, "get_articles_by_ids", return_value=[article])
    mocker.patch.object(orch, "insert_post", return_value=SimpleNamespace(id=500))
    mocker.patch.object(orch, "call_haiku", return_value=("Texto síntese.", 40, 10))

    selection = SelectionResult(
        winner_cluster_id=None,
        winner_article_ids=None,
        fallback_article_id=99,
        rejected_by_antirepeat=[],
        all_cluster_ids=[],
        counts_patch={},
        winner_centroid=None,
    )
    session = MagicMock(name="Session")
    session.get = MagicMock(return_value=article)
    session.flush = MagicMock()

    result = orch.run_synthesis(
        session, "cid", selection, _settings(),
        _sources_config(), MagicMock(), _allowlist(),
    )
    assert result.hashtags == ["#tech"]
    assert result.source_url == "https://verge.com/f"
    assert result.post_id == 500
    assert len(result.thread_texts) == 2


def test_run_synthesis_dry_run_still_calls_anthropic(mocker):
    """DRY_RUN=1 → status='dry_run' but cost_usd > 0 (D-12)."""
    from tech_news_synth.synth import orchestrator as orch
    _patch_thread_dependencies(mocker, orch)

    articles = [_make_article(id=1, source="techcrunch", title="T", url="https://tc.com/a")]
    mocker.patch.object(orch, "get_articles_by_ids", return_value=articles)

    captured: dict = {}

    def fake_insert(session, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(id=1)

    mocker.patch.object(orch, "insert_post", side_effect=fake_insert)
    mocker.patch.object(orch, "call_haiku", return_value=("Curto.", 50, 10))

    selection = SelectionResult(
        winner_cluster_id=42, winner_article_ids=[1], fallback_article_id=None,
        rejected_by_antirepeat=[], all_cluster_ids=[42], counts_patch={},
        winner_centroid=b"x",
    )
    session = _mock_session_with_cluster({"apple": 0.9})

    result = orch.run_synthesis(
        session, "cid", selection, _settings(dry_run=True),
        _sources_config(), MagicMock(), _allowlist(),
    )
    assert result.status == "dry_run"
    assert captured["status"] == "dry_run"
    assert result.cost_usd > 0


def test_run_synthesis_empty_selection_raises(mocker):
    from tech_news_synth.synth import orchestrator as orch

    selection = SelectionResult(
        winner_cluster_id=None, winner_article_ids=None, fallback_article_id=None,
        rejected_by_antirepeat=[], all_cluster_ids=[], counts_patch={},
    )
    with pytest.raises(ValueError):
        orch.run_synthesis(
            MagicMock(), "cid", selection, _settings(),
            _sources_config(), MagicMock(), _allowlist(),
        )


def test_run_synthesis_anthropic_error_propagates(mocker):
    """anthropic errors must propagate, no posts row written."""
    from tech_news_synth.synth import orchestrator as orch
    _patch_thread_dependencies(mocker, orch)

    articles = [_make_article(id=1, source="techcrunch", title="T", url="https://tc.com/a")]
    mocker.patch.object(orch, "get_articles_by_ids", return_value=articles)

    insert_mock = mocker.patch.object(orch, "insert_post")

    class FakeAPIErr(Exception):
        pass

    mocker.patch.object(orch, "call_haiku", side_effect=FakeAPIErr("boom"))

    selection = SelectionResult(
        winner_cluster_id=42, winner_article_ids=[1], fallback_article_id=None,
        rejected_by_antirepeat=[], all_cluster_ids=[42], counts_patch={},
        winner_centroid=b"x",
    )
    session = _mock_session_with_cluster({"apple": 0.9})

    with pytest.raises(FakeAPIErr):
        orch.run_synthesis(
            session, "cid", selection, _settings(),
            _sources_config(), MagicMock(), _allowlist(),
        )
    insert_mock.assert_not_called()


def test_run_synthesis_persist_false_skips_insert(mocker):
    """Phase 8 D-12: persist=False MUST skip insert_post, return post_id=None,
    status='replay', and counts_patch['post_id']=None. Text/cost still produced.
    """
    from tech_news_synth.synth import orchestrator as orch
    _patch_thread_dependencies(mocker, orch)

    articles = [_make_article(id=1, source="techcrunch", title="Apple M5", url="https://tc.com/a")]
    mocker.patch.object(orch, "get_articles_by_ids", return_value=articles)
    insert_mock = mocker.patch.object(orch, "insert_post")
    mocker.patch.object(orch, "call_haiku", return_value=("Apple anuncia.", 30, 10))

    selection = SelectionResult(
        winner_cluster_id=42,
        winner_article_ids=[1],
        fallback_article_id=None,
        rejected_by_antirepeat=[],
        all_cluster_ids=[42],
        counts_patch={},
        winner_centroid=b"x",
    )
    session = _mock_session_with_cluster({"apple": 0.9})

    result = orch.run_synthesis(
        session, "cid", selection, _settings(),
        _sources_config(), MagicMock(), _allowlist(),
        persist=False,
    )
    insert_mock.assert_not_called()
    assert result.post_id is None
    assert result.status == "replay"
    assert result.counts_patch["post_id"] is None
    assert "char_budget_used" in result.counts_patch  # Phase 8 OPS-01
    assert result.cost_usd > 0
    assert result.text  # synthesis still ran end-to-end


def test_run_synthesis_persist_must_be_keyword_only(mocker):
    """Defense-in-depth: positional persist passes TypeError (T-08-02 mitigation)."""
    from tech_news_synth.synth import orchestrator as orch
    _patch_thread_dependencies(mocker, orch)

    articles = [_make_article(id=1, source="techcrunch", title="T", url="https://tc.com/a")]
    mocker.patch.object(orch, "get_articles_by_ids", return_value=articles)

    selection = SelectionResult(
        winner_cluster_id=42, winner_article_ids=[1], fallback_article_id=None,
        rejected_by_antirepeat=[], all_cluster_ids=[42], counts_patch={},
        winner_centroid=b"x",
    )
    session = _mock_session_with_cluster({"apple": 0.9})
    with pytest.raises(TypeError):
        orch.run_synthesis(
            session, "cid", selection, _settings(),
            _sources_config(), MagicMock(), _allowlist(),
            False,  # positional — must fail
        )


def test_run_synthesis_cluster_terms_drive_hashtags(mocker):
    """Ensure cluster centroid_terms flow to select_hashtags."""
    from tech_news_synth.synth import orchestrator as orch
    _patch_thread_dependencies(mocker, orch)

    articles = [_make_article(id=1, source="techcrunch", title="Apple", url="https://tc.com/a")]
    mocker.patch.object(orch, "get_articles_by_ids", return_value=articles)
    mocker.patch.object(orch, "insert_post", return_value=SimpleNamespace(id=1))
    mocker.patch.object(orch, "call_haiku", return_value=("body", 10, 10))

    selection = SelectionResult(
        winner_cluster_id=42, winner_article_ids=[1], fallback_article_id=None,
        rejected_by_antirepeat=[], all_cluster_ids=[42], counts_patch={},
        winner_centroid=b"x",
    )
    session = _mock_session_with_cluster({"apple": 0.99})

    result = orch.run_synthesis(
        session, "cid", selection, _settings(),
        _sources_config(), MagicMock(), _allowlist(),
    )
    assert "#Apple" in result.hashtags
