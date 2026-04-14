"""Unit tests for synth.client.call_haiku + synth.pricing + synth.models.

Covers SYNTH-01 (model id literal + max_tokens), SYNTH-07 (pricing
constants reachable), T-06-03 (literal model id), T-06-02 (no extra
content in messages), and anthropic error propagation.
"""

from __future__ import annotations

from types import SimpleNamespace

import anthropic
import pytest

from tech_news_synth.synth.client import call_haiku
from tech_news_synth.synth.models import SynthesisResult
from tech_news_synth.synth.pricing import (
    HAIKU_INPUT_USD_PER_MTOK,
    HAIKU_OUTPUT_USD_PER_MTOK,
    MODEL_ID,
    compute_cost_usd,
)


# ---------------------------------------------------------------------------
# pricing — T-06-03 literal model id; SYNTH-07 cost math
# ---------------------------------------------------------------------------
def test_model_id_is_literal_claude_haiku_4_5():
    assert MODEL_ID == "claude-haiku-4-5"


def test_pricing_constants():
    assert HAIKU_INPUT_USD_PER_MTOK == 1.00
    assert HAIKU_OUTPUT_USD_PER_MTOK == 5.00


def test_compute_cost_1M_input():
    assert compute_cost_usd(1_000_000, 0) == pytest.approx(1.00)


def test_compute_cost_1M_output():
    assert compute_cost_usd(0, 1_000_000) == pytest.approx(5.00)


def test_compute_cost_mixed():
    expected = (500 / 1_000_000) * 1.00 + (300 / 1_000_000) * 5.00
    assert compute_cost_usd(500, 300) == pytest.approx(expected)


# ---------------------------------------------------------------------------
# SynthesisResult
# ---------------------------------------------------------------------------
def _sr_kwargs() -> dict:
    return dict(
        text="body url #tag",
        body_text="body",
        hashtags=["#tag"],
        source_url="url",
        attempts=1,
        final_method="completed",
        input_tokens=100,
        output_tokens=50,
        cost_usd=0.0001,
        post_id=None,
        status="pending",
        counts_patch={},
    )


def test_synthesis_result_frozen():
    r = SynthesisResult(**_sr_kwargs())
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        r.text = "other"  # type: ignore[misc]


def test_synthesis_result_status_literal_restrictions():
    kw = _sr_kwargs()
    kw["status"] = "invalid"
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        SynthesisResult(**kw)


def test_synthesis_result_final_method_literal_restrictions():
    kw = _sr_kwargs()
    kw["final_method"] = "bogus"
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        SynthesisResult(**kw)


# ---------------------------------------------------------------------------
# call_haiku — SDK wrapper
# ---------------------------------------------------------------------------
def _make_mock_client(mocker, text="olá", input_tokens=100, output_tokens=50):
    client = mocker.Mock(spec=anthropic.Anthropic)
    response = SimpleNamespace(
        content=[SimpleNamespace(text=text)],
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
    )
    client.messages = mocker.Mock()
    client.messages.create = mocker.Mock(return_value=response)
    return client


def test_call_haiku_returns_text_and_tokens(mocker):
    client = _make_mock_client(mocker, text="resposta", input_tokens=120, output_tokens=40)
    text, in_tok, out_tok = call_haiku(client, system="sys", user_prompt="user", max_tokens=150)
    assert text == "resposta"
    assert in_tok == 120
    assert out_tok == 40


def test_call_haiku_invokes_sdk_with_exact_kwargs(mocker):
    client = _make_mock_client(mocker)
    call_haiku(client, system="sys_prompt", user_prompt="user_prompt", max_tokens=150)
    kwargs = client.messages.create.call_args.kwargs
    assert kwargs == {
        "model": "claude-haiku-4-5",
        "max_tokens": 150,
        "system": "sys_prompt",
        "messages": [{"role": "user", "content": "user_prompt"}],
    }


def test_call_haiku_threads_max_tokens(mocker):
    client = _make_mock_client(mocker)
    call_haiku(client, system="s", user_prompt="u", max_tokens=300)
    assert client.messages.create.call_args.kwargs["max_tokens"] == 300


def test_call_haiku_does_not_leak_extra_content(mocker):
    """T-06-02: only the single passed-in user prompt ends up in messages."""
    client = _make_mock_client(mocker)
    secret_text = "TOP SECRET USER CONTENT"
    call_haiku(client, system="s", user_prompt=secret_text, max_tokens=150)
    msgs = client.messages.create.call_args.kwargs["messages"]
    assert len(msgs) == 1
    assert msgs[0]["content"] == secret_text
    # No extra entries with, e.g., full article bodies.


def test_call_haiku_propagates_api_error(mocker):
    """Exceptions from the SDK must NOT be swallowed (cycle-level isolation)."""
    client = mocker.Mock(spec=anthropic.Anthropic)
    client.messages = mocker.Mock()
    client.messages.create = mocker.Mock(
        side_effect=anthropic.APIError(
            message="boom",
            request=mocker.Mock(),
            body=None,
        )
    )
    with pytest.raises(anthropic.APIError):
        call_haiku(client, system="s", user_prompt="u", max_tokens=150)
