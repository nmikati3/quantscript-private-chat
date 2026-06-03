# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the QuantScript backend sidecar.

Usage (run from the repo root):
    pyinstaller frontend/scripts/desktop/quantscript-backend.spec

Environment variables (set by build-sidecar.mjs):
    QUANTSCRIPT_OUTPUT_NAME  – final binary name including target triple
"""

import os
import platform
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules, collect_dynamic_libs, collect_data_files

block_cipher = None

REPO_ROOT = Path(SPECPATH).resolve().parent.parent.parent
BACKEND_DIR = REPO_ROOT / "backend"
LAUNCH_SCRIPT = Path(SPECPATH) / "launch_backend.py"

output_name = os.environ.get(
    "QUANTSCRIPT_OUTPUT_NAME",
    "quantscript-backend-" + platform.machine(),
)

# collect_submodules captures every runtime-loaded submodule for packages whose
# internals are resolved dynamically (protocol auto-loaders, validator plugins,
# schema engines, etc.).  Plain hidden-import entries are only used for small
# packages where the top-level name is sufficient.
hidden_imports = (
    collect_submodules("uvicorn")
    + collect_submodules("fastapi")
    + collect_submodules("starlette")
    + collect_submodules("pydantic")
    + collect_submodules("pydantic_core")
    + collect_submodules("anyio")
    + collect_submodules("slowapi")
    + collect_submodules("llama_cpp")
    + collect_submodules("huggingface_hub")
    + [
        # uvicorn runtime deps that are not always traced statically
        "h11",
        "click",
        "typing_extensions",
        "annotated_types",
        # multipart / dotenv
        "dotenv",
        "multipart",
        "python_multipart",
        # Data formats (pandas chooses an engine at read-time)
        "numpy",
        "pandas",
        "openpyxl",
        "pyarrow",
        "fastparquet",
        "rank_bm25",
        # Web search (webserp uses curl_cffi which has a C extension)
        "webserp",
        "webserp.cli",
        "curl_cffi",
        "requests",
        "bs4",
        "trafilatura",
        # PDF / images
        "pypdfium2",
        "pypdfium2_raw",
        "PIL",
    ]
)

# Native shared libraries (.dylib / .so / .dll) that are loaded via ctypes at
# runtime — collect_submodules does NOT pick these up.
native_binaries = (
    collect_dynamic_libs("llama_cpp")
    + collect_dynamic_libs("curl_cffi")
    + collect_dynamic_libs("pypdfium2_raw")
)

# Some packages store native libs as data files rather than binary extensions.
# pypdfium2 ships its bundled PDFium binary inside pypdfium2_raw as a data file.
native_data = (
    collect_data_files("llama_cpp", include_py_files=False, subdir="lib")
    + collect_data_files("pypdfium2_raw", include_py_files=False)
)

a = Analysis(
    [str(LAUNCH_SCRIPT)],
    pathex=[str(BACKEND_DIR)],
    binaries=native_binaries,
    # NOTE: never bundle backend/.env — it can carry secrets and is not even
    # user-editable once frozen into _MEIPASS. Runtime config comes from code
    # defaults plus a user-editable .env created in the app-data dir at launch
    # (see launch_backend.py).
    datas=[
        (str(BACKEND_DIR / "app"), "backend/app"),
    ] + native_data,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # GUI / dev-tooling
        "tkinter",
        "matplotlib",
        "IPython",
        "notebook",
        "test",
        # PDF rendering uses pypdfium2; actively exclude PyMuPDF/fitz so a
        # stray transitive dep can't drag the (AGPL) library back into the
        # bundle. `yaml` is intentionally NOT excluded — huggingface_hub has
        # top-level yaml imports in some submodules reached via error paths.
        "fitz",
        "pymupdf",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name=output_name,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # UPX-packed binaries cannot be reliably code-signed and are rejected by
    # Apple's notary service, so keep compression off for signed releases.
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
