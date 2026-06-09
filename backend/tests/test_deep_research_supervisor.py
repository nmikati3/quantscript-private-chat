"""Tests for the deep-research supervisor's context-window handling."""

import asyncio
from unittest.mock import patch

import app.engine.deep_research.deep_research as dr
from app.engine.deep_research.deep_research import SupervisorDecision, supervisor


def _history(n):
    """Build n alternating supervisor history messages."""
    msgs = []
    for i in range(n):
        role = "assistant" if i % 2 == 0 else "user"
        msgs.append({"role": role, "content": f"msg-{i}"})
    return msgs


def test_supervisor_retries_and_trims_on_token_limit():
    history = _history(8)
    decision = SupervisorDecision(reflection="ok", is_complete=True, research_topic="")

    seen_lengths = []

    def fake_structured(_model, messages, **kwargs):
        seen_lengths.append(len(messages))
        # Fail until the prompt has been trimmed at least once.
        if len(seen_lengths) < 3:
            raise ValueError("Requested tokens (40000) exceed context window of 32768")
        return decision

    with patch.object(dr, "get_structured_llm_response", side_effect=fake_structured):
        result = asyncio.run(supervisor(history, "What is X?"))

    assert result is decision
    # It retried (called more than once) and each retry sent fewer messages.
    assert len(seen_lengths) >= 3
    assert seen_lengths[-1] < seen_lengths[0]


def test_supervisor_reraises_non_token_errors():
    def fake_structured(_model, messages, **kwargs):
        raise ValueError("some unrelated parsing failure")

    with patch.object(dr, "get_structured_llm_response", side_effect=fake_structured):
        try:
            asyncio.run(supervisor(_history(4), "What is X?"))
        except ValueError as e:
            assert "unrelated" in str(e)
        else:
            raise AssertionError("expected the non-token error to propagate")


def test_supervisor_gives_up_when_history_empty_but_still_too_large():
    # Token errors persist even after the whole history is dropped: the call must
    # eventually surface the error rather than loop forever.
    def fake_structured(_model, messages, **kwargs):
        raise ValueError("context length exceeded")

    with patch.object(dr, "get_structured_llm_response", side_effect=fake_structured):
        try:
            asyncio.run(supervisor(_history(3), "What is X?"))
        except ValueError as e:
            assert "context length" in str(e)
        else:
            raise AssertionError("expected the token error to propagate once history is empty")
