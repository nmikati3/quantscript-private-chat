from unittest.mock import MagicMock, patch

import app.engine.llm.inference as inference


def test_unload_llama_closes_client_and_handler():
    mock_client = MagicMock()
    mock_handler = MagicMock()
    inference.CLIENT_LLAMA = mock_client
    inference.CHAT_HANDLER = mock_handler

    with patch.object(inference.gc, "collect") as mock_collect:
        inference._unload_llama()

    mock_client.close.assert_called_once()
    mock_handler.close.assert_called_once()
    mock_collect.assert_called_once()
    assert inference.CLIENT_LLAMA is None
    assert inference.CHAT_HANDLER is None


def test_unload_llama_noop_when_nothing_loaded():
    inference.CLIENT_LLAMA = None
    inference.CHAT_HANDLER = None

    with patch.object(inference.gc, "collect") as mock_collect:
        inference._unload_llama()

    mock_collect.assert_called_once()
    assert inference.CLIENT_LLAMA is None
    assert inference.CHAT_HANDLER is None


def test_initialize_llama_unloads_before_loading():
    mock_client = MagicMock()

    with (
        patch.object(inference, "_unload_llama") as mock_unload,
        patch.object(inference, "download_model_files", return_value=("/model.gguf", None)),
        patch.object(inference, "Llama", return_value=mock_client) as mock_llama_ctor,
    ):
        result = inference.initialize_llama(deep_research=True)

    mock_unload.assert_called_once()
    mock_llama_ctor.assert_called_once()
    assert result is mock_client
