# QuantScript - A zero-config, local, ChatGPT alternative that works even on 8GB laptops.

No config needed, no need to choose the right model and quantization, the app automatically scales to your hardware and chooses the best model out of the gemma4 suite, that will work privately and locally on your laptop, starting from 8GB RAM.

Great for private day-to-day chats, for brainstorming business ideas without anybody watching, analyzing sensitive documents, asking for feedback on your resume etc.

[https://github.com/user-attachments/assets/4da50680-bcb2-4de5-bf5b-5ff9e6aaf701](https://github.com/user-attachments/assets/4da50680-bcb2-4de5-bf5b-5ff9e6aaf701)

## Features

- **Zero-config**: download the app and open it, and you're good to go: it will automatically choose the best model for your hardware and will work directly without any actions needed on your end.
- **Cross-platform**: native desktop apps for **macOS, Windows and Linux**, plus a browser mode for any OS that runs Python.
- **Private, local-first**: the app only communicates with the outside world when using web search or deep research. The user has full control on whether to use these features or not. All inference, search, and storage happens on your laptop. **No accounts, no cloud, no telemetry.** The app does not phone home.
- **Works on 8GB RAM**: the app works on laptops with low memory, starting at 8GB RAM, on macOS, Windows and Linux alike — the model auto-scales to the memory it detects.
- **Deep Research - Lite** (from 16GB RAM): the app can run a lighter version of Deep Research even with a lightweight gemma4 model.

## Installation

QuantScript runs **fully locally** and supports two deployment modes. Both keep all inference and storage on your own machine.

### Option 1 — Desktop app (macOS, Windows, Linux)

A one-click native app. No Python or terminal required. Download the build for
your platform from the **[latest release](https://github.com/nmikati3/quantscript-private-chat/releases/latest)**:


| Platform                      | Asset                                  | Signing                     |
| ----------------------------- | -------------------------------------- | --------------------------- |
| macOS (Apple Silicon, M1–M4)  | `QuantScript_<version>_aarch64.dmg`    | Signed & notarized by Apple |
| macOS (Intel, x86-64)         | `QuantScript_<version>_x64.dmg`        | Signed & notarized by Apple |
| Windows 10/11 (x86-64)        | `QuantScript_<version>_x64-setup.exe`  | Unsigned (see note ↓)       |
| Linux (Debian/Ubuntu, x86-64) | `QuantScript_<version>_amd64.deb`      | Unsigned                    |
| Linux (portable, x86-64)      | `QuantScript_<version>_amd64.AppImage` | Unsigned                    |


Every asset ships with a matching `.sha256` checksum so you can verify the download. Pick the macOS build that matches your chip: **`aarch64`** for Apple Silicon (M1–M4) and **`x64`** for Intel Macs — an Apple Silicon build will not run on Intel and vice-versa.

> **Unsigned Windows/Linux builds.** Because the Windows and Linux installers
> are not yet code-signed, the OS will warn you on first launch:
>
> - **Windows:** SmartScreen shows "Windows protected your PC." Click **More info → Run anyway**.
> - **Linux (AppImage):** `chmod +x QuantScript_*.AppImage` and run it. The `.deb` installs with `sudo apt install ./QuantScript_*.deb`.
>
> See [SECURITY.md](SECURITY.md) › "Code signing & distribution" for the full per-platform story and how to verify checksums.

### Option 2 — Browser mode (any OS)

Run the local backend yourself and open the web UI in your browser. This works on **any OS that can run Python 3.14+** (macOS, Linux, Windows), including Intel Macs and machines without Apple Silicon.

```bash
# 1. Backend (serves the local API on 127.0.0.1:8000)
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.lock
uvicorn app.api.main:app --host 127.0.0.1 --port 8000

# 2. Frontend (in a second terminal)
cd frontend
npm install
npm run build && npm run preview                     # or `npm run dev` for hot-reload
```

The auto-tiering system that scales the model to your hardware now runs on **macOS, Windows and Linux** in both desktop and browser mode. You can still override the model choice via the backend `.env` file (see [Hardware requirements](#hardware-requirements)) if you want to pin a specific model or quant.

Then open the URL printed by Vite (e.g. `http://localhost:4173`). The first launch downloads the model once; after that it works offline.

> **Security note:** in browser mode the local API has **no sidecar token** and is reachable by any process running under your user account. This is the intended trade-off for a single-user machine. See [SECURITY.md](SECURITY.md) › "Security model & trust boundaries".

## Links/Contact

Website: [https://quantscript.io/](https://quantscript.io/)
Email: [info@quantscript.io](mailto:info@quantscript.io)

## Hardware requirements

QuantScript runs the model entirely on your own machine through `llama-cpp-python`, so requirements scale with the model. The desktop app **auto-detects your installed memory (RAM) at startup** and picks the largest Gemma 4 variant that fits, so it runs on everything starting from an 8 GB laptop without any configuration. Memory detection is platform-specific — `sysctl hw.memsize` on macOS, `GlobalMemoryStatusEx` on Windows, and `sysconf` on Linux — so tiering works the same across all three. Deep Research - Lite only runs from 16GB onwards.


| Detected memory (RAM) | Model (auto-selected)                       | Context window |
| --------------------- | ------------------------------------------- | -------------- |
| < 16 GB               | Gemma 4 **E2B** QAT, `UD-Q4_K_XL` (~2.6 GB) | 8K             |
| 16 GB – 24 GB         | Gemma 4 **E4B** QAT, `UD-Q4_K_XL` (~4.2 GB) | 16K            |
| ≥ 24 GB               | Gemma 4 **E4B**, `Q8_0` (~8.2 GB)           | 32K            |


On Windows and Linux the OS reports slightly less than the installed RAM (it excludes firmware-, kernel-, and integrated-GPU-reserved memory), so QuantScript applies a small tolerance when picking a tier — a "16 GB" machine still lands in the mid tier. If your machine sits right on a boundary, pin a tier with the `QUANTSCRIPT_TOTAL_MEMORY_BYTES` environment variable (e.g. `QUANTSCRIPT_TOTAL_MEMORY_BYTES=17179869184` to force the 16 GB tier).

If you see the chat returning inconsistent answers or being very slow, try closing other apps as it usually helps. **On an 8 GB machine this matters a lot:** the model, the OS, and the app's own webview together use most of your RAM, so quit other memory-hungry apps (browsers, IDEs, Docker, etc.) before a session — especially before running Deep Research.

Deep Research is the most memory-intensive feature. It is currently not supported on machines under 16 GB. However, the implementation is there potentially implement in the future an automatic switch to fewer planning rounds, searches, articles, and a smaller token budget so it can finish on modest hardware.

Vision/attachment support works on every tier. More memory means a higher-quality quant and a larger context window; lower tiers stay responsive on modest hardware.


| Resource          | Minimum                                                    | Recommended |
| ----------------- | ---------------------------------------------------------- | ----------- |
| OS (desktop app)  | macOS 10.15 (Apple Silicon or Intel), Windows 10 (x64), Linux (x64) | Latest OS   |
| OS (browser mode) | Any OS with Python 3.14+                                   | —           |
| Memory (RAM)      | 8 GB                                                       | 24 GB+      |


You can override the auto-selection (model, quant, and context window) with the `LLAMA_REPO_ID`, `LLAMA_FILENAME`, `LLAMA_MMPROJ_FILENAME`, and `N_CTX` environment variables — e.g. to run a larger model in browser mode via the backend `.env`. Browser mode runs on Intel Macs, Linux, and Windows; the prebuilt desktop apps cover Apple Silicon and Intel macOS, x86-64 Windows, and x86-64 Linux.

## Repository layout

```
quantscript-private-chat/
├── backend/                     Python FastAPI backend (runs as a sidecar)
│   ├── app/
│   │   ├── api/                 Routes and app entry point
│   │   ├── core/                Middleware, sanitization, startup state
│   │   ├── engine/              LLM inference, deep research, attachments
│   ├── tests
│   ├── requirements-dev.txt
│   ├── requirements.txt
│   └── requirements.lock
├── frontend/                    Vite + React + TypeScript
│   ├── src/                     Application source
│   ├── src-tauri/               Tauri desktop shell (Rust)
│   └── scripts/desktop/         Desktop build tooling
├── .github/                     Issue/PR templates and CI workflows
├── CONTRIBUTING.md              Contributor guidelines
├── CODE_OF_CONDUCT.md           Community standards
├── SECURITY.md                  Security policy and trust boundaries
├── CHANGELOG.md                 Release notes
├── NOTICE                       Third-party attribution
└── LICENSE                      Apache License 2.0
```

## Local development

### Prerequisites

- Node.js 20+
- Python 3.14+
- Rust stable toolchain (`rustup default stable`)
- PyInstaller (`pip install pyinstaller`) — installed automatically by the
desktop build scripts
- For desktop builds, the per-OS prerequisites listed under
[Building the desktop app](#building-the-desktop-app)

### Backend (dev server)

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.lock
uvicorn app.api.main:app --host 127.0.0.1 --port 8000 --reload
```

### Frontend (web preview)

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`. Vite proxies `/api` to the backend at
`localhost:8000`.

### Building the desktop app

The desktop app bundles a PyInstaller sidecar of the backend, so **builds are
per-OS and cannot be cross-compiled** — you build the macOS app on macOS, the
Windows app on Windows, and the Linux app on Linux. From `frontend/`:

```bash
npm run tauri:build          # builds the right installers for the current OS
```

This picks sensible bundle targets per platform (`app,dmg` on macOS, `nsis` on
Windows, `deb,appimage` on Linux); override with `npm run tauri:build -- --bundles=<list>`.

Per-platform build prerequisites:

- **macOS:** Xcode command-line tools.
- **Windows:** Visual Studio Build Tools (MSVC) + CMake (for `llama-cpp-python`).
WebView2 is preinstalled on Windows 10/11.
- **Linux:** `libwebkit2gtk-4.1-dev`, `libgtk-3-dev`, `librsvg2-dev`,
`libayatana-appindicator3-dev`, `libsoup-3.0-dev`, `patchelf`,
`build-essential`, `cmake`, `file`, and `libfuse2` (for AppImage). See the
exact list in `.github/workflows/release.yml`.

> **Don't have all three machines?** The repo's
> [release workflow](.github/workflows/release.yml) builds, checksums, and
> publishes macOS, Windows, and Linux installers in parallel on GitHub-hosted
> runners — so you can produce every platform's build from CI even if you only
> own one OS. Push a `v`* tag (or run the workflow manually) and collect the
> artifacts from the draft Release.

## How the desktop app works

Tauri wraps the React frontend in the platform's native webview — **WKWebView**
on macOS, **WebView2** (Edge/Chromium) on Windows, and **WebKitGTK** on Linux.
On launch:

1. The frontend invokes the Rust shell command `start_backend_sidecar`.
2. Rust generates a 32-byte random sidecar token and picks a random
  high-ephemeral loopback port.
3. Rust launches the PyInstaller sidecar binary (or, in dev mode, falls back
  to `python3 -m uvicorn` from source).
4. Rust authenticates backend startup with `/startup_status_probe` (a nonce-
  bound HMAC-SHA256 proof), then polls `/startup_status` while models load.
5. The base URL and token are returned to the frontend, which attaches the
  token to every request via the `X-Sidecar-Token` header.
6. On window close, the Rust shell kills the backend process.

## Where your data lives

All data lives under the OS's per-user application-data directory, in a
`com.quantscript.desktop` folder. None of it leaves your machine.


| OS      | Application-data root                                                                                 |
| ------- | ----------------------------------------------------------------------------------------------------- |
| macOS   | `~/Library/Application Support/com.quantscript.desktop/`                                              |
| Windows | `%APPDATA%\com.quantscript.desktop\` (i.e. `C:\Users\<you>\AppData\Roaming\com.quantscript.desktop\`) |
| Linux   | `~/.local/share/com.quantscript.desktop/`                                                             |


Inside that folder:


| Data               | Subpath                          | Leaves your machine? |
| ------------------ | -------------------------------- | -------------------- |
| Chat conversations | `storage/conversations/`         | No                   |
| LLM model weights  | `models/`                        | No                   |
| Hugging Face cache | `cache/`                         | No                   |
| User config        | `.env` (edit to override models) | No                   |


The only outbound network traffic is:

- Hugging Face Hub, on first launch (to download the model).
- Search engines via `webserp`, only when you toggle **Search** or run **Deep Research** on a message.
- Article URLs returned by those searches.

> **What leaves your machine when you use Search / Deep Research:** these features are **opt-in per message and off by default**. When you enable them, a search query **derived from your message (and recent conversation context)** is sent to a third-party search engine, and the resulting article URLs are fetched. In other words, "local and private" means *no conversation content leaves your machine by default*, but enabling Search/Deep Research necessarily transmits query content externally so the model can read the web. Leave these toggles off to stay fully offline (after the one-time model download).

## License

Apache License 2.0 — see `LICENSE` for terms.

### Model & third-party licenses

QuantScript automatically downloads a GGUF build of Google's **Gemma 4** from HuggingFace on first launch, depending on your hardware (see [Hardware requirements](#hardware-requirements)): the QAT (quantization-aware training) `unsloth/gemma-4-E2B-it-qat-GGUF` or `unsloth/gemma-4-E4B-it-qat-GGUF` on machines under 24 GB, or `unsloth/gemma-4-E4B-it-GGUF` (`Q8_0`) on machines with 24 GB or more. Gemma 4 is released under the [Apache License 2.0](https://www.apache.org/licenses/LICENSE-2.0); the same permissive license as QuantScript itself. (Note: this differs from earlier Gemma generations, which used Google's custom *Gemma Terms of Use*.)

As with any Apache-2.0 component, "Gemma" remains a Google trademark: you may say an app is "powered by Gemma," but the license grants no trademark rights and does not imply Google endorsement. See [NOTICE](NOTICE) for the full list of bundled third-party components and their licenses.