"""Phase 8 OPS-02 — replay CLI unit tests.

Covers the three resolution branches (winner, fallback, unresolvable) at the
CLI layer. Session + run_synthesis mocked — real DB coverage in integration.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from tech_news_synth.cli import replay


@pytest.fixture(autouse=True)
def _cli_boot(mocker):
    mocker.patch("tech_news_synth.cli.replay.load_settings", return_value=mocker.MagicMock(
        anthropic_api_key=SimpleNamespace(get_secret_value=lambda: "sk-ant-test"),
        sources_config_path="/dev/null",
        hashtags_config_path="/dev/null",
    ))
    mocker.patch("tech_news_synth.cli.replay.configure_logging")
    mocker.patch("tech_news_synth.cli.replay.init_engine")
    mocker.patch("tech_news_synth.cli.replay.load_sources_config", return_value=mocker.MagicMock())
    mocker.patch(
        "tech_news_synth.cli.replay.load_hashtag_allowlist",
        return_value=mocker.MagicMock(),
    )
    mocker.patch("tech_news_synth.cli.replay.anthropic.Anthropic")

    session = mocker.MagicMock()
    session.__enter__ = lambda self: session
    session.__exit__ = lambda self, *a: None
    mocker.patch("tech_news_synth.cli.replay.SessionLocal", return_value=session)
    return session


def _synth_result(mocker):
    return mocker.MagicMock(
        text="Apple apresentou M5. https://tc.com/a #Apple",
        hashtags=["#Apple"],
        source_url="https://tc.com/a",
        cost_usd=0.00004,
        input_tokens=50,
        output_tokens=10,
        final_method="completed",
    )


def test_replay_unknown_cycle_exits_1(_cli_boot, mocker, capsys):
    """No Post AND no RunLog with fallback_article_id → exit 1."""
    # session.execute(...).scalar_one_or_none() returns None both times.
    _cli_boot.execute.return_value.scalar_one_or_none.return_value = None

    rc = replay.main(["--cycle-id", "BOGUS"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "cycle-id" in err and "BOGUS" in err and "not found" in err


def test_replay_winner_branch_builds_selection(_cli_boot, mocker, capsys):
    post = SimpleNamespace(cluster_id=42, theme_centroid=b"\x00\x01")
    cluster = SimpleNamespace(id=42, member_article_ids=[1, 2, 3])
    # First execute → Post; get() → Cluster
    _cli_boot.execute.return_value.scalar_one_or_none.return_value = post
    _cli_boot.get.return_value = cluster

    synth = mocker.patch(
        "tech_news_synth.cli.replay.run_synthesis", return_value=_synth_result(mocker)
    )

    rc = replay.main(["--cycle-id", "01ABC"])
    assert rc == 0

    # run_synthesis called with persist=False (keyword-only)
    assert synth.call_count == 1
    assert synth.call_args.kwargs.get("persist") is False

    # The selection passed as positional arg index 2 (session, cycle_id, selection)
    sel = synth.call_args.args[2]
    assert sel.winner_cluster_id == 42
    assert sel.winner_article_ids == [1, 2, 3]
    assert sel.fallback_article_id is None

    # rollback called after synthesis (T-08-02)
    _cli_boot.rollback.assert_called_once()

    payload = json.loads(capsys.readouterr().out)
    assert payload["cycle_id"] == "01ABC"
    assert payload["hashtags"] == ["#Apple"]


def test_replay_fallback_branch_reads_run_log_counts(_cli_boot, mocker, capsys):
    """post.cluster_id IS NULL → read fallback_article_id from run_log.counts."""
    post = SimpleNamespace(cluster_id=None, theme_centroid=None)
    runlog = SimpleNamespace(counts={"fallback_article_id": 99})

    # Two execute() calls — first returns Post, second returns RunLog.
    scalars = [post, runlog]

    def _execute(*_a, **_kw):
        result = mocker.MagicMock()
        result.scalar_one_or_none.return_value = scalars.pop(0)
        return result

    _cli_boot.execute.side_effect = _execute

    synth = mocker.patch(
        "tech_news_synth.cli.replay.run_synthesis", return_value=_synth_result(mocker)
    )

    rc = replay.main(["--cycle-id", "01FALL"])
    assert rc == 0
    sel = synth.call_args.args[2]
    assert sel.winner_cluster_id is None
    assert sel.fallback_article_id == 99
    assert synth.call_args.kwargs.get("persist") is False


def test_replay_missing_cycle_id_exits_argparse(_cli_boot):
    with pytest.raises(SystemExit) as exc:
        replay.main([])
    assert exc.value.code == 2


def test_replay_post_exists_but_cluster_dangling_exits_1(_cli_boot, mocker, capsys):
    """Post.cluster_id set but Cluster row missing (deleted) → exit 1."""
    post = SimpleNamespace(cluster_id=42, theme_centroid=b"x")
    _cli_boot.execute.return_value.scalar_one_or_none.return_value = post
    _cli_boot.get.return_value = None  # Cluster not found

    rc = replay.main(["--cycle-id", "01DANGLE"])
    assert rc == 1
    assert "not found" in capsys.readouterr().err
