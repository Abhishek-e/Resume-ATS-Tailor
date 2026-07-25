"""
Storage for the Find Jobs feature.

Project/2 kept both listings and application state in a local SQLite file.
Resumify is multi-user and deploys to Render, so the two halves are split:

  Listings    - a process-level cache. They are public data that goes stale in
                days, and writing ~1k docs to Firestore on every refresh would
                burn the free-tier write quota for no durability benefit.
  Applications - Firestore, per user. Each row carries its own snapshot of the
                job (title, company, department, category), so the dashboard
                keeps working after the listing cache is gone.
"""
import hashlib
import threading
from collections import Counter
from datetime import datetime, timedelta, timezone

# How long a fetched listing set is served before the UI offers a refresh.
CACHE_TTL = timedelta(hours=6)

_lock = threading.Lock()
_cache: dict = {"jobs": [], "fetched_at": None, "errors": []}

# Set while a background refresh is in flight, so the public landing page can
# render instantly instead of blocking ~8s on the first visitor's fetch.
_warming = threading.Event()


def job_id(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]


# --------------------------------------------------------------------------
# Listing cache
# --------------------------------------------------------------------------

def store_jobs(jobs: list[dict], errors: list[str] | None = None) -> None:
    for job in jobs:
        job["id"] = job_id(job["url"])
    with _lock:
        _cache["jobs"] = jobs
        _cache["fetched_at"] = datetime.now(timezone.utc)
        _cache["errors"] = errors or []


def cache_state() -> dict:
    with _lock:
        fetched_at = _cache["fetched_at"]
        return {
            "count": len(_cache["jobs"]),
            "fetched_at": fetched_at,
            "errors": list(_cache["errors"]),
            "is_stale": fetched_at is None or datetime.now(timezone.utc) - fetched_at > CACHE_TTL,
        }


def all_jobs() -> list[dict]:
    with _lock:
        return list(_cache["jobs"])


def is_warming() -> bool:
    return _warming.is_set()


def warm_async(fetch_fn) -> bool:
    """Fills the cache on a background thread. Returns False if a refresh is
    already running, so concurrent visitors can't stack up fetches against the
    job boards."""
    if _warming.is_set():
        return False
    _warming.set()

    def run():
        try:
            jobs, errors = fetch_fn()
            # Only replace on success - a failed refresh must not blank out a
            # cache that is currently serving perfectly good listings.
            if jobs:
                store_jobs(jobs, errors)
        except Exception:  # noqa: BLE001 - background thread, nothing to raise to
            pass
        finally:
            _warming.clear()

    threading.Thread(target=run, daemon=True, name="jobs-warm").start()
    return True


def preview_jobs(jobs: list[dict], applied_ids: set | None = None,
                 personalised: bool = False, limit: int = 6) -> list[dict]:
    """Picks the handful shown on the public landing page.

    Signed in with skills, the ranking is meaningful so take the top matches.
    Anonymously it isn't, so lead with postings that support assisted apply and
    spread them across categories rather than showing six near-identical rows."""
    applied_ids = applied_ids or set()
    pool = [j for j in jobs if j.get("id") not in applied_ids]
    if not pool:
        return []

    if personalised:
        return sorted(pool, key=lambda j: -(j.get("match_percentage") or 0))[:limit]

    assisted = [j for j in pool if j.get("ats_type") in {"greenhouse", "lever"}]
    picked, seen_categories = [], set()
    for job in assisted + pool:
        category = job.get("category")
        if category in seen_categories:
            continue
        seen_categories.add(category)
        picked.append(job)
        if len(picked) == limit:
            break
    return picked


def get_job(jid: str) -> dict | None:
    with _lock:
        return next((j for j in _cache["jobs"] if j.get("id") == jid), None)


def filter_jobs(jobs: list[dict], search: str = "", source: str = "",
                category: str = "", applied_ids: set | None = None,
                hide_applied: bool = False, limit: int = 60) -> list[dict]:
    applied_ids = applied_ids or set()
    needle = (search or "").strip().lower()
    out = []
    for job in jobs:
        if needle and needle not in (
            f"{job.get('title', '')} {job.get('company', '')} {job.get('location', '')}".lower()
        ):
            continue
        if source and job.get("source") != source:
            continue
        if category and job.get("category") != category:
            continue
        if hide_applied and job.get("id") in applied_ids:
            continue
        job["applied"] = job.get("id") in applied_ids
        out.append(job)
    out.sort(key=lambda j: (-(j.get("match_percentage") or 0), j.get("title") or ""))
    return out[:limit]


