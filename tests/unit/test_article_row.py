"""Unit tests for tech_news_synth.ingest.models.ArticleRow (INGEST-06, T-04-08)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from tech_news_synth.ingest.models import ArticleRow


def _sample(**overrides) -> dict:
    base = {
        "source": "techcrunch",
        "url": "https://techcrunch.com/2026/04/13/post/",
        "canonical_url": "https://techcrunch.com/2026/04/13/post/",
        "article_hash": "a" * 64,
        "title": "Sample",
        "summary": "",
        "published_at": datetime(2026, 4, 13, 10, 0, tzinfo=UTC),
        "fetched_at": datetime(2026, 4, 13, 12, 0, tzinfo=UTC),
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Test 1 — happy path
# ---------------------------------------------------------------------------
def test_valid_construction():
    row = ArticleRow(**_sample())
    assert row.source == "techcrunch"
    assert row.article_hash == "a" * 64
    assert row.published_at.tzinfo is not None


# ---------------------------------------------------------------------------
# Test 2 — naive published_at rejected
# ---------------------------------------------------------------------------
def test_naive_published_at_rejected():
    naive = datetime(2026, 4, 13, 10, 0)  # no tzinfo
    with pytest.raises(ValidationError) as excinfo:
        ArticleRow(**_sample(published_at=naive))
    assert "utc" in str(excinfo.value).lower()


def test_naive_fetched_at_rejected():
    naive = datetime(2026, 4, 13, 12, 0)
    with pytest.raises(ValidationError):
        ArticleRow(**_sample(fetched_at=naive))


# ---------------------------------------------------------------------------
# Test 3 — empty title rejected
# ---------------------------------------------------------------------------
def test_empty_title_rejected():
    with pytest.raises(ValidationError):
        ArticleRow(**_sample(title=""))


# ---------------------------------------------------------------------------
# Test 4 — article_hash width enforced
# ---------------------------------------------------------------------------
def test_article_hash_width():
    with pytest.raises(ValidationError):
        ArticleRow(**_sample(article_hash="tooShort"))
    with pytest.raises(ValidationError):
        ArticleRow(**_sample(article_hash="a" * 65))


# ---------------------------------------------------------------------------
# Test 5 — model_dump produces keys compatible with Phase 2 upsert_batch
# ---------------------------------------------------------------------------
def test_model_dump_keys_for_upsert_batch():
    row = ArticleRow(**_sample())
    dumped = row.model_dump()
    # Keys required by Phase 2 TypedDict (subset check; fetched_at extra is OK)
    for key in (
        "source",
        "url",
        "canonical_url",
        "title",
        "summary",
        "published_at",
        "article_hash",
    ):
        assert key in dumped
