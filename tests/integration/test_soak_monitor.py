"""Integration tests for scripts/soak_monitor.py — D-07/D-08 invariant checks.

Seeds synthetic run_log + posts rows into the test DB and calls the
``check_invariants`` + ``classify_red_flags`` + ``compute_d08_pass`` helpers.
Does NOT exercise the polling loop (that's covered by a direct import-and-call
with a single iteration).
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from tech_news_synth.db.models import Post, RunLog

# Import the script module dynamically (it lives in scripts/, not in the package).
_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "soak_monitor.py"
_spec = importlib.util.spec_from_file_location("soak_monitor", _SCRIPT_PATH)
assert _spec is not None and _spec.loader is not None
soak_monitor = importlib.util.module_from_spec(_spec)
sys.modules["soak_monitor"] = soak_monitor
_spec.loader.exec_module(soak_monitor)


def _seed_run_log(session, cycle_id: str, started_at: datetime, status: str = "ok") -> None:
    session.add(
        RunLog(
            cycle_id=cycle_id,
            started_at=started_at,
            finished_at=started_at + timedelta(seconds=10),
            status=status,
            counts={},
        )
    )
    session.flush()


def _seed_post(session, cycle_id: str, created_at: datetime, status: str = "dry_run") -> None:
    # The SQLAlchemy default for created_at is server_default=NOW(); to override
    # we must set it explicitly AFTER flush, since server_default wins on insert.
    # So use a raw INSERT via the session connection.
    session.add(Post(cycle_id=cycle_id, status=status))
    session.flush()
    # Overwrite created_at with the value we want (server_default already fired).
    from sqlalchemy import update

    session.execute(
        update(Post)
        .where(Post.cycle_id == cycle_id, Post.status == status)
        .values(created_at=created_at)
    )
    session.flush()


def test_check_invariants_seeded_rows(db_session) -> None:
    now = datetime.now(UTC)
    # Seed 24 cycles over the last 48h, status='ok'.
    for i in range(24):
        _seed_run_log(
            db_session,
            cycle_id=f"01SOAKOK{i:018d}",
            started_at=now - timedelta(hours=48) + timedelta(hours=2 * i),
            status="ok",
        )
    # Most recent cycle 10 minutes ago.
    _seed_run_log(
        db_session,
        cycle_id="01SOAKOKRECENT00000000001",
        started_at=now - timedelta(minutes=10),
        status="ok",
    )
    # One dry_run post in the last 24h.
    _seed_post(db_session, "01SOAKOKRECENT00000000001", now - timedelta(minutes=9), "dry_run")
    db_session.commit()

    status: dict[str, Any] = soak_monitor.check_invariants(db_session)
    assert status["cycles_last_48h"] >= 24
    assert status["failed_last_48h"] == 0
    # last cycle was 10 min ago → age should be ~10.
    assert status["last_cycle_age_min"] is not None
    assert status["last_cycle_age_min"] < 15.0
    assert status["dry_run_posts_last_24h"] >= 1


def test_red_flag_failed_cycles_triggers_hard(db_session) -> None:
    now = datetime.now(UTC)
    for i in range(3):
        _seed_run_log(
            db_session,
            cycle_id=f"01SOAKFAIL{i:018d}",
            started_at=now - timedelta(hours=1 + i),
            status="failed",
        )
    db_session.commit()

    status = soak_monitor.check_invariants(db_session)
    assert status["failed_last_48h"] == 3
    flags = soak_monitor.classify_red_flags(status)
    assert flags["hard"] is True
    assert any("failed" in m.lower() for m in flags["messages"])


def test_red_flag_stale_cycle_triggers_soft(db_session) -> None:
    now = datetime.now(UTC)
    _seed_run_log(
        db_session,
        cycle_id="01SOAKSTALE0000000000000001",
        started_at=now - timedelta(hours=3),
        status="ok",
    )
    db_session.commit()

    status = soak_monitor.check_invariants(db_session)
    flags = soak_monitor.classify_red_flags(status)
    assert flags["hard"] is False
    assert flags["soft"] is True
    assert any("cycle" in m.lower() and "2.5h" in m for m in flags["messages"])


def test_compute_d08_pass_happy_path() -> None:
    summary = {
        "cycles_last_48h": 24,
        "failed_last_48h": 0,
        "dry_run_posts_last_24h": 12,
        "last_cycle_age_min": 5.0,
    }
    assert soak_monitor.compute_d08_pass(summary) is True


def test_compute_d08_pass_fails_low_cycle_count() -> None:
    summary = {
        "cycles_last_48h": 20,
        "failed_last_48h": 0,
        "dry_run_posts_last_24h": 12,
        "last_cycle_age_min": 5.0,
    }
    assert soak_monitor.compute_d08_pass(summary) is False


def test_compute_d08_pass_fails_too_many_failures() -> None:
    summary = {
        "cycles_last_48h": 24,
        "failed_last_48h": 3,
        "dry_run_posts_last_24h": 12,
        "last_cycle_age_min": 5.0,
    }
    assert soak_monitor.compute_d08_pass(summary) is False
