"""Shared fixtures for backend tests.

Heavy ML dependencies (llama-cpp-python, huggingface-hub, pypdfium2) are mocked
at the *module* level so they never initialise during CI / testing.
"""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Mock heavy / GPU / network dependencies BEFORE any app code is imported.
# These run at conftest load time — before test collection.
# ---------------------------------------------------------------------------
_mock_llama = MagicMock()
_mock_llama.Llama = MagicMock()
_mock_llama.Llama.from_pretrained = MagicMock(return_value=MagicMock())
sys.modules.setdefault("llama_cpp", _mock_llama)

_mock_chat_format = MagicMock()
sys.modules.setdefault("llama_cpp.llama_chat_format", _mock_chat_format)

_mock_hf = MagicMock()
_mock_hf.hf_hub_download = MagicMock(return_value="/fake/path/model.gguf")
_mock_hf.hf_hub_url = MagicMock(return_value="https://fake.hf.co/model.gguf")
_mock_hf.get_hf_file_metadata = MagicMock()
sys.modules.setdefault("huggingface_hub", _mock_hf)

_mock_hf_utils = MagicMock()


class _EntryNotFoundError(Exception):
    """Stand-in for huggingface_hub.utils.EntryNotFoundError in tests."""


_mock_hf_utils.EntryNotFoundError = _EntryNotFoundError
sys.modules.setdefault("huggingface_hub.utils", _mock_hf_utils)

_mock_webserp = MagicMock()
_mock_webserp_cli = MagicMock()
sys.modules.setdefault("webserp", _mock_webserp)
sys.modules.setdefault("webserp.cli", _mock_webserp_cli)

_mock_pypdfium2 = MagicMock()
sys.modules.setdefault("pypdfium2", _mock_pypdfium2)

# Env vars the app expects at import time
os.environ.setdefault("LLAMA_REPO_ID", "test-org/test-model")
os.environ.setdefault("LLAMA_FILENAME", "model.gguf")
os.environ.setdefault("LLAMA_MMPROJ_FILENAME", "mmproj.gguf")
# TrustedHostMiddleware is always on (loopback by default); the Starlette
# TestClient sends `Host: testserver`, so allow it for the test suite.
# ALLOWED_HOSTS extends — never replaces — the loopback defaults.
os.environ.setdefault("ALLOWED_HOSTS", "testserver")

# ---------------------------------------------------------------------------
# Now safe to import app modules
# ---------------------------------------------------------------------------
from app.api.main import app as _app  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def app_client(tmp_path):
    """Starlette TestClient with startup-gate bypassed and LLM responses stubbed."""
    from starlette.testclient import TestClient

    conv_dir = tmp_path / "storage" / "conversations"
    conv_dir.mkdir(parents=True)

    with (
        patch("app.core.startup_state.is_ready", return_value=True),
        patch(
            "app.api.routes.stream_llm_response",
            side_effect=lambda *args, **kwargs: iter(["Hello", " world"]),
        ),
        patch(
            "app.api.conversations.CONVERSATIONS_STORAGE_PATH",
            conv_dir,
        ),
        patch(
            "app.api.conversations.create_title_from_messages",
            return_value="Test title",
        ),
    ):
        with TestClient(_app, raise_server_exceptions=False) as client:
            yield client


@pytest.fixture()
def conversations_dir(tmp_path):
    """Temporary conversations directory for storage-layer tests."""
    conv_dir = tmp_path / "storage" / "conversations"
    conv_dir.mkdir(parents=True)
    with (
        patch("app.api.conversations.CONVERSATIONS_STORAGE_PATH", conv_dir),
        patch(
            "app.api.conversations.create_title_from_messages",
            return_value="Test title",
        ),
    ):
        yield conv_dir
