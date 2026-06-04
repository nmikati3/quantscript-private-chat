"""Tests for the deterministic (non-function-calling) researcher loop."""

import asyncio
from unittest.mock import patch

import pytest

import app.engine.deep_research.deep_research as dr
from app.engine.deep_research.deep_research import (
    ResearcherDecision,
    researcher_workflow,
)


# ---------------------------------------------------------------------------
# ResearcherDecision schema coercion
# ---------------------------------------------------------------------------

def test_decision_infers_search_when_query_present_but_action_missing():
    d = ResearcherDecision.model_validate({"reasoning": "need more", "search_query": "lvmh revenue"})
    assert d.action == "search"
    assert d.search_query == "lvmh revenue"


def test_decision_infers_complete_when_no_query():
    d = ResearcherDecision.model_validate({"reasoning": "have enough"})
    assert d.action == "complete"
    assert d.search_query == ""


def test_decision_accepts_alternate_reflection_key():
    d = ResearcherDecision.model_validate({"reflection": "thinking", "action": "complete"})
    assert d.reasoning == "thinking"


def test_decision_requires_reasoning():
    with pytest.raises(Exception):
        ResearcherDecision.model_validate({"action": "complete"})


# ---------------------------------------------------------------------------
# researcher_workflow loop
# ---------------------------------------------------------------------------

def _run(coro):
    return asyncio.run(coro)


def test_researcher_workflow_runs_searches_then_completes():
    # First decision: search; second decision: complete.
    decisions = [
        ResearcherDecision(reasoning="start", action="search", search_query="lvmh 2024 revenue"),
        ResearcherDecision(reasoning="enough now", action="complete", search_query=""),
    ]
    articles = [{"title": "LVMH", "url": "http://lvmh.com/ar", "content": "Revenue 84.7B"}]

    async def fake_search(query, n=5):
        return articles

    with patch.object(dr, "get_structured_llm_response", side_effect=decisions), \
         patch.object(dr, "web_search_and_fetch_articles_async", side_effect=fake_search), \
         patch.object(dr, "get_llm_response_with_tools", return_value={"content": "COMPRESSED SUMMARY of findings about revenue " * 5}):
        result = _run(researcher_workflow("LVMH revenue", progress_callback=None))

    # One search ran; its source was captured structurally.
    assert result["sources"] == [{"title": "LVMH", "url": "http://lvmh.com/ar"}]
    assert "COMPRESSED SUMMARY" in result["compressed_research"]
    # Raw notes carry the transcript including the actual article content.
    assert "84.7B" in "\n".join(result["raw_notes"])


def test_researcher_workflow_stops_on_repeated_query():
    # Model keeps asking for the same query; loop must not spin forever.
    same = ResearcherDecision(reasoning="again", action="search", search_query="dup query")
    calls = {"n": 0}

    async def fake_search(query, n=5):
        calls["n"] += 1
        return [{"title": "T", "url": "http://x.com/1", "content": "c"}]

    with patch.object(dr, "get_structured_llm_response", return_value=same), \
         patch.object(dr, "web_search_and_fetch_articles_async", side_effect=fake_search), \
         patch.object(dr, "get_llm_response_with_tools", return_value={"content": "x" * 300}):
        result = _run(researcher_workflow("topic", progress_callback=None))

    # The duplicate query is executed at most once.
    assert calls["n"] == 1
    assert result["sources"] == [{"title": "T", "url": "http://x.com/1"}]


def test_researcher_workflow_handles_search_failure_gracefully():
    decisions = [
        ResearcherDecision(reasoning="go", action="search", search_query="q1"),
        ResearcherDecision(reasoning="done", action="complete", search_query=""),
    ]

    async def boom(query, n=5):
        raise RuntimeError("network down")

    with patch.object(dr, "get_structured_llm_response", side_effect=decisions), \
         patch.object(dr, "web_search_and_fetch_articles_async", side_effect=boom), \
         patch.object(dr, "get_llm_response_with_tools", return_value={"content": "y" * 300}):
        result = _run(researcher_workflow("topic", progress_callback=None))

    # No sources, but the workflow still completes and records the failure.
    assert result["sources"] == []
    assert "search failed" in "\n".join(result["raw_notes"])
