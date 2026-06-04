"""
hr_ui
=====

Streamlit page for HR / Recruiter mode. Kept in its own module (like
`scan_ui.py`) so the candidate-facing dashboard in `streamlit_app.py` stays
untouched. Entry point: `render_hr_mode(llm, emb)`.

Two views, switched by the nav buttons at the top:
  - "Screen the pool": semantic search + optional AI deep-screen over a
    folder of resumes.
  - "Candidate chat": grounded Q&A about one selected candidate, with
    evidence quotes and a confidence flag on every answer.
"""

from __future__ import annotations

import os
from typing import Any

import streamlit as st

from hr_service import (
    DEFAULT_RESUME_DIR,
    list_resume_files,
    index_resumes,
    search_resumes,
    answer_question,
    screen_candidate,
    parse_candidate_profile,
)

_CONFIDENCE_BADGE = {
    "explicitly_stated": ("✅ Stated in resume", "#1a7f37"),
    "implied": ("≈ Implied by resume", "#b35900"),
    "not_found": ("⚠ Not in this resume", "#c0392b"),
}

_VERDICT_BADGE = {
    "strong_match": ("Strong match", "#1a7f37"),
    "possible_match": ("Possible match", "#2d7d9a"),
    "weak_match": ("Weak match", "#b35900"),
    "not_a_match": ("Not a match", "#c0392b"),
}

_SUGGESTED_QUESTIONS = [
    "What are this candidate's strongest skills?",
    "How many years of relevant experience do they have?",
    "Have they led a team or a project?",
    "What is missing or unclear in this resume?",
]


def _ss(key: str, default: Any = None) -> Any:
    if key not in st.session_state:
        st.session_state[key] = default
    return st.session_state[key]


def _badge(text: str, color: str) -> str:
    return (
        f"<span style='background:{color};color:white;padding:2px 8px;"
        f"border-radius:10px;font-size:0.8em;font-weight:600;'>{text}</span>"
    )


# ---------------------------------------------------------------------------
# Indexing (sidebar)
# ---------------------------------------------------------------------------

def _sidebar_pool(emb) -> None:
    with st.sidebar:
        st.subheader("Resume pool")
        directory = st.text_input("Folder with resumes (PDF)", value=st.session_state["hr_dir"])
        st.session_state["hr_dir"] = directory

        files = list_resume_files(directory)
        st.caption(f"{len(files)} PDF(s) found in this folder.")

        if st.button("Index / refresh pool", type="primary", use_container_width=True, disabled=not files):
            prog = st.progress(0.0, text="Starting…")

            def _cb(i: int, n: int, name: str) -> None:
                prog.progress(min(1.0, i / max(1, n)), text=f"Indexing {i}/{n}: {name}")

            with st.spinner("Reading + embedding resumes locally (no LLM, cached on disk)…"):
                st.session_state["hr_index"] = index_resumes(directory, emb, progress_cb=_cb)
            prog.empty()
            st.success(f"Indexed {len(st.session_state['hr_index'])} resume(s).")

        st.caption("Indexing extracts text + builds embeddings on your machine. No quota used. Re-running is instant for unchanged files.")


# ---------------------------------------------------------------------------
# View 1 — screen the pool
# ---------------------------------------------------------------------------

