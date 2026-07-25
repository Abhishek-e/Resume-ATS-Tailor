import time

from . import greenhouse, lever, remoteok, usajobs, wwr
from .config import load_config
from .matching import score_job, score_jobs
from .taxonomy import (
    categorize, clean_department, clean_text, hosted_ats_type, is_real_posting,
)

SOURCE_MODULES = {
    "usajobs": usajobs,
    "remoteok": remoteok,
    "wwr": wwr,
    "greenhouse": greenhouse,
    "lever": lever,
}

__all__ = [
    "fetch_all", "load_config", "score_job", "score_jobs",
    "categorize", "clean_department", "SOURCE_MODULES",
]


def fetch_all(config: dict) -> tuple[list[dict], list[str]]:
    delay = config.get("fetch", {}).get("request_delay_seconds", 1.0)
    all_jobs: list[dict] = []
    errors: list[str] = []
    for name, module in SOURCE_MODULES.items():
        cfg = config.get(name, {})
        if not cfg.get("enabled"):
            continue
        try:
            all_jobs.extend(module.fetch(cfg))
        except Exception as exc:  # noqa: BLE001 - surface one connector's failure, keep the rest running
            errors.append(f"{name}: {exc}")
        time.sleep(delay)

    # Normalising here rather than in each connector keeps the five fetchers
    # thin and guarantees no source can slip unescaped markup or a placeholder
    # row into the job list.
    cleaned: list[dict] = []
    seen_urls: set[str] = set()
    for job in all_jobs:
        for field in ("title", "company", "location", "department", "category"):
            job[field] = clean_text(job.get(field))
        job["ats_type"] = hosted_ats_type(job.get("ats_type", "other"), job.get("url", ""))
        if not is_real_posting(job) or job["url"] in seen_urls:
            continue
        seen_urls.add(job["url"])
        cleaned.append(job)
    return cleaned, errors
