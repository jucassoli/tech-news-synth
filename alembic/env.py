"""Alembic environment — reads DSN from Settings at runtime (T-02-01).

The DSN is NOT in `alembic.ini`. We materialize it from
`tech_news_synth.config.load_settings().database_url` here, so the checked-in
config has no credentials. `target_metadata` is `Base.metadata` — the single
authoritative source from `tech_news_synth.db.base` after `db.models` is
imported to register the four ORM classes.

Logging is intentionally configured at WARN via `alembic.ini` so the DSN
doesn't leak into INFO output (T-02-02). Programmatic `run_migrations()`
installs structlog; this file only runs on `alembic <cmd>` CLI invocations.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from tech_news_synth.config import load_settings
from tech_news_synth.db import models  # noqa: F401 — register models on Base.metadata
from tech_news_synth.db.base import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

_settings = load_settings()
# Set at runtime so alembic.ini stays DSN-free (T-02-01).
config.set_main_option("sqlalchemy.url", _settings.database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Emit SQL without connecting — used by `alembic upgrade --sql`."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Connect and apply migrations — normal path."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
