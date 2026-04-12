"""INFRA-06 — UTC invariants enforced in logs AND statically via ruff DTZ."""

from __future__ import annotations

import json
import logging
import re
import subprocess
from pathlib import Path


def test_log_timestamp_is_utc(monkeypatch_env):
    from tech_news_synth.config import load_settings
    from tech_news_synth.logging import configure_logging, get_logger

    settings = load_settings()
    configure_logging(settings)
    get_logger("test").info("utc_probe")
    for h in logging.getLogger().handlers:
        h.flush()

    log_file = Path(settings.log_dir) / "app.jsonl"
    lines = [json.loads(ln) for ln in log_file.read_text().splitlines() if ln.strip()]
    hit = next(line for line in lines if line.get("event") == "utc_probe")
    ts = hit["timestamp"]
    assert re.search(r"(\+00:00|Z)$", ts), f"timestamp not UTC: {ts!r}"


def test_src_has_no_naive_datetime_usage():
    """Ruff DTZ rules ban ``datetime.now()`` / ``datetime.utcnow()`` without tz."""
    repo_root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        ["uv", "run", "ruff", "check", "--select=DTZ", "src/"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"ruff DTZ rules failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
