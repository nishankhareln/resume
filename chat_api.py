"""
chat_api
========

A small FastAPI backend that exposes the career-coach chatbot to a real
frontend (the React + Tailwind app in ./frontend).

Why this exists
---------------
All the intelligence in this project is Python — Gemini via langchain, local
sentence-transformers embeddings, PyMuPDF/Tesseract PDF parsing. None of that
has a clean JavaScript equivalent. So instead of rewriting it, we keep the
Python as a thin API and let a polished JS frontend talk to it. This is the
same shape almost every production AI app uses.

Endpoints
---------
  GET  /api/health   -> sanity check + which model is wired up
  POST /api/resume   -> upload a PDF, get back a "background" briefing the
                        coach uses to personalize answers (+ a small profile)
  POST /api/chat      -> stream the assistant's reply for a conversation

The chat reply is streamed as plain UTF-8 text chunks so the frontend can show
a realistic "typing" effect by appending tokens as they arrive.

Run it:
    uvicorn chat_api:app --reload --port 8000
"""

from __future__ import annotations

import logging
import os
from typing import List, Optional

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app import extract_text_from_pdf, get_llm_model, parse_resume
from chat_service import ASSISTANT_NAME, build_background, stream_reply

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="Resume Career-Coach Chat API", version="1.0.0")

# The React dev server runs on a different port (Vite :5173) during development.
# In production the Vite proxy makes it same-origin, but allowing localhost here
# means it works either way without surprises.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Lazy, cached model init (don't pay the cost until first real use) -------
_llm = None


def get_llm():
    global _llm
    if _llm is None:
        logger.info("Initializing Gemini LLM for the chat API…")
        _llm = get_llm_model()
    return _llm


# --- Request/response shapes -------------------------------------------------
class ChatMessage(BaseModel):
    role: str  # "user" | "assistant"
    content: str


class ChatRequest(BaseModel):
    messages: List[ChatMessage]
    # Optional resume briefing from /api/resume; the coach personalizes with it.
    background: Optional[str] = ""


class _UploadShim:
    """Adapts FastAPI's UploadFile to the tiny interface `extract_text_from_pdf`
    expects from a Streamlit upload (`.name` + `.getbuffer()`), so we reuse the
    existing OCR-capable extractor instead of duplicating it."""

    def __init__(self, name: str, data: bytes):
        # Strip any directory parts a browser might send, keep a safe filename.
        self.name = os.path.basename(name or "resume.pdf")
        self._data = data

    def getbuffer(self) -> bytes:
        return self._data


# --- Routes ------------------------------------------------------------------
@app.get("/api/health")
def health() -> dict:
    return {
        "status": "ok",
        "assistant": ASSISTANT_NAME,
        "model": os.getenv("GEMINI_MODEL", "gemini-2.0-flash"),
    }


@app.post("/api/resume")
async def upload_resume(file: UploadFile = File(...), target_role: str = Form("")) -> dict:
    """Parse an uploaded resume PDF into a short briefing the coach can use.

    One Gemini call (the parse). Returns a 'background' string the frontend
    holds and sends back with each chat message, plus a tiny profile preview.
    """
    data = await file.read()
    text = extract_text_from_pdf(_UploadShim(file.filename, data)) or ""
    if not text.strip():
        return {"ok": False, "error": "I couldn't read any text from that PDF. Is it a scanned image with no OCR layer?"}

    try:
        info = parse_resume(text, get_llm())
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Resume parse failed: {e}")
        return {"ok": False, "error": f"Couldn't parse that resume ({e})."}

    if not info:
        return {"ok": False, "error": "Couldn't extract structured details from that resume."}

    background = build_background(info, None, (target_role or "").strip() or None)
    profile = {
        "name": info.name,
        "job_title": info.job_title,
        "experience_years": info.experience_years,
        "skills": info.skills or [],
    }
    return {"ok": True, "background": background, "profile": profile}


@app.post("/api/chat")
def chat(req: ChatRequest) -> StreamingResponse:
    """Stream the assistant's reply for the conversation so far.

    `messages` includes the latest user turn as the final item. Output is raw
    UTF-8 text chunks — the frontend appends them for a live typing effect.
    """
    history = [{"role": m.role, "content": m.content} for m in req.messages]

    def token_stream():
        for chunk in stream_reply(history, get_llm(), req.background or ""):
            yield chunk

    return StreamingResponse(
        token_stream(),
        media_type="text/plain; charset=utf-8",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# --- Optional: serve the built frontend (after `npm run build`) --------------
# In dev you'll use the Vite server (npm run dev). But if ./frontend/dist exists,
# we also serve it here so `uvicorn chat_api:app` alone opens the whole app.
_DIST = os.path.join(os.path.dirname(__file__), "frontend", "dist")
if os.path.isdir(_DIST):
    app.mount("/", StaticFiles(directory=_DIST, html=True), name="frontend")
    logger.info(f"Serving built frontend from {_DIST}")
