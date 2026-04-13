"""Phase 4 pydantic boundary models (D-07).

``ArticleRow`` is the normalized row emitted by fetchers and consumed by
``tech_news_synth.db.articles.upsert_batch``. Distinct from the Phase 2
``ArticleRow`` TypedDict in ``db.articles`` — this pydantic model enforces
UTC-aware datetimes and the SHA256 hash width at construction time.
Convert via ``row.model_dump()`` when calling ``upsert_batch``.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class ArticleRow(BaseModel):
    """Normalized article produced by a Phase 4 fetcher (INGEST-06).

    Field semantics:
    - ``source``: source.name from sources.yaml (trusted identity, T-04-07)
    - ``url``: raw URL from feed
    - ``canonical_url``: via :func:`tech_news_synth.db.hashing.canonicalize_url`
    - ``article_hash``: 64-char lowercase hex SHA256 of canonical_url
    - ``title``: stripped raw title
    - ``summary``: HTML-stripped, truncated to 1000 chars
    - ``published_at``: UTC-aware datetime (falls back to fetched_at if source
      omits; a naive input is rejected by :meth:`_require_utc`)
    - ``fetched_at``: UTC-aware datetime set by orchestrator
    """

    source: str = Field(min_length=1)
    url: str = Field(min_length=1)
    canonical_url: str = Field(min_length=1)
    article_hash: str = Field(min_length=64, max_length=64)
    title: str = Field(min_length=1)
    summary: str = ""
    published_at: datetime
    fetched_at: datetime

    @field_validator("published_at", "fetched_at")
    @classmethod
    def _require_utc(cls, v: datetime) -> datetime:
        """T-04-08: tz-aware datetimes only — naive inputs would break the
        48h anti-repetition math downstream."""
        if v.tzinfo is None:
            raise ValueError("must be tz-aware UTC")
        return v


__all__ = ["ArticleRow"]
