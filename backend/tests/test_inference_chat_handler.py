from unittest.mock import MagicMock, patch

import pytest

import app.engine.llm.inference as inference
from app.engine.llm.inference import (
    MODE_DEEP_RESEARCH,
    MODE_TEXT,
    MODE_VISION,
    _apply_system_prompt,
    _get_chat_handler,
    _messages_have_attachment,
    _resolve_model_mode,
)


@pytest.fixture(autouse=True)
def reset_model_state():
    """Reset module globals so each test starts from a clean, unloaded state."""
    inference.CLIENT_LLAMA = None
    inference.CHAT_HANDLER = None
    inference._CURRENT_MODE = None
    # Pretend the multimodal projector is already on disk so vision mode never
    # tries to download it during tests.
    inference.MMPROJ_PATH = "/fake/mmproj.gguf"
    yield


# ---------------------------------------------------------------------------
# Mode resolution
# ---------------------------------------------------------------------------

def test_resolve_model_mode_prefers_deep_research():
    assert _resolve_model_mode(deep_research=True, has_attachment=False) == MODE_DEEP_RESEARCH
    # Deep research wins even if an attachment is present.
    assert _resolve_model_mode(deep_research=True, has_attachment=True) == MODE_DEEP_RESEARCH


def test_resolve_model_mode_vision_when_attachment():
    assert _resolve_model_mode(deep_research=False, has_attachment=True) == MODE_VISION


def test_resolve_model_mode_defaults_to_text():
    assert _resolve_model_mode(deep_research=False, has_attachment=False) == MODE_TEXT


# ---------------------------------------------------------------------------
# Attachment detection
# ---------------------------------------------------------------------------

def test_messages_have_attachment_true_for_list_content():
    messages = [
        {"role": "user", "content": "hello"},
        {"role": "user", "content": [{"type": "text", "text": "see this"}, {"type": "image_url", "image_url": {"url": "data:..."}}]},
    ]
    assert _messages_have_attachment(messages) is True


def test_messages_have_attachment_false_for_plain_text():
    messages = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi"},
    ]
    assert _messages_have_attachment(messages) is False


# ---------------------------------------------------------------------------
# Chat-template selection
# ---------------------------------------------------------------------------

def test_get_chat_handler_deep_research_uses_gemma():
    # Deep research is now a deterministic structured-JSON workflow, so it uses
    # the model's native Gemma template rather than chatml-function-calling.
    assert _get_chat_handler(MODE_DEEP_RESEARCH) == {"chat_format": "gemma"}


def test_get_chat_handler_text_uses_gemma():
    assert _get_chat_handler(MODE_TEXT) == {"chat_format": "gemma"}


def test_get_chat_handler_vision_uses_llava_handler():
    kwargs = _get_chat_handler(MODE_VISION)
    assert "chat_handler" in kwargs
    assert "chat_format" not in kwargs
    # Handler is cached on the module after first build.
    assert inference.CHAT_HANDLER is kwargs["chat_handler"]


# ---------------------------------------------------------------------------
# initialize_llama: correct kwargs + reload-only-on-mode-change
# ---------------------------------------------------------------------------

def _patched_init():
    return (
        patch.object(inference, "is_ready", return_value=True),
        patch.object(inference, "download_model_files", return_value=("/model.gguf", None)),
    )


def test_initialize_llama_text_passes_gemma_format():
    p_ready, p_dl = _patched_init()
    with p_ready, p_dl, patch.object(inference, "Llama", return_value=MagicMock()) as mock_llama:
        inference.initialize_llama()

    assert mock_llama.call_args.kwargs["chat_format"] == "gemma"
    assert "chat_handler" not in mock_llama.call_args.kwargs
    assert inference._CURRENT_MODE == MODE_TEXT


def test_initialize_llama_vision_passes_chat_handler():
    p_ready, p_dl = _patched_init()
    with p_ready, p_dl, patch.object(inference, "Llama", return_value=MagicMock()) as mock_llama:
        inference.initialize_llama(has_attachment=True)

    assert "chat_handler" in mock_llama.call_args.kwargs
    assert "chat_format" not in mock_llama.call_args.kwargs
    assert inference._CURRENT_MODE == MODE_VISION


def test_initialize_llama_deep_research_passes_gemma():
    p_ready, p_dl = _patched_init()
    with p_ready, p_dl, patch.object(inference, "Llama", return_value=MagicMock()) as mock_llama:
        inference.initialize_llama(deep_research=True)

    assert mock_llama.call_args.kwargs["chat_format"] == "gemma"
    assert inference._CURRENT_MODE == MODE_DEEP_RESEARCH


def test_initialize_llama_reuses_model_for_same_mode():
    p_ready, p_dl = _patched_init()
    with p_ready, p_dl, patch.object(inference, "Llama", return_value=MagicMock()) as mock_llama:
        first = inference.initialize_llama()        # text
        second = inference.initialize_llama()       # text again

    assert first is second
    assert mock_llama.call_count == 1               # no reload for same mode


def test_initialize_llama_reloads_on_mode_change():
    p_ready, p_dl = _patched_init()
    with p_ready, p_dl, patch.object(inference, "Llama", side_effect=[MagicMock(), MagicMock()]) as mock_llama:
        with patch.object(inference, "_unload_llama", wraps=inference._unload_llama) as mock_unload:
            inference.initialize_llama()                 # text
            inference.initialize_llama(has_attachment=True)  # -> vision, must reload

    assert mock_llama.call_count == 2
    assert mock_unload.call_count >= 1
    assert inference._CURRENT_MODE == MODE_VISION


# ---------------------------------------------------------------------------
# System-prompt placement per mode
# ---------------------------------------------------------------------------

def test_apply_system_prompt_merges_into_user_in_text_mode():
    inference._CURRENT_MODE = MODE_TEXT
    messages = [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "reply"},
        {"role": "user", "content": "what is X?"},
    ]
    out = _apply_system_prompt(messages, "SYS")

    # No separate system message (Gemma would drop it).
    assert all(m["role"] != "system" for m in out)
    # Merged into the latest user turn.
    assert out[-1]["role"] == "user"
    assert out[-1]["content"] == "SYS\n\nwhat is X?"
    # Earlier turns untouched.
    assert out[0]["content"] == "first"


def test_apply_system_prompt_inserts_system_message_in_vision_mode():
    inference._CURRENT_MODE = MODE_VISION
    messages = [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "reply"},
        {"role": "user", "content": "describe the image"},
    ]
    out = _apply_system_prompt(messages, "SYS")

    # System message inserted just before the final user turn.
    assert out[-2] == {"role": "system", "content": "SYS"}
    assert out[-1]["content"] == "describe the image"
