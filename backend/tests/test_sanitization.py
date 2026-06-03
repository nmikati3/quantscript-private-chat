"""Tests for app.core.sanitization — pure functions, no heavy deps needed."""

from app.core.sanitization import (
    sanitize_user_input,
    sanitize_messages,
)


# ── sanitize_user_input ────────────────────────────────────────────────────

class TestSanitizeUserInput:
    def test_empty_string(self):
        assert sanitize_user_input("") == ""

    def test_none(self):
        assert sanitize_user_input(None) == ""

    def test_non_string(self):
        assert sanitize_user_input(42) == ""

    def test_normal_text_passes_through(self):
        assert sanitize_user_input("Hello, world!") == "Hello, world!"

    def test_unicode_preserved(self):
        assert sanitize_user_input("Héllo 中文 🌍") == "Héllo 中文 🌍"

    def test_control_chars_removed(self):
        result = sanitize_user_input("Hello\x00\x01\x02World")
        assert result == "HelloWorld"

    def test_tab_and_newline_preserved(self):
        result = sanitize_user_input("line1\nline2\ttab")
        assert "\n" in result
        assert "\t" in result

    def test_script_tags_removed(self):
        result = sanitize_user_input("before<script>alert('xss')</script>after")
        assert "<script" not in result
        assert "beforeafter" == result

    def test_iframe_tags_removed(self):
        result = sanitize_user_input("ok<iframe src='x'></iframe>ok")
        assert "<iframe" not in result

    def test_object_tags_removed(self):
        result = sanitize_user_input("a<object data='x'>b</object>c")
        assert "<object" not in result

    def test_internal_whitespace_preserved(self):
        # Whitespace is intentionally NOT collapsed so pasted code/markdown
        # keeps its indentation and paragraph structure.
        assert sanitize_user_input("a     b") == "a     b"

    def test_code_indentation_preserved(self):
        code = "def f():\n    if x:\n        return 1\n\n\nprint(f())"
        # .strip() only trims the ends; internal newlines/indentation survive.
        assert sanitize_user_input(code) == code

    def test_truncation_at_max_length(self):
        long_text = "x" * 100
        result = sanitize_user_input(long_text, max_length=50)
        assert len(result) == 50

    def test_leading_trailing_whitespace_stripped(self):
        assert sanitize_user_input("  hello  ") == "hello"


# ── sanitize_messages ──────────────────────────────────────────────────────

class TestSanitizeMessages:
    def test_empty_list(self):
        assert sanitize_messages([]) == []

    def test_none_input(self):
        assert sanitize_messages(None) is None

    def test_non_list(self):
        assert sanitize_messages("not a list") == "not a list"

    def test_normal_messages(self):
        msgs = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]
        result = sanitize_messages(msgs)
        assert len(result) == 2
        assert result[0]["content"] == "hi"
        assert result[1]["content"] == "hello"

    def test_control_chars_cleaned_in_messages(self):
        msgs = [{"role": "user", "content": "hi\x00there"}]
        result = sanitize_messages(msgs)
        assert result[0]["content"] == "hithere"

    def test_non_dict_items_filtered(self):
        msgs = [{"role": "user", "content": "ok"}, "not a dict", 42]
        result = sanitize_messages(msgs)
        assert len(result) == 1

    def test_multipart_content(self):
        msgs = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "describe this\x00"},
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
                ],
            }
        ]
        result = sanitize_messages(msgs)
        assert result[0]["content"][0]["text"] == "describe this"
        assert result[0]["content"][1]["type"] == "image_url"

    def test_unknown_role_passed_through(self):
        msgs = [{"role": "tool", "content": "result"}]
        result = sanitize_messages(msgs)
        assert len(result) == 1
        assert result[0]["content"] == "result"

    def test_preserves_extra_keys(self):
        msgs = [{"role": "user", "content": "hi", "extra_key": "value"}]
        result = sanitize_messages(msgs)
        assert result[0]["extra_key"] == "value"
