"""Cycle ID generation (D-09).

A ULID is a 26-char Crockford-base32 string, time-sortable and
monotonic-within-ms. Downstream components treat it as an opaque string.
"""

from __future__ import annotations

from ulid import ULID


def new_cycle_id() -> str:
    """Return a fresh 26-char Crockford-base32 ULID string."""
    return str(ULID())
