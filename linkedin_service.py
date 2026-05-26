"""
linkedin_service
================

Given the candidate's ResumeInfo and a target role, ask Gemini to produce
LinkedIn-style improvements: a stronger headline, a rewritten About section,
missing keywords to add, achievement rewrites, and profile tips.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from langchain.prompts import PromptTemplate
from langchain.output_parsers import PydanticOutputParser
from pydantic import ValidationError

from schemas import LinkedInOptimizationReport

logger = logging.getLogger(__name__)


_parser = PydanticOutputParser(pydantic_object=LinkedInOptimizationReport)

_PROMPT = PromptTemplate(
    template="""You are a career coach who specializes in LinkedIn branding.

Produce a LinkedIn optimization report for this candidate targeting the role of "{target_role}".

The headline must be 10-15 words, punchy, and contain 1-2 keywords from the target role.
The About section must be 3-5 sentences, written in FIRST PERSON, and emphasize measurable impact.
Achievement rewrites should take real bullets from the resume and rewrite them with stronger action verbs, quantification, and outcome focus. Pick 2-4 of the WEAKEST bullets to rewrite — never invent metrics that aren't implied.
Missing keywords: 5-10 industry terms missing from the resume that recruiters search for.
Profile tips: 3-5 concrete LinkedIn-specific bullets (banner image, featured section, recommendations, endorsements, post cadence, etc.).

Candidate name: {name}
Current job title: {current_title}
Years of experience: {years}
Summary: {summary}
Skills: {skills}
Sample work experience bullets (truncated):
{bullets}
Missing skills for this role: {missing_skills}

{format_instructions}
""",
    input_variables=["target_role", "name", "current_title", "years", "summary", "skills", "bullets", "missing_skills"],
    partial_variables={"format_instructions": _parser.get_format_instructions()},
)


def _collect_bullets(resume_info, limit: int = 12) -> str:
    out: List[str] = []
    for exp in (resume_info.work_experience or [])[:5]:
        for resp in (exp.responsibilities or [])[:4]:
            out.append(f"- ({exp.title}) {resp}")
            if len(out) >= limit:
                return "\n".join(out)
    return "\n".join(out) if out else "(no bullets extracted)"


def generate_linkedin_report(
    resume_info,
    target_role: str,
    missing_skills: Optional[List[str]] = None,
    llm=None,
) -> Optional[LinkedInOptimizationReport]:
    if llm is None:
        logger.error("LLM is required for linkedin_service.")
        return None

    try:
        chain = _PROMPT | llm | _parser
        return chain.invoke({
            "target_role": target_role,
            "name": resume_info.name or "Candidate",
            "current_title": resume_info.job_title or "(unknown)",
            "years": resume_info.experience_years if resume_info.experience_years is not None else 0,
            "summary": resume_info.summary or "(no summary)",
            "skills": ", ".join(resume_info.skills or []) or "(none)",
            "bullets": _collect_bullets(resume_info),
            "missing_skills": ", ".join(missing_skills or []) or "(none)",
        })
    except (ValidationError, Exception) as e:
        logger.error(f"LinkedIn report generation failed: {e}")
        return None
