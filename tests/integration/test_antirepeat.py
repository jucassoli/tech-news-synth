"""CLUSTER-05 — end-to-end anti-repeat filtering via run_clustering."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from tech_news_synth.cluster.orchestrator import run_clustering
from tech_news_synth.config import Settings, load_settings
from tech_news_synth.db.articles import ArticleRow, upsert_batch
from tech_news_synth.db.clusters import insert_cluster
from tech_news_synth.db.hashing import article_hash as hash_url
from tech_news_synth.db.hashing import canonicalize_url
from tech_news_synth.db.models import Article, Post
from tech_news_synth.db.run_log import start_cycle
from tech_news_synth.ingest.sources_config import RssSource, SourcesConfig


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


def _seed_two_topic_window(db_session, prefix: str) -> None:
    """Seed current-window articles: topic A (Apple M5) + topic B (GPT-5).

    Uses lexically-tight PT-BR phrasings borrowed from hot_topic.json —
    known to cluster at distance_threshold=0.35.
    """
    now = datetime.now(UTC)
    # Apple articles are MORE recent so rank_candidates picks Apple first
    # (both topics have source_count=4; most_recent_ts breaks the tie per D-09).
    rows = [
        # Topic B — OpenAI GPT-5 (4 sources) — older
        _row(
            f"https://{prefix}.test/b1",
            "techcrunch",
            "OpenAI lança GPT-5 para desenvolvedores",
            "OpenAI lançou GPT-5 para desenvolvedores via API com contexto maior hoje.",
            now - timedelta(minutes=40),
        ),
        _row(
            f"https://{prefix}.test/b2",
            "verge",
            "OpenAI lança GPT-5 desenvolvedores",
            "OpenAI lançou GPT-5 desenvolvedores via API com contexto maior.",
            now - timedelta(minutes=35),
        ),
        _row(
            f"https://{prefix}.test/b3",
            "ars_technica",
            "OpenAI lança GPT-5 para desenvolvedores API",
            "OpenAI lançou GPT-5 para desenvolvedores API contexto maior.",
            now - timedelta(minutes=30),
        ),
        _row(
            f"https://{prefix}.test/b4",
            "reddit_technology",
            "OpenAI GPT-5 lança desenvolvedores",
            "OpenAI GPT-5 lançou desenvolvedores API contexto.",
            now - timedelta(minutes=25),
        ),
        # Topic A — Apple iPhone M5 (4 sources) — more recent → ranked first
        _row(
            f"https://{prefix}.test/a1",
            "techcrunch",
            "Apple anuncia novo iPhone com chip M5",
            "Apple anunciou novo iPhone com chip M5 e foco em IA no dispositivo hoje.",
            now - timedelta(minutes=20),
        ),
        _row(
            f"https://{prefix}.test/a2",
            "verge",
            "Apple anuncia iPhone com chip M5",
            "Apple anunciou iPhone com chip M5 e NPU para IA no dispositivo.",
            now - timedelta(minutes=15),
        ),
        _row(
            f"https://{prefix}.test/a3",
            "ars_technica",
            "Apple anuncia iPhone com novo chip M5",
            "Apple anunciou iPhone com novo chip M5 focado em IA no dispositivo.",
            now - timedelta(minutes=10),
        ),
        _row(
            f"https://{prefix}.test/a4",
            "hacker_news",
            "Apple anuncia iPhone chip M5",
            "Apple anunciou iPhone chip M5 com IA no dispositivo.",
            now - timedelta(minutes=5),
        ),
    ]
    upsert_batch(db_session, rows)
    db_session.flush()


def _seed_past_post_matching(
    db_session,
    cycle_id_past: str,
    posted_ago_hours: int,
    article_rows: list[ArticleRow],
    status: str = "posted",
) -> int:
    """Seed a past post with a cluster referring to article_rows."""
    upsert_batch(db_session, article_rows)
    db_session.flush()
    article_ids = list(
        db_session.execute(
            select(Article.id).where(
                Article.canonical_url.in_([r["canonical_url"] for r in article_rows])
            )
        ).scalars()
    )
    cluster = insert_cluster(
        db_session,
        cycle_id=cycle_id_past,
        member_article_ids=article_ids,
    )
    posted_at = (
        datetime.now(UTC) - timedelta(hours=posted_ago_hours)
        if status == "posted"
        else None
    )
    post = Post(
        cycle_id=cycle_id_past,
        cluster_id=cluster.id,
        status=status,
        synthesized_text="past",
        hashtags=[],
        posted_at=posted_at,
    )
    db_session.add(post)
    db_session.flush()
    return post.id


def test_winner_rejected_by_antirepeat_chooses_next(
    db_session, settings: Settings
) -> None:
    """Past post matches topic A → topic B wins."""
    past_cycle = "01ANTIREP00000000000000001"
    curr_cycle = "01ANTIREP00000000000000002"
    start_cycle(db_session, past_cycle)
    # Past post's source articles mirror topic A (Apple M5) lexically.
    past_rows = [
        _row(
            "https://past.test/p1",
            "techcrunch",
            "Apple anuncia novo iPhone com chip M5",
            "Apple anunciou novo iPhone com chip M5 e foco em IA no dispositivo.",
            datetime.now(UTC) - timedelta(hours=30),
        ),
        _row(
            "https://past.test/p2",
            "verge",
            "Apple anuncia iPhone com chip M5 IA",
            "Apple anunciou iPhone com chip M5 e NPU para IA no dispositivo.",
            datetime.now(UTC) - timedelta(hours=30),
        ),
    ]
    _seed_past_post_matching(db_session, past_cycle, 30, past_rows)

    start_cycle(db_session, curr_cycle)
    _seed_two_topic_window(db_session, "cur1")
    cfg = _sources_config(
        ["techcrunch", "verge", "ars_technica", "hacker_news", "reddit_technology"]
    )

    result = run_clustering(db_session, curr_cycle, settings, cfg)

    assert result.winner_cluster_id is not None
    # Topic A (Apple M5) should be rejected; Topic B (GPT-5) wins.
    assert len(result.rejected_by_antirepeat) >= 1
    assert result.winner_cluster_id not in result.rejected_by_antirepeat
    assert result.counts_patch["rejected_by_antirepeat"] == result.rejected_by_antirepeat
    # Winner articles should NOT be Apple.
    winner_titles = [
        t for t in db_session.execute(
            select(Article.title).where(Article.id.in_(result.winner_article_ids))
        ).scalars()
    ]
    assert any("OpenAI" in t or "GPT" in t for t in winner_titles)
    assert not any("Apple" in t for t in winner_titles)


def test_past_post_with_pending_status_does_NOT_trigger_antirepeat(
    db_session, settings: Settings
) -> None:
    """P-9 filter: pending/failed/dry_run posts never block."""
    past_cycle = "01ANTIREP00000000000000003"
    curr_cycle = "01ANTIREP00000000000000004"
    start_cycle(db_session, past_cycle)
    past_rows = [
        _row(
            "https://past2.test/p1",
            "techcrunch",
            "Apple anuncia novo iPhone com chip M5",
            "Apple anunciou novo iPhone com chip M5 e foco em IA no dispositivo.",
            datetime.now(UTC) - timedelta(hours=30),
        ),
        _row(
            "https://past2.test/p2",
            "verge",
            "Apple anuncia iPhone com chip M5 IA",
            "Apple anunciou iPhone com chip M5 e NPU para IA no dispositivo.",
            datetime.now(UTC) - timedelta(hours=30),
        ),
    ]
    _seed_past_post_matching(db_session, past_cycle, 30, past_rows, status="pending")

    start_cycle(db_session, curr_cycle)
    _seed_two_topic_window(db_session, "cur2")
    cfg = _sources_config(
        ["techcrunch", "verge", "ars_technica", "hacker_news", "reddit_technology"]
    )

    result = run_clustering(db_session, curr_cycle, settings, cfg)
    # Pending post must not block.
    assert result.rejected_by_antirepeat == []


def test_past_post_outside_window_does_NOT_trigger(
    db_session, settings: Settings
) -> None:
    """posted_at > within_hours excluded (window=48h, post=72h old)."""
    past_cycle = "01ANTIREP00000000000000005"
    curr_cycle = "01ANTIREP00000000000000006"
    start_cycle(db_session, past_cycle)
    past_rows = [
        _row(
            "https://past3.test/p1",
            "techcrunch",
            "Apple anuncia novo iPhone com chip M5",
            "Apple anunciou novo iPhone com chip M5 e foco em IA no dispositivo.",
            datetime.now(UTC) - timedelta(hours=72),
        ),
        _row(
            "https://past3.test/p2",
            "verge",
            "Apple anuncia iPhone com chip M5 IA",
            "Apple anunciou iPhone com chip M5 e NPU para IA no dispositivo.",
            datetime.now(UTC) - timedelta(hours=72),
        ),
    ]
    _seed_past_post_matching(db_session, past_cycle, 72, past_rows, status="posted")

    start_cycle(db_session, curr_cycle)
    _seed_two_topic_window(db_session, "cur3")
    cfg = _sources_config(
        ["techcrunch", "verge", "ars_technica", "hacker_news", "reddit_technology"]
    )

    result = run_clustering(db_session, curr_cycle, settings, cfg)
    assert result.rejected_by_antirepeat == []
