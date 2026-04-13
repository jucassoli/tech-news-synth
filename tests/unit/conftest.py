"""Unit-test fixtures.

Plan 02-02 wires ``run_cycle`` to write to ``run_log`` via ``SessionLocal``.
Unit tests must NOT touch a real DB, so we autouse-patch the three symbols
the scheduler imports (``SessionLocal``, ``start_cycle``, ``finish_cycle``)
to in-memory MagicMocks. Tests that want to assert specific call shapes can
override via the ``mock_db_in_scheduler`` fixture (returns the trio).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


@pytest.fixture(autouse=True)
def mock_db_in_scheduler(mocker, request):
    """Auto-patch DB deps imported by ``tech_news_synth.scheduler``.

    Skipped for any test that doesn't import scheduler (no harm done — the
    patch targets exist after import) and for tests that explicitly want to
    skip via the ``no_db_mock`` marker.
    """
    if request.node.get_closest_marker("no_db_mock"):
        yield None
        return

    session = MagicMock(name="SessionLocal_session")
    session_factory = mocker.patch("tech_news_synth.scheduler.SessionLocal", return_value=session)
    start = mocker.patch("tech_news_synth.scheduler.start_cycle")
    finish = mocker.patch("tech_news_synth.scheduler.finish_cycle")
    yield session_factory, session, start, finish
