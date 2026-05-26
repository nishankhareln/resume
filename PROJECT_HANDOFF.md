# AI Resume + Skill Gap Analyzer — Project Handoff

**Location:** `D:\resume 2`
**Stack:** Python 3.11 · Streamlit · LangChain · Google Gemini · sentence-transformers · scikit-learn
**Status:** Working end-to-end. Ready to demo.

---

## 1. What this project does (60-second pitch)

A web app that takes a candidate's resume (PDF) and produces a complete **career-readiness report** for a chosen target role:

1. Extracts structured profile data from the resume (skills, work history, education, contact info)
2. Compares the candidate's skills against the market's expectations for the target role
3. Produces six analytical reports: skill gap, live job matches, LinkedIn optimization, interview prep, 30/60/90-day learning roadmap, and ATS resume audit
4. Renders everything in a 7-tab Streamlit dashboard with a weighted overall "readiness score"

Supports both the **US job market** (via JSearch RapidAPI) and the **Nepal job market** (via merojob.com's public API).

---

## 2. The reading order for a new developer

Read in this order to understand the codebase:

1. `streamlit_app.py` — the UI entry point. Shows the whole pipeline in order.
2. `app.py` — PDF extraction + LLM/embedding initialization + resume parsing.
3. `schemas.py` — every Pydantic report shape used downstream.
4. `main_job_matcher.py` — embedding-based similarity matching.
5. `skill_gap_service.py` — the deterministic-then-LLM skill comparison logic.
6. The other service files (linkedin, interview, roadmap, resume_feedback, market_insight, scoring) — same pattern repeated.

---

## 3. Architecture overview

```
                  ┌──────────────────────┐
                  │   streamlit_app.py    │  ← UI: sidebar + 7 tabs
                  └──────────┬───────────┘
                             │
        ┌────────────────────┼─────────────────────────────┐
        │                    │                             │
        ▼                    ▼                             ▼
┌──────────────┐  ┌──────────────────────┐  ┌──────────────────────┐
│   app.py     │  │ main_job_matcher.py  │  │   Service modules    │
│              │  │                      │  │ (one per tab)        │
│ • PDF→text   │  │ • Embed resume       │  │ • skill_gap_service  │
│ • OCR        │  │ • Embed each job     │  │ • linkedin_service   │
│ • parse_     │  │ • cosine_similarity  │  │ • interview_service  │
│   resume()   │  │ • Filter by exp     │  │ • roadmap_service    │
│ • get_llm    │  │ • Categorize         │  │ • resume_feedback    │
│ • get_emb    │  │                      │  │ • scoring_service    │
└──────┬───────┘  └──────────┬───────────┘  │ • market_insight     │
       │                     │              └──────────┬───────────┘
       │                     │                         │
       ▼                     ▼                         ▼
┌──────────────┐  ┌──────────────────────┐  ┌──────────────────────┐
│  Gemini LLM  │  │  Local embeddings    │  │   Pydantic schemas   │
│  (chat)      │  │  (sentence-          │  │   (schemas.py)       │
│              │  │   transformers)      │  │                      │
└──────────────┘  └──────────────────────┘  └──────────────────────┘
                             │
                             ▼
                  ┌──────────────────────┐
                  │   Job data sources   │
                  ├──────────────────────┤
                  │ job_portal.py        │ → JSearch RapidAPI (US)
                  │ merojob_client.py    │ → merojob.com API (Nepal)
                  │ job_metadata.json    │ → 30 cached jobs (offline)
                  └──────────────────────┘
```

---

## 4. Every file in the repo

### Core application files

| File | Purpose | Notes |
|---|---|---|
| `streamlit_app.py` | Main UI. Sidebar (upload + role + country) + 7 tabs. | Lazy: each tab has its own "Generate" button so LLM calls aren't fired up-front. |
| `app.py` | PDF text extraction (PyMuPDF), OCR fallback (Tesseract), Gemini LLM init, embeddings init, resume parser, job-description experience extractor, job-title categorizer. | The original "everything file" — still does heavy lifting. |
| `main_job_matcher.py` | Takes the parsed resume + an embeddings model, fetches jobs (US or Nepal), embeds them, ranks by cosine similarity, filters by experience, categorizes. | Takes `country` param: `"us"` or `"np"`. |
| `job_portal.py` | JSearch RapidAPI client (US jobs only). | Reads `JSEARCH_RAPIDAPI_KEY` from `.env`. |
| `merojob_client.py` | **New.** Calls merojob.com's public JSON API. No auth required. | URL: `api.merojob.com/api/v1/jobs/?search={kw}`. |

### Service modules (one per dashboard tab)

| File | Builds | Pydantic output | LLM calls |
|---|---|---|---|
| `skill_gap_service.py` | matched / missing / recommended skills + summary | `SkillGapReport` | 0 (deterministic) or 1 (LLM-enriched) |
| `market_insight_service.py` | Top demanded skills per role from `job_metadata.json` | (no schema, returns lists) | 0 — pure regex over offline data |
| `linkedin_service.py` | Headline, About section, missing keywords, achievement rewrites, profile tips | `LinkedInOptimizationReport` | 1 |
| `interview_service.py` | 6-8 tailored interview questions with answer outlines | `InterviewPrepReport` | 1 |
| `roadmap_service.py` | 30/60/90-day learning plan with mini-projects + milestones | `RoadmapReport` | 1 |
| `resume_feedback_service.py` | ATS score (deterministic heuristic) + structure/keyword feedback + bullet rewrites | `ResumeFeedbackReport` | 1 |
| `scoring_service.py` | The weighted overall readiness score | `OverallScore` | 0 (pure math) |

### Schema + helpers

| File | Purpose |
|---|---|
| `schemas.py` | Centralized Pydantic models: `ResumeInfo` (in `app.py`), `SkillGapReport`, `LinkedInOptimizationReport`, `InterviewPrepReport`, `RoadmapReport`, `ResumeFeedbackReport`, `OverallScore`, `AchievementRewrite`, `InterviewQuestion`, `RoadmapPhase`. |
| `local_embeddings.py` | **New.** Wraps `sentence-transformers` to expose the same `embed_documents()` / `embed_query()` interface as Google's embedder. So `main_job_matcher.py` doesn't need to know which backend is active. |
| `list_models.py` | Diagnostic. Prints which Gemini models your API key has access to. Run with: `python list_models.py`. |
| `resume_parser.py` | Alternative resume parser using `pdfplumber` + `python-docx`. Not currently called by the main pipeline. |

### Data files

| File | Contents |
|---|---|
| `job_metadata.json` | 30 cached US job postings (title, company, description, location, etc.). Used by `market_insight_service` for skill-frequency analysis and as an offline fallback in the Job Matches tab. |
| `faiss_index_data` / `job_listings.faiss` | Legacy FAISS index files from an earlier iteration. **Not used by current code.** Safe to ignore. |

### Config / environment

| File | Purpose |
|---|---|
| `.env` | All secrets and tunables. **Never commit this file.** See section 7 below. |
| `.gitignore` | Standard Python / Streamlit ignores. |
| `requirements.txt` | Pinned dependency list. Use to recreate the venv on a new machine. |

### Directories

| Path | Purpose |
|---|---|
| `venv/` | Python 3.11.9 virtual environment. Recreate with `py -3.11 -m venv venv` if missing. |
| `temp/` | Scratch space for PDF uploads during processing. Auto-cleaned. |
| `temp_resumes/`, `test_resumes/` | Sample inputs for development. |
| `__pycache__/` | Python bytecode cache. Auto-managed. |

---

## 5. Models used

This app uses **two completely different types of AI model**:

### 5.1 The LLM (text generation, reasoning, writing)

| Setting | Value |
|---|---|
| Provider | Google Gemini |
| Default model | `gemini-2.5-flash-lite` |
| Override env var | `GEMINI_MODEL` |
| Temperature | 0.3 (low — deterministic extraction) |
| Cost | Free tier with daily quota |

**What it does in this app:**
- Reads the resume text and turns it into structured `ResumeInfo` (one call per upload)
- Optional: enriches the deterministic skill-gap with reasoning
- Writes the LinkedIn report
- Writes the interview questions
- Writes the 30/60/90 roadmap
- Writes the ATS feedback
- Per-job: extracts "minimum years experience required" from job descriptions
- Per-job: categorizes job titles into role buckets

**Quota note.** Free tier currently shows `limit: 0` for `gemini-2.0-flash` and `gemini-2.0-flash-lite` (Google removed those tiers for new projects). Working models on this account: `gemini-2.5-flash-lite`, `gemini-2.5-flash`, `gemini-flash-latest`, `gemini-flash-lite-latest`. Run `python list_models.py` to see what's available.

### 5.2 The embedding model (text → vector for similarity)

| Setting | Value |
|---|---|
| Backend (default) | **Local** — `sentence-transformers` |
| Default model | `sentence-transformers/all-MiniLM-L6-v2` |
| Override env var | `LOCAL_EMBEDDING_MODEL` |
| Dimension | 384 |
| Size on disk | ~90 MB (auto-downloaded to `~/.cache/huggingface/` on first run) |
| Cost | Free, runs locally |
| Speed | ~0.1s to embed 4 short texts on a CPU |

**Alternative backend (Google API):** set `EMBEDDING_BACKEND=google` in `.env`. Uses `models/gemini-embedding-001` (3072-dim) via the Gemini API. Costs quota. We switched off this by default because we hit deprecation issues (`models/embedding-001` was retired mid-project).

**What it does in this app:**
- Embeds the resume into a 384-dimensional vector
- Embeds each fetched job into the same space
- Computes cosine similarity between resume and each job → the "match score" displayed on each job card

**Why two models?** LLMs reason and write text. Embedders measure semantic similarity. Different jobs, different architectures.

---

## 6. External APIs used

| Service | Used for | Auth | Quota |
|---|---|---|---|
| Google Gemini API | All LLM calls (resume parsing, all 5 LLM reports, per-job analysis) | `GEMINI_API_KEY` | Free tier with daily limits per model |
| JSearch (RapidAPI) | US live job listings | `JSEARCH_RAPIDAPI_KEY` + `JSEARCH_RAPIDAPI_HOST` | RapidAPI free tier |
| merojob.com API | Nepal live job listings | None (public endpoint) | None — be polite |
| HuggingFace Hub | Downloads the local embedding model on first run | None | One-time only |

---

## 7. Environment variables (`.env`)

Create a `.env` file at the project root with these keys:

```dotenv
# --- LLM (required for all LLM-driven tabs) ---
GEMINI_API_KEY=your_google_ai_studio_key_here

# Optional: override the LLM model. Default: gemini-2.5-flash-lite
# Use list_models.py to see which models your key supports.
GEMINI_MODEL=gemini-2.5-flash-lite

# --- Embeddings (defaults are fine — these are just for reference) ---
# Backend: "local" (default) or "google"
EMBEDDING_BACKEND=local
# If local backend:
LOCAL_EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
# If google backend:
GEMINI_EMBEDDING_MODEL=models/gemini-embedding-001

# --- Job APIs ---
# Required for US live jobs (otherwise use offline dataset)
JSEARCH_RAPIDAPI_KEY=your_rapidapi_key
JSEARCH_RAPIDAPI_HOST=jsearch.p.rapidapi.com
```

**How to get the keys:**
- **GEMINI_API_KEY:** https://aistudio.google.com/app/apikey (free, no card needed)
- **JSEARCH_RAPIDAPI_KEY:** https://rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch (free tier, sign up needed)

---

## 8. Setup from scratch (clone-and-run)

```powershell
# 1) Create a fresh Python 3.11 venv
py -3.11 -m venv venv

# 2) Activate it (PowerShell)
.\venv\Scripts\Activate.ps1

# 3) Upgrade pip + install everything
python -m pip install --upgrade pip setuptools wheel
pip install -r requirements.txt

# 4) Create .env with your keys (see section 7)
notepad .env

# 5) Run the app
streamlit run streamlit_app.py
```

**First run will take longer** because the local embedding model (~90 MB) downloads from HuggingFace. Subsequent runs use the cached copy.

**External tools (optional, only needed for OCR/scanned PDFs):**
- **Tesseract OCR** — Windows installer: https://github.com/UB-Mannheim/tesseract/wiki
- **Poppler** — Windows builds: https://github.com/oschwartz10612/poppler-windows/releases

If you're working with normal text-based PDFs, you don't need these.

---

## 9. The dashboard, tab by tab

The UI lives in `streamlit_app.py`. Each tab maps to one service module.

### Sidebar (always visible)
- **Resume (PDF)** upload field
- **Target role** dropdown (15 buckets auto-extracted from `job_metadata.json` + free text option)
- **Job market** radio: 🇺🇸 US (JSearch) or 🇳🇵 Nepal (merojob.com)
- **Analyze resume** primary button — runs the cheap parsing step

### Tab 1: Overview
- Parsed candidate profile (name, email, phone, LinkedIn, skills, experience years)
- Full work history + education in an expander
- **Weighted readiness score** with 5 sub-metrics (see section 10)

### Tab 2: Skill Gap
- Match percentage progress bar
- Three columns: **Matched skills** ✅ · **Missing skills** ❌ · **Recommended next skills**
- "Enrich with LLM" button (optional — uses 1 LLM call to add reasoning)
- Expander: top skills the market asks for (from `job_metadata.json`)

### Tab 3: Job Matches
- Two buttons: **Find live jobs** (uses JSearch or merojob depending on country toggle) and **Use offline dataset** (uses `job_metadata.json`)
- Each job card shows: title, company, location, required experience, **similarity score** (color-coded green/yellow/red), apply link, expandable description
- Live US mode uses LLM calls per job for experience extraction + categorization
- Live Nepal mode uses merojob's API directly (no auth needed)
- Offline mode: zero API calls, pure local matching

### Tab 4: LinkedIn Tips
- Generate-on-demand button
- Suggested headline (10-15 words, with role keywords)
- Rewritten About section (3-5 sentences, first person, measurable impact)
- Missing keywords list
- Achievement rewrites (before/after with reasoning)
- Profile tips (banner, featured section, endorsements, etc.)

### Tab 5: Interview
- Generate-on-demand button
- 6-8 questions across categories: technical, behavioral, system_design, hr, role_specific
- Each question expandable to show "Why asked" and "Answer outline"

### Tab 6: Roadmap
- Generate-on-demand button
- 30/60/90-day plan with three phase cards
- Per phase: focus, skills to learn, weekly actions, mini-project, measurable milestone

### Tab 7: Resume Audit
- Generate-on-demand button
- **ATS friendliness score** (0-100, deterministic heuristic — see below)
- Structure feedback, action verb feedback, quantification feedback
- Keywords to add for the target role
- Bullet improvements (before/after)
- Top recommendations in priority order

---

## 10. The scoring formula

The "Overall match" number on the Overview tab is a weighted blend (defined in `scoring_service.py`):

```
total = 0.35 × skill_overlap
      + 0.25 × semantic_similarity
      + 0.20 × experience_fit
      + 0.10 × keyword_quality
      + 0.10 × linkedin_readiness
```

Each component is 0-100:
- **skill_overlap** = `% matched skills out of (matched + missing)` — from `skill_gap_service`
- **semantic_similarity** = top job's cosine similarity × 100 — from `main_job_matcher`
- **experience_fit** = 100 if candidate years fall inside the target role's expected band, linearly penalized otherwise — see `scoring_service._experience_fit`
- **keyword_quality** = ATS heuristic score (0-100) when resume audit has run; otherwise a fallback from keyword/skill counts
- **linkedin_readiness** = LinkedIn URL present (50) + has summary (25) + ≥5 skills (25)

The percentages match the hackathon doc's spec exactly.

---

## 11. The ATS heuristic (in `resume_feedback_service.py`)

A deterministic 0-100 score computed without any LLM call. Award points for:

| Check | Max points |
|---|---|
| Email present (not "Unknown") | 8 |
| Phone present | 7 |
| Has section headers (experience / education / skills) — 5 each | 15 |
| Distinct action verbs found (×2 each, cap 20) | 20 |
| Digit-led numbers found (quantification, cap 20) | 20 |
| Word count in 300-1200 sweet spot | 10 |
| Low special-char ratio (well-formed text) | 10 |
| ≥5 skills extracted | 10 |

The LLM then writes structure / verb / quantification feedback against this deterministic baseline.

---

## 12. Packages installed (in `requirements.txt`)

```
streamlit
pydantic
python-dotenv
nest_asyncio
google-api-core
google-generativeai
langchain<1.0
langchain-core<1.0
langchain-google-genai<3.0
PyMuPDF
Pillow
sentence-transformers
beautifulsoup4
lxml
pytesseract
scikit-learn
requests
pdfplumber
pdf2image
python-docx
```

**Note on version pins.** LangChain 1.0 removed the `langchain.prompts` import path that this code uses. We pinned to the 0.3.x series. The downstream `langgraph` package complains about this in pip's resolver, but `langgraph` is not actually imported by this project — it came in as a transitive dependency and is unused. Safe to ignore the warning.

**Transitive heavy dependencies (auto-installed):**
- `torch` (~1.8 GB) — required by `sentence-transformers`
- `transformers` — used by `sentence-transformers`
- `lxml` — used by `beautifulsoup4`'s parser

---

## 13. History of what was built (session log)

Built end-to-end in one session on top of the original "AI-Powered Resume Job Matcher (US Jobs Only)" codebase. The hackathon doc spec was implemented as additive service modules, not a rewrite.

### Infrastructure
1. Found broken venv (pointed to deleted Python on a different machine). Recreated with Python 3.11.9.
2. Identified 17 missing third-party packages from imports. Built `requirements.txt`. Installed everything.
3. Hit LangChain 1.0 breaking change (`langchain.prompts` removed). Pinned to `<1.0`.
4. Hit Google deprecation of `models/embedding-001`. Switched to `gemini-embedding-001`.
5. Hit `gemini-2.0-flash` having `limit: 0` on the user's free tier. Made the model configurable; switched default to `gemini-2.5-flash-lite`.
6. Switched embeddings from Google API to local `sentence-transformers/all-MiniLM-L6-v2` to permanently eliminate embedding quota and deprecation risk.

### Features (the 6 doc-required additions)
7. Built `schemas.py` centralizing all Pydantic report shapes.
8. Built `market_insight_service.py` — reads `job_metadata.json`, buckets job titles into 15 role categories using regex, builds a 100+-skill vocabulary, counts skill frequency per role.
9. Built `skill_gap_service.py` — deterministic set-diff with alias normalization (`js → javascript`, `k8s → kubernetes`, etc.) + optional LLM enrichment.
10. Built `linkedin_service.py` — headline + About + missing keywords + achievement rewrites + profile tips.
11. Built `interview_service.py` — 6-8 questions mixing technical / behavioral / system_design / hr.
12. Built `roadmap_service.py` — 30/60/90-day learning plan with measurable milestones.
13. Built `resume_feedback_service.py` — deterministic ATS heuristic + LLM-written feedback.
14. Built `scoring_service.py` — implements the doc's 35/25/20/10/10 weighted formula.

### UI rewrite
15. Rewrote `streamlit_app.py` from a single-page layout into a sidebar + 7-tab dashboard.
16. Made it lazy: each tab has its own "Generate" button so we only burn LLM quota on what's actually demoed. This is the real fix for the quota issues from earlier sessions.
17. Added quota-aware error handling: 429 errors surface a clear message with hint to switch models.

### Nepal job market support
18. Tested JSearch with `country=np` — confirmed it returns 0 jobs (no Nepal coverage).
19. Probed merojob.com — discovered it's a React app with no server-rendered job data, but it calls a public JSON API at `api.merojob.com/api/v1/jobs/`.
20. Built `merojob_client.py` — clean client that hits the API directly, normalizes responses to the same shape as `job_portal.py`.
21. Added country toggle (US/Nepal) in the sidebar; routed it through `main_job_matcher.process_jobs(country=...)`.

### Local embeddings
22. Installed `sentence-transformers` (pulls torch + transformers).
23. Built `local_embeddings.py` wrapper exposing `embed_documents()` / `embed_query()` — drop-in replacement for `GoogleGenerativeAIEmbeddings`.
24. Added `EMBEDDING_BACKEND` env var so the same code can run on either local or Google embeddings without changes.

---

## 14. Known issues / quirks

- **`langgraph` dependency conflict warning.** Pip complains because `langgraph` (pulled in by an older transitive) wants `langchain-core >= 1.4`, but we pinned `<1.0`. `langgraph` is not imported anywhere in this project. Warning is cosmetic.
- **`google.generativeai` deprecation warning.** Google deprecated the `google-generativeai` package in favor of `google-genai`. Only `list_models.py` uses it. Will continue to work but should be migrated eventually.
- **merojob.com API is undocumented.** If they redesign their site, `merojob_client.py` may break. Schema has been stable as of 2025.
- **Live US mode is LLM-expensive.** Each job's experience + category extraction is one LLM call. 20 jobs = 40 calls. If quota is tight, use the **Use offline dataset** button instead.
- **First run downloads ~90 MB.** The local embedding model downloads from HuggingFace on the first call. Cached after that.

---

## 15. Useful commands

```powershell
# Activate the venv (PowerShell)
.\venv\Scripts\Activate.ps1

# Run the app
streamlit run streamlit_app.py

# See which Gemini models your API key can use
python list_models.py

# Recompile-check a single file without running it
python -c "import py_compile; py_compile.compile('streamlit_app.py', doraise=True)"

# Reinstall everything from scratch
pip install --force-reinstall -r requirements.txt
```

---

## 16. Where to extend next

If continuing development, the lowest-effort / highest-impact directions are:

1. **Add more Nepali job sources** (kumarijob.com, ramrojob.com, jobsnepal.com) — same shape as `merojob_client.py`, ~50 lines each.
2. **Cache LLM responses** by (resume hash + target role) so re-runs are free.
3. **PDF report download** — combine all reports into one PDF the user can download.
4. **Compare multiple target roles** side-by-side ("How do I score for Backend vs Data Engineer?").
5. **Cover-letter generator** — 1 more LLM call, large perceived value.
6. **Migrate `google-generativeai` to `google-genai`** in `list_models.py` (already deprecated).
7. **Add Adzuna or Remotive as a third job source** — free APIs, broader coverage.
8. **Switch to a stronger embedding model** — change `LOCAL_EMBEDDING_MODEL` env var to `BAAI/bge-base-en-v1.5` (better quality, ~440 MB).

---

*Generated 2026-05-26. If anything in this document is wrong, the code is the source of truth — start with `streamlit_app.py` and follow the imports.*
