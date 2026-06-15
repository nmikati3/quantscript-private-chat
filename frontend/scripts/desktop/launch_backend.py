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


def _ensure_backend_on_path(backend_dir: pathlib.Path) -> None:
    """Make sure the backend package is importable."""
    bd = str(backend_dir)
    if bd not in sys.path:
        sys.path.insert(0, bd)


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
    from app.api.main import app as application  # noqa: E402

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
