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

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _env_file_for_settings() -> str | None:
    """Return ``.env`` by default; ``None`` when tests disable env-file loading."""
    if os.environ.get("PYDANTIC_SETTINGS_DISABLE_ENV_FILE") == "1":
        return None
    return ".env"


class Settings(BaseSettings):
    """Frozen, typed settings object for the agent."""

    model_config = SettingsConfigDict(
        env_file=_env_file_for_settings(),
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
        return Settings()  # type: ignore[call-arg]
    except Exception as e:
        print(f"Configuration error:\n{e}", file=sys.stderr)
        raise
