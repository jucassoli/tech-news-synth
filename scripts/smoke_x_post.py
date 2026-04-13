#!/usr/bin/env python3
"""GATE-03 smoke: X live post + delete round-trip with rate-limit header capture.

Standalone operator tool per Phase 3 CONTEXT D-01/D-03/D-04/D-05. Invoked via:

    uv run python scripts/smoke_x_post.py --arm-live-post

This script publishes a REAL tweet to @ByteRelevant (costs real money on the
pay-per-use tier), then deletes it within seconds. The ``--arm-live-post``
flag is a literal-string safety gate (T-03-02): running without the flag
prints a REFUSING warning to stderr and exits 2. No retries on any failure.

CRITICAL: ``return_type=requests.Response`` is REQUIRED on the tweepy.Client
used for ``create_tweet``. Without it tweepy returns a Response namedtuple
with no ``.headers``, and the rate-limit headers (``x-rate-limit-*``,
``x-user-limit-24hour-*``) cannot be read. See tweepy Discussion #1984 and
Phase 3 RESEARCH §3/4.

Security (T-03-01, T-03-05): all four X secrets are materialized inline via
``SecretStr.get_secret_value()`` at the ``tweepy.Client`` constructor and
never printed or logged. The tweet body (D-04) is a fixed template with only
a UTC ISO timestamp interpolated — no user-supplied content (T-03-06).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime

import requests
import tweepy

from tech_news_synth.config import load_settings


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="smoke_x_post",
        description=(
            "GATE-03 smoke: post a disposable tweet to @ByteRelevant and "
            "delete it, capturing rate-limit headers. Requires --arm-live-post."
        ),
    )
    parser.add_argument(
        "--arm-live-post",
        action="store_true",
        help=(
            "REQUIRED to actually post. Without this flag the script exits 2 "
            "with a REFUSING warning. No env-var alias; no aliases."
        ),
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    # D-03 / T-03-02 safety gate — MUST fire before any Settings load / network.
    if not args.arm_live_post:
        print(
            "REFUSING: pass --arm-live-post to actually post a real tweet.",
            file=sys.stderr,
        )
        print(
            "This script publishes a REAL tweet to @ByteRelevant (costs money), "
            "then deletes it.",
            file=sys.stderr,
        )
        sys.exit(2)

    settings = load_settings()

    # D-04: fixed harmless body; only the UTC ISO timestamp is interpolated.
    utc_iso = datetime.now(UTC).isoformat()
    body = (
        f"[gate-smoke {utc_iso}] validating API access — "
        f"this will be deleted within 60s"
    )

    print(
        f"[smoke_x_post] ARMED — posting to @ByteRelevant:\n  {body}",
        file=sys.stderr,
    )

    # CRITICAL: return_type=requests.Response is REQUIRED to expose rate-limit
    # headers on the create_tweet response (tweepy Discussion #1984).
    client = tweepy.Client(
        consumer_key=settings.x_consumer_key.get_secret_value(),
        consumer_secret=settings.x_consumer_secret.get_secret_value(),
        access_token=settings.x_access_token.get_secret_value(),
        access_token_secret=settings.x_access_token_secret.get_secret_value(),
        return_type=requests.Response,  # REQUIRED — see module docstring + RESEARCH §3/4
    )

    # --- POST ---
    posted_at = datetime.now(UTC)
    start = time.monotonic()
    r = client.create_tweet(text=body)
    elapsed_ms = int((time.monotonic() - start) * 1000)

    headers = dict(r.headers)
    payload = r.json()
    tweet_id = payload["data"]["id"]

    # --- DELETE (D-05: no retries; loud manual-cleanup signal on failure) ---
    try:
        client.delete_tweet(tweet_id)
        deleted_at = datetime.now(UTC)
    except Exception as e:
        print(
            f"MANUAL CLEANUP REQUIRED: tweet_id={tweet_id} — "
            f"delete at https://x.com/ByteRelevant/status/{tweet_id}  (error: {e!r})",
            file=sys.stderr,
        )
        sys.exit(1)

    # Filter headers down to rate-limit-relevant ones for the summary.
    rl = {
        k: v
        for k, v in headers.items()
        if k.lower().startswith(("x-rate-limit", "x-user-limit"))
    }

    summary = {
        "tweet_id": tweet_id,
        "posted_at": posted_at.isoformat(),
        "deleted_at": deleted_at.isoformat(),
        "elapsed_ms": elapsed_ms,
        "rate_limit_headers": rl,
        "body": body,
    }
    print(json.dumps(summary, ensure_ascii=False))
    sys.exit(0)


if __name__ == "__main__":
    main()
