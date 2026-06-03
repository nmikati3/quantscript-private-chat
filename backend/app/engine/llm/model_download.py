"""Hugging Face model downloads with startup progress reporting to show users the progress of the download on first startup."""

from __future__ import annotations

import logging
from typing import Callable

from huggingface_hub import hf_hub_download, hf_hub_url
from huggingface_hub.utils import EntryNotFoundError
from tqdm.auto import tqdm as base_tqdm

from app.core.startup_state import set_phase_progress

logger = logging.getLogger(__name__)

try:
    from huggingface_hub import get_hf_file_metadata
except ImportError:  # pragma: no cover
    get_hf_file_metadata = None  # type: ignore[misc, assignment]


def _file_size_bytes(repo_id: str, filename: str) -> int | None:
    if get_hf_file_metadata is None:
        return None
    try:
        url = hf_hub_url(repo_id=repo_id, filename=filename)
        meta = get_hf_file_metadata(url)
        size = getattr(meta, "size", None)
        return int(size) if size and size > 0 else None
    except (EntryNotFoundError, OSError, ValueError, TypeError) as e:
        logger.debug("Could not resolve size for %s/%s: %s", repo_id, filename, e)
        return None


class _MultiFileDownloadTracker:
    """Tracks aggregate byte progress across sequential hf_hub_download calls."""

    def __init__(
        self,
        phase_id: str,
        files: list[tuple[str, str, str]],
        on_progress: Callable[..., None] | None = None,
    ) -> None:
        self.phase_id = phase_id
        self.files = files
        self._on_progress = on_progress or set_phase_progress
        self._offsets: list[int] = []
        self._sizes: list[int | None] = []
        total = 0
        for _label, repo_id, filename in files:
            size = _file_size_bytes(repo_id, filename)
            self._offsets.append(total)
            self._sizes.append(size)
            if size:
                total += size
        self._total_bytes = total if total > 0 else None

    def _report(self, file_index: int, file_n: int, desc: str | None) -> None:
        label = self.files[file_index][0]
        detail = desc or label
        if self._total_bytes:
            file_size = self._sizes[file_index] or 0
            if file_size > 0:
                done = self._offsets[file_index] + min(file_n, file_size)
            else:
                done = self._offsets[file_index] + file_n
            percent = min(99, int(100 * done / self._total_bytes))
        else:
            file_size = self._sizes[file_index]
            if file_size and file_size > 0:
                percent = min(99, int(100 * file_n / file_size))
            else:
                percent = None
        self._on_progress(
            self.phase_id,
            percent=percent,
            detail=detail,
        )

    def _tqdm_class(self, file_index: int):
        tracker = self

        class _ProgressTqdm(base_tqdm):
            def update(self, n=1):
                result = super().update(n)
                tracker._report(file_index, self.n, self.desc)
                return result

        return _ProgressTqdm

    def download(self, repo_id: str, filename: str, label: str) -> str:
        file_index = next(
            i for i, (lbl, rid, fn) in enumerate(self.files) if rid == repo_id and fn == filename
        )
        self._report(file_index, 0, f"Downloading {label}…")
        return hf_hub_download(
            repo_id=repo_id,
            filename=filename,
            tqdm_class=self._tqdm_class(file_index),
        )

    def download_all(self) -> dict[str, str]:
        paths: dict[str, str] = {}
        for label, repo_id, filename in self.files:
            path = self.download(repo_id, filename, label)
            paths[filename] = path
        return paths


def download_mmproj(
    phase_id: str,
    repo_id: str,
    filename: str,
    *,
    report_progress: bool = True,
) -> str:
    if not report_progress:
        return hf_hub_download(repo_id=repo_id, filename=filename)
    tracker = _MultiFileDownloadTracker(phase_id, [("vision projector", repo_id, filename)])
    return tracker.download(repo_id, filename, "vision projector")


def download_model_files(
    phase_id: str,
    repo_id: str,
    *,
    main_filename: str,
    mmproj_filename: str | None = None,
    report_progress: bool = True,
) -> tuple[str, str | None]:
    """Download GGUF (and optional mmproj) weights; return local paths."""
    files: list[tuple[str, str, str]] = []
    if mmproj_filename:
        files.append(("vision projector", repo_id, mmproj_filename))
    files.append(("language model", repo_id, main_filename))

    if not report_progress:
        mmproj_path = None
        if mmproj_filename:
            mmproj_path = hf_hub_download(repo_id=repo_id, filename=mmproj_filename)
        main_path = hf_hub_download(repo_id=repo_id, filename=main_filename)
        return main_path, mmproj_path

    tracker = _MultiFileDownloadTracker(phase_id, files)
    paths = tracker.download_all()
    return paths[main_filename], paths.get(mmproj_filename) if mmproj_filename else None
