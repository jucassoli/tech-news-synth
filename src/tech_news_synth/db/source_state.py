"""source_state repository helpers (D-04).

Module-level functions following the Phase 2 repo style — caller owns the
transaction. All state transitions write ``last_fetched_at`` +
``last_status`` for the audit trail (T-04-06).
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from tech_news_synth.db.models import SourceState


def upsert_source(session: Session, name: str) -> None:
    """Insert a source_state row if absent; no-op on conflict (idempotent)."""
    stmt = pg_insert(SourceState).values(name=name).on_conflict_do_nothing(index_elements=["name"])
    session.execute(stmt)
    session.flush()


def get_state(session: Session, name: str) -> SourceState | None:
    """Return the SourceState row for ``name`` or None."""
    return session.execute(select(SourceState).where(SourceState.name == name)).scalar_one_or_none()


def mark_ok(
    session: Session,
    name: str,
    *,
    etag: str | None = None,
    last_modified: str | None = None,
) -> None:
    """Reset failure counter; record successful fetch + optional CG headers."""
    row = get_state(session, name)
    assert row is not None, f"source_state row missing for {name!r}"
    row.consecutive_failures = 0
    row.last_status = "ok"
    row.last_fetched_at = datetime.now(UTC)
    if etag is not None:
        row.etag = etag
    if last_modified is not None:
        row.last_modified = last_modified
    session.flush()


def mark_304(session: Session, name: str) -> None:
    """Record a conditional-GET 304 (not-modified). Does not touch failure
    counter (D-14)."""
    row = get_state(session, name)
    assert row is not None, f"source_state row missing for {name!r}"
    row.last_status = "skipped_304"
    row.last_fetched_at = datetime.now(UTC)
    session.flush()


def mark_error(session: Session, name: str, error_kind: str) -> None:
    """Increment consecutive_failures; record error kind (D-11)."""
    row = get_state(session, name)
    assert row is not None, f"source_state row missing for {name!r}"
    row.consecutive_failures += 1
    row.last_status = f"error:{error_kind}"
    row.last_fetched_at = datetime.now(UTC)
    session.flush()


def mark_disabled(session: Session, name: str) -> None:
    """Set disabled_at if currently null (idempotent; does not overwrite)."""
    row = get_state(session, name)
    assert row is not None, f"source_state row missing for {name!r}"
    if row.disabled_at is None:
        row.disabled_at = datetime.now(UTC)
    session.flush()


def get_all_source_states(session: Session) -> list[SourceState]:
    """Return all source_state rows ordered by name (Phase 8 OPS-04).

    Pure read — caller owns session lifecycle. Used by ``cli.source_health``
    status and ``--json`` modes.
    """
    return list(
        session.execute(select(SourceState).order_by(SourceState.name)).scalars()
    )


def enable_source(session: Session, name: str) -> bool:
    """Clear ``disabled_at`` and reset ``consecutive_failures`` (Phase 8 OPS-04).

    Returns ``True`` on successful update, ``False`` when ``name`` is not in
    ``source_state`` (completes the Phase 4 D-13 re-enable contract). Caller
    owns the commit.
    """
    row = get_state(session, name)
    if row is None:
        return False
    row.disabled_at = None
    row.consecutive_failures = 0
    session.flush()
    return True


def disable_source(session: Session, name: str) -> bool:
    """Set ``disabled_at`` to now if currently null (Phase 8 OPS-04).

    Returns ``True`` on successful update (idempotent — re-disabling a
    disabled source is a no-op but still returns True), ``False`` when
    ``name`` is not in ``source_state``. Caller owns the commit.
    """
    row = get_state(session, name)
    if row is None:
        return False
    if row.disabled_at is None:
        row.disabled_at = datetime.now(UTC)
        session.flush()
    return True


__all__ = [
    "disable_source",
    "enable_source",
    "get_all_source_states",
    "get_state",
    "mark_304",
    "mark_disabled",
    "mark_error",
    "mark_ok",
    "upsert_source",
]
