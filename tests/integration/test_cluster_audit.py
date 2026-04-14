"""CLUSTER-07 — orchestrator persists ALL candidates; winner flagged."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from tech_news_synth.cluster.orchestrator import run_clustering
from tech_news_synth.config import Settings, load_settings
from tech_news_synth.db.articles import ArticleRow, upsert_batch
from tech_news_synth.db.hashing import article_hash as hash_url
from tech_news_synth.db.hashing import canonicalize_url
from tech_news_synth.db.models import Cluster
from tech_news_synth.db.run_log import start_cycle
from tech_news_synth.ingest.sources_config import RssSource, SourcesConfig

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "cluster"


@pytest.fixture
def settings(monkeypatch_env) -> Settings:
    return load_settings()


def _seed_fixture(db_session, fixture_name: str) -> None:
    data = json.loads((FIXTURE_DIR / fixture_name).read_text())
    if isinstance(data, dict):
        items = data["current_articles"]
    else:
        items = data
    now = datetime.now(UTC)
    rows: list[ArticleRow] = []
    for i, a in enumerate(items):
        url = f"https://seed.test/{fixture_name}/{a['id']}"
        rows.append(
            ArticleRow(
                source=a["source"],
                url=url,
                canonical_url=canonicalize_url(url),
                title=a["title"],
                summary=a["summary"],
                # Use a recent timestamp so the 6h window covers it; preserve order.
                published_at=now - timedelta(minutes=len(items) - i),
                article_hash=hash_url(url),
                etag=None,
                last_modified=None,
            )
        )
    upsert_batch(db_session, rows)
    db_session.flush()


def _sources_config(sources: list[str]) -> SourcesConfig:
    src_models = [
        RssSource(
            name=s,
            url="https://example.com/feed",  # validator only
            type="rss",
            weight=1.0,
        )
        for s in sources
    ]
    return SourcesConfig(sources=src_models)


def test_all_candidates_persisted_with_chosen_false_then_winner_flagged(
    db_session, settings: Settings
) -> None:
    cycle_id = "01AUDITSEED000000000000001"
    start_cycle(db_session, cycle_id)
    _seed_fixture(db_session, "hot_topic.json")
    cfg = _sources_config(["techcrunch", "verge", "ars_technica", "hacker_news"])

    result = run_clustering(db_session, cycle_id, settings, cfg)

    clusters = list(
        db_session.execute(
            select(Cluster).where(Cluster.cycle_id == cycle_id).order_by(Cluster.id)
        ).scalars()
    )
    # hot_topic has 3 multi-source clusters of 4 each.
    assert len(clusters) == 3
    chosen_rows = [c for c in clusters if c.chosen]
    assert len(chosen_rows) == 1
    assert chosen_rows[0].id == result.winner_cluster_id
    assert len(result.all_cluster_ids) == 3
    assert result.counts_patch["chosen_cluster_id"] == chosen_rows[0].id
    assert result.counts_patch["cluster_count"] == 3
    assert result.counts_patch["singleton_count"] == 0


def test_singletons_persisted_with_chosen_false(
    db_session, settings: Settings
) -> None:
    cycle_id = "01AUDITSEED000000000000002"
    start_cycle(db_session, cycle_id)
    _seed_fixture(db_session, "mixed.json")
    cfg = _sources_config(
        ["techcrunch", "verge", "ars_technica", "hacker_news", "reddit_technology"]
    )

    result = run_clustering(db_session, cycle_id, settings, cfg)

    clusters = list(
        db_session.execute(
            select(Cluster).where(Cluster.cycle_id == cycle_id).order_by(Cluster.id)
        ).scalars()
    )
    # mixed = 1 multi (EU AI Act, 4 articles, 3 sources) + 6 singletons.
    assert len(clusters) >= 2
    chosen_rows = [c for c in clusters if c.chosen]
    assert len(chosen_rows) == 1
    # Remaining must be singletons (coverage 1.0) OR the chosen multi.
    non_chosen = [c for c in clusters if not c.chosen]
    assert all(c.coverage_score is not None for c in non_chosen)
    # Singleton count in patch matches rows with coverage_score == 1.0.
    singletons_in_db = [c for c in clusters if c.coverage_score == 1.0]
    assert result.counts_patch["singleton_count"] == len(singletons_in_db)


def test_centroid_terms_populated(db_session, settings: Settings) -> None:
    cycle_id = "01AUDITSEED000000000000003"
    start_cycle(db_session, cycle_id)
    _seed_fixture(db_session, "hot_topic.json")
    cfg = _sources_config(["techcrunch", "verge", "ars_technica", "hacker_news"])

    run_clustering(db_session, cycle_id, settings, cfg)

    clusters = list(
        db_session.execute(
            select(Cluster).where(Cluster.cycle_id == cycle_id)
        ).scalars()
    )
    assert clusters
    for c in clusters:
        assert isinstance(c.centroid_terms, dict)
        assert len(c.centroid_terms) > 0
        assert len(c.centroid_terms) <= 20
        for term, weight in c.centroid_terms.items():
            assert isinstance(term, str)
            assert isinstance(weight, float)


def test_no_commit_inside_orchestrator(db_session, settings: Settings) -> None:
    """Wrap in savepoint, rollback, assert orchestrator didn't persist beyond."""
    cycle_id = "01AUDITSEED000000000000004"
    start_cycle(db_session, cycle_id)
    _seed_fixture(db_session, "hot_topic.json")
    cfg = _sources_config(["techcrunch", "verge", "ars_technica", "hacker_news"])

    run_clustering(db_session, cycle_id, settings, cfg)
    # Confirm rows present in-session.
    pre_rollback = db_session.execute(
        select(Cluster).where(Cluster.cycle_id == cycle_id)
    ).scalars().all()
    assert len(pre_rollback) > 0

    # Roll back to savepoint (the db_session fixture uses nested savepoints).
    db_session.rollback()

    post_rollback = db_session.execute(
        select(Cluster).where(Cluster.cycle_id == cycle_id)
    ).scalars().all()
    assert len(post_rollback) == 0
