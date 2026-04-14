"""``post-now`` CLI (Phase 8 OPS-03 / D-02).

    python -m tech_news_synth post-now

Inline-invokes ``scheduler.run_cycle`` exactly once, honoring ALL Phase 7
guardrails: kill-switch, DRY_RUN, daily/monthly caps, anti-repeat,
stale-pending cleanup, idempotency. Does NOT register with APScheduler —
this is a one-shot operator action. Safe to run alongside the scheduler
(Phase 7 stale-pending guard + posts.cycle_id uniqueness prevent
double-posting).

Exit codes:
  0 — cycle completed with run_log.status='ok' (or paused: no row written,
      because the killswitch is documented behavior, not error)
  1 — cycle completed with a failure status

The cycle_summary log line from scheduler.run_cycle (Task 2) is the
operator's primary feedback channel.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import desc, select

from tech_news_synth.config import load_settings
from tech_news_synth.db.models import RunLog
from tech_news_synth.db.session import SessionLocal, init_engine
from tech_news_synth.ingest.sources_config import load_sources_config
from tech_news_synth.logging import configure_logging, get_logger
from tech_news_synth.scheduler import run_cycle
from tech_news_synth.synth.hashtags import load_hashtag_allowlist

log = get_logger(__name__)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="post-now")
    parser.parse_args(argv)  # no args in v1 (D-02)

    settings = load_settings()
    configure_logging(settings)
    init_engine(settings)
    sources_config = load_sources_config(Path(settings.sources_config_path))
    hashtag_allowlist = load_hashtag_allowlist(Path(settings.hashtags_config_path))

    # Capture invoked_at with a small back-buffer to survive clock-skew /
    # timestamp-precision edge cases where RunLog.started_at (server NOW())
    # resolves slightly before our Python clock on a fast machine.
    invoked_at = datetime.now(UTC).replace(microsecond=0)
    log.info("post_now_start", dry_run=bool(settings.dry_run))

    run_cycle(
        settings,
        sources_config=sources_config,
        hashtag_allowlist=hashtag_allowlist,
    )

    # Find the run_log row created by this invocation (most recent since
    # invoked_at). Paused cycles never write a row — treat as exit 0.
    with SessionLocal() as s:
        latest = s.execute(
            select(RunLog)
            .where(RunLog.started_at >= invoked_at)
            .order_by(desc(RunLog.started_at))
            .limit(1)
        ).scalar_one_or_none()

    if latest is None:
        print(
            "cycle skipped (paused or killswitch active)",
            file=sys.stderr,
        )
        return 0
    # Graceful outcomes (ok, capped→ok) exit 0; only run_log.status='error' is 1.
    return 0 if latest.status == "ok" else 1
