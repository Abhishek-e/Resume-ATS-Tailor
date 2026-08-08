"""
B2B organisations: colleges (placement cells) and employers.

Two org types share one model:
  - college  -> a placement-cell dashboard with cohort analytics over the
                resumes / ATS analyses / applications its members already create.
  - employer -> a self-serve portal to post jobs and see who applied.

Membership lives on the user document (org_id + org_role) so a signed-in user's
org is one read away. Everything goes through the same `db` datastore shim the
rest of the app uses, so this runs wherever the app runs (MariaDB on the Pi).
Nothing here charges money; seats are a soft limit recorded on the org.

Collections
  organizations    one doc per org
  users            existing; gains org_id + org_role for members
  org_job_posts    employer openings (kept separate from admin job_posts)
  org_applications one row per applicant per posting
"""
import time
import uuid

ORG_TYPES = ("college", "employer")
DEFAULT_SEATS = {"college": 50, "employer": 10}


def _now():
    return time.time()


# --- organisations & membership --------------------------------------------

def create_org(db, name, org_type, owner_email, seat_limit=None) -> str:
    """Create an org and make the creator its org-admin. Returns the org id."""
    org_type = org_type if org_type in ORG_TYPES else "college"
    org_id = uuid.uuid4().hex[:12]
    db.collection("organizations").document(org_id).set({
        "name": (name or "").strip() or "My organisation",
        "type": org_type,
        "owner_email": owner_email,
        "seat_limit": int(seat_limit or DEFAULT_SEATS[org_type]),
        "plan": "team",
        "created_at": _now(),
    })
    set_membership(db, owner_email, org_id, "org_admin")
    return org_id


def get_org(db, org_id):
    if db is None or not org_id:
        return None
    doc = db.collection("organizations").document(org_id).get()
    if not doc.exists:
        return None
    org = doc.to_dict()
    org["id"] = org_id
    return org


def set_membership(db, email, org_id, role) -> None:
    """Record org_id + org_role on the user document."""
    db.collection("users").document(email).update({"org_id": org_id, "org_role": role})


def clear_membership(db, email) -> None:
    db.collection("users").document(email).update({"org_id": "", "org_role": ""})


def org_for_user(db, email):
    """The org a user belongs to (with their role attached), or None."""
    if db is None or not email:
        return None
    doc = db.collection("users").document(email).get()
    if not doc.exists:
        return None
    data = doc.to_dict()
    org = get_org(db, data.get("org_id"))
    if org is None:
        return None
    org["my_role"] = data.get("org_role", "member")
    return org


def list_members(db, org_id) -> list:
    """Users whose org_id matches, newest-ish first by email."""
    if db is None:
        return []
    from dbstore import FieldFilter
    members = []
    for doc in db.collection("users").where(filter=FieldFilter("org_id", "==", org_id)).stream():
        u = doc.to_dict()
        members.append({
            "email": u.get("email") or doc.id,
            "username": u.get("username", ""),
            "role": u.get("org_role", "member"),
        })
    members.sort(key=lambda m: (m["role"] != "org_admin", m["email"]))
    return members


def seats(db, org_id) -> dict:
    org = get_org(db, org_id)
    limit = org["seat_limit"] if org else 0
    used = len(list_members(db, org_id))
    return {"limit": limit, "used": used, "left": max(limit - used, 0)}


def add_member(db, org_id, email):
    """Add an existing user to the org. Returns (ok, message)."""
    email = (email or "").strip().lower()
    if not email:
        return False, "Enter an email address."
    user = db.collection("users").document(email).get()
    if not user.exists:
        return False, f"No account exists for {email}. They must register first."
    data = user.to_dict()
    if data.get("org_id"):
        return False, f"{email} already belongs to an organisation."
    if seats(db, org_id)["left"] <= 0:
        return False, "No seats left — raise the seat limit or remove a member."
    set_membership(db, email, org_id, "member")
    return True, f"Added {email}."


def remove_member(db, org_id, email):
    """Remove a member. The owner/org-admin cannot remove themselves here."""
    org = get_org(db, org_id)
    if org and email == org.get("owner_email"):
        return False, "The organisation owner cannot be removed."
    clear_membership(db, email)
    return True, f"Removed {email}."


