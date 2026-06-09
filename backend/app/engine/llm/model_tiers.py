"""Pick the local model variant that fits the host's unified memory.

The desktop app ships a single binary that runs on very different Macs (an 8 GB
M1 Air through a 64 GB Studio). The Gemma weights must fit in unified memory
*alongside* macOS, the webview and the Python sidecar, so loading the largest
quant everywhere either OOM-kills the process or thrashes. Instead we detect
total RAM at startup and choose a (model, quant, context window) tier.

The small and mid tiers use Unsloth's Gemma 4 QAT (quantization-aware training)
GGUFs in the ``UD-Q4_K_XL`` format (near-BF16 quality at ~4-bit size). The high
tier runs the near-lossless 8-bit E4B ``Q8_0``:

    < 16 GB  -> Gemma 4 E2B QAT, UD-Q4_K_XL, N_CTX 8192   (~2.6 GB weights)
    16-24 GB -> Gemma 4 E4B QAT, UD-Q4_K_XL, N_CTX 16384  (~4.2 GB weights)
    >= 24 GB -> Gemma 4 E4B,     Q8_0,       N_CTX 32768  (~8.2 GB weights)

Every value can still be overridden explicitly via environment variables
(``LLAMA_REPO_ID``/``LLAMA_FILENAME``/``LLAMA_MMPROJ_FILENAME``/``N_CTX``),
which is how browser mode and power users tune the runtime.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from dataclasses import dataclass

logger = logging.getLogger(__name__)

GIB = 1024**3

# Thresholds in bytes. A nominal "16 GB" Mac reports exactly 16 GiB via
# hw.memsize, so the comparisons are written so that 16 GB lands in the mid
# tier and 24 GB in the high tier.
MID_TIER_MIN_BYTES = 16 * GIB
HIGH_TIER_MIN_BYTES = 24 * GIB


@dataclass(frozen=True)
class ModelTier:
    label: str
    repo_id: str
    filename: str
    mmproj_filename: str
    n_ctx: int
    # Memory-constrained tier (e.g. 8 GB Macs). Heavy multi-call paths such as
    # deep research scale themselves down ("lite" mode) when this is set, so a
    # long run does not exhaust unified memory and crash mid-workflow.
    low_memory: bool = False


TIER_LOW = ModelTier(
    label="low (<16GB RAM)",
    repo_id="unsloth/gemma-4-E2B-it-qat-GGUF",
    filename="gemma-4-E2B-it-qat-UD-Q4_K_XL.gguf",
    mmproj_filename="mmproj-F16.gguf",
    n_ctx=8192,
    low_memory=True,
)
TIER_MID = ModelTier(
    label="mid (16-24GB RAM)",
    repo_id="unsloth/gemma-4-E4B-it-qat-GGUF",
    filename="gemma-4-E4B-it-qat-UD-Q4_K_XL.gguf",
    mmproj_filename="mmproj-F16.gguf",
    n_ctx=16384,
)
TIER_HIGH = ModelTier(
    label="high (>=24GB RAM)",
    repo_id="unsloth/gemma-4-E4B-it-GGUF",
    filename="gemma-4-E4B-it-Q8_0.gguf",
    mmproj_filename="mmproj-F16.gguf",
    n_ctx=32768,
)


def detect_total_memory_bytes() -> int | None:
    """Best-effort total physical RAM in bytes, or ``None`` if undetectable.

    ``QUANTSCRIPT_TOTAL_MEMORY_BYTES`` forces a value (used by tests and to let
    users pin a tier on misbehaving hardware).
    """
    override = os.environ.get("QUANTSCRIPT_TOTAL_MEMORY_BYTES", "").strip()
    if override:
        try:
            return int(override)
        except ValueError:
            logger.warning("Ignoring invalid QUANTSCRIPT_TOTAL_MEMORY_BYTES=%r", override)

    # macOS (the desktop target): hw.memsize is the exact installed RAM.
    if sys.platform == "darwin":
        try:
            out = subprocess.check_output(["sysctl", "-n", "hw.memsize"], text=True, timeout=5)
            return int(out.strip())
        except (OSError, ValueError, subprocess.SubprocessError) as e:
            logger.warning("Could not read hw.memsize via sysctl: %s", e)

    # POSIX fallback (Linux / browser mode on other platforms).
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (ValueError, OSError, AttributeError):
        return None


def select_model_tier(total_memory_bytes: int | None) -> ModelTier:
    """Map detected RAM to a tier; default to the safest (smallest) tier."""
    if total_memory_bytes is None:
        logger.warning("Unable to detect system memory; defaulting to the low (E2B) tier")
        return TIER_LOW
    if total_memory_bytes < MID_TIER_MIN_BYTES:
        return TIER_LOW
    if total_memory_bytes < HIGH_TIER_MIN_BYTES:
        return TIER_MID
    return TIER_HIGH


def resolve_model_config() -> dict:
    """Final runtime model settings: auto-tier defaults with env-var overrides.

    Explicit environment variables always win, preserving the existing browser
    mode / power-user tuning contract.
    """
    total = detect_total_memory_bytes()
    tier = select_model_tier(total)

    repo_id = os.environ.get("LLAMA_REPO_ID", tier.repo_id)
    filename = os.environ.get("LLAMA_FILENAME", tier.filename)
    mmproj_filename = os.environ.get("LLAMA_MMPROJ_FILENAME", tier.mmproj_filename)
    n_ctx = int(os.environ.get("N_CTX", str(tier.n_ctx)))

    gib = (total / GIB) if total is not None else None
    logger.info(
        "Model tier '%s' selected (RAM=%s): repo=%s file=%s n_ctx=%d",
        tier.label,
        f"{gib:.1f} GiB" if gib is not None else "unknown",
        repo_id,
        filename,
        n_ctx,
    )

    return {
        "tier": tier,
        "repo_id": repo_id,
        "filename": filename,
        "mmproj_filename": mmproj_filename,
        "n_ctx": n_ctx,
    }
