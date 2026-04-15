"""Unit tests for ``synth.prompt`` (SYNTH-02/03, T-06-01)."""

from __future__ import annotations

from dataclasses import dataclass

from tech_news_synth.synth.prompt import (
    SUMMARY_TRUNCATE_CHARS,
    build_repair_prompt,
    build_retry_prompt,
    build_system_prompt,
    build_user_prompt,
)


@dataclass
class _A:
    source: str
    title: str
    summary: str | None


# ---------------------------------------------------------------------------
# build_system_prompt — SYNTH-02/03 anchors
# ---------------------------------------------------------------------------
def test_system_prompt_contains_all_keyword_anchors():
    s = build_system_prompt(225)
    for anchor in ("jornalístico", "neutro", "português", "APENAS", "NÃO invente"):
        assert anchor in s, f"missing anchor: {anchor}"


def test_system_prompt_contains_brand_reference():
    assert "ByteRelevant" in build_system_prompt(225)


def test_system_prompt_interpolates_char_budget():
    assert "225" in build_system_prompt(225)
    assert "200" in build_system_prompt(200)


def test_system_prompt_contains_injection_mitigation_clause():
    """T-06-01: prompt injection mitigation clause present."""
    s = build_system_prompt(225)
    assert "Ignore" in s and "instruções" in s


def test_system_prompt_requires_publishable_only_output():
    s = build_system_prompt(225)
    assert "APENAS o texto final publicável" in s


# ---------------------------------------------------------------------------
# build_user_prompt
# ---------------------------------------------------------------------------
def test_user_prompt_has_fonte_titulo_resumo_framing():
    articles = [_A("techcrunch", "Apple M5", "Apple launched the M5 chip.")]
    u = build_user_prompt(articles)
    assert "Fonte:" in u
    assert "Título:" in u
    assert "Resumo:" in u


def test_user_prompt_numbers_articles():
    articles = [
        _A("a", "t1", "s1"),
        _A("b", "t2", "s2"),
    ]
    u = build_user_prompt(articles)
    assert "[1]" in u
    assert "[2]" in u


def test_user_prompt_truncates_long_summaries():
    long_summary = "x" * 2000
    articles = [_A("src", "t", long_summary)]
    u = build_user_prompt(articles)
    # Only the first SUMMARY_TRUNCATE_CHARS chars of the 'x' stream survive.
    x_count = u.count("x")
    assert x_count == SUMMARY_TRUNCATE_CHARS


def test_user_prompt_handles_none_summary():
    articles = [_A("src", "title", None)]
    u = build_user_prompt(articles)
    assert "Resumo:" in u


def test_user_prompt_ends_with_synthesis_instruction():
    articles = [_A("src", "t", "s")]
    u = build_user_prompt(articles)
    assert "Sintetize em 1-2 frases" in u
    assert "somente o post final" in u


# ---------------------------------------------------------------------------
# build_retry_prompt — D-06 suffix
# ---------------------------------------------------------------------------
def test_retry_prompt_contains_actual_len_and_new_budget():
    r = build_retry_prompt(
        "Artigos:\n[1] Fonte: src | Título: t | Resumo: s",
        "algum texto anterior",
        actual_len=260,
        new_budget=225,
    )
    assert "260" in r
    assert "225" in r


def test_retry_prompt_instructs_to_shorten():
    r = build_retry_prompt(
        "Artigos:\n[1] Fonte: src | Título: t | Resumo: s",
        "x",
        actual_len=300,
        new_budget=225,
    )
    # At least one of the shorten verbs must appear.
    assert "Reescreva" in r or "encurte" in r


def test_repair_prompt_demands_final_post_only():
    r = build_repair_prompt(
        "Artigos:\n[1] Fonte: src | Título: t | Resumo: s",
        "Entendi. Estou pronto.",
        "assistant_preamble",
        225,
    )
    assert "SOMENTE o post final" in r
    assert "sem prefácio" in r
    assert "225" in r


def test_retry_prompt_keeps_original_source_context():
    ctx = "Artigos:\n[1] Fonte: reddit | Título: Disney layoffs | Resumo: ..."
    r = build_retry_prompt(ctx, "texto longo", actual_len=320, new_budget=215)
    assert "Contexto factual original" in r
    assert ctx in r


def test_repair_prompt_keeps_original_source_context():
    ctx = "Artigos:\n[1] Fonte: hn | Título: WhatsApp CLI | Resumo: ..."
    r = build_repair_prompt(ctx, "Com base no artigo fornecido", "assistant_preamble", 225)
    assert "Contexto factual original" in r
    assert ctx in r
