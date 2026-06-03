"""Tests for deep research utility functions."""

import re
from app.engine.deep_research.utils import (
    get_today_str,
    get_buffer_string,
    filter_messages,
    remove_up_to_last_ai_message,
    is_token_limit_exceeded,
    get_all_tools,
    think_tool,
)


class TestGetTodayStr:
    def test_format(self):
        result = get_today_str()
        assert re.match(r"^\d{4}-\d{2}-\d{2}$", result)

    def test_length(self):
        assert len(get_today_str()) == 10


class TestGetBufferString:
    def test_formats_messages(self):
        msgs = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]
        result = get_buffer_string(msgs)
        assert "user: hello" in result
        assert "assistant: hi" in result

    def test_empty_messages(self):
        assert get_buffer_string([]) == ""

    def test_skips_empty_content(self):
        msgs = [{"role": "user", "content": ""}, {"role": "assistant", "content": "hi"}]
        result = get_buffer_string(msgs)
        assert "user:" not in result
        assert "assistant: hi" in result

    def test_missing_keys(self):
        msgs = [{"role": "user"}, {"content": "orphan"}]
        result = get_buffer_string(msgs)
        assert "unknown: orphan" in result


class TestFilterMessages:
    def test_returns_all_when_no_filter(self):
        msgs = [{"role": "user"}, {"role": "assistant"}]
        assert filter_messages(msgs) == msgs

    def test_filters_by_role(self):
        msgs = [
            {"role": "user", "content": "q"},
            {"role": "assistant", "content": "a"},
            {"role": "system", "content": "s"},
        ]
        result = filter_messages(msgs, include_types=["user"])
        assert len(result) == 1
        assert result[0]["role"] == "user"

    def test_ai_alias_for_assistant(self):
        msgs = [{"role": "assistant", "content": "a"}, {"role": "user", "content": "q"}]
        result = filter_messages(msgs, include_types=["ai"])
        assert len(result) == 1
        assert result[0]["role"] == "assistant"

    def test_multiple_types(self):
        msgs = [
            {"role": "user", "content": "q"},
            {"role": "assistant", "content": "a"},
            {"role": "tool", "content": "t"},
        ]
        result = filter_messages(msgs, include_types=["user", "tool"])
        assert len(result) == 2


class TestRemoveUpToLastAiMessage:
    def test_removes_through_last_assistant(self):
        msgs = [
            {"role": "user", "content": "q1"},
            {"role": "assistant", "content": "a1"},
            {"role": "user", "content": "q2"},
            {"role": "assistant", "content": "a2"},
            {"role": "user", "content": "q3"},
        ]
        result = remove_up_to_last_ai_message(msgs)
        # Should keep everything before the last assistant message (exclusive)
        assert len(result) == 3
        assert result[-1]["content"] == "q2"

    def test_no_assistant_returns_all(self):
        msgs = [{"role": "user", "content": "q1"}, {"role": "user", "content": "q2"}]
        result = remove_up_to_last_ai_message(msgs)
        assert result == msgs

    def test_single_assistant(self):
        msgs = [
            {"role": "user", "content": "q1"},
            {"role": "assistant", "content": "a1"},
        ]
        result = remove_up_to_last_ai_message(msgs)
        assert len(result) == 1
        assert result[0]["content"] == "q1"


class TestIsTokenLimitExceeded:
    def test_token_error(self):
        assert is_token_limit_exceeded(Exception("maximum context length exceeded")) is True

    def test_too_many_tokens(self):
        assert is_token_limit_exceeded(Exception("too many tokens")) is True

    def test_generic_error(self):
        assert is_token_limit_exceeded(Exception("connection refused")) is False

    def test_empty_error(self):
        assert is_token_limit_exceeded(Exception("")) is False


class TestThinkTool:
    def test_returns_formatted_string(self):
        result = think_tool("I need more data")
        assert "Reflection recorded" in result
        assert "I need more data" in result


class TestGetAllTools:
    def test_returns_two_tools(self):
        tools = get_all_tools()
        assert len(tools) == 2

    def test_tool_structure(self):
        tools = get_all_tools()
        for tool in tools:
            assert tool["type"] == "function"
            assert "function" in tool
            assert "name" in tool["function"]
            assert "parameters" in tool["function"]

    def test_tool_names(self):
        tools = get_all_tools()
        names = {t["function"]["name"] for t in tools}
        assert names == {"think_tool", "web_search"}
