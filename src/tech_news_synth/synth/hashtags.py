"""Hashtag allowlist + selector — stub for Plan 06-01 Task 1.

Task 4 implements the D-11 loader + selector.
"""

from __future__ import annotations

from pathlib import Path  # noqa: F401 — used by future Task 4

from pydantic import BaseModel, ConfigDict


class HashtagAllowlist(BaseModel):
    model_config = ConfigDict(frozen=True)
    topics: dict[str, list[str]]
    default: list[str]


def load_hashtag_allowlist(path: Path) -> HashtagAllowlist:  # noqa: ARG001
    raise NotImplementedError("Plan 06-01 Task 4 implements load_hashtag_allowlist")


def select_hashtags(
    centroid_terms: dict[str, float],  # noqa: ARG001
    allowlist: HashtagAllowlist,  # noqa: ARG001
    top_k: int = 10,  # noqa: ARG001
    max_tags: int = 2,  # noqa: ARG001
) -> list[str]:
    raise NotImplementedError("Plan 06-01 Task 4 implements select_hashtags")


__all__ = ["HashtagAllowlist", "load_hashtag_allowlist", "select_hashtags"]
