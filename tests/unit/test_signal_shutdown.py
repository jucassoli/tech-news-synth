"""SIGTERM / SIGINT handlers wire to scheduler.shutdown(wait=True) exactly once
per signal (cross-cutting INFRA-05 / INFRA-08).

These tests do not actually deliver signals — they retrieve the installed
handler and invoke it directly."""

from __future__ import annotations

import signal
from unittest.mock import MagicMock

import pytest

from tech_news_synth.scheduler import _install_signal_handlers


@pytest.fixture(autouse=True)
def _restore_signal_handlers():
    """Preserve pytest's default signal handlers across tests."""
    prev_term = signal.getsignal(signal.SIGTERM)
    prev_int = signal.getsignal(signal.SIGINT)
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, prev_term)
        signal.signal(signal.SIGINT, prev_int)


def test_handlers_installed() -> None:
    sched = MagicMock()
    _install_signal_handlers(sched)

    term_handler = signal.getsignal(signal.SIGTERM)
    int_handler = signal.getsignal(signal.SIGINT)

    assert callable(term_handler)
    assert callable(int_handler)
    assert term_handler is not signal.SIG_DFL
    assert term_handler is not signal.SIG_IGN
    assert int_handler is not signal.SIG_DFL
    assert int_handler is not signal.SIG_IGN


def test_sigterm_calls_shutdown_once() -> None:
    sched = MagicMock()
    _install_signal_handlers(sched)

    handler = signal.getsignal(signal.SIGTERM)
    with pytest.raises(SystemExit) as exc:
        handler(signal.SIGTERM, None)
    assert exc.value.code == 0
    sched.shutdown.assert_called_once_with(wait=True)


def test_sigint_also_calls_shutdown() -> None:
    sched = MagicMock()
    _install_signal_handlers(sched)

    handler = signal.getsignal(signal.SIGINT)
    with pytest.raises(SystemExit) as exc:
        handler(signal.SIGINT, None)
    assert exc.value.code == 0
    sched.shutdown.assert_called_once_with(wait=True)
