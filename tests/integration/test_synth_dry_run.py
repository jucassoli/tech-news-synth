"""D-12: DRY_RUN still calls Anthropic; status='dry_run' + cost_usd > 0."""

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


def _settings_dry() -> Settings:
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
    os.environ["DRY_RUN"] = "1"
    return Settings()  # type: ignore[call-arg]


def test_dry_run_writes_status_dry_run(db_session, mocker):
    cid = "01DRYRUN000000000000000001"
    start_cycle(db_session, cid)
    upsert_batch(
        db_session,
        [
            {
                "source": "techcrunch",
                "url": "https://tc.com/d",
                "canonical_url": "https://tc.com/d",
                "title": "DRY_RUN Title",
                "summary": "sum",
                "published_at": datetime(2026, 4, 14, 9, 0, tzinfo=UTC),
                "article_hash": "d" * 64,
            }
        ],
    )
    db_session.flush()
    article = db_session.execute(select(Article)).scalar_one()
    cluster = insert_cluster(
        db_session, cycle_id=cid,
        member_article_ids=[article.id],
        centroid_terms={"apple": 0.9}, chosen=True, coverage_score=1.0,
    )

    mocker.patch.object(orch, "call_haiku", return_value=("Curto texto.", 80, 20))

    selection = SelectionResult(
        winner_cluster_id=cluster.id,
        winner_article_ids=[article.id],
        fallback_article_id=None,
        rejected_by_antirepeat=[],
        all_cluster_ids=[cluster.id],
        counts_patch={},
        winner_centroid=b"\x00\x00\x80\x3f",
    )

    sources = SourcesConfig(
        max_articles_per_fetch=30, max_article_age_hours=24,
        sources=[
            RssSource(name="techcrunch", type="rss", url="https://tc.com/feed", timeout_sec=20),  # type: ignore[arg-type]
        ],
    )
    allowlist = HashtagAllowlist(topics={"apple": ["#Apple"]}, default=["#tech"])

    result = orch.run_synthesis(
        db_session, cid, selection, _settings_dry(), sources, MagicMock(), allowlist,
    )
    assert result.status == "dry_run"
    row = db_session.execute(select(Post).where(Post.id == result.post_id)).scalar_one()
    assert row.status == "dry_run"
    assert float(row.cost_usd) > 0
