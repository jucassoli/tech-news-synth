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
    """Boot order (D-01):

    1. ``load_settings`` — fail-fast on bad config (no logging yet, stderr only).
    2. ``configure_logging`` — installs JSON pipeline so subsequent steps log.
    3. ``init_engine`` — module-level engine + SessionLocal singleton.
    4. ``run_migrations`` — ``alembic upgrade head`` (D-01; raises on failure
       so the container exits non-zero).
    5. ``scheduler.run`` — installs signal handlers and blocks.
    """
    from pathlib import Path

    from tech_news_synth.config import load_settings
    from tech_news_synth.db.migrations import run_migrations
    from tech_news_synth.db.session import init_engine
    from tech_news_synth.ingest.sources_config import load_sources_config
    from tech_news_synth.logging import configure_logging, get_logger
    from tech_news_synth.scheduler import run
    from tech_news_synth.synth.hashtags import load_hashtag_allowlist

    try:
        settings = load_settings()
    except ValidationError as e:
        print(f"Configuration error:\n{e}", file=sys.stderr)
        return 2

    configure_logging(settings)
    init_engine(settings)
    run_migrations()

    # INGEST-01: fail-fast sources.yaml validation at boot.
    try:
        sources_config = load_sources_config(Path(settings.sources_config_path))
    except Exception:
        # load_sources_config already printed a readable error to stderr.
        return 2

    # T-06-15: fail-fast hashtags.yaml validation at boot.
    try:
        hashtag_allowlist = load_hashtag_allowlist(Path(settings.hashtags_config_path))
    except Exception as e:
        print(f"hashtags.yaml error ({settings.hashtags_config_path}):\n{e}", file=sys.stderr)
        return 2
    log = get_logger(__name__)
    log.info(
        "hashtag_allowlist_loaded",
        topics=len(hashtag_allowlist.topics),
        default=hashtag_allowlist.default,
    )

    run(settings, sources_config=sources_config, hashtag_allowlist=hashtag_allowlist)
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
