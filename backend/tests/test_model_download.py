"""Tests for startup download progress tracking."""

from unittest.mock import MagicMock, patch

from app.core.startup_state import (
    clear_phase_progress,
    get_startup_snapshot,
    set_phase_progress,
)
from app.engine.llm.model_download import _MultiFileDownloadTracker


class TestStartupProgress:
    def test_snapshot_includes_percent_and_detail(self):
        clear_phase_progress("llm")
        set_phase_progress("llm", percent=42, detail="Downloading language model…")
        snap = get_startup_snapshot()
        phase = next(p for p in snap["phases"] if p["id"] == "llm")
        assert phase["percent"] == 42
        assert phase["detail"] == "Downloading language model…"

    def test_percent_clamped(self):
        set_phase_progress("llm", percent=150)
        snap = get_startup_snapshot()
        phase = next(p for p in snap["phases"] if p["id"] == "llm")
        assert phase["percent"] == 100


class TestMultiFileDownloadTracker:
    def test_aggregate_progress(self):
        with patch(
            "app.engine.llm.model_download._file_size_bytes",
            side_effect=[100, 900],
        ):
            tracker = _MultiFileDownloadTracker(
                "llm",
                [
                    ("vision projector", "org/model", "mmproj.gguf"),
                    ("language model", "org/model", "model.gguf"),
                ],
                on_progress=MagicMock(),
            )
        tqdm_cls = tracker._tqdm_class(1)
        bar = tqdm_cls(total=900, desc="language model")
        bar.update(450)
        tracker._on_progress.assert_called()
        call = tracker._on_progress.call_args
        assert call[0][0] == "llm"
        assert call[1]["percent"] == 55
