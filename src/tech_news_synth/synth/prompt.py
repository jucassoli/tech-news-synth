"""Synthesis prompts + final-post formatter — stub for Plan 06-01 Task 1.

Task 4 populates build_system_prompt / build_user_prompt / build_retry_prompt
/ format_final_post per D-07.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tech_news_synth.db.models import Article


def build_system_prompt(char_budget: int) -> str:  # noqa: ARG001
    raise NotImplementedError("Plan 06-01 Task 4 implements build_system_prompt")


def build_user_prompt(articles: list[Article]) -> str:  # noqa: ARG001
    raise NotImplementedError("Plan 06-01 Task 4 implements build_user_prompt")


def build_retry_prompt(previous_text: str, actual_len: int, new_budget: int) -> str:  # noqa: ARG001
    raise NotImplementedError("Plan 06-01 Task 4 implements build_retry_prompt")


def format_final_post(body: str, url: str, hashtags: list[str]) -> str:  # noqa: ARG001
    raise NotImplementedError("Plan 06-01 Task 4 implements format_final_post")


__all__ = [
    "build_retry_prompt",
    "build_system_prompt",
    "build_user_prompt",
    "format_final_post",
]
