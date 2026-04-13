#!/usr/bin/env python3
"""GATE-02 smoke: X OAuth 1.0a User Context read-only auth check.

Standalone operator tool per Phase 3 CONTEXT D-01. Invoked via:

    uv run python scripts/smoke_x_auth.py

Calls ``tweepy.Client.get_me()`` (strictly read-only) and prints one JSON
line on stdout with the authenticated user's username, id, and name. Exits
non-zero if the username is anything other than ``ByteRelevant``.

Security (T-03-01): all four X secrets are ``SecretStr`` in Settings;
``.get_secret_value()`` is invoked inline at the ``tweepy.Client`` call site
and never bound to a named variable.
"""

from __future__ import annotations

import argparse
import json
import sys

import tweepy

from tech_news_synth.config import load_settings


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="smoke_x_auth",
        description=(
            "GATE-02 smoke: call tweepy.Client.get_me() via OAuth 1.0a User "
            "Context and print {'username', 'id', 'name'} as one JSON line. "
            "Exits 1 if the authenticated username is not 'ByteRelevant'."
        ),
    )
    return parser.parse_args()


def main() -> None:
    _parse_args()
    settings = load_settings()

    print("[smoke_x_auth] calling tweepy.Client.get_me()...", file=sys.stderr)

    client = tweepy.Client(
        consumer_key=settings.x_consumer_key.get_secret_value(),
        consumer_secret=settings.x_consumer_secret.get_secret_value(),
        access_token=settings.x_access_token.get_secret_value(),
        access_token_secret=settings.x_access_token_secret.get_secret_value(),
    )
    response = client.get_me()

    username = response.data.username
    user_id = str(response.data.id)
    name = response.data.name

    print(json.dumps({"username": username, "id": user_id, "name": name}, ensure_ascii=False))

    if username != "ByteRelevant":
        print(
            f"WARNING: expected @ByteRelevant, got @{username}",
            file=sys.stderr,
        )
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
