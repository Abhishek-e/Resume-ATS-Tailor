import requests

from .taxonomy import categorize, clean_department


def fetch(cfg: dict) -> list[dict]:
    """RemoteOK public JSON feed - no key required."""
    if not cfg.get("enabled"):
        return []

    resp = requests.get(
        "https://remoteok.com/api",
        headers={"User-Agent": "resumify-job-fetcher (personal use)"},
        timeout=20,
    )
    resp.raise_for_status()

    jobs = []
    for item in resp.json():
        # The first element of the feed is a legal notice, not a posting.
        if not isinstance(item, dict) or "id" not in item or "position" not in item:
            continue
        title = item.get("position", "")
        description = item.get("description", "")
        # RemoteOK has no department field. Its tags look like a stand-in but
        # are really tech/market labels ("saas", "wordpress", "dev"), which
        # make meaningless dashboard slices - infer from the title instead.
        jobs.append({
            "source": "remoteok",
            "ats_type": "other",
            "title": title,
            "company": item.get("company", ""),
            "location": item.get("location") or "Remote",
            "url": item.get("url", ""),
            "description": description,
            "posted_date": item.get("date", ""),
            "department": clean_department("", title, description),
            "category": categorize(title, description),
            "score": 0.0,
        })
    return [j for j in jobs if j["url"]]