def _render_screen(llm, emb) -> None:
    index = st.session_state["hr_index"]
    st.subheader("Screen the pool")
    st.caption("Describe who you're looking for (or paste a job description). Search ranks every resume by meaning — not just keywords.")

    query = st.text_area(
        "What are you looking for?",
        value=st.session_state.get("hr_last_query", ""),
        placeholder="e.g. Backend engineer with 3+ years Python and AWS who has led a small team",
        height=90,
    )

    c1, c2, c3 = st.columns([1, 1, 3])
    search_clicked = c1.button("🔎 Search pool", use_container_width=True)
    top_n = c2.selectbox("Deep-screen", [3, 5, 10], index=1, label_visibility="collapsed")
    deep_clicked = c3.button(f"🤖 AI deep-screen top {top_n}", use_container_width=True,
                             help="Runs a grounded LLM fit assessment on the top candidates (1 LLM call each).")

    if search_clicked or deep_clicked:
        if not query.strip():
            st.warning("Type what you're looking for first.")
        else:
            st.session_state["hr_last_query"] = query
            st.session_state["hr_results"] = search_resumes(query, index, emb, top_k=10)
            if deep_clicked:
                with st.spinner(f"Deep-screening top {top_n} candidates against your criteria…"):
                    for rec, _score in st.session_state["hr_results"][:top_n]:
                        res = screen_candidate(rec["text"], query, llm, candidate_name=rec["name"])
                        if res:
                            st.session_state["hr_screen"][rec["file"]] = res

    results = st.session_state.get("hr_results", [])
    if not results:
        st.info(f"Indexed {len(index)} candidate(s). Enter criteria above and search.")
        return

    st.markdown(f"**Top {len(results)} of {len(index)} candidates**")
    for rank, (rec, score) in enumerate(results, 1):
        screen = st.session_state["hr_screen"].get(rec["file"])
        with st.container(border=True):
            head = st.columns([5, 2, 2])
            head[0].markdown(f"**{rank}. {rec['name']}**  \n<small>{os.path.basename(rec['file'])}</small>", unsafe_allow_html=True)
            head[1].metric("Semantic match", f"{score * 100:.0f}%")
            if screen:
                label, color = _VERDICT_BADGE.get(screen.verdict, (screen.verdict, "#555"))
                head[2].markdown(
                    f"{_badge(label, color)}<br><small>fit {screen.fit_score}/100</small>",
                    unsafe_allow_html=True,
                )

            snippet = " ".join((rec["text"] or "").split())[:240]
            st.caption(snippet + "…")

            if screen:
                if screen.rationale:
                    st.markdown(f"**Why:** {screen.rationale}")
                sc1, sc2 = st.columns(2)
                with sc1:
                    st.markdown("**Meets**")
                    for r in screen.matched_requirements or []:
                        st.markdown(f"- ✅ {r}")
                    if not screen.matched_requirements:
                        st.caption("(none clearly evidenced)")
                with sc2:
                    st.markdown("**Gaps**")
                    for r in screen.missing_requirements or []:
                        st.markdown(f"- ❌ {r}")
                    if not screen.missing_requirements:
                        st.caption("(none)")
                if screen.evidence:
                    with st.expander("Evidence from resume"):
                        for q in screen.evidence:
                            st.markdown(f"> {q}")

            if st.button("💬 Open in chat", key=f"open_{rec['file']}", use_container_width=True):
                st.session_state["hr_selected"] = rec["file"]
                st.session_state["hr_view"] = "chat"
                st.rerun()


# ---------------------------------------------------------------------------
# View 2 — chat with one candidate
# ---------------------------------------------------------------------------

def _record_for(file_path: str) -> dict | None:
    for rec in st.session_state["hr_index"]:
        if rec["file"] == file_path:
            return rec
    return None


