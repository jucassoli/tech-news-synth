"""SelectionResult — Phase 5's public return type to the scheduler (D-14).

Plan 05-01 exposes this model so Plan 05-02's orchestrator and Phase 6's
synthesis stage can rely on a stable, frozen contract.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class SelectionResult(BaseModel):
    """Per-cycle clustering + ranking outcome (D-14)."""

    model_config = ConfigDict(frozen=True)

    winner_cluster_id: int | None
    winner_article_ids: list[int] | None
    fallback_article_id: int | None
    rejected_by_antirepeat: list[int]
    all_cluster_ids: list[int]
    counts_patch: dict[str, object]
    # Phase 6 Plan 06-01: numpy float32 centroid bytes (D-09 plumbing).
    # Default None preserves backward compat for the fallback branch and
    # for tests constructed before this field existed.
    winner_centroid: bytes | None = None


__all__ = ["SelectionResult"]
