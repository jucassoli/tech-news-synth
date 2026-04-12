"""Unit tests for tech_news_synth.ids.new_cycle_id (D-09)."""

from __future__ import annotations

import re

ULID_RE = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")


def test_cycle_id_format_is_crockford_ulid():
    from tech_news_synth.ids import new_cycle_id

    cid = new_cycle_id()
    assert isinstance(cid, str)
    assert len(cid) == 26
    assert ULID_RE.match(cid), f"{cid!r} is not a valid Crockford-base32 ULID"


def test_cycle_ids_are_lexicographically_sortable():
    """python-ulid is monotonic within a ms, so consecutive ids sort in order."""
    import time

    from tech_news_synth.ids import new_cycle_id

    id1 = new_cycle_id()
    time.sleep(0.002)
    id2 = new_cycle_id()
    assert sorted([id2, id1]) == [id1, id2]


def test_cycle_ids_are_unique():
    from tech_news_synth.ids import new_cycle_id

    ids = {new_cycle_id() for _ in range(1000)}
    assert len(ids) == 1000
