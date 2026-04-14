"""STORE-04 extension — ``get_recent_posts_with_source_texts`` P-9 filter."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from tech_news_synth.db.articles import ArticleRow, upsert_batch
from tech_news_synth.db.clusters import insert_cluster
from tech_news_synth.db.hashing import article_hash as hash_url
from tech_news_synth.db.hashing import canonicalize_url
from tech_news_synth.db.models import Post
from tech_news_synth.db.posts import PostWithTexts, get_recent_posts_with_source_texts
from tech_news_synth.db.run_log import start_cycle


def _row(url: str, title: str, summary: str | None = None) -> ArticleRow:
    return ArticleRow(
        source="techcrunch",
        url=url,
        canonical_url=canonicalize_url(url),
        title=title,
        summary=summary,
        published_at=datetime.now(UTC),
        article_hash=hash_url(url),
        etag=None,
        last_modified=None,
    )


def _seed_article_ids(db_session, rows: list[ArticleRow]) -> list[int]:
    upsert_batch(db_session, rows)
    db_session.flush()
    from sqlalchemy import select

    from tech_news_synth.db.models import Article

    ids = list(
        db_session.execute(select(Article.id).order_by(Article.id.asc())).scalars()
    )
    return ids


def _seed_post(
    db_session,
    cycle_id: str,
    cluster_id: int | None,
    status: str,
    posted_at: datetime | None,
) -> Post:
    post = Post(
        cycle_id=cycle_id,
        cluster_id=cluster_id,
        status=status,
        synthesized_text="t",
        hashtags=[],
        posted_at=posted_at,
    )
    db_session.add(post)
    db_session.flush()
    return post


def test_returns_posted_within_window(db_session) -> None:
    cycle_id = "01POSTSEED000000000000001"
    start_cycle(db_session, cycle_id)
    ids = _seed_article_ids(
        db_session,
        [
            _row("https://ex.com/1", "AI breakthrough", "Deep summary 1"),
            _row("https://ex.com/2", "AI news", "Deep summary 2"),
        ],
    )
    cluster = insert_cluster(db_session, cycle_id=cycle_id, member_article_ids=ids)
    _seed_post(
        db_session, cycle_id, cluster.id, "posted", datetime.now(UTC) - timedelta(hours=10)
    )

    got = get_recent_posts_with_source_texts(db_session, within_hours=48)
    assert len(got) == 1
    assert isinstance(got[0], PostWithTexts)
    assert len(got[0].source_texts) == 2


def test_excludes_pending_and_failed_and_dry_run(db_session) -> None:
    cycle_id = "01POSTSEED000000000000002"
    start_cycle(db_session, cycle_id)
    ids = _seed_article_ids(
        db_session, [_row("https://ex.com/p1", "T", "S")]
    )
    cluster = insert_cluster(db_session, cycle_id=cycle_id, member_article_ids=ids)
    now = datetime.now(UTC)
    _seed_post(db_session, cycle_id, cluster.id, "pending", None)
    _seed_post(db_session, cycle_id, cluster.id, "failed", None)
    _seed_post(db_session, cycle_id, cluster.id, "dry_run", None)
    _seed_post(db_session, cycle_id, cluster.id, "posted", now - timedelta(hours=10))

    got = get_recent_posts_with_source_texts(db_session, within_hours=48)
    assert len(got) == 1


def test_excludes_posts_outside_window(db_session) -> None:
    cycle_id = "01POSTSEED000000000000003"
    start_cycle(db_session, cycle_id)
    ids = _seed_article_ids(db_session, [_row("https://ex.com/w1", "T", "S")])
    cluster = insert_cluster(db_session, cycle_id=cycle_id, member_article_ids=ids)
    _seed_post(
        db_session, cycle_id, cluster.id, "posted", datetime.now(UTC) - timedelta(hours=50)
    )

    got = get_recent_posts_with_source_texts(db_session, within_hours=48)
    assert got == []


def test_excludes_posts_with_null_cluster_id(db_session) -> None:
    cycle_id = "01POSTSEED000000000000004"
    start_cycle(db_session, cycle_id)
    _seed_post(
        db_session, cycle_id, None, "posted", datetime.now(UTC) - timedelta(hours=1)
    )

    got = get_recent_posts_with_source_texts(db_session, within_hours=48)
    assert got == []


def test_source_texts_format(db_session) -> None:
    cycle_id = "01POSTSEED000000000000005"
    start_cycle(db_session, cycle_id)
    ids = _seed_article_ids(
        db_session,
        [
            _row("https://ex.com/f1", "Title A", "Summary A"),
            _row("https://ex.com/f2", "Title B", "Summary B"),
        ],
    )
    cluster = insert_cluster(db_session, cycle_id=cycle_id, member_article_ids=ids)
    _seed_post(
        db_session, cycle_id, cluster.id, "posted", datetime.now(UTC) - timedelta(hours=1)
    )

    got = get_recent_posts_with_source_texts(db_session, within_hours=48)
    assert len(got) == 1
    # Articles returned in id ASC — first seeded first.
    assert got[0].source_texts == ["Title A Summary A", "Title B Summary B"]


def test_source_texts_handles_null_summary(db_session) -> None:
    cycle_id = "01POSTSEED000000000000006"
    start_cycle(db_session, cycle_id)
    ids = _seed_article_ids(
        db_session, [_row("https://ex.com/n1", "Only title", None)]
    )
    cluster = insert_cluster(db_session, cycle_id=cycle_id, member_article_ids=ids)
    _seed_post(
        db_session, cycle_id, cluster.id, "posted", datetime.now(UTC) - timedelta(hours=1)
    )

    got = get_recent_posts_with_source_texts(db_session, within_hours=48)
    assert got[0].source_texts == ["Only title"]
