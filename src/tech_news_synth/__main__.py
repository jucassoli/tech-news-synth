"""Entrypoint: ``python -m tech_news_synth [subcommand]`` (D-05 / D-06).

Default (no subcommand) → boots the APScheduler. Subcommands ``replay``,
``post-now``, ``source-health`` dispatch to stubs that are implemented in
Phase 8 (OPS-02..04).

On ``ValidationError`` from ``load_settings`` we print to stderr (no logging
yet — logging hasn't been configured) and exit with code 2 (PITFALLS #5).
"""

from __future__ import annotations

import argparse
import sys

from pydantic import ValidationError


def _dispatch_scheduler() -> int:
    from tech_news_synth.config import load_settings
    from tech_news_synth.scheduler import run

    try:
        settings = load_settings()
    except ValidationError as e:
        print(f"Configuration error:\n{e}", file=sys.stderr)
        return 2

    run(settings)
    return 0


def _dispatch_cli(subcommand: str, argv: list[str]) -> int:
    if subcommand == "replay":
        from tech_news_synth.cli import replay

        return replay.main(argv)
    if subcommand == "post-now":
        from tech_news_synth.cli import post_now

        return post_now.main(argv)
    if subcommand == "source-health":
        from tech_news_synth.cli import source_health

        return source_health.main(argv)
    print(f"Unknown subcommand: {subcommand}", file=sys.stderr)
    return 2


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    parser = argparse.ArgumentParser(
        prog="python -m tech_news_synth",
        description="tech-news-synth — autonomous tech-news synthesizer for @ByteRelevant",
    )
    sub = parser.add_subparsers(dest="subcommand")
    sub.add_parser("replay", help="Re-run synthesis on a past cycle (Phase 8)")
    sub.add_parser("post-now", help="Force an off-cadence cycle (Phase 8)")
    sub.add_parser("source-health", help="Show per-source fetch status (Phase 8)")

    args, rest = parser.parse_known_args(argv)
    if args.subcommand is None:
        return _dispatch_scheduler()
    return _dispatch_cli(args.subcommand, rest)


if __name__ == "__main__":
    raise SystemExit(main())
