"""Phase 8 OPS-04 — source-health CLI integration tests (real DB).

Invokes ``source_health.main`` in-process but routes ``SessionLocal`` to the
test ``db_session`` fixture so the SUT's ``commit()`` is captured by the
nested-SAVEPOINT rollback pattern. Subprocess approach rejected because the
per-test DB isolation relies on the test-owned connection.
"""

from __future__ import annotations

import json
import os

import pytest

from tech_news_synth.cli import source_health
from tech_news_synth.db.source_state import get_state, mark_disabled, upsert_source

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _cli_boot(mocker, db_session, tmp_path):
    """Route CLI boot to the test session + a tmp log dir."""
    os.environ["LOG_DIR"] = str(tmp_path)
    mocker.patch(
        "tech_news_synth.cli.source_health.load_settings",
        return_value=mocker.MagicMock(log_dir=str(tmp_path)),
    )
    mocker.patch("tech_news_synth.cli.source_health.configure_logging")
    mocker.patch("tech_news_synth.cli.source_health.init_engine")
    # Yield db_session wrapped as a context manager.
    session_cm = mocker.MagicMock()
    session_cm.__enter__ = lambda self: db_session
    session_cm.__exit__ = lambda self, *a: None
    mocker.patch("tech_news_synth.cli.source_health.SessionLocal", return_value=session_cm)


_DEFAULT_NAMES = ("techcrunch", "verge", "ars_technica", "hacker_news", "reddit_technology")


def _seed(db_session, names=_DEFAULT_NAMES):
    for n in names:
        upsert_source(db_session, n)
    db_session.flush()


def test_status_mode(db_session, capsys):
    _seed(db_session)
    rc = source_health.main([])
    assert rc == 0
    out = capsys.readouterr().out
    for name in ("techcrunch", "verge", "ars_technica", "hacker_news", "reddit_technology"):
        assert name in out


def test_json_mode(db_session, capsys):
    _seed(db_session, ("techcrunch", "verge"))
    rc = source_health.main(["--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert isinstance(payload, list)
    names = {p["name"] for p in payload}
    assert {"techcrunch", "verge"} <= names
    for entry in payload:
        assert set(entry.keys()) == {
            "name", "last_fetched_at", "last_status",
            "consecutive_failures", "disabled",
        }


def test_enable_persists(db_session):
    """--enable clears disabled_at AND resets consecutive_failures."""
    _seed(db_session, ("techcrunch",))
    mark_disabled(db_session, "techcrunch")
    row = get_state(db_session, "techcrunch")
    row.consecutive_failures = 5
    db_session.flush()
    assert row.disabled_at is not None

    rc = source_health.main(["--enable", "techcrunch"])
    assert rc == 0

    row2 = get_state(db_session, "techcrunch")
    assert row2.disabled_at is None
    assert row2.consecutive_failures == 0


def test_disable_persists(db_session):
    _seed(db_session, ("techcrunch",))
    row = get_state(db_session, "techcrunch")
    assert row.disabled_at is None

    rc = source_health.main(["--disable", "techcrunch"])
    assert rc == 0

    row2 = get_state(db_session, "techcrunch")
    assert row2.disabled_at is not None


def test_enable_unknown_exits_1(db_session, capsys):
    rc = source_health.main(["--enable", "ghost_source"])
    assert rc == 1
    assert "unknown source" in capsys.readouterr().err


def test_disable_unknown_exits_1(db_session, capsys):
    rc = source_health.main(["--disable", "ghost_source"])
    assert rc == 1
    assert "unknown source" in capsys.readouterr().err
