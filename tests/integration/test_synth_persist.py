"""Integration: run_synthesis writes a full posts row with cost + tokens (Plan 06-02).

Seeds minimal Phase-5-ish state (run_log + articles + cluster) and exercises
the orchestrator against a real DB with ``call_haiku`` mocked.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from sqlalchemy import select

from tech_news_synth.cluster.models import SelectionResult
from tech_news_synth.config import Settings
from tech_news_synth.db.articles import upsert_batch
from tech_news_synth.db.clusters import insert_cluster
from tech_news_synth.db.models import Article, Post
from tech_news_synth.db.run_log import start_cycle
from tech_news_synth.ingest.sources_config import RssSource, SourcesConfig
from tech_news_synth.synth import orchestrator as orch
from tech_news_synth.synth.hashtags import HashtagAllowlist

pytestmark = pytest.mark.integration


def _settings(dry_run: bool = False) -> Settings:
    import os

    for k, v in {
        "ANTHROPIC_API_KEY": "sk-ant-test",
        "X_CONSUMER_KEY": "k",
        "X_CONSUMER_SECRET": "s",
        "X_ACCESS_TOKEN": "t",
        "X_ACCESS_TOKEN_SECRET": "ts",
        "POSTGRES_PASSWORD": "pw",
    }.items():
        os.environ.setdefault(k, v)
    os.environ["PYDANTIC_SETTINGS_DISABLE_ENV_FILE"] = "1"
    os.environ["DRY_RUN"] = "1" if dry_run else "0"
    return Settings()  # type: ignore[call-arg]


def _sources() -> SourcesConfig:
    return SourcesConfig(
        max_articles_per_fetch=30,
        max_article_age_hours=24,
        sources=[
            RssSource(name="techcrunch", type="rss", url="https://tc.com/feed", timeout_sec=20),  # type: ignore[arg-type]
            RssSource(name="verge", type="rss", url="https://verge.com/feed", timeout_sec=20),  # type: ignore[arg-type]
        ],
    )


def _allowlist() -> HashtagAllowlist:
    return HashtagAllowlist(
        topics={"apple": ["#Apple"], "ai": ["#IA"]},
        default=["#tech"],
    )


def _seed(db_session, cycle_id: str):
    start_cycle(db_session, cycle_id)
    upsert_batch(
        db_session,
        [
            {
                "source": "techcrunch",
                "url": "https://tc.com/a",
                "canonical_url": "https://tc.com/a",
                "title": "Apple unveils M5",
                "summary": "Apple chip with AI acceleration.",
                "published_at": datetime(2026, 4, 14, 9, 0, tzinfo=UTC),
                "article_hash": "h" * 64,
            },
            {
                "source": "verge",
                "url": "https://verge.com/b",
                "canonical_url": "https://verge.com/b",
                "title": "Inside M5 event",
                "summary": "Verge coverage of Apple event.",
                "published_at": datetime(2026, 4, 14, 9, 30, tzinfo=UTC),
                "article_hash": "i" * 64,
            },
        ],
    )
    db_session.flush()
    article_ids = [
        r.id for r in db_session.execute(select(Article).order_by(Article.id)).scalars()
    ]
    cluster = insert_cluster(
        db_session,
        cycle_id=cycle_id,
        member_article_ids=article_ids,
        centroid_terms={"apple": 0.95, "m5": 0.7},
        chosen=True,
        coverage_score=2.0,
    )
    return cluster.id, article_ids


def test_posts_row_written_with_cost_and_tokens(db_session, mocker):
    cid = "01PERSIST00000000000000001"
    cluster_id, article_ids = _seed(db_session, cid)

    mocker.patch.object(
        orch,
        "call_haiku",
        return_value=("Apple anuncia o chip M5 com foco em IA.", 100, 40),
    )

    selection = SelectionResult(
        winner_cluster_id=cluster_id,
        winner_article_ids=article_ids,
        fallback_article_id=None,
        rejected_by_antirepeat=[],
        all_cluster_ids=[cluster_id],
        counts_patch={},
        winner_centroid=b"\x00\x00\x80\x3f" * 4,
    )

    result = orch.run_synthesis(
        db_session,
        cid,
        selection,
        _settings(dry_run=False),
        _sources(),
        MagicMock(name="anthropic"),
        _allowlist(),
    )

    assert result.post_id is not None
    row = db_session.execute(select(Post).where(Post.id == result.post_id)).scalar_one()
    assert row.status == "pending"
    assert row.cluster_id == cluster_id
    assert row.synthesized_text == result.text
    assert "#Apple" in row.hashtags
    assert row.cost_usd is not None
    assert float(row.cost_usd) > 0
    # theme_centroid BYTEA roundtrip
    assert row.theme_centroid is not None
    assert len(row.theme_centroid) > 0
    # error_detail None on completed
    assert row.error_detail is None


def test_truncation_persists_error_detail(db_session, mocker):
    """All 3 attempts over budget → error_detail JSON populated on posts row."""
    cid = "01TRUNC0000000000000000002"
    cluster_id, article_ids = _seed(db_session, cid)

    over = "Z" * 260
    mocker.patch.object(orch, "call_haiku", return_value=(over, 150, 120))

    selection = SelectionResult(
        winner_cluster_id=cluster_id,
        winner_article_ids=article_ids,
        fallback_article_id=None,
        rejected_by_antirepeat=[],
        all_cluster_ids=[cluster_id],
        counts_patch={},
        winner_centroid=b"\x00\x00\x80\x3f" * 4,
    )

    result = orch.run_synthesis(
        db_session, cid, selection, _settings(False),
        _sources(), MagicMock(), _allowlist(),
    )

    assert result.final_method == "truncated"
    row = db_session.execute(select(Post).where(Post.id == result.post_id)).scalar_one()
    assert row.error_detail is not None
    import json as _j
    parsed = _j.loads(row.error_detail)
    assert len(parsed) == 3
