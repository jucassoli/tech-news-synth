"""Unit tests for ``synth.hashtags`` — D-11, SYNTH-05, T-06-05, T-06-08."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from tech_news_synth.synth.hashtags import (
    HashtagAllowlist,
    load_hashtag_allowlist,
    select_hashtags,
)

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "synth" / "hashtags.yaml"


# ---------------------------------------------------------------------------
# load_hashtag_allowlist
# ---------------------------------------------------------------------------
def test_load_allowlist_from_fixture():
    allowlist = load_hashtag_allowlist(FIXTURE)
    assert isinstance(allowlist, HashtagAllowlist)
    assert "ai" in allowlist.topics
    assert "#IA" in allowlist.topics["ai"]
    assert allowlist.default == ["#tech"]


def test_load_allowlist_missing_default(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("topics:\n  ai: ['#IA']\n", encoding="utf-8")
    with pytest.raises(ValidationError):
        load_hashtag_allowlist(bad)


def test_load_allowlist_empty_default(tmp_path):
    bad = tmp_path / "empty_default.yaml"
    bad.write_text("topics:\n  ai: ['#IA']\ndefault: []\n", encoding="utf-8")
    with pytest.raises(ValidationError):
        load_hashtag_allowlist(bad)


def test_load_allowlist_non_mapping(tmp_path):
    bad = tmp_path / "list.yaml"
    bad.write_text("- foo\n- bar\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_hashtag_allowlist(bad)


# ---------------------------------------------------------------------------
# select_hashtags
# ---------------------------------------------------------------------------
def _allowlist() -> HashtagAllowlist:
    return load_hashtag_allowlist(FIXTURE)


def test_select_matches_apple_and_chips():
    terms = {"apple": 0.9, "m5": 0.5, "chips": 0.3}
    result = select_hashtags(terms, _allowlist(), max_tags=2)
    # max_tags=2, order by weight — apple first, then chips match
    assert result == ["#Apple", "#Semicondutores"]


def test_select_returns_default_when_no_match():
    terms = {"unrelated": 1.0, "xyz": 0.5}
    result = select_hashtags(terms, _allowlist(), max_tags=2)
    assert result == ["#tech"]


def test_select_empty_terms_returns_default():
    assert select_hashtags({}, _allowlist(), max_tags=2) == ["#tech"]


def test_select_caps_at_max_tags():
    # Multiple matching topics, but cap should apply.
    terms = {"apple": 0.9, "security": 0.8, "ai": 0.7, "chips": 0.5}
    result = select_hashtags(terms, _allowlist(), max_tags=2)
    assert len(result) == 2


def test_select_deduplicates_same_tag_from_different_terms():
    # Two terms that both slug-match "ai" → should yield single #IA.
    terms = {"ai": 0.9, "ai-bot": 0.5}
    result = select_hashtags(terms, _allowlist(), max_tags=2)
    # #IA must not appear twice
    assert result.count("#IA") == 1


def test_select_never_returns_out_of_allowlist_tag():
    allowlist = _allowlist()
    allowed = set(sum(allowlist.topics.values(), [])) | set(allowlist.default)
    terms = {"apple": 0.9, "security": 0.8, "chips": 0.7}
    result = select_hashtags(terms, allowlist, max_tags=2)
    for tag in result:
        assert tag in allowed
