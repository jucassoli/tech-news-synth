"""sources.yaml loader + pydantic v2 discriminated union (D-01, D-02, D-03).

Implements INGEST-01 fail-fast config validation: the container exits
non-zero at boot on any schema violation. `yaml.safe_load` is mandatory —
`!!python/object*` tags are rejected before any object is instantiated
(T-04-01 mitigation).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, Field, HttpUrl, ValidationError, model_validator


class _SourceBase(BaseModel):
    """Common fields for every source type."""

    name: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    url: HttpUrl
    max_articles_per_fetch: int | None = Field(default=None, ge=1, le=200)
    # Phase 5 D-04/D-05: per-source weight for cluster ranking + fallback tiebreak.
    # Default 1.0 preserves backward compat with existing sources.yaml.
    weight: float = Field(default=1.0, ge=0.0, le=10.0)


class RssSource(_SourceBase):
    type: Literal["rss"]
    timeout_sec: float = Field(default=20.0, gt=0, le=120)


class HnFirebaseSource(_SourceBase):
    type: Literal["hn_firebase"]
    timeout_sec: float = Field(default=15.0, gt=0, le=120)


class RedditJsonSource(_SourceBase):
    type: Literal["reddit_json"]
    timeout_sec: float = Field(default=15.0, gt=0, le=120)


Source = Annotated[
    RssSource | HnFirebaseSource | RedditJsonSource,
    Field(discriminator="type"),
]


class SourcesConfig(BaseModel):
    """Top-level schema for config/sources.yaml."""

    max_articles_per_fetch: int = Field(default=30, ge=1, le=200)
    max_article_age_hours: int = Field(default=24, ge=1, le=168)
    sources: list[Source] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_unique_names(self) -> SourcesConfig:
        seen: set[str] = set()
        for s in self.sources:
            if s.name in seen:
                raise ValueError(f"duplicate source name: {s.name!r}")
            seen.add(s.name)
        return self


def load_sources_config(path: Path) -> SourcesConfig:
    """Load and validate ``sources.yaml``. Fail-fast on error (D-02, INGEST-01).

    Uses :func:`yaml.safe_load` — never :func:`yaml.load` (D-03, T-04-01).
    Malformed yaml or schema violations print to stderr and re-raise.
    """
    try:
        with path.open("r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)  # D-03 — NEVER yaml.load
        return SourcesConfig.model_validate(raw)
    except (yaml.YAMLError, ValidationError, ValueError) as e:
        print(f"sources.yaml error ({path}):\n{e}", file=sys.stderr)
        raise


__all__ = [
    "HnFirebaseSource",
    "RedditJsonSource",
    "RssSource",
    "Source",
    "SourcesConfig",
    "load_sources_config",
]
