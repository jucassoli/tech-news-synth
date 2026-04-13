"""Integration test fixtures — live postgres via compose.

Setup:
    docker compose up -d postgres
    ./scripts/create_test_db.sh     # creates <db>_test (idempotent)
    uv run pytest tests/integration -q -x -m integration

Configuration:
    TEST_DATABASE_URL (optional env override). Defaults to the main
    ``Settings.database_url`` with the DB name suffixed ``_test``.

Guardrails:
    * ``engine`` fixture refuses to proceed unless the DB name ends in
      ``_test`` (T-02-03-A / T-02-08). Prevents any chance of
      ``create_all``/``drop_all`` hitting the production schema.
    * ``db_session`` uses the nested-SAVEPOINT + ``after_transaction_end``
      listener pattern so SUT-level ``session.commit()`` calls remain rolled
      back between tests.
    * Every collected test under this directory is automatically marked with
      ``@pytest.mark.integration``.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

import tech_news_synth.db.models  # noqa: F401 — register models on Base.metadata
from tech_news_synth.config import Settings
from tech_news_synth.db.base import Base


# ---------------------------------------------------------------------------
# Auto-apply the `integration` marker to everything under tests/integration/.
# ---------------------------------------------------------------------------
def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    integration_root = os.path.join("tests", "integration")
    for item in items:
        if integration_root in str(item.fspath):
            item.add_marker(pytest.mark.integration)


# ---------------------------------------------------------------------------
# DSN resolution
# ---------------------------------------------------------------------------
def _test_database_url() -> str:
    """Return the test-DB DSN.

    Order of precedence:
      1. ``TEST_DATABASE_URL`` env var (explicit override).
      2. ``Settings.database_url`` with the DB name suffixed ``_test``.
    """
    override = os.environ.get("TEST_DATABASE_URL")
    if override:
        return override

    settings = Settings()  # type: ignore[call-arg]
    base = settings.database_url
    # Swap last path segment to <db>_test
    prefix, _, _ = base.rpartition("/")
    return f"{prefix}/{settings.postgres_db}_test"


def _assert_safe_test_db(url: str) -> None:
    """Refuse to run if the target DB name does not end in ``_test``.

    Mitigates T-02-03-A / T-02-08 — a mis-configured environment cannot
    accidentally nuke the production schema.
    """
    # The DB name is the path component after the final '/'
    dbname = url.rsplit("/", 1)[-1]
    # Strip any query string (defensive; we don't use one today).
    dbname = dbname.split("?", 1)[0]
    if not dbname.endswith("_test"):
        raise ValueError(
            f"Refusing to create schema on DB {dbname!r}: integration fixtures "
            f"require the database name to end in '_test' (T-02-03-A)."
        )


# ---------------------------------------------------------------------------
# Engine / connection / session fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    """Session-scoped SA engine bound to the test DB.

    Creates the full schema via ``Base.metadata.create_all`` on setup and
    tears it down with ``drop_all`` on teardown. Plan 02-02 will swap this
    to ``alembic upgrade head`` once the alembic tree exists.
    """
    url = _test_database_url()
    _assert_safe_test_db(url)

    eng = create_engine(url, future=True, pool_pre_ping=True)
    Base.metadata.create_all(eng)
    try:
        yield eng
    finally:
        Base.metadata.drop_all(eng)
        eng.dispose()


@pytest.fixture
def connection(engine: Engine) -> Iterator[Connection]:
    """Function-scoped connection wrapped in an outer transaction that is
    rolled back on teardown."""
    conn = engine.connect()
    trans = conn.begin()
    try:
        yield conn
    finally:
        trans.rollback()
        conn.close()


@pytest.fixture
def db_session(connection: Connection) -> Iterator[Session]:
    """Session that isolates SUT-level ``commit()`` calls via nested SAVEPOINT.

    Pattern (per SA docs — "Joining a Session into an External Transaction"):
    the outer transaction is managed by the ``connection`` fixture; we
    ``begin_nested()`` a SAVEPOINT and restart it every time the SUT commits,
    so the outer rollback always wipes the slate clean.
    """
    session = Session(bind=connection, expire_on_commit=False)
    nested = connection.begin_nested()

    @event.listens_for(session, "after_transaction_end")
    def _restart_savepoint(sess: Session, transaction) -> None:
        nonlocal nested
        if transaction.nested and not transaction._parent.nested:
            nested = connection.begin_nested()

    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def clean_db(engine: Engine) -> Iterator[None]:
    """Hard reset — TRUNCATE all four tables with RESTART IDENTITY CASCADE.

    Use this only when a test explicitly needs a fresh slate outside the
    transactional-rollback pattern (most tests should depend on ``db_session``
    instead).
    """
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE articles, clusters, posts, run_log RESTART IDENTITY CASCADE"))
    yield
