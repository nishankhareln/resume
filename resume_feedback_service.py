"""
resume_feedback_service
=======================

ATS-friendliness and resume-quality feedback. Combines a deterministic
heuristic ATS score with an LLM-written feedback report.

Deterministic ATS heuristic checks:
  - has contact info (email, phone)
  - has clearly defined sections (experience, education, skills)
  - uses action verbs in bullets
  - quantifies achievements (numbers / %)
  - reasonable length (300-1200 words)
  - no excessive special chars / tables
The heuristic returns 0-100. The LLM is then asked to produce the rest
of the feedback report.
"""

from __future__ import annotations

import logging
import re
from typing import List, Optional

from langchain.prompts import PromptTemplate
from langchain.output_parsers import PydanticOutputParser
from pydantic import ValidationError

from schemas import ResumeFeedbackReport

logger = logging.getLogger(__name__)


ACTION_VERBS = {
    "led", "built", "designed", "shipped", "launched", "created", "developed",
    "owned", "drove", "delivered", "implemented", "improved", "reduced",
    "increased", "saved", "optimized", "automated", "architected", "scaled",
    "migrated", "deployed", "managed", "mentored", "coordinated", "negotiated",
    "analyzed", "researched", "presented", "spearheaded", "streamlined",
}


def _ats_heuristic(resume_text: str, resume_info) -> int:
    """0-100 score for ATS friendliness."""
    if not resume_text:
        return 0

    score = 0
    text = resume_text.lower()
    word_count = len(resume_text.split())

    # Contact info (15)
    if resume_info and (resume_info.email and resume_info.email != "Unknown"):
        score += 8
    if resume_info and (resume_info.phone_number and resume_info.phone_number != "Unknown"):
        score += 7

    # Section headers (15)
    for kw in ("experience", "education", "skills"):
        if kw in text:
            score += 5

    # Action verbs (20) — at least 5 distinct
    verbs_found = sum(1 for v in ACTION_VERBS if re.search(rf"\b{v}\b", text))
    score += min(20, verbs_found * 2)

    # Quantification (20) — count of % or digit-led numbers
    digits = len(re.findall(r"\b\d+(?:\.\d+)?%?\b", resume_text))
    score += min(20, digits)

    # Length sweet spot (10): 300-1200 words
    if 300 <= word_count <= 1200:
        score += 10
    elif 200 <= word_count < 300 or 1200 < word_count <= 1500:
        score += 5

    # No huge special-char noise (10): low ratio of non-alphanum
    non_alnum_ratio = sum(1 for c in resume_text if not c.isalnum() and not c.isspace()) / max(1, len(resume_text))
    if non_alnum_ratio < 0.1:
        score += 10
    elif non_alnum_ratio < 0.15:
        score += 5

    # Skills extracted (10)
    if resume_info and len(resume_info.skills or []) >= 5:
        score += 10
    elif resume_info and len(resume_info.skills or []) >= 1:
        score += 5

    return min(100, score)


_parser = PydanticOutputParser(pydantic_object=ResumeFeedbackReport)

_PROMPT = PromptTemplate(
    template="""You are an expert resume reviewer for the role of "{target_role}".

You have already been given an ATS heuristic score of {ats_score}/100.

Your job is to produce the rest of the feedback. KEEP `ats_score` exactly at {ats_score}.

For `structure_feedback`: comment on section ordering, whitespace, and readability.
For `action_verbs_feedback`: comment on verb strength and variety; cite 1-2 examples from the resume.
For `quantification_feedback`: comment on whether bullets have numbers/percentages/scale.
For `keyword_optimization`: 5-10 keywords to add for the target role.
For `bullet_improvements`: pick 2-4 of the WEAKEST bullets and rewrite each (original + rewritten + why stronger).
For `top_recommendations`: 3-5 highest-impact improvements in priority order.

Candidate name: {name}
Target role: {target_role}
Skills: {skills}
Resume text (truncated to 3000 chars):
\"\"\"
{resume_text}
\"\"\"

{format_instructions}
""",
    input_variables=["target_role", "ats_score", "name", "skills", "resume_text"],
    partial_variables={"format_instructions": _parser.get_format_instructions()},
)


def generate_resume_feedback(
    resume_text: str,
    resume_info,
    target_role: str,
    llm=None,
) -> Optional[ResumeFeedbackReport]:
    ats = _ats_heuristic(resume_text or "", resume_info)
    if llm is None:
        # Return a minimal report with just the deterministic ATS score.
        return ResumeFeedbackReport(
            ats_score=ats,
            structure_feedback="(LLM unavailable — ATS score only.)",
            action_verbs_feedback="(LLM unavailable.)",
            quantification_feedback="(LLM unavailable.)",
            keyword_optimization=[],
            bullet_improvements=[],
            top_recommendations=[],
        )

    try:
        chain = _PROMPT | llm | _parser
        report = chain.invoke({
            "target_role": target_role,
            "ats_score": ats,
            "name": (resume_info.name if resume_info else "Candidate"),
            "skills": ", ".join((resume_info.skills if resume_info else []) or []) or "(none)",
            "resume_text": (resume_text or "")[:3000],
        })
        report.ats_score = ats  # defensive
        return report
    except (ValidationError, Exception) as e:
        logger.error(f"Resume feedback generation failed: {e}")
        return ResumeFeedbackReport(
            ats_score=ats,
            structure_feedback="(LLM call failed.)",
            action_verbs_feedback="",
            quantification_feedback="",
            keyword_optimization=[],
            bullet_improvements=[],
            top_recommendations=[],
        )
