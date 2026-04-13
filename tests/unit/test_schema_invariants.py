"""Schema-level invariants (STORE-02, STORE-04, STORE-06).

Pure introspection of ``Base.metadata`` — no DB roundtrip required.
"""

from __future__ import annotations

import sqlalchemy as sa

import tech_news_synth.db.models  # noqa: F401 — register models on Base.metadata
from tech_news_synth.db.base import Base

EXPECTED_TABLES = {"articles", "clusters", "posts", "run_log"}


def test_tables_present() -> None:
    assert set(Base.metadata.tables) == EXPECTED_TABLES


def test_every_datetime_is_timestamptz() -> None:
    """STORE-06 — every datetime column must be TIMESTAMPTZ (timezone=True)."""
    for table in Base.metadata.tables.values():
        for col in table.columns:
            if isinstance(col.type, sa.DateTime):
                assert col.type.timezone is True, f"{table.name}.{col.name} is not TIMESTAMPTZ"


def test_article_hash_is_char64_unique() -> None:
    col = Base.metadata.tables["articles"].c.article_hash
    assert isinstance(col.type, sa.String)
    assert col.type.length == 64
    assert col.unique is True
    assert col.nullable is False


def test_posts_status_check_covers_all_four_statuses() -> None:
    table = Base.metadata.tables["posts"]
    checks = [c for c in table.constraints if isinstance(c, sa.CheckConstraint)]
    assert checks, "posts has no CheckConstraint"

    sqltexts = [str(c.sqltext) for c in checks]
    joined = " ".join(sqltexts)
    for status in ("pending", "posted", "failed", "dry_run"):
        assert status in joined, f"status '{status}' missing from posts CHECK: {joined}"


def test_posts_theme_centroid_is_largebinary_nullable() -> None:
    col = Base.metadata.tables["posts"].c.theme_centroid
    assert isinstance(col.type, sa.LargeBinary)
    assert col.nullable is True


def test_cycle_id_fk_relationships() -> None:
    run_log_cycle = Base.metadata.tables["run_log"].c.cycle_id
    assert run_log_cycle.primary_key is True
    assert isinstance(run_log_cycle.type, sa.Text)

    for child in ("clusters", "posts"):
        col = Base.metadata.tables[child].c.cycle_id
        fks = list(col.foreign_keys)
        assert len(fks) == 1, f"{child}.cycle_id should have exactly one FK"
        assert fks[0].column is run_log_cycle
        assert col.nullable is False


def test_article_and_cluster_and_post_ids_are_bigint() -> None:
    """D-04 — bigserial PKs."""
    for name in ("articles", "clusters", "posts"):
        col = Base.metadata.tables[name].c.id
        assert isinstance(col.type, sa.BigInteger), (
            f"{name}.id is not BigInteger (got {type(col.type).__name__})"
        )
        assert col.primary_key is True
