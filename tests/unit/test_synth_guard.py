"""Unit tests for assistant-style output rejection in ``synth.guard``."""

from __future__ import annotations

from tech_news_synth.synth.guard import explain_invalid_body


def test_rejects_assistant_preamble_entendi():
    text = "Entendi. Estou pronto para reescrever o texto."
    assert explain_invalid_body(text) == "assistant_preamble"


def test_rejects_meta_summary_intro():
    text = "Com base no artigo fornecido, aqui está a síntese: novidade no WhatsApp."
    assert explain_invalid_body(text) == "assistant_preamble"


def test_rejects_request_for_more_context():
    text = (
        "Por favor, compartilhe:\n"
        "- O texto anterior\n"
        "- Os artigos-fonte com as informações"
    )
    assert explain_invalid_body(text) in {"assistant_preamble", "assistant_meta_request"}


def test_allows_normal_publishable_text():
    text = "Ferramenta CLI para WhatsApp permite sincronizar e buscar mensagens no terminal."
    assert explain_invalid_body(text) is None
