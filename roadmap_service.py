"""
roadmap_service
===============

Produce a 30/60/90-day learning roadmap targeting the candidate's missing
skills. Each phase includes a focus, skills, weekly actions, a portfolio
project, and a measurable milestone.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from langchain.prompts import PromptTemplate
from langchain.output_parsers import PydanticOutputParser
from pydantic import ValidationError

from schemas import RoadmapReport

logger = logging.getLogger(__name__)


_parser = PydanticOutputParser(pydantic_object=RoadmapReport)

_PROMPT = PromptTemplate(
    template="""You are a learning coach.

Build a personalized 30/60/90-day roadmap that prepares this candidate for a "{target_role}" role.

Rules:
- Output EXACTLY three phases with `phase` values "30_days", "60_days", "90_days" in that order.
- Pick 3-5 PRIORITY skills overall from the missing list, ordered by impact.
- 30_days = foundations of the easiest 1-2 missing skills; mini-project should be small (1-2 weeks of effort).
- 60_days = deeper skills + integrating with what they already know; mini-project is medium-sized.
- 90_days = capstone-level project that demonstrates ROLE READINESS for "{target_role}".
- Each phase: 3-5 concrete weekly_actions written as "Week N: do X" lines (mix learning, building, networking).
- Each milestone must be MEASURABLE (e.g., "Deploy a working API with 80% test coverage").

Candidate context:
- Current title: {current_title}
- Years of experience: {years}
- Skills they already have: {skills}
- Missing skills for target role: {missing_skills}

{format_instructions}
""",
    input_variables=["target_role", "current_title", "years", "skills", "missing_skills"],
    partial_variables={"format_instructions": _parser.get_format_instructions()},
)


def generate_roadmap(
    resume_info,
    target_role: str,
    missing_skills: Optional[List[str]] = None,
    llm=None,
) -> Optional[RoadmapReport]:
    if llm is None:
        logger.error("LLM required for roadmap_service.")
        return None
    if not missing_skills:
        logger.info("No missing skills provided — roadmap will be light.")

    try:
        chain = _PROMPT | llm | _parser
        report = chain.invoke({
            "target_role": target_role,
            "current_title": resume_info.job_title or "(unknown)",
            "years": resume_info.experience_years if resume_info.experience_years is not None else 0,
            "skills": ", ".join(resume_info.skills or []) or "(none)",
            "missing_skills": ", ".join(missing_skills or []) or "(none)",
        })
        report.target_role = target_role
        return report
    except (ValidationError, Exception) as e:
        logger.error(f"Roadmap generation failed: {e}")
        return None
