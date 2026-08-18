"""Pick the local model variant that fits the host's total memory.

The desktop app ships a single binary per platform that runs on very different
machines (an 8 GB laptop through a 64 GB workstation), across macOS, Windows and
Linux. The Gemma weights must fit in memory *alongside* the OS, the webview and
the Python sidecar, so loading the largest quant everywhere either OOM-kills the
process or thrashes. Instead we detect total RAM at startup and choose a
(model, quant, context window) tier.

The small and mid tiers use Unsloth's Gemma 4 QAT (quantization-aware training)
GGUFs in the ``UD-Q4_K_XL`` format (near-BF16 quality at ~4-bit size). The high
tier runs the near-lossless 8-bit E4B ``Q8_0``:

    < 16 GB  -> Gemma 4 E2B QAT, UD-Q4_K_XL, N_CTX 8192   (~2.6 GB weights)
    16-24 GB -> Gemma 4 E4B QAT, UD-Q4_K_XL, N_CTX 8192   (~4.2 GB weights)
    >= 24 GB -> Gemma 4 E4B,     Q8_0,       N_CTX 32768  (~8.2 GB weights)

Memory detection is platform-specific:

    macOS    -> ``sysctl hw.memsize`` (exact installed RAM)
    Windows  -> ``GlobalMemoryStatusEx`` via ctypes (kernel32)
    Linux/*  -> ``sysconf(SC_PAGE_SIZE) * sysconf(SC_PHYS_PAGES)``

Every value can still be overridden explicitly via environment variables
(``LLAMA_REPO_ID``/``LLAMA_FILENAME``/``LLAMA_MMPROJ_FILENAME``/``N_CTX``),
which is how browser mode and power users tune the runtime.
"""

from __future__ import annotations

import ctypes
import logging
import os
import subprocess
import sys
from dataclasses import dataclass

logger = logging.getLogger(__name__)

GIB = 1024**3

# Tier boundaries carry a small tolerance below the nominal RAM sizes because
# not every platform reports the exact installed amount:
#   * macOS ``hw.memsize`` reports the exact installed RAM (a 16 GB Mac == 16 GiB).
#   * Windows ``GlobalMemoryStatusEx`` and Linux ``sysconf`` both *exclude*
#     firmware-/kernel-/iGPU-reserved memory, so a "16 GB" box typically reports
#     ~15.7 GiB and can dip lower when integrated graphics steal a chunk.
# Subtracting a 2 GiB margin keeps a 16 GB machine in the mid tier and a 24 GB
# machine in the high tier on every platform, while 8/12 GB machines stay in the
# low tier. Pin a tier explicitly with QUANTSCRIPT_TOTAL_MEMORY_BYTES if your
# hardware sits right on a boundary.
TIER_TOLERANCE_BYTES = 2 * GIB
MID_TIER_MIN_BYTES = 16 * GIB - TIER_TOLERANCE_BYTES
HIGH_TIER_MIN_BYTES = 24 * GIB - TIER_TOLERANCE_BYTES


@dataclass(frozen=True)
class ModelTier:
    label: str
    repo_id: str
    filename: str
    mmproj_filename: str
    n_ctx: int
    deep_research_available: bool = True
    low_memory: bool = False
    mid_memory: bool = False


TIER_LOW = ModelTier(
    label="low (<16GB RAM)",
    repo_id="unsloth/gemma-4-E2B-it-qat-GGUF",
    filename="gemma-4-E2B-it-qat-UD-Q4_K_XL.gguf",
    mmproj_filename="mmproj-F16.gguf",
    n_ctx=8192,
    low_memory=True,
    deep_research_available=False,
)
TIER_MID = ModelTier(
    label="mid (16-24GB RAM)",
    repo_id="unsloth/gemma-4-E4B-it-qat-GGUF",
    filename="gemma-4-E4B-it-qat-UD-Q4_K_XL.gguf",
    mmproj_filename="mmproj-F16.gguf",
    n_ctx=8192,
    mid_memory=True
)
TIER_HIGH = ModelTier(
    label="high (>=24GB RAM)",
    repo_id="unsloth/gemma-4-E4B-it-GGUF",
    filename="gemma-4-E4B-it-Q8_0.gguf",
    mmproj_filename="mmproj-F16.gguf",
    n_ctx=32768,
)


def _detect_macos_memory_bytes() -> int | None:
    """Exact installed RAM on macOS via ``sysctl hw.memsize``."""
    try:
        out = subprocess.check_output(["sysctl", "-n", "hw.memsize"], text=True, timeout=5)
        return int(out.strip())
    except (OSError, ValueError, subprocess.SubprocessError) as e:
        logger.warning("Could not read hw.memsize via sysctl: %s", e)
        return None


def _detect_windows_memory_bytes() -> int | None:
    """Total physical RAM on Windows via ``GlobalMemoryStatusEx`` (kernel32).

    ``ullTotalPhys`` is the amount of physical memory visible to the OS, i.e.
    installed RAM minus any firmware-/hardware-reserved memory (integrated GPUs
    can claim a non-trivial slice), which is exactly what we want to budget the
    model against.
    """

    class _MemoryStatusEx(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    try:
        stat = _MemoryStatusEx()
        stat.dwLength = ctypes.sizeof(_MemoryStatusEx)
        # windll exists only on Windows; guarded by the sys.platform check below.
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):  # type: ignore[attr-defined]
            return int(stat.ullTotalPhys)
        logger.warning("GlobalMemoryStatusEx returned 0 (no memory info)")
    except (OSError, AttributeError, ValueError) as e:
        logger.warning("Could not read memory via GlobalMemoryStatusEx: %s", e)
    return None


def _detect_posix_memory_bytes() -> int | None:
    """Total physical RAM on Linux/POSIX via ``sysconf`` page accounting."""
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (ValueError, OSError, AttributeError):
        return None


def detect_total_memory_bytes() -> int | None:
    """Best-effort total physical RAM in bytes, or ``None`` if undetectable.

    ``QUANTSCRIPT_TOTAL_MEMORY_BYTES`` forces a value (used by tests and to let
    users pin a tier on misbehaving hardware). Detection is platform-specific so
    the desktop app tiers correctly on macOS, Windows and Linux alike.
    """
    override = os.environ.get("QUANTSCRIPT_TOTAL_MEMORY_BYTES", "").strip()
    if override:
        try:
            return int(override)
        except ValueError:
            logger.warning("Ignoring invalid QUANTSCRIPT_TOTAL_MEMORY_BYTES=%r", override)

    if sys.platform == "darwin":
        detected = _detect_macos_memory_bytes()
        if detected is not None:
            return detected
    elif sys.platform == "win32":
        detected = _detect_windows_memory_bytes()
        if detected is not None:
            return detected

    # POSIX fallback: Linux primarily, plus a last-resort path on macOS/Windows
    # if the platform-specific probe above failed for any reason.
    return _detect_posix_memory_bytes()


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
