import requests

from .taxonomy import categorize, clean_department


def fetch(cfg: dict) -> list[dict]:
    """Greenhouse's public job-board API. These postings link to
    boards.greenhouse.io application pages, which the apply service knows how
    to pre-fill."""
    if not cfg.get("enabled"):
        return []

    jobs = []
    for board in cfg.get("boards", []):
        resp = requests.get(
            f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs",
            params={"content": "true"},
            timeout=20,
        )
        if resp.status_code != 200:
            continue
        for item in resp.json().get("jobs", []):
            title = item.get("title", "")
            description = item.get("content", "")
            jobs.append({
                "source": "greenhouse",
                "ats_type": "greenhouse",
                "title": title,
                "company": board,
                "location": (item.get("location") or {}).get("name", ""),
                "url": item.get("absolute_url", ""),
                "description": description,
                "posted_date": item.get("updated_at", ""),
                "department": clean_department(item.get("departments"), title, description),
                "category": categorize(title, description),
                "score": 0.0,
            })
    return [j for j in jobs if j["url"]]
