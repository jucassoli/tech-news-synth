"""Frozen pydantic models exposed by the synth package (Phase 6)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SynthesisResult(BaseModel):
    """Per-cycle synthesis outcome, consumed by 06-02 orchestrator + scheduler."""

    model_config = ConfigDict(frozen=True)

    text: str  # root post text
    body_text: str  # root body only
    hashtags: list[str]
    source_url: str
    attempts: int  # 1..synthesis_max_retries+1
    final_method: Literal["completed", "truncated"]
    input_tokens: int
    output_tokens: int
    cost_usd: float
    post_id: int | None  # populated after 06-02 persists; None when persist=False (Phase 8)
    status: Literal["pending", "dry_run", "replay"]
    counts_patch: dict[str, object]  # for run_log.counts merge
    reply_texts: list[str] = Field(default_factory=list)
    thread_texts: list[str] = Field(default_factory=list)
    thread_parts_planned: int = 1
    card_probe: dict[str, object] = Field(default_factory=dict)


__all__ = ["SynthesisResult"]
