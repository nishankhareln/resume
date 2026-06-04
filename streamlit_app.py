"""
AI Resume + Skill Gap Analyzer — Streamlit dashboard (lazy / quota-friendly).

The first "Analyze resume" step only does the cheap work: PDF extraction +
1 LLM call to parse the resume + 1 deterministic skill-gap. The other five
heavy LLM tabs (LinkedIn, Interview, Roadmap, Resume Audit, Job Matches)
each have their own "Generate" button so you only spend quota on what
you actually demo.

This solves the "limit: 0" 429 errors from gemini free tier — instead of
7 calls fired at once on upload, you get one call upfront + 1 per tab
you actively click.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

import streamlit as st

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# --- Core imports -----------------------------------------------------------
try:
    from app import (
        parse_resume,
        get_llm_model,
        get_embeddings_model,
        ResumeInfo,
        extract_text_from_pdf,
    )
    from main_job_matcher import process_jobs, generate_embedding, calculate_similarity
    from market_insight_service import list_roles, market_skills_for_role, offline_jobs_for_keywords, load_jobs, top_skills_for_role
    from skill_gap_service import analyze_skill_gap
    from linkedin_service import generate_linkedin_report
    from interview_service import generate_interview_prep
    from roadmap_service import generate_roadmap
    from resume_feedback_service import generate_resume_feedback, _ats_heuristic
    from scoring_service import compute_overall_score
    from scan_ui import render_scan_steps
    from chat_service import stream_reply, build_background, ASSISTANT_NAME
except Exception as e:
    logger.exception("Failed to import core modules.")
    st.error(f"Failed to load core components: {e}")
    st.stop()

# --- Page config ------------------------------------------------------------
st.set_page_config(layout="wide", page_title="AI Resume + Skill Gap Analyzer")

if not os.path.exists("temp"):
    os.makedirs("temp")


# --- Cached model init ------------------------------------------------------
@st.cache_resource
def _llm():
    try:
        return get_llm_model()
    except Exception as e:
        logger.error(f"LLM init failed: {e}")
        return None


@st.cache_resource
def _emb():
    try:
        return get_embeddings_model()
    except Exception as e:
        logger.error(f"Embeddings init failed: {e}")
        return None


llm = _llm()
emb = _emb()
if llm is None or emb is None:
    st.error("AI models could not be initialized. Check GEMINI_API_KEY in your .env file.")
    st.stop()


# --- Mode: candidate-facing dashboard vs HR / recruiter tool ----------------
with st.sidebar:
    app_mode = st.radio(
        "Mode",
        options=["Candidate", "HR / Recruiter"],
        help="Candidate = career-readiness report for one job seeker. "
             "HR = search/screen a folder of resumes and chat with any candidate.",
    )
    st.divider()

if app_mode == "HR / Recruiter":
    from hr_ui import render_hr_mode
    render_hr_mode(llm, emb)
    st.stop()


# --- Candidate mode ---------------------------------------------------------
st.title("AI Resume + Skill Gap Analyzer")
st.caption("Upload a resume. Get a career-readiness report: gap analysis, LinkedIn tips, interview prep, roadmap.")


# --- Session state ----------------------------------------------------------
def _ss(key: str, default: Any = None) -> Any:
    if key not in st.session_state:
        st.session_state[key] = default
    return st.session_state[key]


_ss("resume_info")
_ss("resume_text")
_ss("target_role")
_ss("skill_gap")
_ss("linkedin")
_ss("interview")
_ss("roadmap")
_ss("feedback")
_ss("matched_jobs", [])
_ss("top_semantic", 0.0)
_ss("overall_score")
_ss("chat_messages", [])


def _quota_hint(err_msg: str) -> Optional[str]:
    msg = (err_msg or "").lower()
    if "resourceexhausted" in msg or "429" in msg or "quota" in msg or "rate limit" in msg:
        return (
            "Gemini quota hit (free tier). Wait a minute and try again, "
            "or switch model by setting `GEMINI_MODEL=gemini-1.5-flash-latest` "
            "(or another available model) in your `.env`."
        )
    return None


# --- Sidebar: upload + target role -----------------------------------------
with st.sidebar:
    st.header("Inputs")
    uploaded = st.file_uploader("Resume (PDF)", type="pdf")

    role_options = list_roles()
    if not role_options:
        role_options = ["Software Engineer", "Data Analyst", "Backend Engineer", "Frontend Engineer", "Data Scientist"]
    role_choice = st.selectbox(
        "Target role",
        options=["(use top job title from resume)"] + role_options + ["Other (type your own)"],
        index=0,
    )
    custom_role = ""
    if role_choice == "Other (type your own)":
        custom_role = st.text_input("Type your target role")

    country = st.radio(
        "Job market",
        options=["us", "np"],
        format_func=lambda c: {"us": "🇺🇸 United States (JSearch)", "np": "🇳🇵 Nepal (merojob.com)"}[c],
        horizontal=False,
    )
    st.session_state["country"] = country

    parse_clicked = st.button("Analyze resume", type="primary", use_container_width=True)
    st.caption("Cheap step — parses resume + computes deterministic skill gap. Each tab has its own generate button for the heavier LLM features.")
    st.divider()
    st.caption(f"Model: `{os.getenv('GEMINI_MODEL', 'gemini-2.0-flash')}` (override via `.env`)")


def _resolve_target_role(resume_info, choice: str, custom: str) -> str:
    if choice == "(use top job title from resume)":
        return (resume_info.job_title if resume_info and resume_info.job_title else "Software Engineer")
    if choice == "Other (type your own)":
        return custom.strip() or "Software Engineer"
    return choice


# --- Step 1: parse + skill gap (cheap) --------------------------------------
def _parse_resume(uploaded_file, role_choice: str, custom_role: str) -> None:
    """Run the upfront analysis with the animated scanner UI."""
    # reset per-target generated reports
    for k in ("linkedin", "interview", "roadmap", "feedback", "matched_jobs", "overall_score"):
        st.session_state[k] = None if k != "matched_jobs" else []

    # Mutable bucket lets each scanner step pass data to the next via closure.
    bucket: dict = {}

    def _step_extract():
        text = extract_text_from_pdf(uploaded_file)
        if not text:
            raise RuntimeError("No text could be extracted from this PDF.")
        bucket["text"] = text
        st.session_state["resume_text"] = text

    def _step_structure():
        try:
            info = parse_resume(bucket["text"], llm)
        except Exception as e:
            hint = _quota_hint(str(e))
            raise RuntimeError(f"{e}\n\n{hint or ''}")
        if not info:
            raise RuntimeError("Resume parsing returned nothing.")
        bucket["info"] = info
        st.session_state["resume_info"] = info

    def _step_skills():
        info = bucket["info"]
        bucket["skills_count"] = len(info.skills or [])
        if not info.skills:
            raise RuntimeError("No skills could be extracted from this resume.")

    def _step_target():
        info = bucket["info"]
        target_role = _resolve_target_role(info, role_choice, custom_role)
        bucket["target_role"] = target_role
        st.session_state["target_role"] = target_role

    def _step_skill_gap():
        info = bucket["info"]
        sg = analyze_skill_gap(info.skills or [], bucket["target_role"], llm=None)
        bucket["skill_gap"] = sg
        st.session_state["skill_gap"] = sg

    def _step_ats():
        ats = _ats_heuristic(bucket["text"], bucket["info"])
        bucket["ats"] = ats

    def _step_score():
        score = compute_overall_score(
            bucket["info"],
            bucket["target_role"],
            skill_gap=bucket["skill_gap"],
            semantic_similarity_0_to_1=0.0,
            resume_feedback=None,
        )
        st.session_state["overall_score"] = score

    steps = [
        {"label": "PDF Parse & File Compatibility",
         "desc": "Extracting text from your CV (with OCR fallback if scanned).",
         "fn": _step_extract},
        {"label": "Resume Structuring (AI)",
         "desc": "Identifying name, contact, skills, experience, and education.",
         "fn": _step_structure},
        {"label": "Skill Extraction",
         "desc": "Building the candidate's skill profile from work history.",
         "fn": _step_skills},
        {"label": "Target Role Lock-In",
         "desc": "Aligning analysis with your chosen role.",
         "fn": _step_target},
        {"label": "Market Comparison",
         "desc": "Comparing your skills against role-specific market demand.",
         "fn": _step_skill_gap},
        {"label": "ATS Compatibility Audit",
         "desc": "Heuristic checks for structure, action verbs, and quantification.",
         "fn": _step_ats},
        {"label": "Readiness Score",
         "desc": "Computing your overall weighted match score.",
         "fn": _step_score},
    ]

    render_scan_steps(uploaded_file, steps, brand="AI Resume Analyzer")


if parse_clicked:
    if not uploaded:
        st.warning("Upload a resume PDF first.")
    else:
        _parse_resume(uploaded, role_choice, custom_role)


# --- Helper: run an LLM call with quota-aware error UI ----------------------
def _safe_call(label: str, fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except Exception as e:
        hint = _quota_hint(str(e))
        st.error(f"{label} failed: {e}")
        if hint:
            st.info(hint)
        return None


# --- Render tabs ------------------------------------------------------------
info: Optional[ResumeInfo] = st.session_state.get("resume_info")
if not info:
    st.info("Upload a resume in the sidebar and click **Analyze resume** to begin.")
    st.stop()

target_role: str = st.session_state.get("target_role", "Software Engineer")

chat_tab, overview_tab, skillgap_tab, jobs_tab, linkedin_tab, interview_tab, roadmap_tab, audit_tab = st.tabs([
    f"💬 Chat with {ASSISTANT_NAME}",
    "Overview",
    "Skill Gap",
    "Job Matches",
    "LinkedIn Tips",
    "Interview",
    "Roadmap",
    "Resume Audit",
])


# ----- Career Chat (conversational coach) -----------------------------------
with chat_tab:
    st.subheader(f"Chat with {ASSISTANT_NAME}, your career coach")
    st.caption("Ask me anything about your resume, skills, job search, or interviews — just type below, like a normal chat.")

    chat_msgs = st.session_state["chat_messages"]
    # Background updates automatically as you generate more (skill gap, etc.).
    background = build_background(info, st.session_state.get("skill_gap"), target_role)
    first_name = (info.name.split()[0] if info.name and info.name != "Unknown" else "there")

    # Friendly opener + one-tap starters, only while the chat is empty.
    if not chat_msgs:
        with st.chat_message("assistant"):
            st.markdown(
                f"Hi {first_name}! 👋 I've read your resume and I'm here to help with your "
                f"job search, skills, interviews — whatever's on your mind. What would you like to talk about?"
            )
        starters = [
            "How does my resume look for my target role?",
            "What skills should I focus on learning next?",
            "Can you help me prep for an interview?",
            "How do I make my resume stand out more?",
        ]
        scols = st.columns(2)
        for i, s in enumerate(starters):
            if scols[i % 2].button(s, key=f"chat_start_{i}", use_container_width=True):
                st.session_state["chat_pending"] = s
                st.rerun()
    else:
        if st.button("🗑️ Clear chat", key="chat_clear"):
            st.session_state["chat_messages"] = []
            st.rerun()

    # Replay the conversation so far.
    for m in chat_msgs:
        with st.chat_message("user" if m["role"] == "user" else "assistant"):
            st.markdown(m["content"])

    # A typed message or a tapped starter both flow through here.
    pending = st.session_state.pop("chat_pending", None)
    user_msg = st.chat_input(f"Message {ASSISTANT_NAME}…") or pending

    if user_msg:
        chat_msgs.append({"role": "user", "content": user_msg})
        with st.chat_message("user"):
            st.markdown(user_msg)
        with st.chat_message("assistant"):
            # Streamed so it feels like a real person typing back.
            reply_text = st.write_stream(stream_reply(chat_msgs, llm, background))
        chat_msgs.append({"role": "assistant", "content": reply_text})
        st.rerun()


# ----- Overview --------------------------------------------------------------
with overview_tab:
    st.subheader("Candidate profile")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown(f"**Name:** {info.name}")
        st.markdown(f"**Email:** {info.email}")
        st.markdown(f"**Phone:** {info.phone_number}")
        st.markdown(f"**LinkedIn:** {info.linkedin_url}")
    with c2:
        st.markdown(f"**Top job title:** {info.job_title}")
        st.markdown(f"**Experience:** {info.experience_years if info.experience_years is not None else 'N/A'} years")
        st.markdown(f"**Target role:** {target_role}")
        st.markdown(f"**Skills:** {', '.join(info.skills or []) or '(none)'}")

    with st.expander("Full summary + work experience"):
        st.markdown(f"**Summary:** {info.summary or '(none)'}")
        for exp in info.work_experience or []:
            st.markdown(f"- **{exp.title}** at **{exp.company}** ({exp.dates})")
            for r in exp.responsibilities or []:
                st.markdown(f"  - {r}")
        if info.education:
            st.markdown("**Education:**")
            for ed in info.education:
                st.markdown(f"- {ed}")

    st.markdown("---")
    st.subheader("Weighted readiness score")
    overall = st.session_state.get("overall_score")
    if overall:
        st.metric("Overall match", f"{overall.total:.1f} / 100")
        bcols = st.columns(5)
        bcols[0].metric("Skill overlap (35%)", f"{overall.skill_overlap:.0f}")
        bcols[1].metric("Semantic (25%)", f"{overall.semantic_similarity:.0f}")
        bcols[2].metric("Experience (20%)", f"{overall.experience_fit:.0f}")
        bcols[3].metric("Keyword quality (10%)", f"{overall.keyword_quality:.0f}")
        bcols[4].metric("LinkedIn (10%)", f"{overall.linkedin_readiness:.0f}")
        st.caption("Score updates as you generate the Job Matches and Resume Audit tabs.")


# ----- Skill Gap -------------------------------------------------------------
with skillgap_tab:
    sg = st.session_state.get("skill_gap")
    if sg:
        st.subheader(f"Skill gap for: {sg.target_role}")
        st.progress(min(1.0, sg.match_percentage / 100), text=f"{sg.match_percentage:.1f}% match")
        st.markdown(f"**Summary:** {sg.summary}")

        col_btn1, col_btn2 = st.columns([1, 4])
        with col_btn1:
            if st.button("Enrich with LLM", key="sg_enrich"):
                with st.spinner("Asking Gemini to rank recommended skills (1 LLM call)..."):
                    enriched = _safe_call("LLM enrichment", analyze_skill_gap,
                                          info.skills or [], target_role, llm=llm)
                    if enriched:
                        st.session_state["skill_gap"] = enriched
                        st.rerun()

        c1, c2, c3 = st.columns(3)
        with c1:
            st.markdown("**Matched skills**")
            for s in sg.matched_skills or []:
                st.markdown(f"- ✅ {s}")
            if not sg.matched_skills:
                st.caption("(none)")
        with c2:
            st.markdown("**Missing skills**")
            for s in sg.missing_skills or []:
                st.markdown(f"- ❌ {s}")
            if not sg.missing_skills:
                st.caption("(none)")
        with c3:
            st.markdown("**Recommended next skills**")
            for i, s in enumerate(sg.recommended_next_skills or [], 1):
                st.markdown(f"{i}. {s}")
            if not sg.recommended_next_skills:
                st.caption("(none)")

        with st.expander("Top skills the market asks for in this role (from job_metadata.json)"):
            top = top_skills_for_role(sg.target_role, k=20)
            if not top:
                st.caption("No offline data for this role.")
            else:
                for skill, count in top:
                    st.markdown(f"- **{skill}** — appears in {count} job(s)")


# ----- Job Matches -----------------------------------------------------------
with jobs_tab:
    st.subheader("Job matches")
    selected_country = st.session_state.get("country", "us")
    market_label = "🇳🇵 Nepal — merojob.com" if selected_country == "np" else "🇺🇸 United States — JSearch"
    st.caption(f"Live market: **{market_label}**  (change in sidebar)")
    jobs = st.session_state.get("matched_jobs", [])
    btn_cols = st.columns([1, 1, 4])
    with btn_cols[0]:
        live_clicked = st.button("Find live jobs", key="jobs_live")
    with btn_cols[1]:
        offline_clicked = st.button("Use offline dataset", key="jobs_offline")
    st.caption("Offline = the 30 cached jobs in job_metadata.json (no API, no LLM). Use it if live is down or rate-limited.")

    if live_clicked:
        with st.spinner(f"Fetching + ranking live jobs from {market_label}..."):
            matched = _safe_call("Live job match", process_jobs, info, llm, emb, selected_country)
            if matched:
                matched, _ = matched
                st.session_state["matched_jobs"] = matched
                top_sim = matched[0].get("similarity_score", 0.0) if matched else 0.0
                st.session_state["top_semantic"] = top_sim
                # refresh overall score with new semantic
                st.session_state["overall_score"] = compute_overall_score(
                    info, target_role, skill_gap=st.session_state.get("skill_gap"),
                    semantic_similarity_0_to_1=top_sim,
                    resume_feedback=st.session_state.get("feedback"),
                )
                st.rerun()

    if offline_clicked:
        with st.spinner("Matching against offline dataset..."):
            keywords = info.optimized_search_keywords or info.skills or [info.job_title or ""]
            raw = offline_jobs_for_keywords(keywords, limit=20)
            resume_blob = f"{info.summary or ''} {' '.join(info.skills or [])} {info.job_title or ''}"
            resume_emb = generate_embedding(resume_blob, emb)
            for j in raw:
                try:
                    blob = (j.get("title", "") + " " + j.get("description", ""))[:2000]
                    j_emb = generate_embedding(blob, emb)
                    j["similarity_score"] = float(calculate_similarity(resume_emb, j_emb)) if resume_emb is not None and j_emb is not None else 0.5
                except Exception:
                    j["similarity_score"] = 0.5
                j["apply_link"] = j.get("job_url") or "#"
                j["parsed_experience_req"] = {"minimum_years_experience_required": None, "inferred_level": "unknown"}
            raw.sort(key=lambda x: x.get("similarity_score", 0), reverse=True)
            st.session_state["matched_jobs"] = raw
            top_sim = raw[0].get("similarity_score", 0.0) if raw else 0.0
            st.session_state["top_semantic"] = top_sim
            st.session_state["overall_score"] = compute_overall_score(
                info, target_role, skill_gap=st.session_state.get("skill_gap"),
                semantic_similarity_0_to_1=top_sim,
                resume_feedback=st.session_state.get("feedback"),
            )
            st.rerun()

    jobs = st.session_state.get("matched_jobs", [])
    if jobs:
        st.markdown(f"**{len(jobs)} job(s) ranked by similarity**")
        for job in jobs:
            parsed = job.get("parsed_experience_req", {}) or {}
            min_years = parsed.get("minimum_years_experience_required")
            level = (parsed.get("inferred_level") or "unknown").replace("_", " ").title()
            sim = job.get("similarity_score", 0.0)
            color = "#90EE90" if sim >= 0.8 else ("#FFD700" if sim >= 0.7 else "#FF6347")
            desc = (job.get("description") or "").replace("\n", " ")
            st.markdown(
                f"""<div style="background:#262730;padding:14px;border-radius:8px;margin-bottom:10px;color:#FAFAFA;">
