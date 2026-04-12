"""Unit tests for tech_news_synth.logging.configure_logging (INFRA-07)."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def test_dual_output_stdout_and_file(monkeypatch_env, capsys):
    import structlog

    from tech_news_synth.config import load_settings
    from tech_news_synth.logging import configure_logging, get_logger

    settings = load_settings()
    configure_logging(settings)

    log = get_logger("test")
    log.info("hello", foo=1)

    # Flush stdlib handlers so the FileHandler writes to disk synchronously.
    for h in logging.getLogger().handlers:
        h.flush()

    out = capsys.readouterr().out
    stdout_lines = [json.loads(line) for line in out.strip().splitlines() if line.strip()]
    assert any(
        line.get("event") == "hello" and line.get("foo") == 1 and line.get("level") == "info"
        for line in stdout_lines
    )
    assert any(re.search(r"(\+00:00|Z)$", line.get("timestamp", "")) for line in stdout_lines)

    log_file = Path(settings.log_dir) / "app.jsonl"
    assert log_file.exists()
    file_lines = _read_jsonl(log_file)
    assert any(line.get("event") == "hello" and line.get("foo") == 1 for line in file_lines)
    # Clean up contextvars for other tests
    structlog.contextvars.clear_contextvars()


def test_contextvars_cycle_id_appears_then_clears(monkeypatch_env, capsys, tmp_path):
    import structlog

    from tech_news_synth.config import load_settings
    from tech_news_synth.logging import configure_logging, get_logger

    settings = load_settings()
    configure_logging(settings)

    log = get_logger("test")
    cid = "01ARZ3NDEKTSV4RRFFQ69G5FAV"
    structlog.contextvars.bind_contextvars(cycle_id=cid)
    log.info("with_cid")

    structlog.contextvars.clear_contextvars()
    log.info("without_cid")

    for h in logging.getLogger().handlers:
        h.flush()

    log_file = Path(settings.log_dir) / "app.jsonl"
    lines = _read_jsonl(log_file)

    with_cid = [line for line in lines if line.get("event") == "with_cid"]
    without_cid = [line for line in lines if line.get("event") == "without_cid"]

    assert with_cid and all(line.get("cycle_id") == cid for line in with_cid)
    assert without_cid and all("cycle_id" not in line for line in without_cid)


def test_configure_logging_is_idempotent(monkeypatch_env):
    from tech_news_synth.config import load_settings
    from tech_news_synth.logging import configure_logging

    settings = load_settings()
    configure_logging(settings)
    configure_logging(settings)

    root = logging.getLogger()
    # Two handlers expected: stdout + file. Calling twice must not double.
    assert len(root.handlers) == 2


def test_log_dir_created_if_missing(monkeypatch_env, monkeypatch, tmp_path):
    missing = tmp_path / "does" / "not" / "exist" / "logs"
    monkeypatch.setenv("LOG_DIR", str(missing))

    from tech_news_synth.config import load_settings
    from tech_news_synth.logging import configure_logging

    settings = load_settings()
    assert not missing.exists()
    configure_logging(settings)
    assert missing.exists()
    assert (missing / "app.jsonl").parent.is_dir()
