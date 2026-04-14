"""Unit tests for tech_news_synth.publish.caps (Phase 7 Plan 07-01 Task 4)."""

from __future__ import annotations

from pydantic import SecretStr

from tech_news_synth.config import Settings
from tech_news_synth.publish.caps import check_caps
from tech_news_synth.publish.models import CapCheckResult


def _settings(**overrides) -> Settings:
    base = {
        "anthropic_api_key": SecretStr("sk-ant-test"),
        "x_consumer_key": SecretStr("ck"),
        "x_consumer_secret": SecretStr("cs"),
        "x_access_token": SecretStr("at"),
        "x_access_token_secret": SecretStr("ats"),
        "postgres_password": SecretStr("pw"),
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def test_check_caps_neither_reached(mocker):
    mocker.patch("tech_news_synth.publish.caps.count_posted_today", return_value=5)
    mocker.patch("tech_news_synth.publish.caps.sum_monthly_cost_usd", return_value=1.0)
    s = _settings()  # defaults: max_posts_per_day=12, max_monthly_cost_usd=30.0
    result = check_caps(session=mocker.MagicMock(), settings=s)
    assert isinstance(result, CapCheckResult)
    assert result.daily_count == 5
    assert result.daily_reached is False
    assert result.monthly_cost_usd == 1.0
    assert result.monthly_cost_reached is False
    assert result.skip_synthesis is False


def test_check_caps_daily_only(mocker):
    mocker.patch("tech_news_synth.publish.caps.count_posted_today", return_value=12)
    mocker.patch("tech_news_synth.publish.caps.sum_monthly_cost_usd", return_value=1.0)
    s = _settings()
    result = check_caps(session=mocker.MagicMock(), settings=s)
    assert result.daily_reached is True
    assert result.monthly_cost_reached is False
    assert result.skip_synthesis is True


def test_check_caps_monthly_only(mocker):
    mocker.patch("tech_news_synth.publish.caps.count_posted_today", return_value=5)
    mocker.patch("tech_news_synth.publish.caps.sum_monthly_cost_usd", return_value=30.0)
    s = _settings()
    result = check_caps(session=mocker.MagicMock(), settings=s)
    assert result.daily_reached is False
    assert result.monthly_cost_reached is True
    assert result.skip_synthesis is True


def test_check_caps_both_reached(mocker):
    mocker.patch("tech_news_synth.publish.caps.count_posted_today", return_value=15)
    mocker.patch("tech_news_synth.publish.caps.sum_monthly_cost_usd", return_value=50.0)
    s = _settings()
    result = check_caps(session=mocker.MagicMock(), settings=s)
    assert result.daily_reached is True
    assert result.monthly_cost_reached is True
    assert result.skip_synthesis is True


def test_check_caps_boundary_exactly_at_limit(mocker):
    """>= semantics: count == max means reached."""
    mocker.patch("tech_news_synth.publish.caps.count_posted_today", return_value=12)
    mocker.patch("tech_news_synth.publish.caps.sum_monthly_cost_usd", return_value=0.0)
    s = _settings()
    result = check_caps(session=mocker.MagicMock(), settings=s)
    assert result.daily_reached is True
    assert result.skip_synthesis is True
