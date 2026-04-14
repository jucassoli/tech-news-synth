"""10-post spot-check: every fixture synthesized output ≤ 280 weighted chars."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from sqlalchemy import select

from tech_news_synth.cluster.models import SelectionResult
from tech_news_synth.config import Settings
from tech_news_synth.db.articles import upsert_batch
from tech_news_synth.db.clusters import insert_cluster
from tech_news_synth.db.models import Article, Post
from tech_news_synth.db.run_log import start_cycle
from tech_news_synth.ingest.sources_config import RedditJsonSource, RssSource, SourcesConfig
from tech_news_synth.synth import orchestrator as orch
from tech_news_synth.synth.charcount import weighted_len
from tech_news_synth.synth.hashtags import load_hashtag_allowlist

pytestmark = pytest.mark.integration

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "synth"
FIXTURE_PATHS = sorted(FIXTURES_DIR.glob("post_*.json"))


def _settings() -> Settings:
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
    os.environ["DRY_RUN"] = "0"
    return Settings()  # type: ignore[call-arg]


def _sources_from_fixture(fixture: dict) -> SourcesConfig:
    names = {a["source"] for a in fixture["cluster_articles"]}
    sources = []
    for n in sorted(names):
        if n.startswith("reddit"):
            sources.append(
                RedditJsonSource(name=n, type="reddit_json", url=f"https://reddit.com/r/{n}.json", timeout_sec=15)  # type: ignore[arg-type]
            )
        else:
            sources.append(
                RssSource(name=n, type="rss", url=f"https://{n}.example.com/feed", timeout_sec=20)  # type: ignore[arg-type]
            )
    return SourcesConfig(
        max_articles_per_fetch=30, max_article_age_hours=24, sources=sources,
    )


def _seed_from_fixture(db_session, fixture: dict, cycle_id: str):
    start_cycle(db_session, cycle_id)
    rows = []
    for i, a in enumerate(fixture["cluster_articles"]):
        h = hashlib.sha256(a["url"].encode()).hexdigest()
        rows.append(
            {
                "source": a["source"],
                "url": a["url"],
                "canonical_url": a["url"],
                "title": a["title"],
                "summary": a.get("summary") or "",
                "published_at": datetime.fromisoformat(a["published_at"].replace("Z", "+00:00")),
                "article_hash": h,
            }
        )
    upsert_batch(db_session, rows)
    db_session.flush()
    # Fetch ids in canonical order
    art_rows = list(db_session.execute(select(Article).order_by(Article.id)).scalars())
    ids = [a.id for a in art_rows]
    cluster = insert_cluster(
        db_session, cycle_id=cycle_id,
        member_article_ids=ids,
        centroid_terms=fixture["centroid_terms"],
        chosen=True, coverage_score=float(len(ids)),
    )
    return cluster.id, ids


@pytest.mark.parametrize("fixture_path", FIXTURE_PATHS, ids=lambda p: p.stem)
def test_fixture_spot_check_weighted_len(db_session, mocker, fixture_path: Path):
    fixture = json.loads(fixture_path.read_text())
    # Short PT-BR body (under budget) — simulates a well-behaved Haiku response.
    body = "Notícia sintetizada em português sobre o tema principal do ciclo."
    mocker.patch.object(orch, "call_haiku", return_value=(body, 120, 40))

    allowlist = load_hashtag_allowlist(FIXTURES_DIR / "hashtags.yaml")

    # cycle_id is 26-char ULID-ish; slug derived from fixture name
    suffix = fixture_path.stem.replace("_", "").upper()
    cid = ("01FIX" + suffix).ljust(26, "0")[:26]

    cluster_id, article_ids = _seed_from_fixture(db_session, fixture, cid)

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
        db_session, cid, selection, _settings(),
        _sources_from_fixture(fixture),
        MagicMock(name="anthropic"),
        allowlist,
    )
    # Invariant
    assert weighted_len(result.text) <= 280
    # URL in text
    assert result.source_url in result.text
    # At least 1 hashtag present
    assert len(result.hashtags) >= 1
    # posts row exists
    row = db_session.execute(select(Post).where(Post.id == result.post_id)).scalar_one()
    assert row.synthesized_text == result.text
