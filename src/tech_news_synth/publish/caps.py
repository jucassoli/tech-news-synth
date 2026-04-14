"""D-04/D-05/D-06 cap checks.

Two cheap queries (~5ms total) returning a structured verdict. Pure:
no side effects. Caller in scheduler decides whether to skip synthesis.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from tech_news_synth.db.posts import count_posted_today, sum_monthly_cost_usd
from tech_news_synth.publish.models import CapCheckResult

if TYPE_CHECKING:
    from tech_news_synth.config import Settings


def check_caps(session: Session, settings: "Settings") -> CapCheckResult:
    """Compute daily + monthly caps; return a frozen verdict.

    D-04: called BETWEEN ``run_clustering`` and ``run_synthesis``. If
    ``skip_synthesis=True`` the scheduler skips both synth and publish.
    """
    daily_count = count_posted_today(session)
    monthly_cost = sum_monthly_cost_usd(session)

    daily_reached = daily_count >= settings.max_posts_per_day
    monthly_cost_reached = monthly_cost >= settings.max_monthly_cost_usd

    return CapCheckResult(
        daily_count=daily_count,
        daily_reached=daily_reached,
        monthly_cost_usd=monthly_cost,
        monthly_cost_reached=monthly_cost_reached,
        skip_synthesis=daily_reached or monthly_cost_reached,
    )


__all__ = ["check_caps"]
