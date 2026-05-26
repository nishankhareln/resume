"""
interview_service
=================

Generate likely interview questions for the candidate's target role,
informed by their resume strengths AND their missing skills (so the
questions probe real weak spots, not generic trivia).
"""

from __future__ import annotations

import logging
from typing import List, Optional

from langchain.prompts import PromptTemplate
from langchain.output_parsers import PydanticOutputParser
from pydantic import ValidationError

from schemas import InterviewPrepReport

logger = logging.getLogger(__name__)


_parser = PydanticOutputParser(pydantic_object=InterviewPrepReport)

_PROMPT = PromptTemplate(
    template="""You are a hiring manager preparing the interview loop for a "{target_role}" role.

Generate 6-8 interview questions tailored to THIS specific candidate. Mix categories:
- 2-3 technical questions probing skills the candidate already claims (verify depth).
- 1-2 technical questions targeting their MISSING skills (gauge willingness/learning).
- 1-2 behavioral/STAR questions tied to their actual work history.
- 1 system_design OR role_specific question appropriate to the seniority level.
- 1 HR question (motivation, role fit, salary expectations, etc.).

For each question, provide:
- question: the question itself
- category: one of technical, behavioral, system_design, hr, role_specific
- why_asked: short reason an interviewer for THIS role would ask
- answer_outline: a SHORT bullet outline (3-5 sub-points joined by "; ") of what a strong answer covers

Candidate profile:
- Current title: {current_title}
- Years of experience: {years}
- Skills: {skills}
- Recent role bullets:
{bullets}
- Missing skills for target role: {missing_skills}

{format_instructions}
""",
    input_variables=["target_role", "current_title", "years", "skills", "bullets", "missing_skills"],
    partial_variables={"format_instructions": _parser.get_format_instructions()},
)


def _bullets(resume_info, limit: int = 8) -> str:
    out: List[str] = []
    for exp in (resume_info.work_experience or [])[:3]:
        for resp in (exp.responsibilities or [])[:3]:
            out.append(f"- ({exp.title} @ {exp.company}) {resp}")
            if len(out) >= limit:
                return "\n".join(out)
    return "\n".join(out) if out else "(no bullets)"


def generate_interview_prep(
    resume_info,
    target_role: str,
    missing_skills: Optional[List[str]] = None,
    llm=None,
) -> Optional[InterviewPrepReport]:
    if llm is None:
        logger.error("LLM required for interview_service.")
        return None

    try:
        chain = _PROMPT | llm | _parser
        report = chain.invoke({
            "target_role": target_role,
            "current_title": resume_info.job_title or "(unknown)",
            "years": resume_info.experience_years if resume_info.experience_years is not None else 0,
            "skills": ", ".join(resume_info.skills or []) or "(none)",
            "bullets": _bullets(resume_info),
            "missing_skills": ", ".join(missing_skills or []) or "(none)",
        })
        report.target_role = target_role  # defensive
        return report
    except (ValidationError, Exception) as e:
        logger.error(f"Interview prep generation failed: {e}")
        return None
