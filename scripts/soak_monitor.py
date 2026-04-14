#!/usr/bin/env python3
"""48h DRY_RUN soak monitor (Phase 8 D-07 / OPS-06 automation).

Polls ``run_log`` + ``posts`` every ``--poll-minutes`` for ``--hours`` and
appends a JSON line per check to stdout AND ``--intel-path``
(default ``.planning/intel/soak-log.md``).

Red-flag policy:
  * **Soft** (stderr warn, continue): last cycle >2.5h ago.
  * **Hard** (stderr error, exit 1): >2 ``status='failed'`` cycles in 48h.

D-08 pass criteria (printed as final summary on clean exit):
  * ``cycles_last_48h`` ≥ 24
  * ``failed_last_48h`` ≤ 2

Usage
-----
    uv run python scripts/soak_monitor.py --hours 48 --poll-minutes 30

Run from operator's host via::

    docker compose run --rm app uv run python scripts/soak_monitor.py

or detached::

    nohup docker compose run --rm app \\
        uv run python scripts/soak_monitor.py --hours 48 > soak.out 2>&1 &

Zero new Python dependencies; uses stdlib + existing project imports.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tech_news_synth.config import load_settings
from tech_news_synth.db.models import Post, RunLog
from tech_news_synth.db.session import SessionLocal, init_engine

DEFAULT_INTEL_PATH = ".planning/intel/soak-log.md"
STALE_CYCLE_MINUTES = 150  # 2.5h soft red-flag threshold
MAX_ALLOWED_FAILURES_48H = 2  # D-08 / hard red-flag threshold
MIN_CYCLES_48H = 24  # D-08 pass criterion


# ---------------------------------------------------------------------------
# Pure-ish helpers (take a Session; no global state; unit-testable)
# ---------------------------------------------------------------------------
def check_invariants(session: Session) -> dict[str, Any]:
    """Return the 5 invariant counters used by the soak monitor.

    All timestamps are UTC. Integer casts avoid Numeric → Decimal surprises in
    JSON output.
    """
    now = datetime.now(UTC)
    last_cycle = session.execute(
        select(RunLog).order_by(RunLog.started_at.desc()).limit(1)
    ).scalar_one_or_none()
    last_age_min: float | None
    if last_cycle is None:
        last_age_min = None
    else:
        last_age_min = (now - last_cycle.started_at).total_seconds() / 60.0

    cycles_24h = int(
        session.execute(
            select(func.count(RunLog.cycle_id)).where(
                RunLog.started_at > now - timedelta(hours=24)
            )
        ).scalar_one()
    )
    cycles_48h = int(
        session.execute(
            select(func.count(RunLog.cycle_id)).where(
                RunLog.started_at > now - timedelta(hours=48)
            )
        ).scalar_one()
    )
    failed_48h = int(
        session.execute(
            select(func.count(RunLog.cycle_id)).where(
                RunLog.status.in_(("error", "failed")),
                RunLog.started_at > now - timedelta(hours=48),
            )
        ).scalar_one()
    )
    dry_run_posts_24h = int(
        session.execute(
            select(func.count(Post.id)).where(
                Post.status == "dry_run",
                Post.created_at > now - timedelta(hours=24),
            )
        ).scalar_one()
    )

    return {
        "ts": now.isoformat(),
        "last_cycle_age_min": last_age_min,
        "cycles_last_24h": cycles_24h,
        "cycles_last_48h": cycles_48h,
        "failed_last_48h": failed_48h,
        "dry_run_posts_last_24h": dry_run_posts_24h,
    }


def classify_red_flags(status: dict[str, Any]) -> dict[str, Any]:
    """Return {'soft': bool, 'hard': bool, 'messages': [...]} for a check."""
    messages: list[str] = []
    soft = False
    hard = False
    age = status.get("last_cycle_age_min")
    if age is not None and age > STALE_CYCLE_MINUTES:
        soft = True
        messages.append(f"RED FLAG (soft): no cycle in >2.5h (age={age:.1f}min)")
    failed = status.get("failed_last_48h", 0)
    if failed is not None and failed > MAX_ALLOWED_FAILURES_48H:
        hard = True
        messages.append(
            f"RED FLAG (hard): {failed} failed cycles in 48h "
            f"(threshold {MAX_ALLOWED_FAILURES_48H})"
        )
    return {"soft": soft, "hard": hard, "messages": messages}


def compute_d08_pass(summary: dict[str, Any]) -> bool:
    """D-08 soak pass criteria: ≥24 cycles in 48h AND ≤2 failed cycles."""
    return (
        summary.get("cycles_last_48h", 0) >= MIN_CYCLES_48H
        and summary.get("failed_last_48h", 0) <= MAX_ALLOWED_FAILURES_48H
    )


# ---------------------------------------------------------------------------
# File-IO helpers
# ---------------------------------------------------------------------------
def _append_intel_line(path: Path, line: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(line)
        if not line.endswith("\n"):
            f.write("\n")


def _write_header(path: Path, started_at: datetime) -> None:
    _append_intel_line(path, f"\n## Soak run started {started_at.isoformat()}\n")


def _write_final_block(path: Path, summary: dict[str, Any], pass_d08: bool, reason: str) -> None:
    ended_at = datetime.now(UTC).isoformat()
    lines = [
        "",
        f"### Soak run ended {ended_at}  (reason: {reason})",
        f"- cycles_48h: {summary.get('cycles_last_48h')}",
        f"- failed_48h: {summary.get('failed_last_48h')}",
        f"- dry_run_posts_24h: {summary.get('dry_run_posts_last_24h')}",
        f"- last_cycle_age_min: {summary.get('last_cycle_age_min')}",
        f"- D-08 PASS: {pass_d08}",
        "",
    ]
    _append_intel_line(path, "\n".join(lines))


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------
def _poll_once(intel_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """Perform one invariant check + append the JSON line to intel + stdout.

    Returns (status, flags) so the caller (main loop) can decide to exit.
    """
    with SessionLocal() as s:
        status = check_invariants(s)
    line = json.dumps(status)
    print(line, flush=True)
    _append_intel_line(intel_path, line)
    flags = classify_red_flags(status)
    for msg in flags["messages"]:
        print(msg, file=sys.stderr, flush=True)
    return status, flags


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="soak_monitor",
        description="Poll run_log + posts for a soak window and flag D-08 violations.",
    )
    parser.add_argument(
        "--hours", type=float, default=48.0, help="Total soak duration in hours (default: 48)."
    )
    parser.add_argument(
        "--poll-minutes",
        type=float,
        default=30.0,
        help="Poll cadence in minutes (default: 30).",
    )
    parser.add_argument(
        "--intel-path",
        default=DEFAULT_INTEL_PATH,
        help=f"Append-only log file (default: {DEFAULT_INTEL_PATH}).",
    )
    args = parser.parse_args(argv)

    settings = load_settings()
    init_engine(settings)

    intel_path = Path(args.intel_path)
    start_ts = datetime.now(UTC)
    end_ts = start_ts + timedelta(hours=args.hours)
    _write_header(intel_path, start_ts)

    poll_interval_sec = max(args.poll_minutes * 60.0, 0.001)
    reason = "completed"
    last_status: dict[str, Any] = {}
    try:
        while datetime.now(UTC) < end_ts:
            last_status, flags = _poll_once(intel_path)
            if flags["hard"]:
                reason = "hard_red_flag"
                summary = last_status
                pass_d08 = compute_d08_pass(summary)
                print(
                    json.dumps({"event": "soak_final", "exit_reason": reason, **summary}),
                    flush=True,
                )
                _write_final_block(intel_path, summary, pass_d08, reason)
                return 1
            # Sleep until next poll OR end_ts, whichever is sooner.
            remaining = (end_ts - datetime.now(UTC)).total_seconds()
            if remaining <= 0:
                break
            time.sleep(min(poll_interval_sec, remaining))
    except KeyboardInterrupt:
        reason = "interrupted"
        print("soak monitor interrupted — writing final summary", file=sys.stderr)

    # Final summary on normal completion or Ctrl+C.
    with SessionLocal() as s:
        summary = check_invariants(s)
    pass_d08 = compute_d08_pass(summary)
    print(
        json.dumps({"event": "soak_final", "exit_reason": reason, "pass_d08": pass_d08, **summary}),
        flush=True,
    )
    _write_final_block(intel_path, summary, pass_d08, reason)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