def distinct(jobs: list[dict], field: str) -> list[str]:
    return sorted({j.get(field) for j in jobs if j.get(field)})


# --------------------------------------------------------------------------
# Applications (Firestore)
# --------------------------------------------------------------------------

APPLICATION_FIELDS = (
    "title", "company", "location", "source", "ats_type", "url",
    "department", "category",
)


def record_application(db, user_id: str, job: dict, status: str,
                       match_percentage: int = 0, note: str = "") -> dict:
    """Upserts one application. Keyed by user+job so re-applying to the same
    posting updates the row instead of double-counting it in the analytics."""
    if db is None:
        raise RuntimeError("Database is not configured on the server.")

    doc_id = f"{hashlib.sha256(user_id.encode()).hexdigest()[:12]}_{job['id']}"
    ref = db.collection("applications").document(doc_id)
    now = datetime.now(timezone.utc)

    existing = ref.get()
    payload = {
        "user_id": user_id,
        "job_id": job["id"],
        "status": status,
        "match_percentage": int(match_percentage or 0),
        "note": note,
        "updated_at": now,
        **{field: job.get(field, "") for field in APPLICATION_FIELDS},
    }
    if existing.exists:
        ref.update(payload)
    else:
        ref.set({**payload, "created_at": now})

    saved = payload.copy()
    saved["id"] = doc_id
    saved["created_at"] = (existing.to_dict().get("created_at") if existing.exists else now)
    return saved


def list_applications(db, user_id: str) -> list[dict]:
    if db is None:
        return []
    from google.cloud.firestore_v1.base_query import FieldFilter

    docs = db.collection("applications").where(
        filter=FieldFilter("user_id", "==", user_id)
    ).stream()
    rows = []
    for doc in docs:
        row = doc.to_dict()
        row["id"] = doc.id
        rows.append(row)
    # Sorted in Python rather than with order_by so Firestore doesn't need a
    # composite index for (user_id, created_at).
    rows.sort(key=lambda r: r.get("created_at") or datetime.min.replace(tzinfo=timezone.utc),
              reverse=True)
    return rows


def applied_job_ids(db, user_id: str) -> set:
    return {row.get("job_id") for row in list_applications(db, user_id)}


def delete_application(db, user_id: str, app_id: str) -> bool:
    if db is None:
        return False
    ref = db.collection("applications").document(app_id)
    doc = ref.get()
    if not doc.exists or doc.to_dict().get("user_id") != user_id:
        return False
    ref.delete()
    return True


# --------------------------------------------------------------------------
# Dashboard analytics
# --------------------------------------------------------------------------

def build_analytics(applications: list[dict]) -> dict:
    """Aggregates the user's applications for the profile dashboard."""
    if not applications:
        return {
            "total": 0, "submitted": 0, "manual": 0, "companies": 0,
            "avg_match": 0, "by_department": [], "by_category": [],
            "by_source": [], "recent": [],
        }

    departments = Counter(a.get("department") or "Unspecified" for a in applications)
    categories = Counter(a.get("category") or "Other" for a in applications)
    sources = Counter(a.get("source") or "other" for a in applications)
    matches = [int(a.get("match_percentage") or 0) for a in applications]

    def ranked(counter: Counter) -> list[dict]:
        total = sum(counter.values()) or 1
        return [
            {"name": name, "count": count, "percent": round(count * 100 / total)}
            for name, count in counter.most_common()
        ]

    return {
        "total": len(applications),
        "submitted": sum(1 for a in applications if a.get("status") == "submitted"),
        "manual": sum(1 for a in applications if a.get("status") != "submitted"),
        "companies": len({(a.get("company") or "").lower() for a in applications if a.get("company")}),
        "avg_match": round(sum(matches) / len(matches)) if matches else 0,
        "by_department": ranked(departments),
        "by_category": ranked(categories),
        "by_source": ranked(sources),
        "recent": applications[:8],
    }
