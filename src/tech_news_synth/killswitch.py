"""Kill-switch (INFRA-09, D-08).

Single source of truth: cycle is paused if ``PAUSED`` env is truthy OR the
marker file at ``settings.paused_marker_path`` exists. The scheduler (Plan 02)
calls ``is_paused`` and trusts its result — never re-implements the OR logic
(threat T-01-09).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tech_news_synth.config import Settings


def is_paused(settings: Settings) -> tuple[bool, str | None]:
    """Return ``(paused, reason)``.

    Reasons: ``"env"``, ``"marker"``, ``"both"``, or ``None`` when not paused.
    """
    env_paused = bool(settings.paused)
    marker_exists = Path(settings.paused_marker_path).exists()

    if env_paused and marker_exists:
        return (True, "both")
    if env_paused:
        return (True, "env")
    if marker_exists:
        return (True, "marker")
    return (False, None)
