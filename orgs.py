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
import re
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

FREE_JOB_LIMIT = 5


def _to_int(value, default=0):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def create_job(db, org_id, data, author) -> str:
    ref = db.collection("org_job_posts").document()
    ref.set({
        "org_id": org_id,
        "title": data.get("title", "").strip(),
        "location": data.get("location", "").strip(),
        "employment_type": data.get("employment_type", "Full-time"),
        "salary": data.get("salary", "").strip(),
        "experience": data.get("experience", "").strip(),
        "openings": _to_int(data.get("openings"), 1),
        # Application closing date as an ISO 'YYYY-MM-DD' string (or '' for none).
        "deadline": (data.get("deadline") or "").strip(),
        "description": data.get("description", "").strip(),
        "posted_by": author,
        "created_at": _now(),
        "sponsored": False,
        "sponsored_at": 0,
    })
    return ref.id


def is_premium(org) -> bool:
    return bool(org and org.get("premium"))


def can_post_job(db, org) -> bool:
    """Employers post up to FREE_JOB_LIMIT jobs free; premium lifts the cap."""
    if is_premium(org):
        return True
    return len(list_jobs(db, org["id"])) < FREE_JOB_LIMIT


def set_premium(db, org_id, on=True) -> None:
    db.collection("organizations").document(org_id).update({"premium": bool(on)})


def list_jobs(db, org_id) -> list:
    if db is None:
        return []
    from dbstore import FieldFilter
    posts = []
    for doc in db.collection("org_job_posts").where(filter=FieldFilter("org_id", "==", org_id)).stream():
        p = doc.to_dict()
        p["id"] = doc.id
        posts.append(p)
    # Sponsored posts float to the top, then newest first.
    posts.sort(key=lambda p: (not p.get("sponsored"), -p.get("created_at", 0)))
    return posts


def set_sponsored(db, org_id, post_id, sponsored) -> bool:
    """Toggle the sponsored/featured flag on one of the org's own posts."""
    post = get_job(db, post_id)
    if post is None or post.get("org_id") != org_id:
        return False
    db.collection("org_job_posts").document(post_id).update({
        "sponsored": bool(sponsored),
        "sponsored_at": _now() if sponsored else 0,
    })
    return True


def list_sponsored_posts(db, limit=6) -> list:
    """Featured openings across every employer, for the public jobs board.

    This is the visibility a sponsor pays for - their post surfaces beyond their
    own careers page. Newest sponsored first; the employer name is attached.
    """
    if db is None:
        return []
    from dbstore import FieldFilter
    posts = []
    org_names = {}
    for doc in db.collection("org_job_posts").where(filter=FieldFilter("sponsored", "==", True)).stream():
        p = doc.to_dict()
        p["id"] = doc.id
        oid = p.get("org_id")
        if oid not in org_names:
            org = get_org(db, oid)
            org_names[oid] = org["name"] if org else ""
        p["org_name"] = org_names[oid]
        posts.append(p)
    posts.sort(key=lambda p: p.get("sponsored_at", 0), reverse=True)
    return posts[:limit]


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


def employer_analytics(db, org_id) -> dict:
    """Headline recruiting metrics for the employer analytics page."""
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    jobs = list_jobs(db, org_id)
    counts = applicant_counts(db, org_id)
    total_applicants = sum(counts.values())
    ranking = sorted(
        ({"title": j["title"], "count": counts.get(j["id"], 0)} for j in jobs),
        key=lambda r: -r["count"],
    )
    open_jobs = sum(1 for j in jobs if not (j.get("deadline") and j["deadline"] < today))
    return {
        "total_jobs": len(jobs),
        "open_jobs": open_jobs,
        "closed_jobs": len(jobs) - open_jobs,
        "featured": sum(1 for j in jobs if j.get("sponsored")),
        "total_applicants": total_applicants,
        "avg_per_job": round(total_applicants / len(jobs), 1) if jobs else 0,
        "ranking": ranking[:10],
    }


# --- employer: candidate database search -----------------------------------

