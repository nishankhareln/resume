"""
chat_service
============

A natural, conversational career-coach chatbot for the candidate dashboard.

Unlike the other service modules (skill gap, interview, roadmap, …) which
ask the LLM for *structured* Pydantic reports, this one is deliberately the
opposite: it talks like a real person. Plain text, friendly, remembers the
conversation, and quietly uses whatever we already know about the candidate's
resume as background so answers feel personal — not like a form.

Design notes:
  - Reuses the same cached Gemini LLM as the rest of the app (no extra init,
    no extra quota surprises). The warm, human tone comes from the system
    prompt, not a separate model.
  - Streams the reply token-by-token so the UI can show a realistic "typing"
    effect via `st.write_stream`.
  - Degrades gracefully: if the model errors or hits the free-tier quota,
    the user still gets a friendly, plain-English message instead of a
    traceback.
"""

from __future__ import annotations

import logging
from typing import Iterator, List, Optional

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

logger = logging.getLogger(__name__)

# The assistant's persona. Named so it feels like talking to a person, not a
# tool. The rules keep it short, warm, and human — the opposite of the rigid,
# badge-and-evidence HR chat.
ASSISTANT_NAME = "NK"

_SYSTEM_PROMPT = """You are {name}, a warm and encouraging AI career coach built into a resume app.
You're chatting with a job seeker. Talk like a real, helpful person — not a robot or a form.

How you talk:
- Be friendly, natural, and conversational. Sound like a supportive friend who happens to be great at careers.
- Keep replies short and easy to read — usually 2 to 5 sentences. Only give long lists when they actually ask for one.
- It's fine to ask a gentle follow-up question to keep the conversation going.
- Use their first name once in a while if you know it, but don't overdo it.
- Plain English. No corporate buzzwords, no "As an AI language model" disclaimers, no walls of text, no emoji spam.

What you help with:
- Resume feedback, skills, career direction, job hunting, interviews, LinkedIn, and learning plans.
- Use the background below to make your answers personal. If something they ask about isn't in it, just say you don't see it and ask them.
- If they go off-topic, answer briefly and gently bring it back to their career.
- Never invent facts about the person. If you're not sure, ask.

{background}
"""

_NO_RESUME_BACKGROUND = (
    "Background: You don't have this person's resume yet. If their question needs details "
    "about their experience, ask them — or suggest they upload their resume in the sidebar "
    "and click 'Analyze resume' so you can give sharper, personalized advice."
)


def build_background(info=None, skill_gap=None, target_role: Optional[str] = None) -> str:
    """Turn the parsed resume + skill gap into a short, readable briefing the
    coach can lean on. Returns a generic note if we don't have a resume yet."""
    if info is None:
        return _NO_RESUME_BACKGROUND

    lines: List[str] = ["Background on the person you're talking to (from their resume):"]

    name = getattr(info, "name", None)
    if name and name != "Unknown":
        lines.append(f"- Name: {name}")
    title = getattr(info, "job_title", None)
    if title and title != "Unknown":
        lines.append(f"- Current/most recent title: {title}")
    years = getattr(info, "experience_years", None)
    if years is not None:
        lines.append(f"- Years of experience: {years}")
    if target_role:
        lines.append(f"- Role they're aiming for: {target_role}")

    skills = getattr(info, "skills", None) or []
    if skills:
        lines.append(f"- Skills on resume: {', '.join(skills[:25])}")

    summary = getattr(info, "summary", None)
    if summary and summary != "Not provided":
        lines.append(f"- Summary: {summary}")

    # A couple of recent roles give the coach something concrete to reference.
    work = getattr(info, "work_experience", None) or []
    if work:
        lines.append("- Recent experience:")
        for exp in work[:3]:
            company = getattr(exp, "company", "") or ""
            etitle = getattr(exp, "title", "") or ""
            dates = getattr(exp, "dates", "") or ""
            lines.append(f"    • {etitle} at {company} ({dates})")

    if skill_gap is not None:
        matched = getattr(skill_gap, "matched_skills", None) or []
        missing = getattr(skill_gap, "missing_skills", None) or []
        match_pct = getattr(skill_gap, "match_percentage", None)
        if match_pct is not None:
            lines.append(f"- Skill match for the target role: about {match_pct:.0f}%")
        if missing:
            lines.append(f"- Skills they're missing for the target role: {', '.join(missing[:12])}")
        if matched:
            lines.append(f"- Skills they already have for it: {', '.join(matched[:12])}")

    lines.append(
        "\nUse this naturally — don't read it back like a report. Bring up specifics only when relevant."
    )
    return "\n".join(lines)


