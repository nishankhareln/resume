# Maya — React + Tailwind chat UI

A polished chat frontend for the AI career coach. It talks to the FastAPI
backend (`../chat_api.py`), which reuses all the existing Python brains
(Gemini, resume parsing, OCR) — no logic was rewritten in JS.

```
frontend/  ← this folder (React + Vite + Tailwind v4)
   └── talks to → /api/*  (proxied to http://localhost:8000)
../chat_api.py  ← FastAPI backend, wraps chat_service.py
```

## One-time setup

You need **Node.js 18+** (not currently installed on this machine).
Get it from https://nodejs.org — the LTS installer. Then:

```bash
cd "D:/resume 2/frontend"
npm install
```

## Run it (two terminals)

**Terminal 1 — the Python backend** (from the project root):

```bash
cd "D:/resume 2"
.\venv\Scripts\python.exe -m uvicorn chat_api:app --reload --port 8000
```

**Terminal 2 — the React frontend:**

```bash
cd "D:/resume 2/frontend"
npm run dev
```

Open the URL Vite prints (usually http://localhost:5173).

## What you get

- A real chat UI with message bubbles and a live "typing" stream.
- Attach a resume PDF (top-right) to make Maya's advice personal.
- Starter prompts, markdown answers, auto-scroll, responsive layout.

## Production build (optional)

```bash
npm run build        # outputs to frontend/dist
```

`chat_api.py` auto-serves `frontend/dist` if it exists, so after a build you
can run **just** the backend (`uvicorn chat_api:app --port 8000`) and open
http://localhost:8000 — no Node needed at runtime.
