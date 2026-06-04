"""Tests for structured-LLM JSON parsing and truncation repair."""

import pytest

from app.engine.llm.inference import (
    _parse_llm_structured_payload,
    _repair_truncated_json,
)


def test_parses_clean_json():
    assert _parse_llm_structured_payload('{"a": 1, "b": "x"}') == {"a": 1, "b": "x"}


def test_parses_json_in_code_fence():
    raw = '```json\n{"a": 1}\n```'
    assert _parse_llm_structured_payload(raw) == {"a": 1}


def test_parses_json_with_surrounding_prose():
    raw = 'Sure! Here is the result: {"a": 1} hope that helps'
    assert _parse_llm_structured_payload(raw) == {"a": 1}


def test_repairs_truncation_mid_string():
    # Reflection cut off mid-sentence (no closing quote or brace).
    raw = '{"reflection": "I found several relevant sources about the topic and'
    out = _parse_llm_structured_payload(raw)
    assert out["reflection"].startswith("I found several relevant sources")


def test_repairs_truncation_after_completed_field():
    raw = '{"reflection": "done", "is_complete"'
    out = _parse_llm_structured_payload(raw)
    assert out == {"reflection": "done"}


def test_repairs_truncation_after_colon_with_no_value():
    raw = '{"reflection": "done", "is_complete":'
    out = _parse_llm_structured_payload(raw)
    assert out == {"reflection": "done"}


def test_repairs_truncation_inside_nested_structure():
    raw = '{"reflection": "x", "items": ["a", "b'
    out = _parse_llm_structured_payload(raw)
    assert out["reflection"] == "x"
    assert out["items"][0] == "a"


def test_repair_returns_none_when_nothing_salvageable():
    assert _repair_truncated_json("not json at all") is None


def test_unrecoverable_payload_raises():
    with pytest.raises(ValueError):
        _parse_llm_structured_payload("not json at all")
