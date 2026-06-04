"""
hr_service
==========

Backend for the HR / Recruiter mode. Two levels of capability:

  Level 1 — grounded Q&A about ONE resume.
    The recruiter asks free-form questions ("does he know Kubernetes?",
    "how many years of Python?") and gets answers grounded ONLY in the
    resume text, with verbatim evidence quotes and a confidence flag.
    `not_found` is an encouraged answer — we never guess a skill that
    isn't in the resume.

  Level 2 — screen a POOL of resumes sitting in a folder.
    Each resume is extracted + embedded once (locally, 0 LLM calls) and
    cached to disk, so semantic search across the whole folder is free.
    An optional "deep-screen" runs a structured LLM assessment on just the
    top candidates (quota-aware, same lazy philosophy as the rest of the app).

Design choices that mirror the existing codebase:
  - Reuses `extract_text_from_pdf` (incl. its OCR fallback) via a tiny shim.
  - Reuses the active embeddings backend from `get_embeddings_model()`
    (local sentence-transformers by default).
  - Uses the same `PromptTemplate | llm | PydanticOutputParser` chain
    pattern as the other service modules.

Fairness note: the chat and screen prompts instruct the model to judge
only skills and experience, and to ignore name, gender, age, and
nationality. For a tool that screens people, that guardrail is not
polish — it's what makes it defensible to deploy.
"""

from __future__ import annotations

import json
import logging
import os
from typing import List, Optional, Tuple

import numpy as np

from langchain.prompts import PromptTemplate
from langchain.output_parsers import PydanticOutputParser
from pydantic import ValidationError

from app import extract_text_from_pdf, parse_resume, ResumeInfo
from schemas import HRChatAnswer, CandidateScreen

logger = logging.getLogger(__name__)

# Default folder the recruiter's resume pool lives in. Override via env.
DEFAULT_RESUME_DIR = os.getenv("HR_RESUME_DIR", "hr_resumes")
# Disk cache so re-indexing an unchanged folder is instant + free.
CACHE_FILE = ".hr_index_cache.json"

# Shared fairness guardrail injected into every recruiter-facing prompt.
_FAIRNESS = (
    "Judge ONLY skills, experience, education, and what the resume states. "
    "Ignore the candidate's name, gender, age, nationality, photo, and any "
    "personal attribute. Never invent or assume information that is not in the resume."
)


# --------------------------------------------------------------------------
# Reading resumes from disk (reuses the OCR-capable extractor in app.py)
# --------------------------------------------------------------------------

class _PathUpload:
    """Adapts a file on disk to the small interface `extract_text_from_pdf`
    expects from a Streamlit upload (`.name` + `.getbuffer()`), so we get the
    existing OCR fallback for free without duplicating extraction logic."""

    def __init__(self, path: str):
        self._path = path
        self.name = os.path.basename(path)

    def getbuffer(self) -> bytes:
        with open(self._path, "rb") as f:
            return f.read()


def list_resume_files(directory: str) -> List[str]:
    """Return absolute paths of every PDF in `directory` (non-recursive)."""
    if not directory or not os.path.isdir(directory):
        return []
    out = []
    for name in sorted(os.listdir(directory)):
        if name.lower().endswith(".pdf"):
            out.append(os.path.join(directory, name))
    return out


def extract_text_from_path(path: str) -> str:
    """Extract text (with OCR fallback) from a PDF on disk."""
    return extract_text_from_pdf(_PathUpload(path)) or ""


def _file_signature(path: str) -> str:
    """Cheap change-detector: size + mtime. If either changes we re-index."""
    try:
        stt = os.stat(path)
        return f"{stt.st_size}-{int(stt.st_mtime)}"
    except OSError:
        return "0-0"


def _guess_name(text: str, fallback: str) -> str:
    """Best-effort candidate name from the top of the resume, with NO LLM call.
    Just for the candidate list; the real name comes from `parse_resume` later."""
    for line in text.splitlines()[:12]:
        s = line.strip()
        if not s or "@" in s or "http" in s.lower():
            continue
        if any(ch.isdigit() for ch in s):
            continue
        words = s.split()
        if 1 <= len(words) <= 4 and len(s) <= 40 and s[0].isalpha():
            alpha = sum(ch.isalpha() or ch.isspace() for ch in s)
            if alpha / max(1, len(s)) > 0.8:
                return s.title() if s.isupper() else s
    return fallback


