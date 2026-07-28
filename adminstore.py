"""
Firestore access for the admin panel.

Everything the admin panel reads on a normal page load - the site name, the
footer signature, the active announcements - is cached in process memory and
invalidated on write. The alternative is a Firestore read on every request from
every visitor, which burns the free tier's quota for data that changes maybe
twice a year. This is the same reasoning as the job listing cache in
jobstore.py, and it carries the same constraint: one gunicorn worker, or the
caches diverge.

Collections
  site/config      one doc - app_name, footer_signature
  site/admin       one doc - email, password hash
  job_posts        admin-authored openings shown on the public site
  announcements    admin messages pushed to signed-in users
  users            existing user collection, read here for the roster
"""
import threading
import time
from datetime import datetime, timezone

from werkzeug.security import generate_password_hash, check_password_hash

DEFAULT_APP_NAME = "Resumify"
DEFAULT_FOOTER = "build your career with AI."

# Seed credentials. Deliberately weak because they were specified as demo
# values - change them from Admin > Profile before this is public.
SEED_ADMIN_EMAIL = "admin@demo.com"
SEED_ADMIN_PASSWORD = "aaaaaa"

JOB_CATEGORIES = [
    "Engineering", "Data & Analytics", "Design", "Product", "Marketing",
    "Sales & Success", "Operations", "People & HR", "Finance & Legal",
    "Infrastructure & DevOps", "Security", "Other",
]

EMPLOYMENT_TYPES = ["Full-time", "Part-time", "Internship", "Contract", "Freelance"]

# What kind of employer this is - asked when posting so students can tell a
# product company from a services one at a glance, which is the distinction
# most placement questions turn on.
COMPANY_TYPES = [
    "Product", "Service / Consulting", "Startup", "MNC",
    "Government / PSU", "Non-profit", "Other",
]

_lock = threading.Lock()
_settings_cache = None
_announcements_cache = None


# --- helpers ---------------------------------------------------------------

def _now() -> float:
    return time.time()


def _as_epoch(value) -> float:
    """Firestore timestamps come back as datetimes; normalise to epoch floats."""
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.timestamp()
    return 0.0


def invalidate():
    """Drop the caches - called after any write that a page load reads."""
    global _settings_cache, _announcements_cache
    with _lock:
        _settings_cache = None
        _announcements_cache = None


# --- site settings ---------------------------------------------------------

def get_settings(db) -> dict:
    global _settings_cache
    if _settings_cache is not None:
        return _settings_cache

    settings = {"app_name": DEFAULT_APP_NAME, "footer_signature": DEFAULT_FOOTER}
    if db is not None:
        try:
            doc = db.collection('site').document('config').get()
            if doc.exists:
                stored = doc.to_dict() or {}
                settings["app_name"] = (stored.get("app_name") or "").strip() or DEFAULT_APP_NAME
                settings["footer_signature"] = (
                    (stored.get("footer_signature") or "").strip() or DEFAULT_FOOTER
                )
        except Exception:
            # A settings read must never take the public site down; the
            # defaults above are a complete, working configuration.
            pass

    with _lock:
        _settings_cache = settings
    return settings


def save_settings(db, app_name: str, footer_signature: str) -> dict:
    payload = {
        "app_name": (app_name or "").strip() or DEFAULT_APP_NAME,
        "footer_signature": (footer_signature or "").strip() or DEFAULT_FOOTER,
    }
    db.collection('site').document('config').set(payload)
    invalidate()
    return payload


# --- admin account ---------------------------------------------------------

def ensure_admin(db) -> None:
    """Seeds the demo admin on first run. Never overwrites an edited account."""
    if db is None:
        return
    try:
        ref = db.collection('site').document('admin')
        if not ref.get().exists:
            ref.set({
                "email": SEED_ADMIN_EMAIL,
                "password": generate_password_hash(SEED_ADMIN_PASSWORD),
            })
    except Exception:
        pass


def get_admin(db) -> dict | None:
    if db is None:
        return None
    doc = db.collection('site').document('admin').get()
    return doc.to_dict() if doc.exists else None


def check_admin_login(db, email: str, password: str) -> bool:
    admin = get_admin(db)
    if not admin:
        return False
    if (email or "").strip().lower() != (admin.get("email") or "").lower():
        return False
    return check_password_hash(admin.get("password", ""), password or "")


def update_admin(db, email: str = None, password: str = None) -> None:
    patch = {}
    if email:
        patch["email"] = email.strip().lower()
    if password:
        patch["password"] = generate_password_hash(password)
    if patch:
        db.collection('site').document('admin').set(patch, merge=True)


# --- job posts -------------------------------------------------------------

def create_job_post(db, data: dict, author: str) -> str:
    ref = db.collection('job_posts').document()
    ref.set({
        "title": data["title"],
        "company": data["company"],
        "location": data.get("location", ""),
        "category": data.get("category") or "Other",
        "department": data.get("department", ""),
        "employment_type": data.get("employment_type") or "Full-time",
        "company_type": data.get("company_type") or "Other",
        "salary": data.get("salary", ""),
        "description": data.get("description", ""),
        "apply_url": data["apply_url"],
        "posted_by": author,
        "created_at": _now(),
    })
    return ref.id


def update_job_post(db, post_id: str, data: dict) -> None:
    db.collection('job_posts').document(post_id).update({
        "title": data["title"],
        "company": data["company"],
        "location": data.get("location", ""),
        "category": data.get("category") or "Other",
        "department": data.get("department", ""),
        "employment_type": data.get("employment_type") or "Full-time",
        "company_type": data.get("company_type") or "Other",
        "salary": data.get("salary", ""),
        "description": data.get("description", ""),
        "apply_url": data["apply_url"],
    })


