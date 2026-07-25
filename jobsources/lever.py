import requests

from .taxonomy import categorize, clean_department


def fetch(cfg: dict) -> list[dict]:
    """Lever's public postings API. These postings link to jobs.lever.co
    application pages, which the apply service knows how to pre-fill."""
    if not cfg.get("enabled"):
        return []

    jobs = []
    for company in cfg.get("companies", []):
        resp = requests.get(
            f"https://api.lever.co/v0/postings/{company}",
            params={"mode": "json"},
            timeout=20,
        )
        if resp.status_code != 200:
            continue
        for item in resp.json():
            categories = item.get("categories") or {}
            title = item.get("text", "")
            description = item.get("descriptionPlain", "")
            jobs.append({
                "source": "lever",
                "ats_type": "lever",
                "title": title,
                "company": company,
                "location": categories.get("location", ""),
                "url": item.get("hostedUrl", ""),
                "description": description,
                "posted_date": str(item.get("createdAt", "")),
                # Lever exposes the employer's own team name directly.
                "department": clean_department(
                    categories.get("department") or categories.get("team"), title, description,
                ),
                "category": categorize(title, description),
                "score": 0.0,
            })
    return [j for j in jobs if j["url"]]
