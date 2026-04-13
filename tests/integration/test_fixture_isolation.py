"""Meta-test: prove the ``db_session`` fixture isolates SUT commits.

Step 1 writes a RunLog row and calls ``session.commit()`` (SUT-level). Step 2
must see the row gone — confirming the nested-SAVEPOINT pattern rolled back
the SUT commit via the outer connection's rollback.
"""

from __future__ import annotations

from tech_news_synth.db.models import RunLog

_CYCLE_ID = "01ISOLATIONTEST0000000001"


def test_commit_in_sut_is_rolled_back_step1(db_session) -> None:
    db_session.add(RunLog(cycle_id=_CYCLE_ID, status="running"))
    db_session.commit()  # SUT-level commit — would normally persist.
    assert db_session.query(RunLog).filter_by(cycle_id=_CYCLE_ID).count() == 1, (
        "row must be visible within its own test"
    )


def test_commit_in_sut_is_rolled_back_step2(db_session) -> None:
    # If isolation works, the row from step1 is gone.
    assert db_session.query(RunLog).filter_by(cycle_id=_CYCLE_ID).count() == 0, (
        "row from previous test leaked — SAVEPOINT isolation broken"
    )