# --- college: cohort analytics ---------------------------------------------

def _group_by_user(db, collection):
    """All docs in a collection grouped by their user_id, in one pass."""
    grouped = {}
    if db is None:
        return grouped
    for doc in db.collection(collection).stream():
        d = doc.to_dict()
        grouped.setdefault(d.get("user_id"), []).append(d)
    return grouped


def cohort_stats(db, org_id) -> dict:
    """Per-member activity for a placement-cell dashboard, plus rolled-up totals.

    Aggregated from the collections members already populate: one resume-ready
    signal (resume count), one quality signal (best ATS after-score), and one
    outcome signal (applications submitted).
    """
    members = list_members(db, org_id)
    resumes = _group_by_user(db, "resumes")
    analyses = _group_by_user(db, "resume_analyses")
    applications = _group_by_user(db, "applications")

    rows, tot_resumes, tot_apps, scored = [], 0, 0, []
    for m in members:
        email = m["email"]
        r_count = len(resumes.get(email, []))
        best = 0
        for a in analyses.get(email, []):
            best = max(best, int((a.get("generated_content") or {}).get("after_score", 0) or 0))
        app_count = len(applications.get(email, []))
        rows.append({
            **m,
            "resume_count": r_count,
            "best_ats": best,
            "applications": app_count,
            "ready": r_count > 0 and best >= 60,
        })
        tot_resumes += r_count
        tot_apps += app_count
        if best:
            scored.append(best)

    return {
        "rows": rows,
        "totals": {
            "members": len(members),
            "resumes": tot_resumes,
            "applications": tot_apps,
            "avg_ats": round(sum(scored) / len(scored)) if scored else 0,
            "ready": sum(1 for r in rows if r["ready"]),
        },
    }


# --- employer: job posts & applicants --------------------------------------

def create_job(db, org_id, data, author) -> str:
    ref = db.collection("org_job_posts").document()
    ref.set({
        "org_id": org_id,
        "title": data.get("title", "").strip(),
        "location": data.get("location", "").strip(),
        "employment_type": data.get("employment_type", "Full-time"),
        "description": data.get("description", "").strip(),
        "posted_by": author,
        "created_at": _now(),
    })
    return ref.id


def list_jobs(db, org_id) -> list:
    if db is None:
        return []
    from dbstore import FieldFilter
    posts = []
    for doc in db.collection("org_job_posts").where(filter=FieldFilter("org_id", "==", org_id)).stream():
        p = doc.to_dict()
        p["id"] = doc.id
        posts.append(p)
    posts.sort(key=lambda p: p.get("created_at", 0), reverse=True)
    return posts


def get_job(db, post_id):
    if db is None or not post_id:
        return None
    doc = db.collection("org_job_posts").document(post_id).get()
    if not doc.exists:
        return None
    p = doc.to_dict()
    p["id"] = post_id
    return p


def record_applicant(db, org_id, post, applicant_email, applicant_name):
    """One application per user per posting (idempotent on re-apply)."""
    doc_id = f"{post['id']}_{applicant_email}"
    db.collection("org_applications").document(doc_id).set({
        "org_id": org_id,
        "post_id": post["id"],
        "post_title": post.get("title", ""),
        "applicant_email": applicant_email,
        "applicant_name": applicant_name,
        "created_at": _now(),
    })


def list_applicants(db, org_id, post_id=None) -> list:
    if db is None:
        return []
    from dbstore import FieldFilter
    rows = []
    for doc in db.collection("org_applications").where(filter=FieldFilter("org_id", "==", org_id)).stream():
        a = doc.to_dict()
        if post_id and a.get("post_id") != post_id:
            continue
        a["id"] = doc.id
        rows.append(a)
    rows.sort(key=lambda a: a.get("created_at", 0), reverse=True)
    return rows


def applicant_counts(db, org_id) -> dict:
    counts = {}
    for a in list_applicants(db, org_id):
        counts[a["post_id"]] = counts.get(a["post_id"], 0) + 1
    return counts
