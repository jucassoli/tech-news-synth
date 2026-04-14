"""Unit tests for ``synth.prompt.format_final_post`` (SYNTH-06)."""

from __future__ import annotations

from tech_news_synth.synth.prompt import format_final_post


def test_format_with_two_hashtags():
    result = format_final_post(
        "Apple anuncia o chip M5.",
        "https://t.co/abc",
        ["#Apple", "#IA"],
    )
    assert result == "Apple anuncia o chip M5. https://t.co/abc #Apple #IA"


def test_format_with_one_hashtag():
    result = format_final_post("body", "https://t.co/xxx", ["#tech"])
    assert result == "body https://t.co/xxx #tech"


def test_format_with_empty_hashtags_no_trailing_space():
    result = format_final_post("body", "https://t.co/xxx", [])
    assert result == "body https://t.co/xxx"
    assert not result.endswith(" ")


def test_format_preserves_unicode():
    result = format_final_post("ação já", "https://t.co/zzz", ["#IA"])
    assert "ação" in result
    assert result.endswith("#IA")
