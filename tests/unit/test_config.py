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


# ---------------------------------------------------------------------------
# Phase 5 — clustering settings (D-15)
# ---------------------------------------------------------------------------
def test_cluster_settings_defaults(monkeypatch_env):
    from tech_news_synth.config import load_settings

    s = load_settings()
    assert s.cluster_window_hours == 6
    assert s.cluster_distance_threshold == 0.35
    assert s.anti_repeat_cosine_threshold == 0.5
    assert s.anti_repeat_window_hours == 48


@pytest.mark.parametrize(
    "env_var,bad_value",
    [
        ("CLUSTER_WINDOW_HOURS", "0"),
        ("CLUSTER_WINDOW_HOURS", "73"),
        ("CLUSTER_DISTANCE_THRESHOLD", "-0.1"),
        ("CLUSTER_DISTANCE_THRESHOLD", "1.1"),
        ("ANTI_REPEAT_COSINE_THRESHOLD", "-0.1"),
        ("ANTI_REPEAT_COSINE_THRESHOLD", "1.5"),
        ("ANTI_REPEAT_WINDOW_HOURS", "0"),
        ("ANTI_REPEAT_WINDOW_HOURS", "169"),
    ],
)
def test_cluster_settings_rejects_invalid(monkeypatch_env, monkeypatch, env_var, bad_value):
    from tech_news_synth.config import load_settings

    monkeypatch.setenv(env_var, bad_value)
    with pytest.raises(ValidationError):
        load_settings()


# ---------------------------------------------------------------------------
# Phase 6 — synthesis settings (D-13)
# ---------------------------------------------------------------------------
def test_synthesis_settings_defaults(monkeypatch_env):
    from tech_news_synth.config import load_settings

    s = load_settings()
    assert s.synthesis_max_tokens == 150
    assert s.synthesis_char_budget == 225
    assert s.synthesis_max_retries == 2
    assert s.hashtag_budget_chars == 30
    assert s.hashtags_config_path == "/app/config/hashtags.yaml"


@pytest.mark.parametrize(
    "env_var,bad_value",
    [
        ("SYNTHESIS_MAX_TOKENS", "49"),
        ("SYNTHESIS_MAX_TOKENS", "501"),
        ("SYNTHESIS_CHAR_BUDGET", "99"),
        ("SYNTHESIS_CHAR_BUDGET", "281"),
        ("SYNTHESIS_MAX_RETRIES", "-1"),
        ("SYNTHESIS_MAX_RETRIES", "6"),
        ("HASHTAG_BUDGET_CHARS", "-1"),
        ("HASHTAG_BUDGET_CHARS", "51"),
    ],
)
def test_synthesis_settings_rejects_invalid(monkeypatch_env, monkeypatch, env_var, bad_value):
    from tech_news_synth.config import load_settings

    monkeypatch.setenv(env_var, bad_value)
    with pytest.raises(ValidationError):
        load_settings()


def test_synthesis_settings_accepts_valid_override(monkeypatch_env, monkeypatch):
    from tech_news_synth.config import load_settings

    monkeypatch.setenv("SYNTHESIS_MAX_TOKENS", "200")
    monkeypatch.setenv("SYNTHESIS_CHAR_BUDGET", "240")
    monkeypatch.setenv("SYNTHESIS_MAX_RETRIES", "3")
    monkeypatch.setenv("HASHTAG_BUDGET_CHARS", "25")
    s = load_settings()
    assert s.synthesis_max_tokens == 200
    assert s.synthesis_char_budget == 240
    assert s.synthesis_max_retries == 3
    assert s.hashtag_budget_chars == 25


# ---------------------------------------------------------------------------
# Phase 7 — publish settings (D-11) + bearer-only rejection (D-01)
# ---------------------------------------------------------------------------
def test_publish_settings_defaults(monkeypatch_env):
    from tech_news_synth.config import load_settings

    s = load_settings()
    assert s.max_posts_per_day == 12
    assert s.max_monthly_cost_usd == 30.00
    assert s.publish_stale_pending_minutes == 5
    assert s.x_api_timeout_sec == 30


def test_config_rejects_bearer_only(monkeypatch_env, monkeypatch):
    """PUBLISH-01 / D-01: any empty x_* OAuth secret → ValidationError at boot."""
    from tech_news_synth.config import load_settings

    monkeypatch.setenv("X_CONSUMER_KEY", "")
    with pytest.raises(ValidationError) as excinfo:
        load_settings()
    assert "x_consumer_key" in str(excinfo.value)


@pytest.mark.parametrize("invalid", ["0", "1001"])
def test_max_posts_per_day_bounds(monkeypatch_env, monkeypatch, invalid):
    from tech_news_synth.config import load_settings

    monkeypatch.setenv("MAX_POSTS_PER_DAY", invalid)
    with pytest.raises(ValidationError):
        load_settings()


@pytest.mark.parametrize(
    "env_var,bad_value",
    [
        ("MAX_MONTHLY_COST_USD", "0.5"),
        ("MAX_MONTHLY_COST_USD", "10001"),
        ("PUBLISH_STALE_PENDING_MINUTES", "0"),
        ("PUBLISH_STALE_PENDING_MINUTES", "1441"),
        ("X_API_TIMEOUT_SEC", "4"),
        ("X_API_TIMEOUT_SEC", "121"),
    ],
)
def test_publish_settings_rejects_invalid(monkeypatch_env, monkeypatch, env_var, bad_value):
    from tech_news_synth.config import load_settings

    monkeypatch.setenv(env_var, bad_value)
    with pytest.raises(ValidationError):
        load_settings()
