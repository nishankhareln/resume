"""
market_insight_service
======================

Offline market intelligence powered by `job_metadata.json`. Used as a
deterministic fallback when the JSearch API is rate-limited and as the
authoritative source for "what does the market actually ask for in role X?".

The dataset has 30 real job descriptions with: title, description, company,
location, is_remote. We extract a vocabulary of skills/technologies per role
group (by clustering job titles into normalized roles).

Functions:
    load_jobs() -> list[dict]
    list_roles() -> list[str]
    top_skills_for_role(role: str, k: int = 15) -> list[(skill, count)]
    market_skills_for_role(role: str) -> list[str]  (just the skill names)
"""

from __future__ import annotations

import json
import os
import re
import logging
from collections import Counter
from functools import lru_cache
from typing import List, Tuple, Optional

logger = logging.getLogger(__name__)

JOB_METADATA_PATH = os.path.join(os.path.dirname(__file__), "job_metadata.json")

# Curated vocabulary of common tech / business skills to look for inside
# job descriptions. We use regex word-boundary matching so "go" doesn't
# match "going". Multi-word skills are matched literally (case-insensitive).
SKILL_VOCAB: List[str] = [
    # Languages
    "Python", "Java", "JavaScript", "TypeScript", "C++", "C#", "Go", "Rust",
    "Kotlin", "Swift", "Ruby", "PHP", "Scala", "R", "MATLAB", "SQL", "NoSQL",
    "Bash", "Shell", "PowerShell",
    # Web / frontend
    "React", "Angular", "Vue", "Next.js", "Node.js", "Express", "HTML", "CSS",
    "Tailwind", "Bootstrap", "Redux", "GraphQL", "REST", "REST API",
    # Backend / frameworks
    "Django", "Flask", "FastAPI", "Spring", "Spring Boot", ".NET", "Laravel",
    "Rails", "Ruby on Rails", "ASP.NET",
    # Data / ML
    "Pandas", "NumPy", "Scikit-learn", "TensorFlow", "PyTorch", "Keras",
    "Machine Learning", "Deep Learning", "NLP", "Computer Vision",
    "Data Analysis", "Data Visualization", "Statistics", "A/B Testing",
    "ETL", "Data Modeling", "Data Warehouse", "Data Pipeline",
    "Tableau", "Power BI", "Looker", "Excel", "VBA",
    # Cloud / DevOps
    "AWS", "Azure", "GCP", "Google Cloud", "Docker", "Kubernetes", "Terraform",
    "Ansible", "Jenkins", "CI/CD", "GitHub Actions", "GitLab", "Git",
    "Linux", "Unix",
    # Databases
    "PostgreSQL", "MySQL", "MongoDB", "Redis", "Elasticsearch", "DynamoDB",
    "Snowflake", "BigQuery", "Redshift", "Oracle",
    # Architecture / Practices
    "Microservices", "Agile", "Scrum", "Kanban", "TDD", "Unit Testing",
    "OOP", "Design Patterns", "System Design", "Distributed Systems",
    # Business / soft
    "Project Management", "Stakeholder Management", "Communication",
    "Leadership", "Problem Solving", "Critical Thinking", "Documentation",
    "SOP", "Reporting", "Dashboard", "KPI",
    # Security
    "Security", "Authentication", "OAuth", "JWT", "Encryption",
]

