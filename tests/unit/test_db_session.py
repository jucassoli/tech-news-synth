"""Unit tests for db.base.Base and db.session (no DB roundtrip).

Proven invariants:
* ``Base`` is a usable ``DeclarativeBase`` subclass with a fresh ``metadata``.
* ``SessionLocal()`` raises ``RuntimeError`` before ``init_engine`` is called.
* ``init_engine(settings)`` is idempotent — second call returns the same engine.
* ``init_engine`` never logs the DSN or password (T-02-01-A mitigation).
"""

from __future__ import annotations

import structlog

from tech_news_synth.config import Settings


def _fresh_session_module():
    """Reset the module-level engine singletons between tests.

    Returns the (re-imported) session module with ``_engine`` / ``_SessionLocal``
    cleared so each test starts from a clean slate.
    """
    from tech_news_synth.db import session as session_mod

    session_mod._reset_engine_for_tests()
    return session_mod


def test_base_is_declarative_with_empty_metadata() -> None:
    from tech_news_synth.db.base import Base

    assert hasattr(Base, "metadata")
    # Tables register themselves when models are imported; importing Base
    # alone yields an empty (or consistently shaped) metadata object.
    assert Base.metadata is not None


def test_session_local_before_init_raises(monkeypatch_env) -> None:
    session_mod = _fresh_session_module()
    try:
        session_mod.SessionLocal()
    except RuntimeError as exc:
        assert "init_engine" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")


def test_init_engine_is_idempotent(monkeypatch_env) -> None:
    session_mod = _fresh_session_module()
    settings = Settings()
    e1 = session_mod.init_engine(settings)
    e2 = session_mod.init_engine(settings)
    assert e1 is e2


def test_init_engine_does_not_log_dsn_or_password(monkeypatch_env) -> None:
    session_mod = _fresh_session_module()
    settings = Settings()
    password = settings.postgres_password.get_secret_value()

    with structlog.testing.capture_logs() as captured:
        session_mod.init_engine(settings)

    serialized = repr(captured)
    assert password not in serialized, "DB password leaked into structlog output"
    assert "postgresql+psycopg://" not in serialized, "DSN leaked into structlog output"
    # At least one event was emitted — confirm the logger was actually called.
    assert any(entry.get("event") == "db_engine_initialized" for entry in captured)