<h5 style="margin-top:0;color:#FAFAFA;">{job.get('title','N/A')}</h5>
<strong>Company:</strong> {job.get('company','N/A')}<br>
<strong>Location:</strong> {job.get('location','N/A')}<br>
<strong>Experience req:</strong> {min_years if min_years is not None else 'N/A'} ({level})<br>
<strong>Match score:</strong> <span style="color:{color};font-weight:bold;">{sim:.2f}</span><br>
<strong>Link:</strong> <a href="{job.get('apply_link','#')}" target="_blank" style="color:#ADD8E6;">Apply</a>
<details style="margin-top:8px;"><summary style="color:#ADD8E6;">Description</summary>
<p style="font-size:0.9em;color:#FAFAFA;">{desc}</p></details></div>""",
                unsafe_allow_html=True,
            )


# ----- LinkedIn Tips ---------------------------------------------------------
with linkedin_tab:
    lr = st.session_state.get("linkedin")
    if not lr:
        st.info("Generate LinkedIn optimization tips for this candidate + target role. Uses 1 LLM call.")
        if st.button("Generate LinkedIn report", key="gen_linkedin"):
            with st.spinner("Asking Gemini for LinkedIn improvements (1 LLM call)..."):
                missing = (st.session_state.get("skill_gap").missing_skills if st.session_state.get("skill_gap") else [])
                lr = _safe_call("LinkedIn report", generate_linkedin_report, info, target_role, missing, llm=llm)
                if lr:
                    st.session_state["linkedin"] = lr
                    st.rerun()
    else:
        st.subheader("Suggested headline")
        st.success(lr.suggested_headline)
        st.subheader("Rewritten About section")
        st.write(lr.about_section)
        st.subheader("Missing keywords to add")
        st.write(", ".join(lr.missing_keywords) or "(none)")
        st.subheader("Achievement rewrites")
        for a in lr.achievement_rewrites or []:
            with st.container(border=True):
                st.markdown(f"**Before:** {a.original}")
                st.markdown(f"**After:** {a.rewritten}")
                st.caption(a.why)
        st.subheader("Profile tips")
        for t in lr.profile_tips or []:
            st.markdown(f"- {t}")
        if st.button("Regenerate", key="regen_linkedin"):
            st.session_state["linkedin"] = None
            st.rerun()


# ----- Interview -------------------------------------------------------------
with interview_tab:
    ip = st.session_state.get("interview")
    if not ip:
        st.info("Generate likely interview questions tailored to this resume + target role. Uses 1 LLM call.")
        if st.button("Generate interview prep", key="gen_interview"):
            with st.spinner("Asking Gemini for likely questions (1 LLM call)..."):
                missing = (st.session_state.get("skill_gap").missing_skills if st.session_state.get("skill_gap") else [])
                ip = _safe_call("Interview prep", generate_interview_prep, info, target_role, missing, llm=llm)
                if ip:
                    st.session_state["interview"] = ip
                    st.rerun()
    else:
        st.subheader(f"Likely interview questions for: {ip.target_role}")
        for i, q in enumerate(ip.questions or [], 1):
            with st.expander(f"Q{i}. [{q.category}] {q.question}"):
                st.markdown(f"**Why asked:** {q.why_asked}")
                st.markdown(f"**Answer outline:** {q.answer_outline}")
        if st.button("Regenerate", key="regen_interview"):
            st.session_state["interview"] = None
            st.rerun()


# ----- Roadmap --------------------------------------------------------------
with roadmap_tab:
    rm = st.session_state.get("roadmap")
    if not rm:
        st.info("Generate a 30/60/90-day learning roadmap from the missing skills. Uses 1 LLM call.")
        if st.button("Generate roadmap", key="gen_roadmap"):
            with st.spinner("Asking Gemini for a 30/60/90 plan (1 LLM call)..."):
                missing = (st.session_state.get("skill_gap").missing_skills if st.session_state.get("skill_gap") else [])
                rm = _safe_call("Roadmap", generate_roadmap, info, target_role, missing, llm=llm)
                if rm:
                    st.session_state["roadmap"] = rm
                    st.rerun()
    else:
        st.subheader(f"30/60/90-day plan for: {rm.target_role}")
        if rm.priority_skills:
            st.markdown(f"**Priority skills overall:** {', '.join(rm.priority_skills)}")
        for phase in rm.phases or []:
            label = {"30_days": "Days 1-30", "60_days": "Days 31-60", "90_days": "Days 61-90"}.get(phase.phase, phase.phase)
            with st.container(border=True):
                st.markdown(f"### {label} — Focus: {phase.focus}")
                if phase.skills_to_learn:
                    st.markdown("**Skills to learn:** " + ", ".join(phase.skills_to_learn))
                if phase.weekly_actions:
                    st.markdown("**Weekly actions:**")
                    for a in phase.weekly_actions:
                        st.markdown(f"- {a}")
                st.markdown(f"**Mini-project:** {phase.mini_project}")
                st.markdown(f"**Milestone:** {phase.milestone}")
        if st.button("Regenerate", key="regen_roadmap"):
            st.session_state["roadmap"] = None
            st.rerun()


# ----- Resume Audit ----------------------------------------------------------
with audit_tab:
    fb = st.session_state.get("feedback")
    if not fb:
        st.info("Compute the ATS score (deterministic) plus LLM-written structure/keyword feedback. Uses 1 LLM call.")
        if st.button("Run resume audit", key="gen_feedback"):
            with st.spinner("Computing ATS score + asking Gemini for feedback (1 LLM call)..."):
                fb = _safe_call("Resume audit", generate_resume_feedback,
                                st.session_state.get("resume_text", ""), info, target_role, llm=llm)
                if fb:
                    st.session_state["feedback"] = fb
                    # refresh overall score with new keyword/ats component
                    st.session_state["overall_score"] = compute_overall_score(
                        info, target_role,
                        skill_gap=st.session_state.get("skill_gap"),
                        semantic_similarity_0_to_1=st.session_state.get("top_semantic", 0.0),
                        resume_feedback=fb,
                    )
                    st.rerun()
    else:
        st.subheader("Resume audit")
        st.metric("ATS friendliness", f"{fb.ats_score}/100")
        st.markdown("**Structure feedback**")
        st.write(fb.structure_feedback)
        st.markdown("**Action verbs**")
        st.write(fb.action_verbs_feedback)
        st.markdown("**Quantification**")
        st.write(fb.quantification_feedback)
        st.markdown("**Keywords to add**")
        st.write(", ".join(fb.keyword_optimization) or "(none)")
        if fb.bullet_improvements:
            st.markdown("**Bullet rewrites**")
            for b in fb.bullet_improvements:
                with st.container(border=True):
                    st.markdown(f"**Before:** {b.original}")
                    st.markdown(f"**After:** {b.rewritten}")
                    st.caption(b.why)
        if fb.top_recommendations:
            st.markdown("**Top recommendations**")
            for r in fb.top_recommendations:
                st.markdown(f"- {r}")
        if st.button("Regenerate", key="regen_feedback"):
            st.session_state["feedback"] = None
            st.rerun()
