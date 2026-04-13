"""ORM models for Phase 2 storage: Article, Cluster, Post, RunLog.

Follows SA 2.0 typed Declarative (:class:`Mapped` + :func:`mapped_column`).
Every datetime column is ``DateTime(timezone=True)`` → Postgres ``TIMESTAMPTZ``
(STORE-06). Postgres-specific types come from ``sqlalchemy.dialects.postgresql``.

Key decisions honored:

* **D-04** — ``bigserial`` PKs on ``articles``, ``clusters``, ``posts``.
* **D-05** — ``run_log.cycle_id`` is the natural TEXT PK (26-char ULID); child
  tables ``clusters.cycle_id`` and ``posts.cycle_id`` are TEXT FKs with
  ``ON DELETE CASCADE``.
* **D-06** — ``articles.article_hash`` is ``String(64)`` (CHAR(64)) ``UNIQUE``
  — SHA256 hex of :func:`tech_news_synth.db.hashing.canonicalize_url`.
* **D-07** — ``posts.theme_centroid`` is ``LargeBinary`` (BYTEA), nullable;
  numpy float32 ``.tobytes()`` / ``np.frombuffer`` roundtrip.
* **posts.status** is constrained by a SQL ``CHECK`` (not pg ENUM) over
  ``{pending, posted, failed, dry_run}``.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from tech_news_synth.db.base import Base


class RunLog(Base):
    """One row per scheduler cycle — STORE-05.

    ``cycle_id`` is the natural TEXT primary key (ULID from Phase 1). Child
    tables reference it directly.
    """

    __tablename__ = "run_log"

    cycle_id: Mapped[str] = mapped_column(Text, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(Text, nullable=False)
    counts: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    notes: Mapped[str | None] = mapped_column(Text)


class Article(Base):
    """Normalized article — STORE-02.

    ``article_hash`` is the unique key; Phase 4 ingest upserts with
    ``ON CONFLICT (article_hash) DO NOTHING``.
    """

    __tablename__ = "articles"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)  # D-04 bigserial
    source: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    # D-06: SHA256 hex digest — CHAR(64) UNIQUE.
    article_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    etag: Mapped[str | None] = mapped_column(Text)
    last_modified: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        Index("ix_articles_published_at", "published_at"),
        Index("ix_articles_source_fetched_at", "source", "fetched_at"),
    )


class Cluster(Base):
    """Cluster membership per cycle — STORE-03."""

    __tablename__ = "clusters"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)  # D-04
    cycle_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("run_log.cycle_id", ondelete="CASCADE"),
        nullable=False,
    )
    member_article_ids: Mapped[list[int]] = mapped_column(
        ARRAY(BigInteger), nullable=False, server_default="{}"
    )
    centroid_terms: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    chosen: Mapped[bool] = mapped_column(nullable=False, server_default="false")
    coverage_score: Mapped[float | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (Index("ix_clusters_cycle_id", "cycle_id"),)


class Post(Base):
    """Publish attempt row — STORE-04.

    ``status`` constrained to ``{pending, posted, failed, dry_run}`` via SQL
    CHECK (not pg ENUM — easier to evolve via migration). ``theme_centroid``
    BYTEA holds the numpy float32 bytes (D-07); populated by Phase 5/7.
    """

    __tablename__ = "posts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)  # D-04
    cycle_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("run_log.cycle_id", ondelete="CASCADE"),
        nullable=False,
    )
    cluster_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("clusters.id", ondelete="SET NULL")
    )
    theme_centroid: Mapped[bytes | None] = mapped_column(LargeBinary)  # D-07
    status: Mapped[str] = mapped_column(Text, nullable=False)
    tweet_id: Mapped[str | None] = mapped_column(Text)
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    synthesized_text: Mapped[str | None] = mapped_column(Text)
    hashtags: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_detail: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'posted', 'failed', 'dry_run')",
            name="ck_posts_status",
        ),
        Index("ix_posts_cycle_id", "cycle_id"),
        Index("ix_posts_posted_at", "posted_at"),
        Index(
            "ix_posts_posted_at_48h",
            "posted_at",
            postgresql_where=(posted_at.isnot(None)),
        ),
    )


class SourceState(Base):
    """Per-source ingest health + conditional-GET cache (Phase 4 D-04).

    One row per entry in ``config/sources.yaml``. Upserted-on-first-sight by
    the orchestrator. Tracks ETag/Last-Modified for conditional GET
    (INGEST-04), consecutive_failures for auto-disable (INGEST-07), and
    last_fetched_at/last_status for operator observability.
    """

    __tablename__ = "source_state"

    name: Mapped[str] = mapped_column(Text, primary_key=True)
    etag: Mapped[str | None] = mapped_column(Text)
    last_modified: Mapped[str | None] = mapped_column(Text)
    consecutive_failures: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_status: Mapped[str | None] = mapped_column(Text)


__all__ = ["Article", "Cluster", "Post", "RunLog", "SourceState"]
