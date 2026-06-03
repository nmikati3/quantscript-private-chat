# Contributing to QuantScript

First of all, thank you for your interest in contributing!

## Getting started

### Prerequisites

- Node.js 20+
- Python 3.14+
- Rust stable toolchain (only needed for desktop builds)

### Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.lock
pip install -r requirements-dev.txt   # pytest, httpx
uvicorn app.api.main:app --host 127.0.0.1 --port 8000 --reload
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`. Vite proxies `/api` to the backend at
`localhost:8000`.

### Desktop app (dev mode)

```bash
cd frontend
npm run tauri:dev
```

## Running tests

### Backend

```bash
cd backend
source .venv/bin/activate
pytest tests/ -v
```

### Frontend

```bash
cd frontend
npm test            # single run
npm run test:watch  # watch mode
```

## Before opening a PR

1. **Run the tests** — both backend and frontend must pass.
2. **Run the security checks locally:**
  ```bash
   cd frontend && npm audit --audit-level=high && npm run desktop:verify
   cd ../frontend/src-tauri && cargo audit
   cd ../../backend && pip-audit -r requirements.lock
  ```
3. **Lint the frontend** — `cd frontend && npm run lint`.
4. **Keep commits focused** — one logical change per commit.

## Code style

- **Python:** No formal formatter is enforced yet. Follow the existing style
(4-space indent, type hints where practical).
- **TypeScript:** ESLint with `typescript-eslint` is configured. Run
`npm run lint` before committing.
- **Commit messages:** Use imperative mood ("Add error boundary", not "Added
error boundary"). Keep the subject line under 72 characters.

## Architecture overview


| Layer         | Location               | Tech                       |
| ------------- | ---------------------- | -------------------------- |
| Desktop shell | `frontend/src-tauri/`  | Rust / Tauri 2             |
| Frontend      | `frontend/src/`        | React 19, TypeScript, Vite |
| Backend       | `backend/app/`         | Python, FastAPI            |
| Storage       | `<app-data>/com.quantscript.desktop/storage/conversations/` | JSON files on disk |


The backend runs as a sidecar process bound to `127.0.0.1`. Communication is authenticated with a random per-launch sidecar token.

