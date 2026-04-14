"""Diverse-sources-first article picker — stub for Plan 06-01 Task 1.

Task 3 implements the D-01 picker.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tech_news_synth.db.models import Article


def pick_articles_for_synthesis(
    cluster_articles: list[Article],  # noqa: ARG001
    max_articles: int = 5,  # noqa: ARG001
) -> list[Article]:
    raise NotImplementedError("Plan 06-01 Task 3 implements pick_articles_for_synthesis")


__all__ = ["pick_articles_for_synthesis"]
