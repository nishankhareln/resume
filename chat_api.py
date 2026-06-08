"""
chat_api
========

FastAPI backend for the React career app. It exposes the existing Python
brains (Gemini, resume parsing/OCR, local embeddings, the offline job dataset)
to a polished frontend — nothing was rewritten in JS.

Endpoints
---------
  GET  /api/health           sanity check + which model is wired up
  POST /api/resume           upload a PDF -> parse, embed, open a session
  GET  /api/jobs             list/search jobs, ranked by match to the resume
  POST /api/chat              stream NK's reply (resume- AND job-aware)

Sessions
--------
On upload we keep a tiny in-memory session: the parsed resume, a "background"
briefing the coach uses, and the resume embedding (for job match scores). The
frontend gets a session_id and passes it back on /api/jobs and /api/chat, so we
don't resend the whole resume each time. In-memory is fine for a single-process
demo; swap for Redis if this ever goes multi-worker.

Run it:
    uvicorn chat_api:app --reload --port 8000
"""

from __future__ import annotations

import logging
import os
import uuid
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app import extract_text_from_pdf, get_embeddings_model, get_llm_model, parse_resume
from chat_service import ASSISTANT_NAME, build_background, format_job_context, stream_reply
from main_job_matcher import calculate_similarity, generate_embedding
from market_insight_service import load_jobs, offline_jobs_for_keywords
from hr_service import (  # recruiter mode: reuse the same grounded/fair screening logic
    _embed_resume,
    _guess_name,
    answer_question,
    screen_candidate,
    search_resumes,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="Career Coach API", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Lazy, cached models (don't pay the cost until first real use) -----------
_llm = None
_emb = None


def get_llm():
    global _llm
    if _llm is None:
        logger.info("Initializing Gemini LLM…")
        _llm = get_llm_model()
    return _llm


def get_emb():
    global _emb
    if _emb is None:
        logger.info("Initializing local embeddings…")
        _emb = get_embeddings_model()
    return _emb


# --- In-memory session + job-embedding caches --------------------------------
_SESSIONS: Dict[str, dict] = {}   # session_id -> {resume_text, info, background, embedding, keywords}
_JOB_EMB: Dict[str, list] = {}    # job id -> embedding (the 30 offline jobs, embedded once)
_HR_SESSIONS: Dict[str, List[dict]] = {}  # hr_session_id -> [candidate records {id,name,file,text,n_chars,embedding}]


# --- Request/response shapes -------------------------------------------------
class ChatMessage(BaseModel):
    role: str  # "user" | "assistant"
    content: str


class ChatRequest(BaseModel):
    messages: List[ChatMessage]
    session_id: Optional[str] = None        # preferred: pulls resume background server-side
    background: Optional[str] = ""           # fallback if no session
    job_context: Optional[Dict[str, Any]] = None  # the job the user is viewing (copilot mode)


class _UploadShim:
    """Adapts FastAPI's UploadFile to the tiny interface `extract_text_from_pdf`
    expects from a Streamlit upload (`.name` + `.getbuffer()`)."""

    def __init__(self, name: str, data: bytes):
        self.name = os.path.basename(name or "resume.pdf")
        self._data = data

    def getbuffer(self) -> bytes:
        return self._data


# --- Helpers -----------------------------------------------------------------
def _clean(v) -> Optional[str]:
    """Treat the dataset's 'N/A'/empty placeholders as missing."""
    if v is None:
        return None
    s = str(v).strip()
    return None if s in ("", "N/A", "n/a") else s


def _job_public(job: dict, idx: int, match_score: Optional[float]) -> dict:
    """Shape one job for the frontend (safe fields, trimmed description)."""
    return {
        "id": str(job.get("job_id") or f"job-{idx}"),
        "title": _clean(job.get("title")) or "Untitled role",
        "company": _clean(job.get("company")),
        "location": _clean(job.get("location")),
        "is_remote": bool(job.get("is_remote")),
        "url": _clean(job.get("job_url")),
        "description": (job.get("description") or "").strip()[:1500],
        "match_score": (round(float(match_score), 4) if match_score is not None else None),
    }


def _job_embedding(job: dict, idx: int):
    """Embed a job once and cache it (local model, free, no quota)."""
    key = str(job.get("job_id") or f"job-{idx}")
    if key in _JOB_EMB:
        return _JOB_EMB[key]
    text = job.get("text_for_embedding") or f"{job.get('title', '')} {job.get('description', '')}"
    emb = generate_embedding((text or "")[:4000], get_emb())
    if emb is not None:
        _JOB_EMB[key] = emb
    return emb


def _resume_blob(info) -> str:
    titles = " ".join([e.title for e in (info.work_experience or []) if getattr(e, "title", None)])
    return f"{info.summary or ''} {' '.join(info.skills or [])} {titles}".strip()


# --- Routes ------------------------------------------------------------------
@app.get("/api/health")
def health() -> dict:
    return {
        "status": "ok",
        "assistant": ASSISTANT_NAME,
        "model": os.getenv("GEMINI_MODEL", "gemini-2.0-flash"),
        "jobs_available": len(load_jobs()),
    }


@app.post("/api/resume")
async def upload_resume(file: UploadFile = File(...), target_role: str = Form("")) -> dict:
    """Parse an uploaded resume, embed it, and open a session.

    One Gemini call (the parse) + a free local embedding. Returns a session_id
    the frontend reuses for job matching and chat.
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

    # Resume embedding for job match scores (local model — free, no quota).
    try:
        resume_emb = generate_embedding(_resume_blob(info), get_emb())
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Resume embedding failed: {e}")
        resume_emb = None

    keywords = info.optimized_search_keywords or info.skills or ([info.job_title] if info.job_title else [])

    session_id = uuid.uuid4().hex
    _SESSIONS[session_id] = {
        "resume_text": text,
        "info": info,
        "background": background,
        "embedding": resume_emb,
        "keywords": keywords,
    }

    return {
        "ok": True,
        "session_id": session_id,
        "background": background,
        "profile": {
            "name": info.name,
            "job_title": info.job_title,
            "experience_years": info.experience_years,
            "skills": info.skills or [],
        },
    }


@app.get("/api/jobs")
def jobs(session_id: str = "", q: str = "", limit: int = 30) -> dict:
    """List/search jobs from the offline dataset, ranked by match to the resume.

    - `q`: free-text keywords (filters the dataset). Empty -> all jobs.
    - `session_id`: if present, every job gets a 0-1 match score vs. the resume
      and the list is sorted best-first. Match scoring is local + free.
    """
    all_jobs = load_jobs()
    sess = _SESSIONS.get(session_id) if session_id else None

    if q.strip():
        kws = [w for w in q.replace(",", " ").split() if len(w) > 1]
        selected = offline_jobs_for_keywords(kws, limit=limit) if kws else all_jobs[:limit]
    else:
        selected = all_jobs[:limit]

    resume_emb = sess.get("embedding") if sess else None
    out: List[dict] = []
    for idx, job in enumerate(selected):
        score = None
        if resume_emb is not None:
            jemb = _job_embedding(job, idx)
            if jemb is not None:
                score = float(calculate_similarity(resume_emb, jemb))
        out.append(_job_public(job, idx, score))

    if resume_emb is not None:
        out.sort(key=lambda j: (j["match_score"] or 0.0), reverse=True)

    return {"ok": True, "count": len(out), "has_resume": bool(sess), "jobs": out}


@app.post("/api/chat")
def chat(req: ChatRequest) -> StreamingResponse:
    """Stream NK's reply. Resume-aware via session_id; job-aware via job_context."""
    history = [{"role": m.role, "content": m.content} for m in req.messages]

    sess = _SESSIONS.get(req.session_id or "")
    background = sess["background"] if sess else (req.background or "")
    if req.job_context:
        block = format_job_context(req.job_context)
        if block:
            background = (background + "\n\n" + block).strip()

    def token_stream():
        for chunk in stream_reply(history, get_llm(), background):
            yield chunk

    return StreamingResponse(
        token_stream(),
        media_type="text/plain; charset=utf-8",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# --- HR / Recruiter mode -----------------------------------------------------
# A recruiter uploads a batch of resumes (the browser can't read a server
# folder), we index them locally (free embeddings), then offer semantic search,
# a grounded fit-screen, and grounded Q&A — all reusing hr_service.py.

class HrSearchRequest(BaseModel):
    hr_session_id: str
    query: str
    top_k: int = 10


class HrScreenRequest(BaseModel):
    hr_session_id: str
    candidate_id: str
    criteria: str


class HrChatRequest(BaseModel):
    hr_session_id: str
    candidate_id: str
    question: str
    history: Optional[List[ChatMessage]] = None


def _to_dict(model) -> dict:
    """Pydantic v1/v2-safe dump."""
    return model.model_dump() if hasattr(model, "model_dump") else model.dict()


def _hr_record(hr_session_id: str, candidate_id: str) -> Optional[dict]:
    for rec in _HR_SESSIONS.get(hr_session_id or "", []):
        if rec["id"] == candidate_id:
            return rec
    return None


@app.post("/api/hr/index")
async def hr_index(files: List[UploadFile] = File(...)) -> dict:
    """Upload + index a batch of resume PDFs. Local embeddings only (no quota)."""
    emb = get_emb()
    records: List[dict] = []
    for f in files:
        data = await f.read()
        text = extract_text_from_pdf(_UploadShim(f.filename, data)) or ""
        if not text.strip():
            continue
        vec = _embed_resume(text, emb)
        if vec is None:
            continue
        base = os.path.splitext(os.path.basename(f.filename or "resume"))[0]
        records.append({
            "id": uuid.uuid4().hex[:8],
            "file": os.path.basename(f.filename or "resume.pdf"),
            "name": _guess_name(text, base),
            "text": text,
            "n_chars": len(text),
            "embedding": vec,
        })

    if not records:
        return {"ok": False, "error": "Couldn't read any text from those PDFs (scanned with no OCR layer?)."}

    hr_session_id = uuid.uuid4().hex
    _HR_SESSIONS[hr_session_id] = records
    return {
        "ok": True,
        "hr_session_id": hr_session_id,
        "candidates": [
            {"id": r["id"], "name": r["name"], "file": r["file"], "n_chars": r["n_chars"]} for r in records
        ],
    }


@app.post("/api/hr/search")
def hr_search(req: HrSearchRequest) -> dict:
    """Rank the indexed pool against a query / pasted job description (semantic, free)."""
    index = _HR_SESSIONS.get(req.hr_session_id)
    if not index:
        return {"ok": False, "error": "No resume pool found — upload resumes first."}
    results = search_resumes(req.query, index, get_emb(), top_k=req.top_k)
    return {
        "ok": True,
        "results": [
            {
                "id": rec["id"],
                "name": rec["name"],
                "file": rec["file"],
                "score": round(float(score), 4),
                "snippet": " ".join((rec["text"] or "").split())[:240],
            }
            for rec, score in results
        ],
    }


@app.post("/api/hr/screen")
def hr_screen(req: HrScreenRequest) -> dict:
    """Grounded AI fit assessment of one candidate against criteria (1 LLM call)."""
    rec = _hr_record(req.hr_session_id, req.candidate_id)
    if not rec:
        return {"ok": False, "error": "Candidate not found."}
    result = screen_candidate(rec["text"], req.criteria, get_llm(), candidate_name=rec["name"])
    if not result:
        return {"ok": False, "error": "Screening failed (model error or quota). Try again in a moment."}
    return {"ok": True, "screen": _to_dict(result)}


@app.post("/api/hr/chat")
def hr_chat(req: HrChatRequest) -> dict:
    """Grounded Q&A about one candidate's resume — answer + evidence + confidence."""
    rec = _hr_record(req.hr_session_id, req.candidate_id)
    if not rec:
        return {"ok": False, "error": "Candidate not found."}
    history = [{"role": m.role, "content": m.content} for m in (req.history or [])]
    ans = answer_question(rec["text"], req.question, get_llm(), history=history)
    return {"ok": True, "answer": _to_dict(ans)}


# --- Optional: serve the built frontend (after `npm run build`) --------------
_DIST = os.path.join(os.path.dirname(__file__), "frontend", "dist")
if os.path.isdir(_DIST):
    app.mount("/", StaticFiles(directory=_DIST, html=True), name="frontend")
    logger.info(f"Serving built frontend from {_DIST}")
