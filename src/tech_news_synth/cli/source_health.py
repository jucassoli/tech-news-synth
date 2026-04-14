"""``source-health`` CLI (Phase 8 OPS-04 / D-03).

Three modes:

    python -m tech_news_synth source-health                  # aligned text table
    python -m tech_news_synth source-health --json           # machine-readable
    python -m tech_news_synth source-health --enable NAME    # clear disabled_at
    python -m tech_news_synth source-health --disable NAME   # set disabled_at

Enable/disable are mutually exclusive (argparse group). No new deps — stdlib
f-string padding for the text table. Returns exit 1 on unknown NAME.

Never loads sources_config or hashtag_allowlist — unrelated to source state
and avoids an unnecessary fail-fast path for this read-only CLI.
"""

from __future__ import annotations

import argparse
import json
import sys

from tech_news_synth.config import load_settings
from tech_news_synth.db.session import SessionLocal, init_engine
from tech_news_synth.db.source_state import (
    disable_source,
    enable_source,
    get_all_source_states,
)
from tech_news_synth.logging import configure_logging, get_logger

log = get_logger(__name__)


def _format_table(rows) -> str:
    """Render aligned 5-column text table (stdlib f-string padding only)."""
    hdr = (
        f"{'name':<20} {'last_fetched_at':<28} {'last_status':<18} "
        f"{'failures':>8} {'disabled':<8}"
    )
    lines = [hdr]
    for r in rows:
        dis = "YES" if r.disabled_at else "NO"
        lf = r.last_fetched_at.isoformat() if r.last_fetched_at else "—"
        ls = r.last_status or "—"
        lines.append(
            f"{r.name:<20} {lf:<28} {ls:<18} "
            f"{r.consecutive_failures:>8} {dis:<8}"
        )
    return "\n".join(lines)


def _to_json(rows) -> str:
    """Machine-readable JSON payload (list of per-source dicts)."""
    payload = [
        {
            "name": r.name,
            "last_fetched_at": r.last_fetched_at.isoformat()
            if r.last_fetched_at
            else None,
            "last_status": r.last_status,
            "consecutive_failures": r.consecutive_failures,
            "disabled": r.disabled_at is not None,
        }
        for r in rows
    ]
    return json.dumps(payload, ensure_ascii=False)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="source-health")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--enable", metavar="NAME")
    group.add_argument("--disable", metavar="NAME")
    parser.add_argument("--json", dest="as_json", action="store_true")
    args = parser.parse_args(argv)

    settings = load_settings()
    configure_logging(settings)
    init_engine(settings)

    with SessionLocal() as session:
        if args.enable:
            ok = enable_source(session, args.enable)
            if not ok:
                print(f"unknown source: {args.enable}", file=sys.stderr)
                return 1
            session.commit()
            log.info("source_toggled", name=args.enable, action="enable")
            return 0
        if args.disable:
            ok = disable_source(session, args.disable)
            if not ok:
                print(f"unknown source: {args.disable}", file=sys.stderr)
                return 1
            session.commit()
            log.info("source_toggled", name=args.disable, action="disable")
            return 0
        rows = get_all_source_states(session)
        print(_to_json(rows) if args.as_json else _format_table(rows))
        return 0
