"""Settings — typed, fail-fast config for tech-news-synth.

INFRA-03: pydantic-settings loads from env (and optionally .env); missing or
invalid keys raise ValidationError at boot.
INFRA-05: INTERVAL_HOURS validator enforces 24 % N == 0 (PITFALLS #3).
INFRA-10: DRY_RUN accepted as a typed bool (visible in logs via contextvars).

Security:
- All API keys and DB password are ``SecretStr`` (T-01-03). Raw values never
  appear in ``repr`` / ``str`` / ``model_dump_json`` output.
- ``frozen=True`` prevents runtime mutation (T-01-07).
- ``extra="ignore"`` avoids crashes on unmodeled Compose/OS env vars.
"""

from __future__ import annotations

import os
import sys

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _env_file_for_settings() -> str | None:
    """Return ``.env`` by default; ``None`` when tests disable env-file loading.

    Evaluated at ``load_settings()`` call time (not class-body time) so test
    fixtures that set ``PYDANTIC_SETTINGS_DISABLE_ENV_FILE=1`` are honored.
    """
    if os.environ.get("PYDANTIC_SETTINGS_DISABLE_ENV_FILE") == "1":
        return None
    return ".env"


class Settings(BaseSettings):
    """Frozen, typed settings object for the agent."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        frozen=True,
    )

    # --- Runtime knobs ---
    interval_hours: int = Field(default=2, ge=1, le=24)
    paused: bool = False
    dry_run: bool = False
    log_dir: str = "/data/logs"
    paused_marker_path: str = "/data/paused"

    # --- Phase 4 ingest ---
    sources_config_path: str = "/app/config/sources.yaml"
    max_consecutive_failures: int = Field(default=20, ge=1, le=1000)

    # --- Phase 5 clustering (D-15) ---
    cluster_window_hours: int = Field(default=6, ge=1, le=72)
    cluster_distance_threshold: float = Field(default=0.35, ge=0.0, le=1.0)
    anti_repeat_cosine_threshold: float = Field(default=0.5, ge=0.0, le=1.0)
    anti_repeat_window_hours: int = Field(default=48, ge=1, le=168)

    # --- Phase 6 synthesis (D-13) ---
    synthesis_max_tokens: int = Field(default=150, ge=50, le=500)
    synthesis_char_budget: int = Field(default=225, ge=100, le=280)
    synthesis_max_retries: int = Field(default=2, ge=0, le=5)
    hashtag_budget_chars: int = Field(default=30, ge=0, le=50)
    hashtags_config_path: str = "/app/config/hashtags.yaml"

    # --- Phase 7 publish (D-11) ---
    max_posts_per_day: int = Field(default=12, ge=1, le=1000)
    max_monthly_cost_usd: float = Field(default=30.00, ge=1.0, le=10000.0)
    publish_stale_pending_minutes: int = Field(default=5, ge=1, le=1440)
    x_api_timeout_sec: int = Field(default=30, ge=5, le=120)

    # --- Secrets (SecretStr — never raw) ---
    anthropic_api_key: SecretStr
    x_consumer_key: SecretStr
    x_consumer_secret: SecretStr
    x_access_token: SecretStr
    x_access_token_secret: SecretStr

    # --- Postgres ---
    postgres_host: str = "postgres"
    postgres_port: int = 5432
    postgres_db: str = "tech_news_synth"
    postgres_user: str = "app"
    postgres_password: SecretStr

    # ------------------------------------------------------------------
    # Validators
    # ------------------------------------------------------------------
    @field_validator("interval_hours")
    @classmethod
    def _interval_hours_must_divide_24(cls, v: int) -> int:
        """Enforce PITFALLS #3: CronTrigger(hour='*/N') only behaves sanely
        when N divides 24 evenly. Otherwise ticks drift across day boundaries.
        """
        if 24 % v != 0:
            raise ValueError(
                "INTERVAL_HOURS must divide 24 evenly — allowed: 1, 2, 3, 4, 6, 8, 12, 24"
            )
        return v

    @model_validator(mode="after")
    def _require_x_oauth_secrets(self) -> "Settings":
        """D-01: reject bearer-only configs at boot (PUBLISH-01)."""
        missing = [
            name
            for name, val in (
                ("x_consumer_key", self.x_consumer_key),
                ("x_consumer_secret", self.x_consumer_secret),
                ("x_access_token", self.x_access_token),
                ("x_access_token_secret", self.x_access_token_secret),
            )
            if not val.get_secret_value()
        ]
        if missing:
            raise ValueError(
                f"X OAuth 1.0a User Context required — missing/empty secrets: {missing}. "
                f"Bearer-only auth is not supported (PUBLISH-01)."
            )
        return self

    # ------------------------------------------------------------------
    # Derived values
    # ------------------------------------------------------------------
    @property
    def database_url(self) -> str:
        """SQLAlchemy 2.0 + psycopg3 DSN. Materializes the SecretStr once."""
        pw = self.postgres_password.get_secret_value()
        return (
            f"postgresql+psycopg://{self.postgres_user}:{pw}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


def load_settings() -> Settings:
    """Instantiate Settings, printing a readable error to stderr on failure.

    Callers (e.g. ``__main__``) can catch ``ValidationError`` and ``sys.exit(2)``.
    No logging happens here — this runs before ``configure_logging`` (PITFALLS #5).
    """
    try:
        return Settings(_env_file=_env_file_for_settings())  # type: ignore[call-arg]
    except Exception as e:
        print(f"Configuration error:\n{e}", file=sys.stderr)
        raise
