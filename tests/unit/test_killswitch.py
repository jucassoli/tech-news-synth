"""Unit tests for tech_news_synth.killswitch.is_paused (INFRA-09 / D-08)."""

from __future__ import annotations

from pathlib import Path


def _load_settings(monkeypatch_env):
    from tech_news_synth.config import load_settings

    return load_settings()


def test_not_paused_when_neither_set(monkeypatch_env, monkeypatch):
    monkeypatch.setenv("PAUSED", "0")
    settings = _load_settings(monkeypatch_env)
    # Marker path points at a nonexistent file (conftest sets it under tmp_path).
    assert Path(settings.paused_marker_path).exists() is False

    from tech_news_synth.killswitch import is_paused

    assert is_paused(settings) == (False, None)


def test_paused_by_env_only(monkeypatch_env, monkeypatch):
    monkeypatch.setenv("PAUSED", "1")
    settings = _load_settings(monkeypatch_env)

    from tech_news_synth.killswitch import is_paused

    assert is_paused(settings) == (True, "env")


def test_paused_by_marker_only(monkeypatch_env, monkeypatch):
    monkeypatch.setenv("PAUSED", "0")
    settings = _load_settings(monkeypatch_env)
    marker = Path(settings.paused_marker_path)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.touch()

    from tech_news_synth.killswitch import is_paused

    assert is_paused(settings) == (True, "marker")


def test_paused_by_both(monkeypatch_env, monkeypatch):
    monkeypatch.setenv("PAUSED", "1")
    settings = _load_settings(monkeypatch_env)
    marker = Path(settings.paused_marker_path)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.touch()

    from tech_news_synth.killswitch import is_paused

    assert is_paused(settings) == (True, "both")


def test_marker_path_is_configurable(monkeypatch_env, monkeypatch, tmp_path):
    """The settings-provided path MUST be honored, not a hardcoded '/data/paused'."""
    custom = tmp_path / "custom-pause-marker"
    monkeypatch.setenv("PAUSED", "0")
    monkeypatch.setenv("PAUSED_MARKER_PATH", str(custom))
    settings = _load_settings(monkeypatch_env)

    from tech_news_synth.killswitch import is_paused

    # Not yet present
    assert is_paused(settings) == (False, None)
    custom.touch()
    assert is_paused(settings) == (True, "marker")
