"""INFRA-10 — DRY_RUN bound via contextvars appears on every log line."""

from __future__ import annotations

import json
import logging
from pathlib import Path


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def test_dry_run_true_visible_in_logs(monkeypatch_env):
    import structlog

    from tech_news_synth.config import load_settings
    from tech_news_synth.logging import configure_logging, get_logger

    settings = load_settings()
    configure_logging(settings)
    log = get_logger("test")

    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(dry_run=True)
    log.info("dry_tick")
    for h in logging.getLogger().handlers:
        h.flush()

    lines = _read_jsonl(Path(settings.log_dir) / "app.jsonl")
    hits = [line for line in lines if line.get("event") == "dry_tick"]
    assert hits and all(line.get("dry_run") is True for line in hits)
    structlog.contextvars.clear_contextvars()


def test_dry_run_false_visible_in_logs(monkeypatch_env):
    import structlog

    from tech_news_synth.config import load_settings
    from tech_news_synth.logging import configure_logging, get_logger

    settings = load_settings()
    configure_logging(settings)
    log = get_logger("test")

    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(dry_run=False)
    log.info("live_tick")
    for h in logging.getLogger().handlers:
        h.flush()

    lines = _read_jsonl(Path(settings.log_dir) / "app.jsonl")
    hits = [line for line in lines if line.get("event") == "live_tick"]
    assert hits and all(line.get("dry_run") is False for line in hits)
    structlog.contextvars.clear_contextvars()
