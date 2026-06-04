"""
Pydantic schemas for all hackathon report objects.

Centralizing these here keeps the prompts and Streamlit dashboard in sync
with the LLM output shape. Every service module imports its target schema
from here and uses PydanticOutputParser against it.
"""

from typing import List, Optional, Literal
from pydantic import BaseModel, Field


# --------------------------- Skill gap ---------------------------

class SkillGapReport(BaseModel):
    target_role: str = Field(..., description="The target role/title used for comparison.")
    matched_skills: List[str] = Field(default_factory=list, description="Skills the candidate already has that the role requires.")
    missing_skills: List[str] = Field(default_factory=list, description="Required skills the candidate does NOT have.")
    recommended_next_skills: List[str] = Field(default_factory=list, description="Top 3-5 skills to learn first, ordered by impact.")
    match_percentage: float = Field(0.0, description="0-100 score: matched / (matched + missing).")
    summary: str = Field("", description="One-paragraph plain-English summary of where the candidate stands.")


# --------------------------- LinkedIn ---------------------------

class AchievementRewrite(BaseModel):
    original: str
    rewritten: str
    why: str = Field(..., description="Short reason this rewrite is stronger (action verb, quantified, etc.).")


class LinkedInOptimizationReport(BaseModel):
    suggested_headline: str = Field(..., description="A punchy 10-15 word LinkedIn headline.")
    about_section: str = Field(..., description="A 3-5 sentence rewritten About section in first person.")
    missing_keywords: List[str] = Field(default_factory=list, description="Industry keywords the profile should add.")
    achievement_rewrites: List[AchievementRewrite] = Field(default_factory=list, description="Stronger versions of 2-4 resume bullet points.")
    profile_tips: List[str] = Field(default_factory=list, description="3-5 actionable bullet tips (banner, featured section, endorsements, etc.).")


# --------------------------- Interview ---------------------------

class InterviewQuestion(BaseModel):
    question: str
    category: Literal["technical", "behavioral", "system_design", "hr", "role_specific"]
    why_asked: str = Field(..., description="Why an interviewer for this role would ask this.")
    answer_outline: str = Field(..., description="A short bullet outline of what a strong answer covers.")


class InterviewPrepReport(BaseModel):
    target_role: str
    questions: List[InterviewQuestion] = Field(default_factory=list, description="5-8 interview questions targeting the candidate's profile and gaps.")


# --------------------------- Roadmap ---------------------------

class RoadmapPhase(BaseModel):
    phase: Literal["30_days", "60_days", "90_days"]
    focus: str = Field(..., description="The single most important focus of this phase.")
    skills_to_learn: List[str] = Field(default_factory=list)
    weekly_actions: List[str] = Field(default_factory=list, description="3-5 concrete weekly actions for this phase.")
    mini_project: str = Field(..., description="A small portfolio project to build during this phase.")
    milestone: str = Field(..., description="A measurable outcome that proves the phase is done.")


class RoadmapReport(BaseModel):
    target_role: str
    phases: List[RoadmapPhase] = Field(default_factory=list, description="Exactly three phases: 30, 60, 90 days.")
    priority_skills: List[str] = Field(default_factory=list, description="The 3-5 highest-impact skills overall.")


# --------------------------- Resume feedback / ATS ---------------------------

class ResumeFeedbackReport(BaseModel):
    ats_score: int = Field(..., ge=0, le=100, description="ATS friendliness score 0-100.")
    structure_feedback: str = Field(..., description="What works and what doesn't about the resume's structure.")
    action_verbs_feedback: str = Field(..., description="Comment on use of strong action verbs.")
    quantification_feedback: str = Field(..., description="Comment on whether achievements are quantified.")
    keyword_optimization: List[str] = Field(default_factory=list, description="Keywords to add for the target role.")
    bullet_improvements: List[AchievementRewrite] = Field(default_factory=list, description="2-4 weakest bullets rewritten stronger.")
    top_recommendations: List[str] = Field(default_factory=list, description="3-5 highest-impact improvements in priority order.")


# --------------------------- HR / Recruiter ---------------------------

class HRChatAnswer(BaseModel):
    """A grounded answer to a recruiter's question about ONE resume.

    The whole point of this shape is trustworthiness: the model must ground
    every answer in the resume text, quote the supporting lines, and flag
    `not_found` instead of guessing. HR decisions can't ride on hallucinations.
    """
    answer: str = Field(..., description="Direct, plain-English answer to the recruiter's question, based ONLY on the resume.")
    confidence: Literal["explicitly_stated", "implied", "not_found"] = Field(
        "not_found",
        description="explicitly_stated = the resume says it outright; implied = reasonably inferable from the resume; not_found = the resume does not mention it.",
    )
    evidence: List[str] = Field(
        default_factory=list,
        description="Short verbatim quotes from the resume that support the answer. Empty if not_found.",
    )
    follow_up_suggestions: List[str] = Field(
        default_factory=list,
        description="2-3 useful next questions the recruiter might ask about this candidate.",
    )


class CandidateScreen(BaseModel):
    """An AI fit assessment of ONE candidate against a role/criteria, grounded in their resume."""
    candidate: str = Field(..., description="Candidate name (or file name if name unknown).")
    verdict: Literal["strong_match", "possible_match", "weak_match", "not_a_match"] = Field(
        "weak_match", description="Overall hiring-screen verdict against the given criteria."
    )
    fit_score: int = Field(0, ge=0, le=100, description="0-100 fit score against the criteria.")
    matched_requirements: List[str] = Field(default_factory=list, description="Criteria the candidate clearly meets.")
    missing_requirements: List[str] = Field(default_factory=list, description="Criteria not evidenced in the resume.")
    evidence: List[str] = Field(default_factory=list, description="Short verbatim quotes backing the matched requirements.")
    rationale: str = Field("", description="2-3 sentence explanation of the verdict, grounded in the resume only.")


# --------------------------- Overall score ---------------------------

class OverallScore(BaseModel):
    """The final weighted readiness score the doc specifies:
    35% skill overlap + 25% semantic + 20% experience + 10% keyword quality + 10% LinkedIn readiness."""
    skill_overlap: float = Field(..., ge=0, le=100)
    semantic_similarity: float = Field(..., ge=0, le=100)
    experience_fit: float = Field(..., ge=0, le=100)
    keyword_quality: float = Field(..., ge=0, le=100)
    linkedin_readiness: float = Field(..., ge=0, le=100)
    total: float = Field(..., ge=0, le=100, description="Weighted total.")

    @classmethod
    def weights(cls) -> dict:
        return {
            "skill_overlap": 0.35,
            "semantic_similarity": 0.25,
            "experience_fit": 0.20,
            "keyword_quality": 0.10,
            "linkedin_readiness": 0.10,
        }