# --------------------------------------------------------------------------
# Embedding a whole resume (mean-pooled over chunks)
# --------------------------------------------------------------------------

def _chunk(text: str, max_chars: int = 1200, max_chunks: int = 8) -> List[str]:
    """Split into a handful of paragraph-ish chunks. MiniLM truncates long
    inputs, so we embed several chunks and average — that captures the whole
    resume instead of just the header."""
    text = (text or "").strip()
    if not text:
        return []
    chunks, buf = [], ""
    for para in text.replace("\r", "").split("\n"):
        if len(buf) + len(para) + 1 > max_chars and buf:
            chunks.append(buf.strip())
            buf = ""
            if len(chunks) >= max_chunks:
                break
        buf += para + "\n"
    if buf.strip() and len(chunks) < max_chunks:
        chunks.append(buf.strip())
    return chunks or [text[: max_chars * max_chunks]]


def _embed_resume(text: str, emb) -> Optional[List[float]]:
    """Mean-pool chunk embeddings into one L2-normalized vector for the resume."""
    chunks = _chunk(text)
    if not chunks:
        return None
    try:
        vecs = np.array(emb.embed_documents(chunks), dtype=float)
    except Exception as e:
        logger.error(f"Embedding failed: {e}")
        return None
    mean = vecs.mean(axis=0)
    norm = np.linalg.norm(mean)
    if norm > 0:
        mean = mean / norm
    return mean.tolist()


def _cosine(a: List[float], b: List[float]) -> float:
    va, vb = np.array(a, dtype=float), np.array(b, dtype=float)
    na, nb = np.linalg.norm(va), np.linalg.norm(vb)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(va, vb) / (na * nb))


# --------------------------------------------------------------------------
# Indexing the folder (cached to disk)
# --------------------------------------------------------------------------

def _load_cache() -> dict:
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Could not read HR index cache: {e}")
    return {}


def _save_cache(cache: dict) -> None:
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f)
    except Exception as e:
        logger.warning(f"Could not write HR index cache: {e}")


def index_resumes(directory: str, emb, progress_cb=None) -> List[dict]:
    """Build (or refresh) the search index for every PDF in `directory`.

    For each resume: extract text + compute a pooled embedding. Both are
    cached by file signature, so unchanged files are reused instantly and
    no work is repeated. This whole step makes ZERO LLM calls — the LLM is
    only used later, lazily, for chat and deep-screen.

    Returns a list of records: {file, name, text, n_chars, embedding}.
    """
    files = list_resume_files(directory)
    cache = _load_cache()
    records: List[dict] = []

    for i, path in enumerate(files):
        if progress_cb:
            progress_cb(i, len(files), os.path.basename(path))

        sig = _file_signature(path)
        cached = cache.get(path)
        if cached and cached.get("signature") == sig and cached.get("embedding"):
            records.append({k: cached[k] for k in ("file", "name", "text", "n_chars", "embedding")})
            continue

        text = extract_text_from_path(path)
        if not text.strip():
            logger.warning(f"No text extracted from {path}; skipping.")
            continue
        embedding = _embed_resume(text, emb)
        if embedding is None:
            logger.warning(f"No embedding for {path}; skipping.")
            continue

        rec = {
            "file": path,
            "name": _guess_name(text, os.path.basename(path)),
            "text": text,
            "n_chars": len(text),
            "embedding": embedding,
        }
        records.append(rec)
        cache[path] = {**rec, "signature": sig}

    # Drop cache entries for files that no longer exist in the folder.
    live = set(files)
    for stale in [p for p in cache if p not in live]:
        cache.pop(stale, None)

    _save_cache(cache)
    if progress_cb:
        progress_cb(len(files), len(files), "done")
    return records


def search_resumes(query: str, index: List[dict], emb, top_k: int = 10) -> List[Tuple[dict, float]]:
    """Rank pool resumes against a free-text query or pasted job description
    by semantic similarity. Local + free (no LLM)."""
    query = (query or "").strip()
    if not query or not index:
        return []
    try:
        qv = emb.embed_query(query)
    except Exception as e:
        logger.error(f"Query embedding failed: {e}")
        return []
    scored = [(rec, _cosine(qv, rec["embedding"])) for rec in index if rec.get("embedding")]
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:top_k]


# --------------------------------------------------------------------------
# Level 1 — grounded Q&A about one resume
# --------------------------------------------------------------------------

_chat_parser = PydanticOutputParser(pydantic_object=HRChatAnswer)

