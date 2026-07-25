import requests

from .taxonomy import categorize, clean_department


def fetch(cfg: dict) -> list[dict]:
    """USAJobs.gov official API - federal government listings."""
    if not cfg.get("enabled"):
        return []

    resp = requests.get(
        "https://data.usajobs.gov/api/search",
        headers={
            "Host": "data.usajobs.gov",
            "User-Agent": cfg["user_agent"],
            "Authorization-Key": cfg["api_key"],
        },
        params={"Keyword": cfg.get("keyword", ""), "ResultsPerPage": 50},
        timeout=20,
    )
    resp.raise_for_status()

    jobs = []
    for item in resp.json().get("SearchResult", {}).get("SearchResultItems", []):
        d = item.get("MatchedObjectDescriptor", {})
        locations = d.get("PositionLocation", [])
        title = d.get("PositionTitle", "")
        description = d.get("UserArea", {}).get("Details", {}).get("JobSummary", "")
        jobs.append({
            "source": "usajobs",
            "ats_type": "other",
            "title": title,
            "company": d.get("OrganizationName", ""),
            "location": locations[0].get("LocationName", "") if locations else "",
            "url": d.get("PositionURI", ""),
            "description": description,
            "posted_date": d.get("PublicationStartDate", ""),
            # USAJobs publishes an occupational series, e.g. "IT Specialist".
            "department": clean_department(d.get("JobCategory"), title, description),
            "category": categorize(title, description),
            "score": 0.0,
        })
    return [j for j in jobs if j["url"]]
