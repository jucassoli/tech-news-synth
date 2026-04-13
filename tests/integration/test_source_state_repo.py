"""Integration tests for tech_news_synth.db.source_state (D-04).

Exercises the 6 repo helpers + 1 autogenerate-roundtrip assertion against
the live test DB. Uses the Phase 2 ``db_session`` fixture (nested SAVEPOINT
rollback pattern).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from tech_news_synth.db.models import SourceState
from tech_news_synth.db.source_state import (
    get_state,
    mark_304,
    mark_disabled,
    mark_error,
    mark_ok,
    upsert_source,
)

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Test 1 — upsert_source: idempotent insert
# ---------------------------------------------------------------------------
def test_upsert_source_inserts_row_with_defaults(db_session):
    upsert_source(db_session, "techcrunch")
    row = get_state(db_session, "techcrunch")
    assert row is not None
    assert row.name == "techcrunch"
    assert row.consecutive_failures == 0
    assert row.etag is None
    assert row.last_modified is None
    assert row.disabled_at is None
    assert row.last_fetched_at is None
    assert row.last_status is None


def test_upsert_source_is_idempotent(db_session):
    upsert_source(db_session, "verge")
    upsert_source(db_session, "verge")
    rows = db_session.query(SourceState).filter(SourceState.name == "verge").all()
    assert len(rows) == 1


# ---------------------------------------------------------------------------
# Test 2 — get_state
# ---------------------------------------------------------------------------
def test_get_state_returns_none_for_missing(db_session):
    assert get_state(db_session, "no_such_source") is None


# ---------------------------------------------------------------------------
# Test 3 — mark_ok: resets counter, sets timestamps, updates CG headers
# ---------------------------------------------------------------------------
def test_mark_ok_resets_counter_and_sets_metadata(db_session):
    upsert_source(db_session, "ars_technica")
    # Seed a failure
    mark_error(db_session, "ars_technica", "transport")
    assert get_state(db_session, "ars_technica").consecutive_failures == 1

    before = datetime.now(UTC)
    mark_ok(db_session, "ars_technica", etag='W/"abc"', last_modified="Mon, 13 Apr 2026 10:00:00 GMT")
    after = datetime.now(UTC)

    row = get_state(db_session, "ars_technica")
    assert row.consecutive_failures == 0
    assert row.last_status == "ok"
    assert row.etag == 'W/"abc"'
    assert row.last_modified == "Mon, 13 Apr 2026 10:00:00 GMT"
    assert before <= row.last_fetched_at <= after


def test_mark_ok_without_headers_preserves_existing(db_session):
    upsert_source(db_session, "hn1")
    mark_ok(db_session, "hn1", etag='"v1"', last_modified="Mon, 13 Apr 2026 09:00:00 GMT")
    # Second call without headers should not wipe them
    mark_ok(db_session, "hn1")
    row = get_state(db_session, "hn1")
    assert row.etag == '"v1"'
    assert row.last_modified == "Mon, 13 Apr 2026 09:00:00 GMT"


# ---------------------------------------------------------------------------
# Test 4 — mark_304: sets skipped_304, does not touch failure counter
# ---------------------------------------------------------------------------
def test_mark_304_preserves_failure_counter(db_session):
    upsert_source(db_session, "rss304")
    mark_error(db_session, "rss304", "transport")
    before_count = get_state(db_session, "rss304").consecutive_failures
    mark_304(db_session, "rss304")
    row = get_state(db_session, "rss304")
    assert row.last_status == "skipped_304"
    assert row.consecutive_failures == before_count  # unchanged
    assert row.last_fetched_at is not None


# ---------------------------------------------------------------------------
# Test 5 — mark_error: increments counter, records kind
# ---------------------------------------------------------------------------
def test_mark_error_increments_counter(db_session):
    upsert_source(db_session, "err_src")
    mark_error(db_session, "err_src", "transport")
    mark_error(db_session, "err_src", "http_500")
    row = get_state(db_session, "err_src")
    assert row.consecutive_failures == 2
    assert row.last_status == "error:http_500"
    assert row.last_fetched_at is not None


# ---------------------------------------------------------------------------
# Test 6 — mark_disabled: sets disabled_at, idempotent
# ---------------------------------------------------------------------------
def test_mark_disabled_sets_timestamp_idempotently(db_session):
    upsert_source(db_session, "dead_src")
    before = datetime.now(UTC)
    mark_disabled(db_session, "dead_src")
    first_ts = get_state(db_session, "dead_src").disabled_at
    assert first_ts is not None
    assert before - timedelta(seconds=5) <= first_ts <= datetime.now(UTC)

    # Second call must not overwrite the original timestamp
    mark_disabled(db_session, "dead_src")
    second_ts = get_state(db_session, "dead_src").disabled_at
    assert second_ts == first_ts


# ---------------------------------------------------------------------------
# Test 7 — autogenerate roundtrip: no schema drift
# ---------------------------------------------------------------------------
def test_migration_autogenerate_clean(engine):
    """alembic.autogenerate.compare_metadata against live DB after upgrade
    head must produce an empty diff (Phase 2 pattern)."""
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    from tech_news_synth.db.base import Base
    import tech_news_synth.db.models  # noqa: F401 — register models

    with engine.connect() as conn:
        mc = MigrationContext.configure(conn)
        diff = compare_metadata(mc, Base.metadata)
    # Ignore any trivial ordering; the expected state is an EMPTY diff.
    assert diff == [], f"schema drift detected: {diff}"
