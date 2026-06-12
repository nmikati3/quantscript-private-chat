#!/usr/bin/env python3
"""Desktop sidecar entrypoint for launching the FastAPI backend safely.

When frozen with PyInstaller this script is the single executable entry point.
It runs uvicorn in-process (no subprocess) so all bundled packages are available.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import sys
import time


def _ensure_backend_on_path(backend_dir: pathlib.Path) -> None:
    """Make sure the backend package is importable."""
    bd = str(backend_dir)
    if bd not in sys.path:
        sys.path.insert(0, bd)


def _setup_sidecar_logging(data_dir: pathlib.Path) -> None:
    """Point the frozen sidecar's stdout/stderr at a log file in the app-data dir.

    The bundled (windowed) desktop app has no console, and the Rust launcher
    discards the sidecar's stdout and keeps only a small slice of stderr — and
    only when the process exits early. So when the backend is merely *slow* to
    import (e.g. a cold PyInstaller one-file extract + heavy imports on an older
    Intel Mac) or crashes in an unusual way, there is nothing left to diagnose.

    Redirecting fds 1/2 to a file captures everything: Python logging, uvicorn
    output, tracebacks, and native dynamic-loader / abort messages. No-op in dev
    (not frozen), where output goes to the inherited terminal instead.
    """
    if not getattr(sys, "frozen", False):
        return
    try:
        log_dir = data_dir / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / "backend.log"
        # Keep the log bounded across launches without a full logging framework.
        try:
            if log_path.exists() and log_path.stat().st_size > 5_000_000:
                log_path.replace(log_dir / "backend.log.1")
        except OSError:
            pass
        log_fh = open(log_path, "a", buffering=1, encoding="utf-8", errors="replace")
    except OSError:
        return

    log_fh.write(
        f"\n===== sidecar session {time.strftime('%Y-%m-%d %H:%M:%S')} "
        f"(pid={os.getpid()}) =====\n"
    )
    log_fh.flush()
    try:
        os.dup2(log_fh.fileno(), 1)
        os.dup2(log_fh.fileno(), 2)
    except (OSError, ValueError):
        pass
    # Reassign the Python-level streams too so logging/uvicorn (which capture
    # sys.stderr/sys.stdout) and print() write line-buffered to the same file.
    sys.stdout = log_fh
    sys.stderr = log_fh


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Launch QuantScript backend sidecar.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--backend-dir", default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.port < 1 or args.port > 65535:
        raise ValueError(f"Invalid port: {args.port}")
    if args.host not in ("127.0.0.1", "localhost"):
        raise ValueError("Desktop backend sidecar only supports loopback hosts.")

    if getattr(sys, "frozen", False):
        base_dir = pathlib.Path(sys._MEIPASS)  # noqa: PyInstaller runtime attribute
        backend_dir = base_dir / "backend"
    else:
        script_dir = pathlib.Path(__file__).resolve().parent
        default_backend_dir = (script_dir / ".." / ".." / ".." / "backend").resolve()
        backend_dir = pathlib.Path(args.backend_dir).resolve() if args.backend_dir else default_backend_dir

    if not backend_dir.exists():
        raise FileNotFoundError(f"Backend directory not found: {backend_dir}")

    _ensure_backend_on_path(backend_dir)

    import dotenv  # noqa: E402

    # User-editable config lives in the writable app-data dir so it persists
    # across launches and updates (the bundled backend dir is a read-only
    # _MEIPASS temp dir, recreated every launch). Seed a secret-free template
    # on first run so users can experiment with different local models.
    data_dir = pathlib.Path(os.environ.get("QUANTSCRIPT_DATA_DIR", str(backend_dir)))
    _setup_sidecar_logging(data_dir)
    print(f"[launch] sidecar starting on {args.host}:{args.port} (data_dir={data_dir})", flush=True)
    user_env = data_dir / ".env"
    if not user_env.exists():
        try:
            data_dir.mkdir(parents=True, exist_ok=True)
            user_env.write_text(
                "# QuantScript configuration — edit and restart to apply.\n"
                "# Uncomment and change these to try a different local model.\n"
                "# LLAMA_REPO_ID=unsloth/gemma-4-E4B-it-GGUF\n"
                "# LLAMA_FILENAME=gemma-4-E4B-it-Q8_0.gguf\n"
                "# LLAMA_MMPROJ_FILENAME=mmproj-F16.gguf\n"
                "# N_CTX=32768\n"
            )
        except OSError:
            pass
    dotenv.load_dotenv(user_env, override=True)

    os.environ.setdefault("ALLOWED_HOSTS", "127.0.0.1,localhost")
    os.environ.setdefault(
        "CORS_ORIGINS",
        "tauri://localhost,http://tauri.localhost,http://localhost:5173",
    )

    import uvicorn  # noqa: E402

    # Import timing is logged so a slow first launch (cold one-file extract +
    # heavy native imports on older/low-RAM machines) is visible in backend.log
    # instead of looking like a silent hang on the "Launching backend…" screen.
    print("[launch] importing backend application…", flush=True)
    _import_start = time.time()
    from app.api.main import app as application  # noqa: E402
    print(f"[launch] backend import finished in {time.time() - _import_start:.1f}s", flush=True)

    print(f"[launch] starting uvicorn on {args.host}:{args.port}", flush=True)
    uvicorn.run(
        application,
        host=args.host,
        port=args.port,
        log_level="info",
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        import traceback
        traceback.print_exc()
        raise SystemExit(1)
