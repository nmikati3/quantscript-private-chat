"""Tests for memory-based model tier selection and env-override precedence."""

import pytest

from app.engine.llm.model_tiers import (
    GIB,
    TIER_LOW,
    TIER_MID,
    TIER_HIGH,
    detect_total_memory_bytes,
    resolve_model_config,
    select_model_tier,
)

_LLAMA_ENV_VARS = (
    "LLAMA_REPO_ID",
    "LLAMA_FILENAME",
    "LLAMA_MMPROJ_FILENAME",
    "N_CTX",
    "QUANTSCRIPT_TOTAL_MEMORY_BYTES",
)


@pytest.fixture()
def clean_model_env(monkeypatch):
    """Remove every env var that influences tier resolution."""
    for var in _LLAMA_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    return monkeypatch


@pytest.mark.parametrize(
    "ram_gib, expected",
    [
        (8, TIER_LOW),
        (12, TIER_LOW),
        (15.9, TIER_LOW),
        (16, TIER_MID),
        (20, TIER_MID),
        (23.9, TIER_MID),
        (24, TIER_HIGH),
        (32, TIER_HIGH),
        (64, TIER_HIGH),
    ],
)
def test_select_model_tier_boundaries(ram_gib, expected):
    assert select_model_tier(int(ram_gib * GIB)) is expected


def test_select_model_tier_unknown_defaults_to_low():
    assert select_model_tier(None) is TIER_LOW


def test_tier_model_choices():
    # E2B/E4B QAT for the small & mid tiers; near-lossless E4B Q8_0 for high.
    assert "E2B" in TIER_LOW.filename and "qat" in TIER_LOW.filename and TIER_LOW.n_ctx == 8192
    assert "E4B" in TIER_MID.filename and "qat" in TIER_MID.filename and TIER_MID.n_ctx == 16384
    assert "E4B" in TIER_HIGH.filename and "Q8_0" in TIER_HIGH.filename and TIER_HIGH.n_ctx == 32768


def test_detect_memory_honors_override(clean_model_env):
    clean_model_env.setenv("QUANTSCRIPT_TOTAL_MEMORY_BYTES", str(16 * GIB))
    assert detect_total_memory_bytes() == 16 * GIB


def test_detect_memory_ignores_invalid_override(clean_model_env):
    clean_model_env.setenv("QUANTSCRIPT_TOTAL_MEMORY_BYTES", "not-a-number")
    # Falls back to real detection, which returns an int (or None) but never raises.
    result = detect_total_memory_bytes()
    assert result is None or isinstance(result, int)


def test_resolve_uses_tier_defaults_when_no_overrides(clean_model_env):
    clean_model_env.setenv("QUANTSCRIPT_TOTAL_MEMORY_BYTES", str(8 * GIB))
    cfg = resolve_model_config()
    assert cfg["tier"] is TIER_LOW
    assert cfg["repo_id"] == TIER_LOW.repo_id
    assert cfg["filename"] == TIER_LOW.filename
    assert cfg["mmproj_filename"] == TIER_LOW.mmproj_filename
    assert cfg["n_ctx"] == TIER_LOW.n_ctx


def test_resolve_mid_tier_at_16gb(clean_model_env):
    clean_model_env.setenv("QUANTSCRIPT_TOTAL_MEMORY_BYTES", str(16 * GIB))
    cfg = resolve_model_config()
    assert cfg["filename"] == TIER_MID.filename
    assert cfg["n_ctx"] == 16384


def test_resolve_high_tier_at_24gb(clean_model_env):
    clean_model_env.setenv("QUANTSCRIPT_TOTAL_MEMORY_BYTES", str(24 * GIB))
    cfg = resolve_model_config()
    assert cfg["tier"] is TIER_HIGH
    assert cfg["filename"] == TIER_HIGH.filename
    assert cfg["n_ctx"] == 32768


def test_env_vars_override_tier(clean_model_env):
    # Even on a "small" machine, explicit env vars win (browser-mode / power users).
    clean_model_env.setenv("QUANTSCRIPT_TOTAL_MEMORY_BYTES", str(8 * GIB))
    clean_model_env.setenv("LLAMA_REPO_ID", "custom/repo")
    clean_model_env.setenv("LLAMA_FILENAME", "custom-model.gguf")
    clean_model_env.setenv("LLAMA_MMPROJ_FILENAME", "custom-mmproj.gguf")
    clean_model_env.setenv("N_CTX", "131072")

    cfg = resolve_model_config()
    assert cfg["repo_id"] == "custom/repo"
    assert cfg["filename"] == "custom-model.gguf"
    assert cfg["mmproj_filename"] == "custom-mmproj.gguf"
    assert cfg["n_ctx"] == 131072
    # The detected tier is still reported even though fields were overridden.
    assert cfg["tier"] is TIER_LOW
