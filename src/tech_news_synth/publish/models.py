"""Frozen pydantic boundary models exposed by the publish package (Phase 7)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class CapCheckResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    daily_count: int
    daily_reached: bool
    monthly_cost_usd: float
    monthly_cost_reached: bool
    skip_synthesis: bool


class PublishResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    post_id: int | None
    status: Literal["posted", "failed", "dry_run", "capped", "empty"]
    tweet_id: str | None
    attempts: int
    elapsed_ms: int
    error_detail: dict | None
    counts_patch: dict[str, object]
    tweet_ids: list[str] = Field(default_factory=list)
    parts_posted: int = 0
    failed_part: int | None = None


__all__ = ["CapCheckResult", "PublishResult"]
