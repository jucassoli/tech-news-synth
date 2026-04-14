"""Phase 8 OPS-02 — replay CLI integration tests (real DB).

Verifies end-to-end replay on both winner + fallback cycles WITHOUT writing
new ``posts`` rows (T-08-02 durability of persist=False). Subprocess
approach rejected — we need transactional isolation via db_session.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from tech_news_synth.cli import replay
from tech_news_synth.db.articles import upsert_batch
from tech_news_synth.db.clusters import insert_cluster
from tech_news_synth.db.models import Article, Cluster, Post, RunLog
from tech_news_synth.db.run_log import start_cycle
from tech_news_synth.ingest.sources_config import RssSource, SourcesConfig
from tech_news_synth.synth.hashtags import HashtagAllowlist

pytestmark = pytest.mark.integration


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
    return HashtagAllowlist(topics={"apple": ["#Apple"]}, default=["#tech"])


@pytest.fixture(autouse=True)
def _cli_boot(mocker, db_session, tmp_path):
    """Route CLI boot to test session + tmp paths + stubbed settings."""
    os.environ["LOG_DIR"] = str(tmp_path)
    settings_stub = mocker.MagicMock(
        anthropic_api_key=SimpleNamespace(get_secret_value=lambda: "sk-ant-test"),
        sources_config_path="/dev/null",
        hashtags_config_path="/dev/null",
        synthesis_max_tokens=150,
        synthesis_char_budget=225,
        synthesis_max_retries=2,
        hashtag_budget_chars=30,
        dry_run=False,
    )
    mocker.patch("tech_news_synth.cli.replay.load_settings", return_value=settings_stub)
    mocker.patch("tech_news_synth.cli.replay.configure_logging")
    mocker.patch("tech_news_synth.cli.replay.init_engine")
    mocker.patch("tech_news_synth.cli.replay.load_sources_config", return_value=_sources())
    mocker.patch("tech_news_synth.cli.replay.load_hashtag_allowlist", return_value=_allowlist())
    mocker.patch("tech_news_synth.cli.replay.anthropic.Anthropic")

    session_cm = mocker.MagicMock()
    session_cm.__enter__ = lambda self: db_session
    session_cm.__exit__ = lambda self, *a: None
    mocker.patch("tech_news_synth.cli.replay.SessionLocal", return_value=session_cm)

    # Mock Anthropic call itself — returns canned body + tokens.
    mocker.patch(
        "tech_news_synth.synth.orchestrator.call_haiku",
        return_value=("Apple apresentou o chip M5 com aceleração IA.", 50, 20),
    )


def _seed_winner_cycle(db_session, cycle_id="01WINCYCLE000000000000001"):
    start_cycle(db_session, cycle_id)
    upsert_batch(
        db_session,
        [
            {
                "source": "techcrunch",
                "url": "https://tc.com/a",
                "canonical_url": "https://tc.com/a",
                "title": "Apple unveils M5",
                "summary": "Apple chip.",
                "published_at": datetime.now(UTC),
                "article_hash": "a" * 64,
            },
            {
                "source": "verge",
                "url": "https://verge.com/b",
                "canonical_url": "https://verge.com/b",
                "title": "Apple M5 revealed",
                "summary": "Silicon news.",
                "published_at": datetime.now(UTC),
                "article_hash": "b" * 64,
            },
        ],
    )
    db_session.flush()
    art_ids = [r.id for r in db_session.execute(select(Article)).scalars()]

    cluster = insert_cluster(
        db_session,
        cycle_id=cycle_id,
        member_article_ids=art_ids,
        centroid_terms={"apple": 0.9},
        chosen=True,
        coverage_score=2.0,
    )
    db_session.flush()

    # The original cycle's posts row. We store centroid bytes so replay can
    # roundtrip them into SelectionResult.winner_centroid.
    post = Post(
        cycle_id=cycle_id,
        cluster_id=cluster.id,
        theme_centroid=b"\x00\x01\x02\x03",
        status="posted",
        synthesized_text="Original text",
        hashtags=["#Apple"],
    )
    db_session.add(post)
    db_session.flush()
    # Commit releases the current SAVEPOINT → fixture restarts a new one.
    # This makes the seeded rows survive any rollback() the SUT performs.
    db_session.commit()
    return cycle_id


def _seed_fallback_cycle(db_session, cycle_id="01FALLCYCLE00000000000001"):
    start_cycle(db_session, cycle_id)
    upsert_batch(
        db_session,
        [
            {
                "source": "techcrunch",
                "url": "https://tc.com/f",
                "canonical_url": "https://tc.com/f",
                "title": "Fallback article",
                "summary": "Slow day.",
                "published_at": datetime.now(UTC),
                "article_hash": "f" * 64,
            },
        ],
    )
    db_session.flush()
    art_id = db_session.execute(select(Article.id)).scalar_one()

    # Update run_log.counts to carry fallback_article_id.
    run = db_session.execute(
        select(RunLog).where(RunLog.cycle_id == cycle_id)
    ).scalar_one()
    run.counts = {"fallback_used": True, "fallback_article_id": art_id}
    db_session.flush()

    # Post row with cluster_id=NULL (fallback branch signal).
    post = Post(
        cycle_id=cycle_id,
        cluster_id=None,
        theme_centroid=None,
        status="posted",
        synthesized_text="Original fallback text",
        hashtags=["#tech"],
    )
    db_session.add(post)
    db_session.flush()
    db_session.commit()  # release SAVEPOINT so seeds survive SUT rollback()
    return cycle_id, art_id


def _posts_count(db_session) -> int:
    return db_session.execute(select(func.count(Post.id))).scalar_one()


def _extract_json_line(stdout: str) -> dict:
    """The replay CLI prints structlog log lines (non-JSON by default during
    tests) followed by a single JSON payload line. Find the last line that
    parses as a JSON object with a ``cycle_id`` field.
    """
    last_err = None
    for line in reversed(stdout.splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as e:
            last_err = e
            continue
        if isinstance(obj, dict) and "cycle_id" in obj:
            return obj
    raise AssertionError(
        f"no JSON payload found in stdout; last error={last_err}\n{stdout!r}"
    )


def test_replay_winner_no_posts_row(db_session, capsys):
    cid = _seed_winner_cycle(db_session)
    before = _posts_count(db_session)

    rc = replay.main(["--cycle-id", cid])
    assert rc == 0

    after = _posts_count(db_session)
    assert after == before, "replay MUST NOT create new posts rows (T-08-02)"

    payload = _extract_json_line(capsys.readouterr().out)
    assert payload["cycle_id"] == cid
    assert payload["text"]
    assert isinstance(payload["hashtags"], list) and len(payload["hashtags"]) >= 1
    assert payload["cost_usd"] > 0


def test_replay_fallback_cycle(db_session, capsys):
    cid, art_id = _seed_fallback_cycle(db_session)
    before = _posts_count(db_session)

    rc = replay.main(["--cycle-id", cid])
    assert rc == 0

    after = _posts_count(db_session)
    assert after == before

    payload = _extract_json_line(capsys.readouterr().out)
    assert payload["cycle_id"] == cid
    assert "https://tc.com/f" in payload["text"]
    assert payload["hashtags"] == ["#tech"]  # fallback uses allowlist default


def test_replay_unknown_exits_1(db_session, capsys):
    rc = replay.main(["--cycle-id", "01BOGUSCYCLE0000000000000"])
    assert rc == 1
    assert "not found" in capsys.readouterr().err