_CHAT_PROMPT = PromptTemplate(
    template="""You are a hiring assistant helping a recruiter understand ONE candidate's resume.

Rules (follow strictly):
- Answer ONLY from the resume text below. Do not use outside knowledge about the person.
- If the resume does not contain the answer, set confidence to "not_found" and say so plainly. Do NOT guess.
- Quote the exact supporting lines from the resume in `evidence` (verbatim, short).
- Set confidence to "explicitly_stated" when the resume says it directly, "implied" when it is reasonably inferable, "not_found" when absent.
- {fairness}

Conversation so far (for context):
{history}

Resume text:
\"\"\"
{resume_text}
\"\"\"

Recruiter's question: {question}

{format_instructions}
""",
    input_variables=["history", "resume_text", "question"],
    partial_variables={
        "format_instructions": _chat_parser.get_format_instructions(),
        "fairness": _FAIRNESS,
    },
)


def _format_history(history: Optional[List[dict]], max_turns: int = 6) -> str:
    if not history:
        return "(none)"
    lines = []
    for turn in history[-max_turns:]:
        role = "Recruiter" if turn.get("role") == "user" else "Assistant"
        lines.append(f"{role}: {turn.get('content', '')}")
    return "\n".join(lines) or "(none)"


def answer_question(
    resume_text: str,
    question: str,
    llm,
    history: Optional[List[dict]] = None,
) -> HRChatAnswer:
    """Answer one recruiter question, grounded in `resume_text`.

    Resumes are short, so we pass the whole text in context — no RAG needed
    for a single document. Returns a structured, citable answer."""
    if llm is None:
        return HRChatAnswer(
            answer="The AI model is not available. Check GEMINI_API_KEY.",
            confidence="not_found",
        )
    if not (resume_text or "").strip():
        return HRChatAnswer(
            answer="No resume text is available for this candidate.",
            confidence="not_found",
        )
    try:
        chain = _CHAT_PROMPT | llm | _chat_parser
        return chain.invoke({
            "history": _format_history(history),
            "resume_text": resume_text[:16000],
            "question": question,
        })
    except (ValidationError, Exception) as e:
        logger.warning(f"HR chat answer failed: {e}")
        return HRChatAnswer(
            answer=f"Could not produce a grounded answer ({e}).",
            confidence="not_found",
        )


# --------------------------------------------------------------------------
# Level 2 — deep-screen one candidate against criteria / a job description
# --------------------------------------------------------------------------

_screen_parser = PydanticOutputParser(pydantic_object=CandidateScreen)

_SCREEN_PROMPT = PromptTemplate(
    template="""You are screening ONE candidate against a recruiter's requirements.

Rules (follow strictly):
- Base every judgment ONLY on the resume text. Quote supporting lines in `evidence`.
- List each requirement the candidate clearly meets in `matched_requirements`, and each one not evidenced in `missing_requirements`.
- Do not credit a requirement unless the resume supports it. When unsure, treat it as missing.
- {fairness}

Verdict scale: strong_match, possible_match, weak_match, not_a_match.
The `candidate` field must be: {candidate}

Recruiter's requirements / job description:
\"\"\"
{criteria}
\"\"\"

Resume text:
\"\"\"
{resume_text}
\"\"\"

{format_instructions}
""",
    input_variables=["candidate", "criteria", "resume_text"],
    partial_variables={
        "format_instructions": _screen_parser.get_format_instructions(),
        "fairness": _FAIRNESS,
    },
)


def screen_candidate(resume_text: str, criteria: str, llm, candidate_name: str = "Candidate") -> Optional[CandidateScreen]:
    """Structured AI fit assessment of one candidate against `criteria`.
    One LLM call. Returns None on failure (caller decides how to surface)."""
    if llm is None or not (resume_text or "").strip() or not (criteria or "").strip():
        return None
    try:
        chain = _SCREEN_PROMPT | llm | _screen_parser
        result = chain.invoke({
            "candidate": candidate_name,
            "criteria": criteria,
            "resume_text": resume_text[:16000],
        })
        result.candidate = candidate_name  # don't let the model rewrite the label
        return result
    except (ValidationError, Exception) as e:
        logger.warning(f"Deep-screen failed for {candidate_name}: {e}")
        return None


def parse_candidate_profile(resume_text: str, llm) -> Optional[ResumeInfo]:
    """Lazy structured parse of one resume (name, skills, experience, etc.).
    Thin pass-through to the existing parser; cached by the caller."""
    return parse_resume(resume_text, llm)
