"""
scoring_service
===============

The weighted readiness score the hackathon doc specifies:
  35% skill_overlap
  25% semantic_similarity
  20% experience_fit
  10% keyword_quality
  10% linkedin_readiness

Each component is a 0-100 number computed deterministically here.
"""

from __future__ import annotations

from typing import Optional
from schemas import OverallScore, SkillGapReport, ResumeFeedbackReport


def _experience_fit(resume_years: int, target_role: str) -> float:
    """Heuristic: target_role implies an expected band; 100 if inside, else linear penalty.

    We use a coarse mapping here (matches what `extract_experience_from_job_description`
    infers in app.py). If we don't recognize the role, we return 70 (neutral).
    """
    role = (target_role or "").lower()
    if any(k in role for k in ("intern", "graduate")):
        band = (0, 1)
    elif any(k in role for k in ("junior", "associate", "entry")):
        band = (0, 2)
    elif "mid" in role:
        band = (2, 5)
    elif "senior" in role:
        band = (5, 10)
    elif any(k in role for k in ("lead", "principal", "staff", "director")):
        band = (8, 20)
    else:
        return 70.0

    lo, hi = band
    if lo <= resume_years <= hi:
        return 100.0
    if resume_years < lo:
        # too junior
        gap = lo - resume_years
        return max(0.0, 100.0 - gap * 20)
    # over-qualified — small penalty
    gap = resume_years - hi
    return max(60.0, 100.0 - gap * 5)


def _keyword_quality(resume_info) -> float:
    """Crude proxy: how many optimized_search_keywords + skills the resume produced."""
    kws = len(resume_info.optimized_search_keywords or []) if resume_info else 0
    skills = len(resume_info.skills or []) if resume_info else 0
    raw = kws * 8 + skills * 3
    return min(100.0, float(raw))


def _linkedin_readiness(resume_info) -> float:
    """Heuristic: has LinkedIn URL (50) + has summary (25) + has good skill count (25)."""
    if not resume_info:
        return 0.0
    score = 0.0
    li = (resume_info.linkedin_url or "").strip()
    if li and li.lower() != "unknown" and "linkedin.com" in li.lower():
        score += 50
    summary = (resume_info.summary or "").strip()
    if summary and summary.lower() not in ("not provided", "unknown", ""):
        score += 25
    if len(resume_info.skills or []) >= 5:
        score += 25
    elif len(resume_info.skills or []) >= 1:
        score += 12
    return score


def compute_overall_score(
    resume_info,
    target_role: str,
    skill_gap: Optional[SkillGapReport] = None,
    semantic_similarity_0_to_1: float = 0.0,
    resume_feedback: Optional[ResumeFeedbackReport] = None,
) -> OverallScore:
    skill_overlap = skill_gap.match_percentage if skill_gap else 0.0
    semantic = max(0.0, min(1.0, float(semantic_similarity_0_to_1))) * 100.0
    years = resume_info.experience_years if (resume_info and resume_info.experience_years is not None) else 0
    exp_fit = _experience_fit(years, target_role)
    # Keyword quality: prefer the LLM's ATS score if available, otherwise heuristic.
    if resume_feedback is not None:
        keyword_q = float(resume_feedback.ats_score)
    else:
        keyword_q = _keyword_quality(resume_info)
    linkedin_q = _linkedin_readiness(resume_info)

    w = OverallScore.weights()
    total = (
        skill_overlap * w["skill_overlap"]
        + semantic * w["semantic_similarity"]
        + exp_fit * w["experience_fit"]
        + keyword_q * w["keyword_quality"]
        + linkedin_q * w["linkedin_readiness"]
    )
    return OverallScore(
        skill_overlap=round(skill_overlap, 1),
        semantic_similarity=round(semantic, 1),
        experience_fit=round(exp_fit, 1),
        keyword_quality=round(keyword_q, 1),
        linkedin_readiness=round(linkedin_q, 1),
        total=round(total, 1),
    )
