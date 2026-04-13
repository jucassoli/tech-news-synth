"""STORE-05 — run_log repository.

One row per scheduler cycle: ``start_cycle`` at entry, ``finish_cycle`` in the
``finally`` block. Caller owns the transaction.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from tech_news_synth.db.models import RunLog


def start_cycle(session: Session, cycle_id: str) -> RunLog:
    """Insert a ``status='running'`` row with ``started_at = server now()``."""
    row = RunLog(cycle_id=cycle_id, status="running", counts={})
    session.add(row)
    session.flush()
    return row


def finish_cycle(
    session: Session,
    cycle_id: str,
    status: str,
    counts: dict[str, Any] | None = None,
    notes: str | None = None,
) -> RunLog:
    """Update the row for ``cycle_id`` with ``finished_at`` + final status.

    Raises ``sqlalchemy.exc.NoResultFound`` if the cycle was never started.
    """
    row = session.execute(select(RunLog).where(RunLog.cycle_id == cycle_id)).scalar_one()
    row.finished_at = datetime.now(UTC)
    row.status = status
    if counts is not None:
        row.counts = counts
    if notes is not None:
        row.notes = notes
    session.flush()
    return row


__all__ = ["finish_cycle", "start_cycle"]
