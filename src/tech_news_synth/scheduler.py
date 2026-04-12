"""APScheduler wiring for tech-news-synth (INFRA-05 / INFRA-08 / D-07 / D-08).

Pattern:
- ``BlockingScheduler`` runs as PID 1 (exec-form CMD in Dockerfile propagates SIGTERM).
- ``CronTrigger(hour="*/{INTERVAL_HOURS}", timezone=timezone.utc)`` for cadence.
- ``next_run_time=datetime.now(timezone.utc)`` on job registration for first-tick-on-boot (D-07).
- SIGTERM/SIGINT handlers call ``scheduler.shutdown(wait=True)`` (PITFALLS #1/#2).
- ``run_cycle`` honors kill-switch first, binds ``cycle_id`` + ``dry_run`` to
  structlog contextvars (INFRA-07 / INFRA-10), never propagates exceptions
  (INFRA-08), and clears contextvars on exit (T-02-03).
"""

from __future__ import annotations

import signal
import sys
from datetime import UTC, datetime
from types import FrameType
from typing import TYPE_CHECKING

from apscheduler.events import EVENT_JOB_ERROR, JobExecutionEvent
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from structlog.contextvars import bind_contextvars, clear_contextvars

from tech_news_synth.ids import new_cycle_id
from tech_news_synth.killswitch import is_paused
from tech_news_synth.logging import configure_logging, get_logger

if TYPE_CHECKING:
    from tech_news_synth.config import Settings

log = get_logger(__name__)


def _run_cycle_body(settings: Settings) -> None:
    """Phase 1 no-op body. Later phases replace with fetch→cluster→synth→publish.

    Extracted as a module-level function so tests can monkeypatch it to inject
    failures (INFRA-08 isolation tests).
    """
    return None


def run_cycle(settings: Settings) -> None:
    """One scheduler tick. Never raises (INFRA-08).

    Invariants:
      - Kill-switch checked first; when paused emits exactly one ``cycle_skipped``
        log line and performs zero other I/O (INFRA-09 / D-08).
      - Binds ``cycle_id`` (ULID) + ``dry_run`` to structlog contextvars before
        any downstream log line (INFRA-07 / INFRA-10 / D-09 / D-10).
      - Clears contextvars in ``finally`` so shutdown / next-cycle lines don't
        carry stale values (T-02-03).
    """
    cycle_id = new_cycle_id()
    bind_contextvars(cycle_id=cycle_id, dry_run=bool(settings.dry_run))
    try:
        paused, reason = is_paused(settings)
        if paused:
            log.info("cycle_skipped", status="paused", paused_by=reason)
            return

        log.info("cycle_start", interval_hours=settings.interval_hours)
        try:
            _run_cycle_body(settings)
        except Exception:
            # INFRA-08: never propagate; log full stacktrace.
            log.exception("cycle_error")
            return
        log.info("cycle_end", status="ok")
    finally:
        clear_contextvars()


def _job_error_listener(event: JobExecutionEvent) -> None:
    """Safety net (PITFALLS #7): run_cycle's try/except should catch everything,
    but if anything slips past APScheduler's EVENT_JOB_ERROR fires here."""
    log.error(
        "scheduler_job_error",
        exception=str(event.exception),
        traceback=event.traceback,
        job_id=event.job_id,
    )


def build_scheduler(settings: Settings) -> BlockingScheduler:
    """Return a configured BlockingScheduler with one job (``run_cycle``).

    D-07: ``next_run_time=datetime.now(timezone.utc)`` makes the first tick
    fire immediately on process start; subsequent ticks follow the cron.
    """
    scheduler = BlockingScheduler(
        timezone=UTC,
        job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 30},
    )
    scheduler.add_listener(_job_error_listener, EVENT_JOB_ERROR)
    scheduler.add_job(
        run_cycle,
        CronTrigger(hour=f"*/{settings.interval_hours}", timezone=UTC),
        kwargs={"settings": settings},
        id="run_cycle",
        replace_existing=True,
        next_run_time=datetime.now(UTC),  # D-07 first-tick-on-boot
    )
    return scheduler


def _install_signal_handlers(scheduler: BlockingScheduler) -> None:
    """Install SIGTERM/SIGINT handlers that call ``shutdown(wait=True)``.

    Without this, Python ignores SIGTERM and ``docker stop`` waits
    ``stop_grace_period`` then SIGKILLs mid-cycle (PITFALLS #1)."""

    def _shutdown(signum: int, _frame: FrameType | None) -> None:
        log.info("shutdown_signal_received", signal=signal.Signals(signum).name)
        scheduler.shutdown(wait=True)
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)


def run(settings: Settings) -> None:
    """Entrypoint invoked by ``__main__.py`` when no subcommand is given."""
    configure_logging(settings)
    scheduler = build_scheduler(settings)
    _install_signal_handlers(scheduler)
    log.info(
        "scheduler_starting",
        interval_hours=settings.interval_hours,
        dry_run=bool(settings.dry_run),
        paused_env=bool(settings.paused),
    )
    scheduler.start()  # blocks until shutdown
