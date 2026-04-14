"""Phase 8 OPS-04 — source-health CLI unit tests.

Exercises argparse wiring + stdout/stderr formatting at the CLI layer.
Session + helpers are mocked — real DB coverage lives in the integration
counterpart.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from tech_news_synth.cli import source_health


def _row(
    *,
    name: str = "techcrunch",
    last_fetched_at=None,
    last_status: str | None = "ok",
    consecutive_failures: int = 0,
    disabled_at=None,
):
    return SimpleNamespace(
        name=name,
        last_fetched_at=last_fetched_at,
        last_status=last_status,
        consecutive_failures=consecutive_failures,
        disabled_at=disabled_at,
    )


@pytest.fixture(autouse=True)
def _mock_boot(mocker):
    """Skip real settings/engine bootstrapping."""
    mocker.patch("tech_news_synth.cli.source_health.load_settings", return_value=mocker.MagicMock())
    mocker.patch("tech_news_synth.cli.source_health.configure_logging")
    mocker.patch("tech_news_synth.cli.source_health.init_engine")

    session = mocker.MagicMock()
    session.__enter__ = lambda self: self
    session.__exit__ = lambda self, *a: None
    mocker.patch("tech_news_synth.cli.source_health.SessionLocal", return_value=session)
    return session


def test_enable_unknown_exits_1(_mock_boot, mocker, capsys):
    mocker.patch("tech_news_synth.cli.source_health.enable_source", return_value=False)
    rc = source_health.main(["--enable", "nope"])
    assert rc == 1
    captured = capsys.readouterr()
    assert "unknown source" in captured.err
    assert "nope" in captured.err


def test_enable_known_returns_0_and_commits(_mock_boot, mocker):
    enable = mocker.patch("tech_news_synth.cli.source_health.enable_source", return_value=True)
    rc = source_health.main(["--enable", "techcrunch"])
    assert rc == 0
    enable.assert_called_once()
    _mock_boot.commit.assert_called_once()


def test_disable_unknown_exits_1(_mock_boot, mocker, capsys):
    mocker.patch("tech_news_synth.cli.source_health.disable_source", return_value=False)
    rc = source_health.main(["--disable", "nope"])
    assert rc == 1
    assert "unknown source" in capsys.readouterr().err


def test_mutually_exclusive_enable_disable(_mock_boot):
    with pytest.raises(SystemExit) as exc:
        source_health.main(["--enable", "a", "--disable", "b"])
    assert exc.value.code == 2  # argparse usage error


def test_format_table_matches_columns(_mock_boot, mocker, capsys):
    rows = [
        _row(
            name="techcrunch",
            last_fetched_at=datetime(2026, 4, 14, 22, 0, tzinfo=UTC),
            last_status="ok",
            consecutive_failures=0,
            disabled_at=None,
        ),
        _row(
            name="reddit_technology",
            last_fetched_at=datetime(2026, 4, 14, 18, 0, tzinfo=UTC),
            last_status="error:http_403",
            consecutive_failures=3,
            disabled_at=None,
        ),
    ]
    mocker.patch(
        "tech_news_synth.cli.source_health.get_all_source_states", return_value=rows
    )

    rc = source_health.main([])
    assert rc == 0
    out = capsys.readouterr().out
    assert "name" in out and "last_fetched_at" in out and "disabled" in out
    assert "techcrunch" in out
    assert "reddit_technology" in out
    assert "error:http_403" in out
    assert "NO" in out  # disabled column


def test_json_mode_emits_list(_mock_boot, mocker, capsys):
    import json

    rows = [
        _row(
            name="techcrunch",
            last_fetched_at=datetime(2026, 4, 14, 22, 0, tzinfo=UTC),
            last_status="ok",
            consecutive_failures=0,
            disabled_at=None,
        ),
        _row(
            name="verge",
            last_fetched_at=None,
            last_status=None,
            consecutive_failures=0,
            disabled_at=datetime(2026, 4, 10, 0, 0, tzinfo=UTC),
        ),
    ]
    mocker.patch(
        "tech_news_synth.cli.source_health.get_all_source_states", return_value=rows
    )

    rc = source_health.main(["--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert isinstance(payload, list) and len(payload) == 2
    tc = next(p for p in payload if p["name"] == "techcrunch")
    assert tc["last_status"] == "ok"
    assert tc["disabled"] is False
    verge = next(p for p in payload if p["name"] == "verge")
    assert verge["disabled"] is True
    assert verge["last_fetched_at"] is None
