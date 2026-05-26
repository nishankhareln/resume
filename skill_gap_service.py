"""
skill_gap_service
=================

Compares the candidate's resume skills against the skills required by a
target role (drawn from job_metadata.json via market_insight_service) OR
against a specific job posting.

Two layers:

1. Deterministic: normalize both sets of skills (lowercase, strip
   punctuation, alias map) and compute matched/missing via set ops.
   This is the part the doc emphasizes for "transparent reasoning."

2. LLM-enhanced: ask Gemini to enrich `recommended_next_skills` (with
   ordering by impact) and to write the natural-language summary. If the
   LLM is unavailable, the deterministic results are returned unchanged.
"""

from __future__ import annotations

import logging
import re
from typing import List, Optional

from langchain.prompts import PromptTemplate
from langchain.output_parsers import PydanticOutputParser
from pydantic import ValidationError

from schemas import SkillGapReport
from market_insight_service import market_skills_for_role

logger = logging.getLogger(__name__)


SKILL_ALIASES = {
    "js": "javascript", "ts": "typescript", "py": "python",
    "ml": "machine learning", "dl": "deep learning",
    "k8s": "kubernetes", "gcp": "google cloud", "aws": "aws",
    "postgres": "postgresql", "psql": "postgresql",
    "node": "node.js", "nodejs": "node.js",
    "react.js": "react", "reactjs": "react", "rest api": "rest",
    "rest apis": "rest", "restful": "rest",
}


def _normalize(skill: str) -> str:
    s = re.sub(r"[^a-z0-9+#\.\s/-]", " ", skill.lower()).strip()
    s = re.sub(r"\s+", " ", s)
    return SKILL_ALIASES.get(s, s)


def _deterministic_gap(resume_skills: List[str], market_skills: List[str]) -> dict:
    resume_set = {_normalize(s): s for s in resume_skills if s}
    market_pairs = [(_normalize(s), s) for s in market_skills if s]

    matched, missing = [], []
    for norm, original in market_pairs:
        if norm in resume_set:
            matched.append(original)
        else:
            missing.append(original)

    total = len(matched) + len(missing)
    pct = round(100.0 * len(matched) / total, 1) if total else 0.0
    return {
        "matched": matched,
        "missing": missing,
        "match_percentage": pct,
    }


_skill_gap_parser = PydanticOutputParser(pydantic_object=SkillGapReport)

_LLM_PROMPT = PromptTemplate(
    template="""You are a career coach analyzing a candidate against a target role.

Given the deterministic skill comparison below, your job is to:
1. Re-order `recommended_next_skills` by IMPACT for the target role (max 5 items, drawn from the missing list).
2. Write a 2-3 sentence `summary` explaining where the candidate stands.
3. Keep `matched_skills`, `missing_skills`, `target_role`, and `match_percentage` EXACTLY as given.

Target role: {target_role}
Candidate skills: {resume_skills}
Market-required skills: {market_skills}
Matched: {matched}
Missing: {missing}
Match percentage: {pct}

{format_instructions}
""",
    input_variables=["target_role", "resume_skills", "market_skills", "matched", "missing", "pct"],
    partial_variables={"format_instructions": _skill_gap_parser.get_format_instructions()},
)


def analyze_skill_gap(
    resume_skills: List[str],
    target_role: str,
    llm=None,
    market_skills_override: Optional[List[str]] = None,
) -> SkillGapReport:
    """Build a SkillGapReport for the given role.

    Args:
        resume_skills: skills extracted from the resume.
        target_role: the role bucket (e.g., "Backend Engineer") OR any free-text title.
        llm: optional langchain-google-genai chat model. If None, deterministic-only.
        market_skills_override: bypass the offline lookup and use these instead
            (e.g., when comparing against a specific live job posting).
    """
    market = market_skills_override if market_skills_override is not None else market_skills_for_role(target_role)
    if not market:
        # No data for this role bucket — fall back to "Other" / empty; still produce a valid report.
        logger.warning(f"No market data for role '{target_role}'. Report will be empty.")
        return SkillGapReport(
            target_role=target_role,
            matched_skills=[],
            missing_skills=[],
            recommended_next_skills=[],
            match_percentage=0.0,
            summary="No market data was available for this role. Try selecting a different role.",
        )

    det = _deterministic_gap(resume_skills, market)

    base_report = SkillGapReport(
        target_role=target_role,
        matched_skills=det["matched"],
        missing_skills=det["missing"],
        recommended_next_skills=det["missing"][:5],
        match_percentage=det["match_percentage"],
        summary=(
            f"You match {det['match_percentage']}% of the typical skill set for {target_role}. "
            f"{len(det['matched'])} skills overlap, {len(det['missing'])} are gaps."
        ),
    )

    if llm is None:
        return base_report

    try:
        chain = _LLM_PROMPT | llm | _skill_gap_parser
        enriched = chain.invoke({
            "target_role": target_role,
            "resume_skills": ", ".join(resume_skills) or "(none)",
            "market_skills": ", ".join(market),
            "matched": ", ".join(det["matched"]) or "(none)",
            "missing": ", ".join(det["missing"]) or "(none)",
            "pct": det["match_percentage"],
        })
        # Defensive: enforce deterministic fields even if LLM tries to override them.
        enriched.matched_skills = base_report.matched_skills
        enriched.missing_skills = base_report.missing_skills
        enriched.match_percentage = base_report.match_percentage
        enriched.target_role = base_report.target_role
        return enriched
    except (ValidationError, Exception) as e:
        logger.warning(f"LLM enrichment failed for skill gap: {e}. Returning deterministic report.")
        return base_report
