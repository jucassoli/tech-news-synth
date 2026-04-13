"""Unit tests for tech_news_synth.config.Settings.

Covers INFRA-03 (fail-fast config), INFRA-10 (DRY_RUN), INFRA-05 (INTERVAL_HOURS
validator), and threat mitigations T-01-03 / T-01-04 / T-01-05 / T-01-07.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError


# ---------------------------------------------------------------------------
# Test 1 — happy path: complete env yields a valid Settings
# ---------------------------------------------------------------------------
def test_settings_happy_path(monkeypatch_env):
    from tech_news_synth.config import load_settings

    s = load_settings()
    assert s.interval_hours == 2
    assert s.paused is False
    assert s.dry_run is False
    assert s.anthropic_api_key.get_secret_value() == "sk-ant-test"


# ---------------------------------------------------------------------------
# Test 2 — SecretStr hygiene: no raw secrets in repr / str / JSON
# ---------------------------------------------------------------------------
def test_settings_secrets_masked(monkeypatch_env):
    from tech_news_synth.config import load_settings

    s = load_settings()
    text_forms = [repr(s), str(s), s.model_dump_json()]
    for text in text_forms:
        assert "sk-ant-test" not in text
        assert "pw" not in text or "password" in text.lower()  # "pw" secret must not leak
        # The SecretStr mask is "**********"
        assert "**********" in text


# ---------------------------------------------------------------------------
# Test 3 — frozen: assignment after construction is rejected
# ---------------------------------------------------------------------------
def test_settings_frozen(monkeypatch_env):
    from tech_news_synth.config import load_settings

    s = load_settings()
    with pytest.raises(ValidationError):
        s.interval_hours = 7


# ---------------------------------------------------------------------------
# Test 4 — missing required key surfaces a clear error
# ---------------------------------------------------------------------------
def test_settings_missing_required(monkeypatch_env, monkeypatch):
    from tech_news_synth.config import load_settings

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(ValidationError) as excinfo:
        load_settings()
    assert "anthropic_api_key" in str(excinfo.value).lower()


# ---------------------------------------------------------------------------
# Test 5 — INTERVAL_HOURS must divide 24 (PITFALLS #3, T-01-05)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("valid", [1, 2, 3, 4, 6, 8, 12, 24])
def test_interval_hours_valid_divisors(monkeypatch_env, monkeypatch, valid):
    from tech_news_synth.config import load_settings

    monkeypatch.setenv("INTERVAL_HOURS", str(valid))
    s = load_settings()
    assert s.interval_hours == valid


@pytest.mark.parametrize("invalid", [5, 7, 9, 10, 11, 13])
def test_interval_hours_invalid_non_divisors(monkeypatch_env, monkeypatch, invalid):
    from tech_news_synth.config import load_settings

    monkeypatch.setenv("INTERVAL_HOURS", str(invalid))
    with pytest.raises(ValidationError) as excinfo:
        load_settings()
    msg = str(excinfo.value).lower()
    assert "24" in msg and "interval_hours" in msg


# ---------------------------------------------------------------------------
# Test 6 — bool coercion truth table (PITFALLS #9, T-01-04)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("0", False),
        ("false", False),
        ("False", False),
        ("no", False),
        ("off", False),
        ("1", True),
        ("true", True),
        ("True", True),
        ("yes", True),
        ("on", True),
    ],
)
def test_paused_bool_coercion(monkeypatch_env, monkeypatch, raw, expected):
    from tech_news_synth.config import load_settings

    monkeypatch.setenv("PAUSED", raw)
    s = load_settings()
    assert s.paused is expected


# ---------------------------------------------------------------------------
# Test 7 — database_url composes correctly from SecretStr secret
# ---------------------------------------------------------------------------
def test_database_url_composition(monkeypatch_env):
    from tech_news_synth.config import load_settings

    s = load_settings()
    url = s.database_url
    assert url == "postgresql+psycopg://app:pw@postgres:5432/tech_news_synth"
    # Ensure we never str()'d the SecretStr wrapper itself
    assert "SecretStr" not in url
    assert "**********" not in url


# ---------------------------------------------------------------------------
# Test 8 — DRY_RUN=1 accepted (INFRA-10)
# ---------------------------------------------------------------------------
def test_dry_run_accepted(monkeypatch_env, monkeypatch):
    from tech_news_synth.config import load_settings

    monkeypatch.setenv("DRY_RUN", "1")
    s = load_settings()
    assert s.dry_run is True


# ---------------------------------------------------------------------------
# Bonus — model_dump_json produces JSON (shape sanity)
# ---------------------------------------------------------------------------
def test_model_dump_json_parseable(monkeypatch_env):
    from tech_news_synth.config import load_settings

    s = load_settings()
    payload = json.loads(s.model_dump_json())
    assert payload["interval_hours"] == 2
    assert "anthropic_api_key" in payload
    # Masked form in JSON
    assert payload["anthropic_api_key"] == "**********"


# ---------------------------------------------------------------------------
# Phase 4 — sources_config_path + max_consecutive_failures
# ---------------------------------------------------------------------------
def test_sources_config_path_default(monkeypatch_env):
    from tech_news_synth.config import load_settings

    s = load_settings()
    assert s.sources_config_path == "/app/config/sources.yaml"


def test_sources_config_path_override(monkeypatch_env, monkeypatch):
    from tech_news_synth.config import load_settings

    monkeypatch.setenv("SOURCES_CONFIG_PATH", "/custom/path/sources.yaml")
    s = load_settings()
    assert s.sources_config_path == "/custom/path/sources.yaml"


def test_max_consecutive_failures_default(monkeypatch_env):
    from tech_news_synth.config import load_settings

    s = load_settings()
    assert s.max_consecutive_failures == 20


@pytest.mark.parametrize("invalid", ["0", "-1", "1001"])
def test_max_consecutive_failures_out_of_bounds(monkeypatch_env, monkeypatch, invalid):
    from tech_news_synth.config import load_settings

    monkeypatch.setenv("MAX_CONSECUTIVE_FAILURES", invalid)
    with pytest.raises(ValidationError):
        load_settings()