# Map raw titles into a smaller set of role buckets.
ROLE_PATTERNS: List[Tuple[str, re.Pattern]] = [
    ("Data Analyst", re.compile(r"data\s+analyst", re.I)),
    ("Data Scientist", re.compile(r"data\s+scientist|machine\s+learning|ml\s+engineer", re.I)),
    ("Data Engineer", re.compile(r"data\s+engineer|etl|big\s+data", re.I)),
    ("Backend Engineer", re.compile(r"backend|back-?end\s+(developer|engineer)", re.I)),
    ("Frontend Engineer", re.compile(r"frontend|front-?end\s+(developer|engineer)", re.I)),
    ("Full Stack Engineer", re.compile(r"full[\s-]?stack", re.I)),
    ("Software Engineer", re.compile(r"software\s+(developer|engineer|programmer)", re.I)),
    ("DevOps / Cloud Engineer", re.compile(r"devops|sre|site\s+reliability|cloud\s+engineer|platform\s+engineer", re.I)),
    ("Mobile Engineer", re.compile(r"ios|android|mobile\s+(developer|engineer)", re.I)),
    ("Product Manager", re.compile(r"product\s+manager", re.I)),
    ("Project Manager", re.compile(r"project\s+manager|program\s+manager", re.I)),
    ("Business Analyst", re.compile(r"business\s+analyst", re.I)),
    ("QA / Test Engineer", re.compile(r"qa\b|quality\s+assurance|test\s+engineer|sdet", re.I)),
    ("UX / UI Designer", re.compile(r"\bux\b|\bui\b|designer", re.I)),
]


def _normalize_role(title: str) -> str:
    for label, pat in ROLE_PATTERNS:
        if pat.search(title or ""):
            return label
    return "Other"


@lru_cache(maxsize=1)
def load_jobs() -> List[dict]:
    """Load and cache the job_metadata.json file."""
    if not os.path.exists(JOB_METADATA_PATH):
        logger.warning(f"job_metadata.json not found at {JOB_METADATA_PATH}")
        return []
    try:
        with open(JOB_METADATA_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            logger.warning("job_metadata.json is not a list — ignoring.")
            return []
        for j in data:
            j["_role"] = _normalize_role(j.get("title", ""))
        logger.info(f"Loaded {len(data)} jobs from job_metadata.json")
        return data
    except Exception as e:
        logger.error(f"Failed to load job_metadata.json: {e}")
        return []


def list_roles() -> List[str]:
    """Return distinct role buckets present in the dataset, sorted by frequency."""
    jobs = load_jobs()
    if not jobs:
        return []
    c = Counter(j.get("_role", "Other") for j in jobs)
    return [r for r, _ in c.most_common()]


def _skills_in_text(text: str) -> List[str]:
    """Return distinct skills from SKILL_VOCAB that appear in text (case-insensitive, word-boundary)."""
    if not text:
        return []
    found = []
    lower = text.lower()
    for skill in SKILL_VOCAB:
        s = skill.lower()
        # word-boundary check that also tolerates trailing punctuation
        pattern = r"(?<![a-z0-9])" + re.escape(s) + r"(?![a-z0-9])"
        if re.search(pattern, lower):
            found.append(skill)
    return found


def top_skills_for_role(role: str, k: int = 15) -> List[Tuple[str, int]]:
    """Count skill occurrences across all jobs in this role bucket."""
    jobs = load_jobs()
    if not jobs:
        return []
    counter: Counter = Counter()
    for j in jobs:
        if j.get("_role") != role:
            continue
        text = " ".join([
            j.get("title", ""),
            j.get("description", ""),
            j.get("text_for_embedding", ""),
        ])
        for skill in _skills_in_text(text):
            counter[skill] += 1
    return counter.most_common(k)


def market_skills_for_role(role: str, k: int = 15) -> List[str]:
    """Just the skill names for the role (used by skill_gap_service)."""
    return [s for s, _ in top_skills_for_role(role, k)]


def offline_jobs_for_keywords(keywords: List[str], limit: int = 20) -> List[dict]:
    """A cheap text search over the offline dataset, used as JSearch fallback.
    Returns jobs whose title or description contains any keyword, ranked
    by number of keyword hits (case-insensitive substring)."""
    if not keywords:
        return []
    jobs = load_jobs()
    if not jobs:
        return []
    kws = [k.lower() for k in keywords if k]
    scored = []
    for j in jobs:
        blob = (j.get("title", "") + " " + j.get("description", "")).lower()
        hits = sum(blob.count(k) for k in kws)
        if hits > 0:
            scored.append((hits, j))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [j for _, j in scored[:limit]]
