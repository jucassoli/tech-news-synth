"""Unit tests for scripts/cutover_verify.py — Jaccard logic + verdict classification.

Pure-function tests over the helpers in the script. The ``compute_verdict``
function that takes a ``Session`` is exercised via a StubSession that returns
pre-canned row fixtures — no live DB required.
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

# Load the script module (lives in scripts/, outside the package).
_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "cutover_verify.py"
_spec = importlib.util.spec_from_file_location("cutover_verify", _SCRIPT_PATH)
assert _spec is not None and _spec.loader is not None
cutover_verify = importlib.util.module_from_spec(_spec)
sys.modules["cutover_verify"] = cutover_verify
_spec.loader.exec_module(cutover_verify)


# ---------------------------------------------------------------------------
# term_jaccard — pure math
# ---------------------------------------------------------------------------
def test_jaccard_identical_terms_returns_1() -> None:
    assert cutover_verify.term_jaccard({"ai": 1.0}, {"ai": 2.0}) == 1.0


def test_jaccard_disjoint_returns_0() -> None:
    assert cutover_verify.term_jaccard({"ai": 1.0}, {"vr": 1.0}) == 0.0


def test_jaccard_half_overlap_returns_expected() -> None:
    # {a,b} vs {a,c} — intersect={a}, union={a,b,c} → 1/3
    assert cutover_verify.term_jaccard({"a": 1, "b": 1}, {"a": 1, "c": 1}) == pytest.approx(1 / 3)


def test_jaccard_empty_returns_0() -> None:
    assert cutover_verify.term_jaccard({}, {"a": 1}) == 0.0
    assert cutover_verify.term_jaccard({"a": 1}, {}) == 0.0
    assert cutover_verify.term_jaccard({}, {}) == 0.0


# ---------------------------------------------------------------------------
# StubSession — mimics session.execute(...).scalar_one() / .all()
# ---------------------------------------------------------------------------
class _StubResult:
    def __init__(self, rows: list[Any] | None = None, scalar: Any = None) -> None:
        self._rows = rows or []
        self._scalar = scalar

    def scalar_one(self) -> Any:
        return self._scalar

    def all(self) -> list[Any]:
        return self._rows


class StubSession:
    """Queue-ordered stub: each ``execute`` call pops the next pre-canned result.

    The script's ``compute_verdict`` issues exactly 3 queries in order:
      1. COUNT posts (24h window)                  → scalar
      2. SELECT post rows joined to clusters       → all()
      3. SUM cost_usd (24h)                        → scalar
    """

    def __init__(self, posted_count: int, rows: list[tuple], cost_sum: Any) -> None:
        self._queue: list[_StubResult] = [
            _StubResult(scalar=posted_count),
            _StubResult(rows=rows),
            _StubResult(scalar=cost_sum),
        ]

    def execute(self, _stmt: Any) -> _StubResult:
        return self._queue.pop(0)


def _row(
    post_id: int, posted_at: datetime, cluster_id: int | None, terms: dict | None
) -> tuple[int, datetime, int | None, dict | None]:
    return (post_id, posted_at, cluster_id, terms)


# ---------------------------------------------------------------------------
# compute_verdict — scenario tests
# ---------------------------------------------------------------------------
def test_verdict_go_clean_cutover() -> None:
    since = datetime(2026, 4, 15, 0, 0, tzinfo=UTC)
    rows = [
        _row(1, since + timedelta(hours=1), 10, {"ai": 1, "chip": 1, "nvidia": 1}),
        _row(2, since + timedelta(hours=3), 11, {"ev": 1, "tesla": 1, "battery": 1}),
        _row(3, since + timedelta(hours=5), 12, {"crypto": 1, "sec": 1, "btc": 1}),
    ]
    session = StubSession(posted_count=12, rows=rows, cost_sum=Decimal("0.40"))
    result = cutover_verify.compute_verdict(since, 0.5, 2.0, session)
    assert result["verdict"] == "GO"
    assert result["count_ok"] is True
    assert result["dups_ok"] is True
    assert result["cost_ok"] is True
    assert result["jaccard_suspects"] == []


def test_verdict_no_go_low_count() -> None:
    since = datetime(2026, 4, 15, 0, 0, tzinfo=UTC)
    session = StubSession(posted_count=10, rows=[], cost_sum=Decimal("0.20"))
    result = cutover_verify.compute_verdict(since, 0.5, 2.0, session)
    assert result["verdict"] == "NO-GO"
    assert result["count_ok"] is False


def test_verdict_no_go_dup_found() -> None:
    since = datetime(2026, 4, 15, 0, 0, tzinfo=UTC)
    # Two posts sharing 3/4 terms → Jaccard = 3/5 = 0.6 ≥ 0.5.
    rows = [
        _row(
            1,
            since + timedelta(hours=1),
            10,
            {"ai": 1, "chip": 1, "nvidia": 1, "gpu": 1},
        ),
        _row(
            2,
            since + timedelta(hours=3),
            11,
            {"ai": 1, "chip": 1, "nvidia": 1, "tpu": 1},
        ),
        _row(3, since + timedelta(hours=5), 12, {"unrelated": 1}),
    ]
    session = StubSession(posted_count=12, rows=rows, cost_sum=Decimal("0.40"))
    result = cutover_verify.compute_verdict(since, 0.5, 2.0, session)
    assert result["verdict"] == "NO-GO"
    assert result["dups_ok"] is False
    assert len(result["jaccard_suspects"]) == 1
    suspect = result["jaccard_suspects"][0]
    assert suspect["post_a"] == 1
    assert suspect["post_b"] == 2
    assert suspect["jaccard"] >= 0.5


def test_verdict_no_go_cost_exceeded() -> None:
    since = datetime(2026, 4, 15, 0, 0, tzinfo=UTC)
    # Cost $0.80 > 2 × baseline ($0.3612) = $0.7224.
    session = StubSession(posted_count=12, rows=[], cost_sum=Decimal("0.80"))
    result = cutover_verify.compute_verdict(since, 0.5, 2.0, session)
    assert result["verdict"] == "NO-GO"
    assert result["cost_ok"] is False


def test_jaccard_flags_ge_0_5_boundary() -> None:
    # 2/3 = 0.667 ≥ 0.5 — must flag.
    since = datetime(2026, 4, 15, tzinfo=UTC)
    rows = [
        _row(1, since + timedelta(hours=1), 10, {"a": 1, "b": 1}),
        _row(2, since + timedelta(hours=2), 11, {"a": 1, "b": 1, "c": 1}),
    ]
    session = StubSession(posted_count=12, rows=rows, cost_sum=Decimal("0.30"))
    result = cutover_verify.compute_verdict(since, 0.5, 2.0, session)
    assert len(result["jaccard_suspects"]) == 1


def test_jaccard_below_threshold_does_not_flag() -> None:
    # {a,b} vs {c,d}: jaccard = 0 < 0.5 — must not flag.
    since = datetime(2026, 4, 15, tzinfo=UTC)
    rows = [
        _row(1, since + timedelta(hours=1), 10, {"a": 1, "b": 1}),
        _row(2, since + timedelta(hours=2), 11, {"c": 1, "d": 1}),
    ]
    session = StubSession(posted_count=12, rows=rows, cost_sum=Decimal("0.30"))
    result = cutover_verify.compute_verdict(since, 0.5, 2.0, session)
    assert len(result["jaccard_suspects"]) == 0


# ---------------------------------------------------------------------------
# render_report — markdown smoke + no-secrets invariant (T-08-08)
# ---------------------------------------------------------------------------
def test_render_report_contains_all_sections() -> None:
    since = datetime(2026, 4, 15, tzinfo=UTC)
    session = StubSession(posted_count=12, rows=[], cost_sum=Decimal("0.40"))
    result = cutover_verify.compute_verdict(since, 0.5, 2.0, session)
    md = cutover_verify.render_report(result)
    assert "Cutover verification" in md
    assert "Verdict" in md
    assert "Post count" in md
    assert "Jaccard" in md
    assert "Cost" in md
    assert "GO" in md  # verdict line


def test_render_report_no_settings_dump() -> None:
    """T-08-08 / Pitfall 5: render_report must never include anything that
    looks like a SecretStr, API key, DB password, or Settings dump.
    """
    since = datetime(2026, 4, 15, tzinfo=UTC)
    session = StubSession(posted_count=12, rows=[], cost_sum=Decimal("0.40"))
    result = cutover_verify.compute_verdict(since, 0.5, 2.0, session)
    md = cutover_verify.render_report(result)
    forbidden = [
        "sk-ant-",
        "ANTHROPIC_API_KEY",
        "X_CONSUMER_KEY",
        "X_CONSUMER_SECRET",
        "X_ACCESS_TOKEN",
        "POSTGRES_PASSWORD",
        "postgresql+psycopg",
        "SecretStr",
        "database_url",
    ]
    for needle in forbidden:
        assert needle not in md, f"render_report leaked {needle!r} into report"


def test_render_report_suspect_table_when_dups_present() -> None:
    since = datetime(2026, 4, 15, tzinfo=UTC)
    rows = [
        _row(1, since + timedelta(hours=1), 10, {"a": 1, "b": 1, "c": 1}),
        _row(2, since + timedelta(hours=2), 11, {"a": 1, "b": 1, "c": 1}),
    ]
    session = StubSession(posted_count=12, rows=rows, cost_sum=Decimal("0.30"))
    result = cutover_verify.compute_verdict(since, 0.5, 2.0, session)
    md = cutover_verify.render_report(result)
    assert "post_a" in md or "Post A" in md or "| 1 |" in md
    assert "NO-GO" in md