def _render_chat(llm) -> None:
    index = st.session_state["hr_index"]
    st.subheader("Candidate chat")
    st.caption("Ask anything about this candidate. Every answer is grounded in their resume, with the supporting quote and a confidence flag.")

    names = {rec["file"]: f"{rec['name']}  ({os.path.basename(rec['file'])})" for rec in index}
    files = list(names.keys())
    current = st.session_state.get("hr_selected")
    if current not in files:
        current = files[0] if files else None
    selected = st.selectbox(
        "Candidate",
        options=files,
        index=files.index(current) if current in files else 0,
        format_func=lambda f: names.get(f, os.path.basename(f)),
    )
    st.session_state["hr_selected"] = selected
    rec = _record_for(selected)
    if not rec:
        st.info("Select a candidate.")
        return

    # Candidate header + optional lazy profile parse
    hc = st.columns([4, 2])
    hc[0].markdown(f"### {rec['name']}")
    hc[1].caption(f"{rec['n_chars']:,} chars of resume text")
    with st.expander("Parsed profile (1 LLM call — optional)"):
        cache = st.session_state["hr_profiles"]
        if selected not in cache:
            if st.button("Parse this resume into a profile", key=f"parse_{selected}"):
                with st.spinner("Parsing resume…"):
                    cache[selected] = parse_candidate_profile(rec["text"], llm)
                st.rerun()
        info = cache.get(selected)
        if info:
            st.markdown(f"**Name:** {info.name}  |  **Title:** {info.job_title}  |  **Experience:** "
                        f"{info.experience_years if info.experience_years is not None else 'N/A'} yrs")
            st.markdown(f"**Skills:** {', '.join(info.skills or []) or '(none)'}")
            st.markdown(f"**Email:** {info.email}  |  **Phone:** {info.phone_number}")

    chats = st.session_state["hr_chats"].setdefault(selected, [])

    # Funnel both the input form and the follow-up buttons through one pending slot,
    # so each question is processed exactly once, before the history is rendered.
    pending = st.session_state.pop("hr_pending", None)
    if pending:
        chats.append({"role": "user", "content": pending})
        with st.spinner("Reading the resume…"):
            ans = answer_question(rec["text"], pending, llm, history=chats[:-1])
        chats.append({
            "role": "assistant",
            "content": ans.answer,
            "confidence": ans.confidence,
            "evidence": ans.evidence,
            "follow_ups": ans.follow_up_suggestions,
        })

    # Render conversation
    if not chats:
        st.markdown("**Try asking:**")
        sq_cols = st.columns(2)
        for i, q in enumerate(_SUGGESTED_QUESTIONS):
            if sq_cols[i % 2].button(q, key=f"sq_{i}", use_container_width=True):
                st.session_state["hr_pending"] = q
                st.rerun()

    for idx, msg in enumerate(chats):
        with st.chat_message("user" if msg["role"] == "user" else "assistant"):
            st.markdown(msg["content"])
            if msg["role"] == "assistant":
                label, color = _CONFIDENCE_BADGE.get(msg.get("confidence", "not_found"))
                st.markdown(_badge(label, color), unsafe_allow_html=True)
                if msg.get("evidence"):
                    with st.expander("Evidence from resume"):
                        for q in msg["evidence"]:
                            st.markdown(f"> {q}")

    # Follow-up chips from the most recent answer
    if chats and chats[-1]["role"] == "assistant" and chats[-1].get("follow_ups"):
        st.caption("Follow-up suggestions:")
        fcols = st.columns(min(3, len(chats[-1]["follow_ups"])))
        for i, q in enumerate(chats[-1]["follow_ups"][:3]):
            if fcols[i].button(q, key=f"fu_{len(chats)}_{i}", use_container_width=True):
                st.session_state["hr_pending"] = q
                st.rerun()

    # Input
    with st.form(key=f"chatform_{selected}", clear_on_submit=True):
        question = st.text_input("Ask about this candidate", placeholder="e.g. Does he have experience with Docker or Kubernetes?")
        col_a, col_b = st.columns([1, 5])
        sent = col_a.form_submit_button("Send", type="primary", use_container_width=True)
        if col_b.form_submit_button("Clear chat", use_container_width=True):
            st.session_state["hr_chats"][selected] = []
            st.rerun()
        if sent and question.strip():
            st.session_state["hr_pending"] = question.strip()
            st.rerun()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def render_hr_mode(llm, emb) -> None:
    st.title("HR / Recruiter — Resume Intelligence")
    st.caption("Search a folder of resumes, screen them against a role, and chat with any candidate — every answer grounded in their CV.")

    # State
    _ss("hr_dir", DEFAULT_RESUME_DIR)
    _ss("hr_index", [])
    _ss("hr_results", [])
    _ss("hr_screen", {})       # file -> CandidateScreen
    _ss("hr_selected", None)
    _ss("hr_chats", {})        # file -> [ {role, content, ...} ]
    _ss("hr_profiles", {})     # file -> ResumeInfo
    _ss("hr_view", "screen")
    _ss("hr_last_query", "")

    _sidebar_pool(emb)

    if not st.session_state["hr_index"]:
        st.info("👈 Set the folder containing your resumes in the sidebar, then click **Index / refresh pool**.")
        st.stop()

    # Nav
    n1, n2, _ = st.columns([1, 1, 4])
    view = st.session_state["hr_view"]
    if n1.button("🔎 Screen the pool", use_container_width=True,
                 type="primary" if view == "screen" else "secondary"):
        st.session_state["hr_view"] = "screen"
        st.rerun()
    if n2.button("💬 Candidate chat", use_container_width=True,
                 type="primary" if view == "chat" else "secondary"):
        st.session_state["hr_view"] = "chat"
        st.rerun()
    st.divider()

    if view == "chat":
        _render_chat(llm)
    else:
        _render_screen(llm, emb)
