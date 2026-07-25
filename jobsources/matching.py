"""
Ranks postings against the signed-in user's profile.

Project/2 returned a raw keyword-overlap count. The Find Jobs UI shows a match
percentage, so this also normalises that count into 0-100 using the number of
skills the user actually listed as the denominator.
"""
import re


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9+#.]+", text.lower()))


def score_job(job: dict, profile: dict) -> tuple[float, int, list[str]]:
    """Returns (raw_score, match_percentage, matched_skills)."""
    blob = f"{job.get('title', '')} {job.get('description', '')}"
    text_tokens = _tokenize(blob)
    blob_lower = blob.lower()

    skills = [s.strip().lower() for s in profile.get("skills", []) if s and s.strip()]
    # Multi-word skills ("machine learning") won't survive tokenisation, so
    # check those against the raw text instead.
    matched = [s for s in skills if s in text_tokens or (" " in s and s in blob_lower)]

    title_lower = (job.get("title") or "").lower()
    title_bonus = 2.0 if any(
        t.lower() in title_lower for t in profile.get("desired_titles", []) if t
    ) else 0.0

    location_lower = (job.get("location") or "").lower()
    location_bonus = 1.0 if any(
        loc.lower() in location_lower for loc in profile.get("desired_locations", []) if loc
    ) else 0.0

    raw = round(len(matched) + title_bonus + location_bonus, 2)

    # Percentage: skill coverage carries most of the weight, with the title and
    # location bonuses topping it up. Capped at 100 so a long skill list that
    # matches everything can't overflow.
    if skills:
        coverage = len(matched) / len(skills)
    else:
        coverage = 0.0
    pct = int(min(100, round(coverage * 80 + title_bonus * 7.5 + location_bonus * 5)))

    return raw, pct, matched


def score_jobs(jobs: list[dict], profile: dict) -> list[dict]:
    for job in jobs:
        raw, pct, matched = score_job(job, profile)
        job["score"] = raw
        job["match_percentage"] = pct
        job["matched_skills"] = matched
    return jobs
