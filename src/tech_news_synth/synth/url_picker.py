"""Source URL picker — stub for Plan 06-01 Task 1.

Task 3 implements the D-02 picker.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tech_news_synth.db.models import Article


def pick_source_url(
    selected_articles: list[Article],  # noqa: ARG001
    source_weights: dict[str, float],  # noqa: ARG001
) -> str:
    raise NotImplementedError("Plan 06-01 Task 3 implements pick_source_url")


__all__ = ["pick_source_url"]
