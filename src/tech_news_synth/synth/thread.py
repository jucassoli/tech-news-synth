"""Official short-thread composition helpers for ByteRelevant posts."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from tech_news_synth.synth.charcount import weighted_len
from tech_news_synth.synth.client import call_haiku
from tech_news_synth.synth.guard import explain_invalid_body
from tech_news_synth.synth.prompt import build_user_prompt
from tech_news_synth.synth.truncate import word_boundary_truncate

if TYPE_CHECKING:
    import anthropic

    from tech_news_synth.config import Settings
    from tech_news_synth.db.models import Article


CTA = "Siga a thread 🧵👇"


def choose_thread_parts(selected_articles: list[Article]) -> int:
    """Simple editorial rule: single-source fallback gets 2 parts, richer sets get 3."""
    return 3 if len(selected_articles) > 1 else 2


def compose_root_post(body_text: str, source_url: str) -> str:
    """Build the lead post with CTA + source URL for the X card."""
    url_weight = 23
    overhead = weighted_len(CTA) + url_weight + 4  # blank lines + separator spaces
    budget = max(0, 280 - overhead)
    lead = word_boundary_truncate(body_text.strip(), budget).strip()
    return f"{lead}\n\n{CTA}\n\n{source_url}"


def compose_reply_post(text: str, *, suffix: str = "") -> str:
    """Trim a reply safely to the X budget, optionally reserving a suffix."""
    reply = text.strip()
    if suffix:
        reply = f"{reply}\n\n{suffix}"
    if weighted_len(reply) <= 280:
        return reply
    budget = 280 - (weighted_len(suffix) + 2 if suffix else 0)
    body = word_boundary_truncate(text.strip(), max(0, budget)).strip()
    return f"{body}\n\n{suffix}" if suffix else body


def build_thread_system_prompt(parts: int) -> str:
    return (
        "Você escreve threads curtas e jornalísticas para a conta @ByteRelevant no X.\n"
        "Tom: jornalístico, claro, neutro, em português brasileiro.\n"
        "Regras:\n"
        "- Use APENAS as informações das fontes fornecidas.\n"
        "- NÃO invente fatos, datas, nomes ou métricas.\n"
        "- NÃO use markdown, aspas de abertura ou listas.\n"
        "- NÃO peça mais contexto nem descreva o processo.\n"
        "- Retorne APENAS JSON válido.\n"
        f"- Gere exatamente {parts - 1} objetos no array replies.\n"
        "- Cada reply deve soar como continuação natural da thread.\n"
        "- O último reply deve fechar a história explicando por que isso importa.\n"
        '- Formato exato: {"replies":["texto 1","texto 2"]}'
    )


def _build_thread_prompt(selected: list[Article], lead_body: str, parts: int) -> str:
    return (
        f"{build_user_prompt(selected)}\n\n"
        f"Lead já usado no primeiro post:\n{lead_body}\n\n"
        f"Gere os próximos {parts - 1} posts da thread. "
        "Os replies devem aprofundar a notícia sem repetir a abertura. "
        "Cada reply precisa caber sozinho em um post do X. "
        "Não inclua URL, hashtag nem CTA."
    )


def _clean_json_payload(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.startswith("json"):
            cleaned = cleaned[4:].strip()
    if "{" in cleaned and "}" in cleaned:
        cleaned = cleaned[cleaned.find("{") : cleaned.rfind("}") + 1]
    return cleaned


def _parse_replies_payload(text: str, parts: int) -> list[str]:
    data = json.loads(_clean_json_payload(text))
    replies = data["replies"]
    if not isinstance(replies, list) or len(replies) != parts - 1:
        raise ValueError(f"invalid replies payload from model: {text}")

    cleaned: list[str] = []
    for reply in replies:
        reply_text = str(reply).strip()
        invalid_reason = explain_invalid_body(reply_text)
        if invalid_reason is not None:
            raise ValueError(f"invalid reply body from model: {invalid_reason}")
        cleaned.append(reply_text)
    return cleaned


def build_thread_repair_prompt(
    selected: list[Article],
    lead_body: str,
    parts: int,
    previous_text: str,
    invalid_reason: str,
) -> str:
    return (
        f"{_build_thread_prompt(selected, lead_body, parts)}\n\n"
        f"A resposta anterior não estava em JSON publicável ({invalid_reason}). "
        "Retorne SOMENTE JSON válido no formato pedido, sem markdown, sem "
        "explicações e sem texto fora do JSON.\n\n"
        f"Resposta anterior:\n{previous_text}"
    )


def generate_thread_replies(
    *,
    anthropic_client: anthropic.Anthropic,
    settings: Settings,
    selected: list[Article],
    lead_body: str,
    parts: int,
) -> tuple[list[str], int, int]:
    """Generate 1-2 ordered thread replies and return tokens consumed."""
    system = build_thread_system_prompt(parts)
    prompt = _build_thread_prompt(selected, lead_body, parts)
    total_in = 0
    total_out = 0
    current_prompt = prompt
    max_attempts = settings.synthesis_max_retries + 1
    last_error = "unknown replies failure"

    for _attempt in range(1, max_attempts + 1):
        text, in_tok, out_tok = call_haiku(
            anthropic_client,
            system,
            current_prompt,
            settings.synthesis_max_tokens * 2,
        )
        total_in += in_tok
        total_out += out_tok
        try:
            replies = _parse_replies_payload(text, parts)
            return replies, total_in, total_out
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            last_error = str(exc)
            current_prompt = build_thread_repair_prompt(
                selected,
                lead_body,
                parts,
                text,
                last_error,
            )

    raise ValueError(
        "thread replies generation failed after "
        f"{max_attempts} attempts: {last_error}"
    )


__all__ = [
    "CTA",
    "build_thread_repair_prompt",
    "build_thread_system_prompt",
    "choose_thread_parts",
    "compose_reply_post",
    "compose_root_post",
    "generate_thread_replies",
]
