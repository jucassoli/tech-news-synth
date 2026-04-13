"""STORE-05 — run_log start_cycle / finish_cycle lifecycle."""

from __future__ import annotations

import pytest
from sqlalchemy.exc import NoResultFound

from tech_news_synth.db.models import RunLog
from tech_news_synth.db.run_log import finish_cycle, start_cycle


def test_start_cycle_inserts_running_row(db_session) -> None:
    cid = "01TESTSTART000000000000001"
    row = start_cycle(db_session, cid)
    assert row.cycle_id == cid
    assert row.status == "running"
    assert row.counts == {}
    assert row.started_at is not None
    assert row.finished_at is None


def test_finish_cycle_updates_status_counts_finished_at(db_session) -> None:
    cid = "01TESTFINISH00000000000001"
    start_cycle(db_session, cid)

    counts = {"sources_ok": 5, "articles": 42, "clusters": 3}
    finish_cycle(db_session, cid, status="ok", counts=counts, notes="all green")

    row = db_session.get(RunLog, cid)
    assert row is not None
    assert row.status == "ok"
    assert row.counts == counts
    assert row.notes == "all green"
    assert row.finished_at is not None
    assert row.finished_at >= row.started_at


def test_finish_cycle_on_unknown_cycle_raises(db_session) -> None:
    with pytest.raises(NoResultFound):
        finish_cycle(db_session, "01NEVERSTARTED00000000001", status="ok")


def test_finish_cycle_preserves_counts_when_omitted(db_session) -> None:
    cid = "01TESTKEEPCOUNTS0000000001"
    row = start_cycle(db_session, cid)
    row.counts = {"prior": 1}
    db_session.flush()
    finish_cycle(db_session, cid, status="error")
    refreshed = db_session.get(RunLog, cid)
    assert refreshed is not None
    assert refreshed.counts == {"prior": 1}
    assert refreshed.status == "error"
