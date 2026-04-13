"""STORE-01 — unit tests for :func:`run_migrations`.

Mocks ``alembic.command.upgrade`` so the test doesn't touch a real DB.
Integration coverage lives in ``tests/integration/test_migration_roundtrip.py``.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from tech_news_synth.db.migrations import _ALEMBIC_INI, run_migrations


def test_alembic_ini_path_resolves_to_repo_root() -> None:
    assert _ALEMBIC_INI.name == "alembic.ini"
    assert _ALEMBIC_INI.exists(), f"{_ALEMBIC_INI} missing"


@patch("tech_news_synth.db.migrations.command.upgrade")
def test_run_migrations_calls_upgrade_head(mock_upgrade) -> None:
    run_migrations()
    assert mock_upgrade.call_count == 1
    args, _kwargs = mock_upgrade.call_args
    cfg, target = args
    assert target == "head"
    # Config points at our alembic/ directory.
    assert cfg.get_main_option("script_location") == "alembic"


@patch("tech_news_synth.db.migrations.command.upgrade")
def test_run_migrations_propagates_exception(mock_upgrade) -> None:
    """D-03: no catch, no retry — exception bubbles so the container exits."""
    mock_upgrade.side_effect = RuntimeError("db down")
    with pytest.raises(RuntimeError, match="db down"):
        run_migrations()