def delete_job_post(db, post_id: str) -> None:
    db.collection('job_posts').document(post_id).delete()


def get_job_post(db, post_id: str) -> dict | None:
    if db is None:
        return None
    doc = db.collection('job_posts').document(post_id).get()
    if not doc.exists:
        return None
    post = doc.to_dict()
    post["id"] = doc.id
    return post


def list_job_posts(db, limit: int = None) -> list[dict]:
    """Newest first. Sorted in Python so no composite index is required."""
    if db is None:
        return []
    try:
        posts = []
        for doc in db.collection('job_posts').stream():
            post = doc.to_dict()
            post["id"] = doc.id
            post["created_at"] = _as_epoch(post.get("created_at"))
            posts.append(post)
    except Exception:
        return []

    posts.sort(key=lambda p: p.get("created_at", 0), reverse=True)
    return posts[:limit] if limit else posts


# --- registered users ------------------------------------------------------

def list_users(db) -> list[dict]:
    if db is None:
        return []
    try:
        users = []
        for doc in db.collection('users').stream():
            data = doc.to_dict() or {}
            users.append({
                "email": data.get("email") or doc.id,
                "username": data.get("username", ""),
                "created_at": _as_epoch(data.get("created_at")),
                # Never expose the hash to a template.
                "has_details": bool(data.get("details")),
            })
    except Exception:
        return []

    users.sort(key=lambda u: u.get("created_at", 0), reverse=True)
    return users


def reset_user_password(db, email: str, new_password: str) -> None:
    db.collection('users').document(email).update({
        "password": generate_password_hash(new_password),
    })


def update_user_email(db, old_email: str, new_email: str) -> None:
    """
    User docs are keyed by email, so a change is a copy to a new document and a
    delete of the old one - Firestore cannot rename a document id.
    """
    new_email = new_email.strip().lower()
    doc = db.collection('users').document(old_email).get()
    if not doc.exists:
        raise ValueError("That user no longer exists.")
    if db.collection('users').document(new_email).get().exists:
        raise ValueError("Another account already uses that email.")

    data = doc.to_dict()
    data["email"] = new_email
    db.collection('users').document(new_email).set(data)
    db.collection('users').document(old_email).delete()


# --- announcements ---------------------------------------------------------

def create_announcement(db, title: str, body: str, level: str = "info") -> str:
    ref = db.collection('announcements').document()
    ref.set({
        "title": title,
        "body": body,
        "level": level if level in {"info", "success", "warning"} else "info",
        "created_at": _now(),
    })
    invalidate()
    return ref.id


def delete_announcement(db, ann_id: str) -> None:
    db.collection('announcements').document(ann_id).delete()
    invalidate()


def list_announcements(db) -> list[dict]:
    global _announcements_cache
    if _announcements_cache is not None:
        return _announcements_cache

    items = []
    if db is not None:
        try:
            for doc in db.collection('announcements').stream():
                item = doc.to_dict()
                item["id"] = doc.id
                item["created_at"] = _as_epoch(item.get("created_at"))
                items.append(item)
        except Exception:
            items = []

    items.sort(key=lambda a: a.get("created_at", 0), reverse=True)
    with _lock:
        _announcements_cache = items
    return items


def unseen_announcements(db, seen_at: float) -> list[dict]:
    """Announcements posted since this user last dismissed the bell."""
    return [a for a in list_announcements(db) if a.get("created_at", 0) > (seen_at or 0)]


# --- analytics -------------------------------------------------------------

def _signup_timeline(users: list[dict]) -> list[dict]:
    """
    Cumulative registrations per day, oldest first.

    Users created before created_at was recorded carry an epoch of 0; they are
    counted in the total but cannot be placed on the timeline, so they are
    reported separately rather than silently bucketed into 1970.
    """
    dated = [u for u in users if u.get("created_at")]
    undated = len(users) - len(dated)

    per_day = {}
    for user in dated:
        day = datetime.fromtimestamp(user["created_at"], tz=timezone.utc).strftime('%Y-%m-%d')
        per_day[day] = per_day.get(day, 0) + 1

    running = undated
    points = []
    for day in sorted(per_day):
        running += per_day[day]
        points.append({"date": day, "new": per_day[day], "total": running})
    return points


def build_analytics(db) -> dict:
    users = list_users(db)
    posts = list_job_posts(db)
    announcements = list_announcements(db)

    by_category = {}
    by_type = {}
    by_company = {}
    for post in posts:
        by_category[post.get("category", "Other")] = by_category.get(post.get("category", "Other"), 0) + 1
        by_type[post.get("employment_type", "Full-time")] = by_type.get(post.get("employment_type", "Full-time"), 0) + 1
        company = post.get("company", "Unknown")
        by_company[company] = by_company.get(company, 0) + 1

    timeline = _signup_timeline(users)
    days_active = len(timeline)

    def ranked(mapping):
        return sorted(
            ({"label": k, "count": v} for k, v in mapping.items()),
            key=lambda r: (-r["count"], r["label"]),
        )

    return {
        "users_total": len(users),
        "posts_total": len(posts),
        "announcements_total": len(announcements),
        "categories_used": len(by_category),
        "companies_total": len(by_company),
        # Guarded so an empty install shows 0 rather than raising.
        "avg_posts_per_company": round(len(posts) / len(by_company), 1) if by_company else 0,
        "avg_signups_per_day": round(len(users) / days_active, 1) if days_active else 0,
        "timeline": timeline,
        "by_category": ranked(by_category),
        "by_type": ranked(by_type),
        "by_company": ranked(by_company)[:10],
        "recent_users": users[:10],
        "recent_posts": posts[:10],
    }
