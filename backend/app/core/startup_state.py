"""Background startup sequence and status for the API."""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any, Literal

from app.engine.llm.model_tiers import detect_total_memory_bytes, select_model_tier

logger = logging.getLogger(__name__)

PhaseStatus = Literal["pending", "running", "done", "error"]

# Deep research is currently blocked for low-memory machines.
DEEP_RESEARCH_AVAILABLE = not select_model_tier(detect_total_memory_bytes()).low_memory

# Order matches main.py startup; labels mirror what you see in the terminal (weights / loading).
PHASES: list[dict[str, str]] = [
    {"id": "llm", "label": "Downloading language model"},
]

_startup_lock = threading.Lock()
_ready = False
_startup_error: str | None = None
_phase_states: dict[str, PhaseStatus] = {p["id"]: "pending" for p in PHASES}
_phase_progress: dict[str, dict[str, Any]] = {}


def is_ready() -> bool:
    with _startup_lock:
        return _ready


def set_phase_progress(
    phase_id: str,
    *,
    percent: int | None = None,
    detail: str | None = None,
) -> None:
    """Update download/load progress for a startup phase (thread-safe)."""
    with _startup_lock:
        entry = _phase_progress.setdefault(phase_id, {})
        if percent is not None:
            entry["percent"] = max(0, min(100, int(percent)))
        if detail is not None:
            entry["detail"] = detail


def clear_phase_progress(phase_id: str) -> None:
    with _startup_lock:
        _phase_progress.pop(phase_id, None)


def get_startup_snapshot() -> dict[str, Any]:
    with _startup_lock:
        phases = []
        for p in PHASES:
            pid = p["id"]
            progress = _phase_progress.get(pid, {})
            phase_payload: dict[str, Any] = {
                "id": pid,
                "label": p["label"],
                "status": _phase_states.get(pid, "pending"),
            }
            if "percent" in progress:
                phase_payload["percent"] = progress["percent"]
            if progress.get("detail"):
                phase_payload["detail"] = progress["detail"]
            phases.append(phase_payload)
        return {
            "ready": _ready,
            "error": _startup_error,
            "phases": phases,
            "deepResearchAvailable": DEEP_RESEARCH_AVAILABLE,
        }


def _set_phase(phase_id: str, status: PhaseStatus) -> None:
    with _startup_lock:
        _phase_states[phase_id] = status
        if status == "done":
            _phase_progress.setdefault(phase_id, {})["percent"] = 100


async def run_startup_background() -> None:
    """Run the same initialization as the former blocking startup, with per-phase status updates."""
    global _ready, _startup_error

    from app.engine.llm.inference import initialize_llama

    steps: list[tuple[str, Any]] = [
        ("llm", initialize_llama),
    ]

    for phase_id, fn in steps:
        clear_phase_progress(phase_id)
        _set_phase(phase_id, "running")
        set_phase_progress(phase_id, percent=0, detail="Preparing download…")
        try:
            await asyncio.to_thread(fn)
            _set_phase(phase_id, "done")
            clear_phase_progress(phase_id)
        except Exception as e:
            logger.exception("Startup phase %s failed", phase_id)
            _set_phase(phase_id, "error")
            with _startup_lock:
                _startup_error = str(e)
            return

    with _startup_lock:
        _ready = True
    logger.info("Application startup complete.")
