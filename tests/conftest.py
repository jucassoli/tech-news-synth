"""Shared pytest fixtures for tech-news-synth unit tests."""

from __future__ import annotations

import pytest


@pytest.fixture
def monkeypatch_env(monkeypatch, tmp_path):
    """Set a complete valid env for Settings() and prevent .env file loading.

    Returns the dict of env vars that were set, for tests that want to inspect them.
    """
    env = {
        "ANTHROPIC_API_KEY": "sk-ant-test",
        "X_CONSUMER_KEY": "k",
        "X_CONSUMER_SECRET": "s",
        "X_ACCESS_TOKEN": "t",
        "X_ACCESS_TOKEN_SECRET": "ts",
        "POSTGRES_PASSWORD": "pw",
        "INTERVAL_HOURS": "2",
        "PAUSED": "0",
        "DRY_RUN": "0",
        "LOG_DIR": str(tmp_path / "logs"),
        "PAUSED_MARKER_PATH": str(tmp_path / "paused"),
    }
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    # Prevent pydantic-settings from loading a real .env during tests.
    monkeypatch.setenv("PYDANTIC_SETTINGS_DISABLE_ENV_FILE", "1")
    return env


@pytest.fixture
def tmp_data_dir(tmp_path, monkeypatch):
    """Provide an isolated /data-like tree for logs and pause marker."""
    d = tmp_path / "data"
    (d / "logs").mkdir(parents=True)
    monkeypatch.setenv("LOG_DIR", str(d / "logs"))
    monkeypatch.setenv("PAUSED_MARKER_PATH", str(d / "paused"))
    return d
