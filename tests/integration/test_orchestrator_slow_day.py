"""CLUSTER-06 — fallback on slow day + empty + N==1 windows; determinism."""

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
from tech_news_synth.db.models import Article, Cluster
from tech_news_synth.db.run_log import start_cycle
from tech_news_synth.ingest.sources_config import RssSource, SourcesConfig

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "cluster"


@pytest.fixture
def settings(monkeypatch_env) -> Settings:
    return load_settings()


def _sources_config(sources: list[str]) -> SourcesConfig:
    return SourcesConfig(
        sources=[
            RssSource(name=s, url="https://example.com/feed", type="rss", weight=1.0)
            for s in sources
        ]
    )


def _row(url: str, source: str, title: str, summary: str, published_at: datetime) -> ArticleRow:
    return ArticleRow(
        source=source,
        url=url,
        canonical_url=canonicalize_url(url),
        title=title,
        summary=summary,
        published_at=published_at,
        article_hash=hash_url(url),
        etag=None,
        last_modified=None,
    )


def _seed_slow_day(db_session) -> list[int]:
    data = json.loads((FIXTURE_DIR / "slow_day.json").read_text())
    now = datetime.now(UTC)
    rows = [
        _row(
            f"https://slow.test/{a['id']}",
            a["source"],
            a["title"],
            a["summary"],
            now - timedelta(minutes=len(data) - i),
        )
        for i, a in enumerate(data)
    ]
    upsert_batch(db_session, rows)
    db_session.flush()
    return list(
        db_session.execute(
            select(Article.id)
            .where(Article.canonical_url.in_([r["canonical_url"] for r in rows]))
            .order_by(Article.id)
        ).scalars()
    )


def test_slow_day_all_singletons_triggers_fallback(
    db_session, settings: Settings
) -> None:
    cycle_id = "01SLOW0000000000000000001"
    start_cycle(db_session, cycle_id)
    _seed_slow_day(db_session)
    cfg = _sources_config(
        ["techcrunch", "verge", "ars_technica", "hacker_news", "reddit_technology"]
    )

    result = run_clustering(db_session, cycle_id, settings, cfg)

    assert result.counts_patch["cluster_count"] == 0  # no multi-source candidates
    assert result.counts_patch["singleton_count"] == 6
    assert result.counts_patch["fallback_used"] is True
    assert result.fallback_article_id is not None

    # All 6 singletons persisted with chosen=False.
    clusters = list(
        db_session.execute(
            select(Cluster).where(Cluster.cycle_id == cycle_id)
        ).scalars()
    )
    assert len(clusters) == 6
    assert all(c.chosen is False for c in clusters)


def test_empty_window_no_writes(db_session, settings: Settings) -> None:
    cycle_id = "01EMPTY000000000000000001"
    start_cycle(db_session, cycle_id)
    cfg = _sources_config(["techcrunch"])

    result = run_clustering(db_session, cycle_id, settings, cfg)

    assert result.winner_cluster_id is None
    assert result.fallback_article_id is None
    assert result.counts_patch["articles_in_window"] == 0

    clusters = list(
        db_session.execute(
            select(Cluster).where(Cluster.cycle_id == cycle_id)
        ).scalars()
    )
    assert clusters == []


def test_single_article_window_fallback(db_session, settings: Settings) -> None:
    cycle_id = "01SINGLE00000000000000001"
    start_cycle(db_session, cycle_id)
    now = datetime.now(UTC)
    upsert_batch(
        db_session,
        [
            _row(
                "https://one.test/x",
                "techcrunch",
                "Only article",
                "Only summary",
                now - timedelta(minutes=5),
            )
        ],
    )
    db_session.flush()
    only_id = db_session.execute(select(Article.id)).scalar_one()
    cfg = _sources_config(["techcrunch"])

    result = run_clustering(db_session, cycle_id, settings, cfg)

    assert result.counts_patch["fallback_used"] is True
    assert result.fallback_article_id == only_id
    # Phase 8 contract lock (D-06 field 5 derives from this key): the
    # counts_patch MUST expose fallback_article_id on the fallback branch so
    # cli.replay can re-materialize the single-article input without touching
    # the posts row. Regression guard — do not remove.
    assert result.counts_patch["fallback_article_id"] == only_id
    assert result.counts_patch["articles_in_window"] == 1

    clusters = list(
        db_session.execute(
            select(Cluster).where(Cluster.cycle_id == cycle_id)
        ).scalars()
    )
    assert clusters == []


def test_determinism_end_to_end(db_session, settings: Settings) -> None:
    """Run 3 times, assert identical SelectionResult each time."""
    cycle_id = "01DETERM00000000000000001"
    start_cycle(db_session, cycle_id)
    _seed_slow_day(db_session)
    cfg = _sources_config(
        ["techcrunch", "verge", "ars_technica", "hacker_news", "reddit_technology"]
    )

    results = []
    for _ in range(3):
        res = run_clustering(db_session, cycle_id, settings, cfg)
        # Drop all_cluster_ids + chosen_cluster_id — they change because we
        # re-insert rows each iteration (new PKs). Determinism contract is
        # on the clustering + fallback outcome, not DB PKs.
        key = (
            res.winner_cluster_id is not None,
            tuple(sorted(res.winner_article_ids or [])),
            res.fallback_article_id,
            res.counts_patch["cluster_count"],
            res.counts_patch["singleton_count"],
            res.counts_patch["fallback_used"],
            res.counts_patch["articles_in_window"],
        )
        results.append(key)
    assert results[0] == results[1] == results[2]
