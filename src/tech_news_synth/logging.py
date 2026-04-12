"""Structured logging pipeline (INFRA-06 / INFRA-07 / INFRA-10).

Pipeline:
    structlog wrapper -> stdlib logging -> {stdout handler, file handler}

Both sinks emit single-line JSON via ``structlog.processors.JSONRenderer``
with ``orjson`` as the serializer. Callers bind ``cycle_id`` / ``dry_run`` /
arbitrary context via ``structlog.contextvars.bind_contextvars`` so the fields
appear on every subsequent log line until cleared.

Security (T-01-03 / T-01-08):
- No module-level ``get_logger()`` at import time — callers must first run
  ``configure_logging(settings)`` (PITFALLS #5).
- ``Settings`` is never auto-bound into context. Only explicit named fields
  land on log lines, which prevents ``SecretStr`` fields from leaking.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import orjson
import structlog

if TYPE_CHECKING:
    from tech_news_synth.config import Settings

_CONFIGURED = False


def _orjson_dumps(obj: Any, default: Any = None) -> str:
    """orjson-backed JSON serializer returning ``str`` (structlog contract)."""
    return orjson.dumps(obj, default=default).decode("utf-8")


def configure_logging(settings: Settings) -> None:
    """Install dual-sink JSON logging pipeline. Safe to call more than once."""
    global _CONFIGURED

    log_dir = Path(settings.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)  # PITFALLS #8 / T-01-10
    log_file = log_dir / "app.jsonl"

    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),  # INFRA-06
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processor=structlog.processors.JSONRenderer(serializer=_orjson_dumps),
    )

    root = logging.getLogger()
    # Idempotent: remove any handlers from a previous call so we don't duplicate.
    for h in list(root.handlers):
        root.removeHandler(h)

    stdout_h = logging.StreamHandler(sys.stdout)
    stdout_h.setFormatter(formatter)
    root.addHandler(stdout_h)

    file_h = logging.FileHandler(log_file, encoding="utf-8")
    file_h.setFormatter(formatter)
    root.addHandler(file_h)

    root.setLevel(logging.INFO)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)

    _CONFIGURED = True


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Return a structlog-bound logger. Call ``configure_logging`` first."""
    return structlog.get_logger(name)
