"""
merojob_client
==============

Talks to the public JSON API at api.merojob.com that powers merojob.com's
search page. Returns jobs in the SAME normalized shape that job_portal.py
returns, so it's a drop-in replacement for `get_jobs_from_api()` when the
user picks Nepal as the target country.

Discovered endpoint:
  GET https://api.merojob.com/api/v1/jobs/?search={kw}&limit={n}

Notable response fields per job:
  id, title, slug, client{client_name, org_name, client_image, about},
  categories[], description, specification, skills, job_level, vacancies,
  deadline, offered_salary, job_locations[], posted_at, posted_date.

Apply link is built as: https://merojob.com/job/{slug}/

No API key required.
"""

from __future__ import annotations

import logging
import re
import requests
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

API_URL = "https://api.merojob.com/api/v1/jobs/"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://merojob.com/",
}

_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(html: str) -> str:
    if not html:
        return ""
    text = _TAG_RE.sub(" ", html)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _join_skills(skills: Any) -> str:
    if not skills:
        return ""
    if isinstance(skills, list):
        parts = []
        for s in skills:
            if isinstance(s, dict):
                parts.append(s.get("title") or s.get("name") or "")
            elif isinstance(s, str):
                parts.append(s)
        return ", ".join([p for p in parts if p])
    if isinstance(skills, str):
        return skills
    return ""


def _join_locations(locs: Any) -> str:
    if not locs:
        return "Nepal"
    if isinstance(locs, list):
        parts = []
        for l in locs:
            if isinstance(l, dict):
                parts.append(l.get("address") or l.get("title") or l.get("name") or "")
            elif isinstance(l, str):
                parts.append(l)
        return ", ".join([p for p in parts if p]) or "Nepal"
    if isinstance(locs, str):
        return locs
    return "Nepal"


def _normalize(job: Dict[str, Any]) -> Dict[str, Any]:
    """Map a merojob API record to the shape job_matcher expects."""
    client = job.get("client") or {}
    slug = job.get("slug")
    title = job.get("title") or "Untitled"
    company = client.get("client_name") or client.get("org_name") or "Unknown"
    desc_html = (job.get("description") or "") + " " + (job.get("specification") or "")
    description = _strip_html(desc_html) or _strip_html(job.get("alternate_description") or "")
    skills_str = _join_skills(job.get("skills"))
    if skills_str:
        description = f"{description}\nKey skills: {skills_str}"
    apply_link = f"https://merojob.com/job/{slug}/" if slug else "https://merojob.com/"

    # Build a text blob suitable for embedding-based similarity downstream
    text_for_embedding = f"{title}. {description[:1500]}"

    return {
        "job_id": str(job.get("id") or slug or title),
        "source": "merojob.com",
        "title": title,
        "company": company,
        "location": _join_locations(job.get("job_locations")),
        "description": description,
        "salary": job.get("offered_salary") or "",
        "posted_date": job.get("posted_date") or job.get("posted_at") or "",
        "deadline": job.get("deadline") or "",
        "job_url": apply_link,
        "apply_link": apply_link,
        "is_remote": False,
        "text_for_embedding": text_for_embedding,
        "_raw_job_level": job.get("job_level") or "",
    }


def get_jobs_from_merojob(keywords: List[str], max_results: int = 30) -> List[Dict[str, Any]]:
    """Fetch jobs from merojob's public API.

    Strategy: try each top keyword once (up to 3 keywords), de-dupe by id.
    Falls back to listing all recent jobs (no search filter) if every
    keyword returns zero.
    """
    if not keywords:
        keywords = [""]

    seen_ids: set = set()
    out: List[Dict[str, Any]] = []

    for kw in keywords[:3]:
        params = {"limit": str(max_results)}
        if kw:
            params["search"] = kw
        try:
            r = requests.get(API_URL, headers=HEADERS, params=params, timeout=20)
            if r.status_code != 200:
                logger.warning(f"merojob status {r.status_code} for keyword {kw!r}")
                continue
            body = r.json()
        except Exception as e:
            logger.error(f"merojob fetch failed for {kw!r}: {e}")
            continue

        results = body.get("results") if isinstance(body, dict) else None
        if not results:
            continue
        for raw in results:
            j = _normalize(raw)
            if j["job_id"] in seen_ids:
                continue
            seen_ids.add(j["job_id"])
            out.append(j)
            if len(out) >= max_results:
                return out

    # Fallback: pull recent jobs if every keyword returned nothing
    if not out:
        try:
            r = requests.get(API_URL, headers=HEADERS, params={"limit": str(max_results)}, timeout=20)
            if r.status_code == 200:
                for raw in (r.json() or {}).get("results") or []:
                    j = _normalize(raw)
                    if j["job_id"] in seen_ids:
                        continue
                    seen_ids.add(j["job_id"])
                    out.append(j)
        except Exception as e:
            logger.error(f"merojob recent-jobs fallback failed: {e}")

    logger.info(f"merojob returned {len(out)} jobs for keywords={keywords[:3]}")
    return out
