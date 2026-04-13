"""Programmatic `alembic upgrade head` — run at container boot (D-01).

`__main__._dispatch_scheduler` calls :func:`run_migrations` after
`configure_logging` + `init_engine` and before `scheduler.run()`. On
alembic failure we re-raise so the container exits non-zero (D-03 —
compose `depends_on: service_healthy` is the only DB-readiness gate, no
retry loop here).
"""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config

from tech_news_synth.logging import get_logger

log = get_logger(__name__)

# In the runtime container the repo root is /app; locally it's the project
# root. Path(__file__) = .../src/tech_news_synth/db/migrations.py →
# parents[3] = repo root (src, tech_news_synth, db are three parents up).
_ALEMBIC_INI = Path(__file__).resolve().parents[3] / "alembic.ini"


def run_migrations() -> None:
    """Run ``alembic upgrade head`` programmatically.

    Raises on failure (D-01 fail-fast, D-03 no retry). The DSN is NEVER
    logged — env.py materializes it from Settings and alembic loggers are
    pinned to WARN in alembic.ini (T-02-02).
    """
    cfg = Config(str(_ALEMBIC_INI))
    log.info("alembic_upgrade_start", target="head")
    command.upgrade(cfg, "head")
    log.info("alembic_upgrade_done")
