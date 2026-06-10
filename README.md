# QuantScript - A zero-config, local, ChatGPT alternative that works even on 8GB laptops.

No config needed, no need to choose the right model and quantization, the app automatically scales to your hardware and chooses the best model out of the gemma4 suite, that will work privately and locally on your laptop, starting from 8GB RAM.

Great for private day-to-day chats, for brainstorming business ideas without anybody watching, analyzing sensitive documents, asking for feedback on your resume etc.

[https://github.com/user-attachments/assets/4da50680-bcb2-4de5-bf5b-5ff9e6aaf701](https://github.com/user-attachments/assets/4da50680-bcb2-4de5-bf5b-5ff9e6aaf701)

## Features

- **Zero-config**: download the app and open it, and you're good to go: it will automatically choose the best model for your hardware and will work directly without any actions needed on your end.
- **Private, local-first**: the app only communicates with the outside world when using web search or deep research. The user has full control on whether to use these features or not. All inference, search, and storage happens on your laptop. **No accounts, no cloud, no telemetry.** The app does not phone home.
- **Works on 8GB RAM**: the app works on laptops with low memory, starting at 8GB RAM for Mac users.
- **Deep Research - Lite**: the app can run a lighter version of Deep Research even with a lightweight gemma4 model. Deep Research - Lite works from 8GB RAM but we recommend at least 16GB RAM for better results.

## Installation

QuantScript runs **fully locally** and supports two deployment modes. Both keep all inference and storage on your own machine.

### Option 1 — Desktop app (macOS only for now)

A one-click native macOS app. No Python or terminal required.

**macOS, Apple Silicon only** (for now):


| Chip                        | Download                                                                                                                                   |
| --------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| Apple Silicon (M1/M2/M3/M4) | [QuantScript 0.1.0 (aarch64)](https://github.com/nmikati3/quantscript-private-chat/releases/download/v0.1.0/QuantScript_0.1.0_aarch64.dmg) |


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

**Windows users**: the auto-tiering system that scales the model based on your hardware is not configured for Windows yet. In browser mode on Windows, the app will default to the lightest model available. Users can override the model choice using the .env file in the backend and choose a bigger model if needed.

Then open the URL printed by Vite (e.g. `http://localhost:4173`). The first launch downloads the model once; after that it works offline.

> **Security note:** in browser mode the local API has **no sidecar token** and is reachable by any process running under your user account. This is the intended trade-off for a single-user machine. See [SECURITY.md](SECURITY.md) › "Security model & trust boundaries".

## Links/Contact

Website: [https://quantscript.io/](https://quantscript.io/)
Email: [info@quantscript.io](mailto:info@quantscript.io)

## Hardware requirements

QuantScript runs the model entirely on your own machine through `llama-cpp-python`, so requirements scale with the model. The desktop app **auto-detects your unified memory at startup** and picks the largest Gemma 4 variant that fits, so it runs on everything starting from an 8 GB MacBook without any configuration:


| Detected unified memory | Model (auto-selected)                       | Context window |
| ----------------------- | ------------------------------------------- | -------------- |
| < 16 GB                 | Gemma 4 **E2B** QAT, `UD-Q4_K_XL` (~2.6 GB) | 8K             |
| 16 GB – 24 GB           | Gemma 4 **E4B** QAT, `UD-Q4_K_XL` (~4.2 GB) | 16K            |
| ≥ 24 GB                 | Gemma 4 **E4B**, `Q8_0` (~8.2 GB)           | 32K            |


If you see the chat returning inconsistent answers or being very slow, try closing other apps as it usually helps. **On an 8 GB machine this matters a lot:** the model, macOS, and the app's own webview together use most of your RAM, so quit other memory-hungry apps (browsers, IDEs, Docker, etc.) before a session — especially before running Deep Research.

Deep Research is the most memory-intensive feature. On machines under 16 GB the app automatically switches to fewer planning rounds, searches, articles, and a smaller token budget so it can finish on modest hardware. If it still errors out on an 8 GB machine, close other apps and retry, or dial it down further via the env vars below (`MAX_RESEARCHER_ITERATIONS`, `MAX_RESEARCHER_SEARCHES`, `RESEARCH_ARTICLES_PER_SEARCH`, `MAX_TOKENS_COMPRESSION`, `MAX_TOKENS_FINAL_REPORT`).

Vision/attachment support works on every tier. More memory means a higher-quality quant and a larger context window; lower tiers stay responsive on modest hardware.


| Resource          | Minimum                    | Recommended  |
| ----------------- | -------------------------- | ------------ |
| OS (desktop app)  | macOS 10.15, Apple Silicon | Latest macOS |
| OS (browser mode) | Any OS with Python 3.14+   | —            |
| Unified Memory    | 8 GB                       | 24 GB+       |


You can override the auto-selection (model, quant, and context window) with the `LLAMA_REPO_ID`, `LLAMA_FILENAME`, `LLAMA_MMPROJ_FILENAME`, and `N_CTX` environment variables — e.g. to run a larger model in browser mode via the backend `.env`. Browser mode runs on Intel Macs, Linux, and Windows; the prebuilt desktop `.dmg` is Apple Silicon only.

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
- PyInstaller (`pip install pyinstaller`)

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

## How the desktop app works

Tauri wraps the React frontend in a native macOS webview. On launch:

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


| Data               | Location                                                                       | Leaves your machine? |
| ------------------ | ------------------------------------------------------------------------------ | -------------------- |
| Chat conversations | `~/Library/Application Support/com.quantscript.desktop/storage/conversations/` | No                   |
| LLM model weights  | `~/Library/Application Support/com.quantscript.desktop/models/`                | No                   |
| Hugging Face cache | `~/Library/Application Support/com.quantscript.desktop/cache/`                 | No                   |


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