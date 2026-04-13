"""SQLAlchemy engine + session factory.

Module-level singletons (``_engine``, ``_SessionLocal``) initialized once via
:func:`init_engine` at container boot. Pool size 5 is plenty for a
single-worker agent. ``pool_pre_ping=True`` makes pooled connections resilient
to postgres restarts (D-03 leaves reliability to compose + cycle-level retry).

Security (T-02-01-A): the DSN (which contains the DB password) is NEVER
logged. Only ``pool_size`` appears in the ``db_engine_initialized`` event.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from tech_news_synth.config import Settings
from tech_news_synth.logging import get_logger

log = get_logger(__name__)

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def init_engine(settings: Settings) -> Engine:
    """Initialize the module-level engine + SessionLocal.

    Idempotent — calling twice with any settings returns the already-built
    engine. The first call wins; downstream callers (tests, scheduler) can
    assume the engine exists after :func:`init_engine` has been invoked once.
    """
    global _engine, _SessionLocal
    if _engine is not None:
        return _engine
    _engine = create_engine(
        settings.database_url,
        pool_pre_ping=True,
        pool_size=5,
        future=True,
    )
    _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False, class_=Session)
    # NEVER log settings.database_url — it contains the password (T-02-01-A).
    log.info("db_engine_initialized", pool_size=5)
    return _engine


def SessionLocal() -> Session:
    """Return a fresh ORM ``Session``.

    :func:`init_engine` must have been called first; otherwise raises
    ``RuntimeError`` with a clear message.
    """
    if _SessionLocal is None:
        raise RuntimeError("init_engine(settings) must be called before SessionLocal()")
    return _SessionLocal()


@contextmanager
def get_session() -> Iterator[Session]:
    """Yield a ``Session`` and close it on exit.

    The caller is responsible for ``commit()``/``rollback()``. This
    contextmanager intentionally does NOT auto-commit because different
    call-sites (run_log start vs. finish) have different commit semantics;
    pushing the decision up keeps the helper minimal.
    """
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def _reset_engine_for_tests() -> None:
    """Test-only helper — never called in production code.

    Clears the module-level singletons so a test can call
    :func:`init_engine` from a clean slate.
    """
    global _engine, _SessionLocal
    _engine = None
    _SessionLocal = None