def search_candidates(db, query="", location="", limit=50) -> list:
    """Opt-in candidate profiles matching a keyword and/or location.

    Privacy is the whole point: a profile is only ever returned when its owner
    set details.recruiter_visible - so this is a directory of people who chose
    to be found, not the whole user table. The keyword matches name, skills,
    desired titles and the about-me blurb.
    """
    if db is None:
        return []
    q = (query or "").strip().lower()
    loc = (location or "").strip().lower()

    results = []
    for doc in db.collection("users").stream():
        u = doc.to_dict()
        details = u.get("details") or {}
        if not details.get("recruiter_visible"):
            continue

        skills_raw = details.get("skills") or ""
        titles_raw = details.get("desired_titles") or ""
        name = details.get("full_name") or u.get("username") or ""
        haystack = " ".join([
            name, skills_raw, titles_raw, details.get("about_me", ""),
        ]).lower()

        if q and q not in haystack:
            continue
        if loc and loc not in (details.get("location") or "").lower():
            continue

        skills = [s.strip() for s in re.split(r"[,\n;]+", skills_raw) if s.strip()]
        titles = [t.strip() for t in re.split(r"[,\n;]+", titles_raw) if t.strip()]
        results.append({
            "email": u.get("email") or doc.id,
            "name": name,
            "headline": titles[0] if titles else "",
            "skills": skills[:12],
            "location": details.get("location", ""),
            "github": details.get("github", ""),
            "linkedin": details.get("linkedin", ""),
        })

    results.sort(key=lambda r: r["name"].lower())
    return results[:limit]


def candidate_pool_size(db) -> int:
    """How many profiles are discoverable, for the empty-state copy."""
    if db is None:
        return 0
    n = 0
    for doc in db.collection("users").stream():
        if (doc.to_dict().get("details") or {}).get("recruiter_visible"):
            n += 1
    return n


# --- billing (order records; no payment processing) ------------------------
#
# Deliberately provider-agnostic and honest: buying records a PENDING order. A
# real payment provider (e.g. Razorpay for INR) would be wired at create_order
# (return a hosted checkout/link) and a webhook would call mark_order_paid on
# success. Until then a site admin reconciles offline payments by marking an
# order paid, which applies its effect (currently: extra member seats).

PRODUCTS = {
    # Employer subscription tiers - both grant premium (unlimited jobs +
    # candidate database). Display details live in employerplans.py.
    "emp_growth": {"label": "Employer Growth (monthly)", "amount": 2699, "premium": True},
    "emp_pro": {"label": "Employer Pro (monthly)", "amount": 7199, "premium": True},
    # Seat packs (colleges or employers).
    "seats_25": {"label": "+25 member seats", "amount": 4999, "seats_delta": 25},
    "seats_100": {"label": "+100 member seats", "amount": 14999, "seats_delta": 100},
}
CURRENCY = "₹"


def create_order(db, org_id, product_slug) -> str | None:
    """Record a pending order for a product. Returns the order id, or None for
    an unknown product."""
    product = PRODUCTS.get(product_slug)
    if product is None:
        return None
    org = get_org(db, org_id)
    ref = db.collection("orders").document()
    ref.set({
        "org_id": org_id,
        "org_name": org["name"] if org else "",
        "product": product_slug,
        "label": product["label"],
        "amount": product["amount"],
        "currency": CURRENCY,
        "status": "pending",
        "created_at": _now(),
        "paid_at": 0,
    })
    return ref.id


def list_orders(db, org_id) -> list:
    if db is None:
        return []
    from dbstore import FieldFilter
    rows = []
    for doc in db.collection("orders").where(filter=FieldFilter("org_id", "==", org_id)).stream():
        o = doc.to_dict()
        o["id"] = doc.id
        rows.append(o)
    rows.sort(key=lambda o: o.get("created_at", 0), reverse=True)
    return rows


def list_all_orders(db) -> list:
    if db is None:
        return []
    rows = []
    for doc in db.collection("orders").stream():
        o = doc.to_dict()
        o["id"] = doc.id
        rows.append(o)
    rows.sort(key=lambda o: (o.get("status") != "pending", -o.get("created_at", 0)))
    return rows


def mark_order_paid(db, order_id) -> bool:
    """Mark an order paid and apply its effect (raise the org's seat limit).
    Idempotent: a re-mark does not apply the effect twice."""
    doc = db.collection("orders").document(order_id).get()
    if not doc.exists:
        return False
    order = doc.to_dict()
    if order.get("status") == "paid":
        return True
    db.collection("orders").document(order_id).update({"status": "paid", "paid_at": _now()})

    product = PRODUCTS.get(order.get("product"))
    org = get_org(db, order.get("org_id"))
    if product and org:
        if product.get("seats_delta"):
            db.collection("organizations").document(org["id"]).update({
                "seat_limit": int(org.get("seat_limit", 0)) + product["seats_delta"],
            })
        if product.get("premium"):
            set_premium(db, org["id"], True)
    return True
