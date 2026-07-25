import feedparser

from .taxonomy import categorize, clean_department


def fetch(cfg: dict) -> list[dict]:
    """We Work Remotely RSS feed - no key required."""
    if not cfg.get("enabled"):
        return []

    category = cfg.get("category", "remote-programming-jobs")
    feed = feedparser.parse(f"https://weworkremotely.com/categories/{category}.rss")

    jobs = []
    for entry in feed.entries:
        raw_title = entry.get("title", "")
        # WWR titles are usually "Company: Job Title".
        company, _, job_title = raw_title.partition(":")
        title = job_title.strip() or raw_title
        description = entry.get("summary", "")
        jobs.append({
            "source": "weworkremotely",
            "ats_type": "other",
            "title": title,
            "company": company.strip(),
            "location": "Remote",
            "url": entry.get("link", ""),
            "description": description,
            "posted_date": entry.get("published", ""),
            "department": clean_department("", title, description),
            "category": categorize(title, description),
            "score": 0.0,
        })
    return [j for j in jobs if j["url"]]