def format_job_context(job: Optional[dict]) -> str:
    """Build a short block describing the job the user is currently viewing, so
    NK can act as a copilot ("am I a fit for THIS one?", "tailor my resume to
    this posting"). Returns "" when no job is in focus."""
    if not job:
        return ""
    lines = ["The user is currently looking at this specific job posting:"]
    title = job.get("title")
    company = job.get("company")
    location = job.get("location")
    if title and title != "N/A":
        lines.append(f"- Title: {title}")
    if company and company != "N/A":
        lines.append(f"- Company: {company}")
    if location and location != "N/A":
        lines.append(f"- Location: {location}")
    score = job.get("match_score")
    if isinstance(score, (int, float)):
        lines.append(f"- Their resume's semantic match to this job: about {round(score * 100)}%")
    desc = (job.get("description") or "").strip()
    if desc:
        lines.append(f"- Job description (may be truncated):\n\"\"\"\n{desc[:2500]}\n\"\"\"")
    lines.append(
        "\nWhen they ask about fit, tailoring, or applying, compare THIS posting against their "
        "resume above and be specific about what matches and what's missing. Don't invent requirements."
    )
    return "\n".join(lines)


def _to_lc_messages(history: List[dict], background: str) -> list:
    """Convert our simple [{role, content}] chat history into LangChain
    message objects, with the persona system prompt up front."""
    messages: list = [
        SystemMessage(content=_SYSTEM_PROMPT.format(name=ASSISTANT_NAME, background=background))
    ]
    for turn in history:
        content = (turn.get("content") or "").strip()
        if not content:
            continue
        if turn.get("role") == "user":
            messages.append(HumanMessage(content=content))
        else:
            messages.append(AIMessage(content=content))
    return messages


def _friendly_error(err: Exception) -> str:
    """Map an exception to a calm, human message (quota errors get a hint)."""
    msg = str(err).lower()
    if "resourceexhausted" in msg or "429" in msg or "quota" in msg or "rate limit" in msg:
        return (
            "I'm getting a lot of requests right now and hit a short rate limit. "
            "Give it a minute and ask me again — I'll be right here."
        )
    return (
        "Sorry, something went wrong on my end and I couldn't finish that thought. "
        "Mind trying again?"
    )


def stream_reply(history: List[dict], llm, background: str = "") -> Iterator[str]:
    """Yield the assistant's reply in chunks, for `st.write_stream`.

    `history` is the full conversation so far INCLUDING the latest user
    message as the last item. `background` comes from `build_background`.
    Always yields *something* readable, even on failure.
    """
    if llm is None:
        yield "The AI model isn't available right now. Please check the GEMINI_API_KEY in your .env file."
        return

    background = background or _NO_RESUME_BACKGROUND
    messages = _to_lc_messages(history, background)

    try:
        produced = False
        for chunk in llm.stream(messages):
            text = getattr(chunk, "content", "") or ""
            if text:
                produced = True
                yield text
        if not produced:
            # Some backends return the whole answer in one non-streamed blob.
            result = llm.invoke(messages)
            yield getattr(result, "content", "") or "I'm not sure how to answer that — could you rephrase?"
    except Exception as e:  # noqa: BLE001 - we want any failure to read as a friendly line
        logger.warning(f"Chat stream failed: {e}")
        yield _friendly_error(e)


def reply(history: List[dict], llm, background: str = "") -> str:
    """Non-streaming convenience wrapper — returns the full reply as a string."""
    return "".join(stream_reply(history, llm, background))
