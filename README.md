# QuantScript - A private, free and somewhat sustainable alternative to ChatGPT.

A free, local, private, and open-source alternative to ChatGPT.

Great for day-to-day chats, for brainstorming private business ideas without anybody watching, analyzing sensitive documents, asking for feedback on your resume etc.

## Features

- **Private, local-first**: the app only communicates with the outside world when using web search or deep research. The user has full control on whether to use these features or not. All inference, search, and storage happens on your laptop. **No accounts, no cloud, no telemetry.** The app does not phone home.
- **Sustainable (-ish)**: the app only runs the small, yet powerful, gemma4 4B model using your laptop's own power. Therefore, it consumes far less energy than calling bigger models from servers. The main energy cost was gemma's model training.
- **Works offline**: the app only needs to download the LLM model once at first use but then, works 100% offline.

### Other features

- **Deep Research - Lite**: the app can run a lighter version of Deep Research even with a lightweight gemma4 4B model.
- **Web Search**: the app can search the web.
- **No third-party API keys required.**

## Links/Contact

Website: [https://quantscript.io/](https://quantscript.io/)
Email: [info@quantscript.io](mailto:info@quantscript.io)

## Hardware requirements

The default settings maximize user experience while minimizing memory and compute utilization, therefore the dmg version runs on a lightweight model: `unsloth/gemma-4-E4B-it-GGUF` (the `Q8_0` GGUF quant by default) through `llama-cpp-python`. Users with more powerful machines can use more powerful models in the browser version by adjusting the environment variables in the .env file for the backend.

QuantScript runs the model entirely on your own machine, so requirements scale with the model you choose. For the default lightweight Gemma 4 (E4B) build:


| Resource          | Minimum                    | Recommended  |
| ----------------- | -------------------------- | ------------ |
| OS (desktop app)  | macOS 10.15, Apple Silicon | Latest macOS |
| OS (browser mode) | Any OS with Python 3.14+   | —            |
| Unified Memory    | 24 GB                      | 24 GB+       |


Larger or higher-precision models need proportionally more RAM and disk. Browser mode runs on Intel Macs, Linux, and Windows; the prebuilt desktop `.dmg` is Apple Silicon only.

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

## Install (end users)

QuantScript runs **fully locally** and supports two deployment modes. Both keep all inference and storage on your own machine.

### Option 1 — Desktop app (macOS only)

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

Then open the URL printed by Vite (e.g. `http://localhost:4173`). The first launch downloads the model once; after that it works offline.

> **Security note:** in browser mode the local API has **no sidecar token** and is reachable by any process running under your user account. This is the intended trade-off for a single-user machine. See [SECURITY.md](SECURITY.md) › "Security model & trust boundaries".

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


| Data               | Location                                                                       | Leaves your machine?        |
| ------------------ | ------------------------------------------------------------------------------ | --------------------------- |
| Chat conversations | `~/Library/Application Support/com.quantscript.desktop/storage/conversations/` | No                          |
| LLM model weights  | `~/Library/Application Support/com.quantscript.desktop/models/`                | No                          |
| Hugging Face cache | `~/Library/Application Support/com.quantscript.desktop/cache/`                 | No                          |
| Temp uploads       | `~/Library/Application Support/com.quantscript.desktop/tmp/`                   | Cleaned after each response |


The only outbound network traffic is:

- Hugging Face Hub, on first launch (to download the model).
- Search engines via `webserp`, only when you toggle **Search** or run **Deep Research** on a message.
- Article URLs returned by those searches.

> **What leaves your machine when you use Search / Deep Research:** these features are **opt-in per message and off by default**. When you enable them, a search query **derived from your message (and recent conversation context)** is sent to a third-party search engine, and the resulting article URLs are fetched. In other words, "local and private" means *no conversation content leaves your machine by default*, but enabling Search/Deep Research necessarily transmits query content externally so the model can read the web. Leave these toggles off to stay fully offline (after the one-time model download).

## Continuous integration

The workflow at
[.github/workflows/security-checks.yml](.github/workflows/security-checks.yml)
runs on every PR, push to `main`, and `v`* release tag:


| Check                       | Tool                                              |
| --------------------------- | ------------------------------------------------- |
| Python dependency audit     | `pip-audit` against `requirements.lock`           |
| Backend tests               | `pytest` over `backend/tests/`                    |
| Rust dependency audit       | `cargo audit` against `Cargo.lock`                |
| NPM dependency audit        | `npm audit --audit-level=high`                    |
| Frontend tests              | `npm test` (Vitest)                               |
| Desktop config verification | `npm run desktop:verify` (CSP, externalBin, etc.) |
| Sensitive-file scan         | `rg` regex over the bundled backend resources     |


## License

Apache License 2.0 — see `LICENSE` for terms.

### Model & third-party licenses

QuantScript automatically downloads the default model (`unsloth/gemma-4-E4B-it-GGUF`, a GGUF build of Google's **Gemma 4**) from HuggingFace on first launch. Gemma 4 is released under the [Apache License 2.0](https://www.apache.org/licenses/LICENSE-2.0); the same permissive license as QuantScript itself. (Note: this differs from earlier Gemma generations, which used Google's custom *Gemma Terms of Use*.)

As with any Apache-2.0 component, "Gemma" remains a Google trademark: you may say an app is "powered by Gemma," but the license grants no trademark rights and does not imply Google endorsement. See [NOTICE](NOTICE) for the full list of bundled third-party components and their licenses.