"""Unit tests for official thread composition helpers."""

from __future__ import annotations

from types import SimpleNamespace

from tech_news_synth.synth.thread import (
    CTA,
    choose_thread_parts,
    compose_reply_post,
    compose_root_post,
)


def test_choose_thread_parts_prefers_three_when_multiple_articles():
    one = [SimpleNamespace(id=1)]
    many = [SimpleNamespace(id=1), SimpleNamespace(id=2)]
    assert choose_thread_parts(one) == 2
    assert choose_thread_parts(many) == 3


def test_compose_root_post_includes_cta_and_url():
    text = compose_root_post("Allbirds vendeu a operação de calçados.", "https://example.com/news")
    assert CTA in text
    assert text.endswith("https://example.com/news")


def test_compose_reply_post_reserves_suffix():
    reply = compose_reply_post("Fechamento da notícia.", suffix="#tech")
    assert reply.endswith("#tech")
