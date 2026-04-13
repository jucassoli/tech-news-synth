"""STORE-01 — alembic upgrade → downgrade → upgrade round-trip against live PG.

Points alembic at the ``*_test`` DB by setting ``POSTGRES_*`` env vars before
``command.upgrade``/``downgrade`` run (``env.py`` reads ``load_settings()``
fresh on each invocation — alembic reloads the env module per call). This
avoids any monkeypatching of the already-imported env module.

Why not use the conftest ``engine`` fixture? That fixture uses
``Base.metadata.create_all`` — here we need to exercise the real alembic
migration path (upgrade/downgrade SQL), so we drive alembic against a
freshly-dropped public schema.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine

from tests.integration.conftest import _test_database_url

TABLES = {"articles", "clusters", "posts", "run_log"}
ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


def _drop_public_schema(engine: Engine) -> None:
    """Wipe the test DB's schema so alembic upgrades from a clean state."""
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))


@pytest.fixture
def test_dsn() -> str:
    """Resolve the TEST DSN BEFORE any env-var munging.

    ``_test_database_url()`` suffixes the DB name with ``_test`` based on the
    current ``POSTGRES_DB`` env var. We must compute it here (before the
    ``alembic_cfg`` fixture sets ``POSTGRES_DB`` to the already-suffixed name)
    so we don't end up double-suffixing to ``..._test_test``.
    """
    return _test_database_url()


@pytest.fixture
def alembic_cfg(monkeypatch, test_dsn: str):
    """Return an alembic Config whose env.py will materialize the TEST DSN.

    env.py calls ``load_settings()`` on import, so we set the ``POSTGRES_*``
    env vars BEFORE alembic invokes env.py. The fixture also supplies stand-ins
    for every other required Settings field so pydantic doesn't raise.
    """
    from urllib.parse import urlparse

    parsed = urlparse(test_dsn.replace("postgresql+psycopg://", "postgresql://"))
    monkeypatch.setenv("PYDANTIC_SETTINGS_DISABLE_ENV_FILE", "1")
    for k, v in {
        "ANTHROPIC_API_KEY": "x",
        "X_CONSUMER_KEY": "x",
        "X_CONSUMER_SECRET": "x",
        "X_ACCESS_TOKEN": "x",
        "X_ACCESS_TOKEN_SECRET": "x",
    }.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("POSTGRES_HOST", parsed.hostname or "localhost")
    monkeypatch.setenv("POSTGRES_PORT", str(parsed.port or 5432))
    monkeypatch.setenv("POSTGRES_USER", parsed.username or "app")
    monkeypatch.setenv("POSTGRES_PASSWORD", parsed.password or "replace-me")
    monkeypatch.setenv("POSTGRES_DB", (parsed.path or "/tech_news_synth_test").lstrip("/"))
    return Config(str(ALEMBIC_INI))


def test_upgrade_downgrade_upgrade_roundtrip(alembic_cfg, test_dsn: str):
    """STORE-01: downgrade reverses upgrade; re-upgrade restores schema."""
    engine = create_engine(test_dsn, future=True)
    try:
        _drop_public_schema(engine)

        # Upgrade → four tables + alembic_version exist.
        command.upgrade(alembic_cfg, "head")
        insp = inspect(engine)
        present = set(insp.get_table_names())
        assert TABLES.issubset(present), f"missing after upgrade: {TABLES - present}"
        assert "alembic_version" in present

        # Downgrade to base → our four tables gone; alembic_version may remain.
        # (Phase 4 added a second revision, so -1 only drops source_state;
        # we verify full reversibility by going all the way to base.)
        command.downgrade(alembic_cfg, "base")
        insp = inspect(engine)
        remaining = set(insp.get_table_names())
        survived = remaining & TABLES
        assert not survived, f"tables survived downgrade: {survived}"

        # Re-upgrade → tables back.
        command.upgrade(alembic_cfg, "head")
        insp = inspect(engine)
        present = set(insp.get_table_names())
        assert TABLES.issubset(present)
    finally:
        engine.dispose()
