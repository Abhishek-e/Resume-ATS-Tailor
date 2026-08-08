"""
Seed a demo employer organisation with one demo user, for showing the B2B
employer portal end to end.

Creates (idempotently - safe to re-run):
  - a demo user account (org admin)
  - an employer organisation owned by that user
  - a couple of sample job postings on it

Run against whatever DATABASE_URL points at:

    DATABASE_URL='mysql://resumify:...@localhost/resumify' python seed.py
    DATABASE_URL='sqlite:///./local.db' python seed.py
"""
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash

import dbstore
import orgs

load_dotenv()

DEMO_EMAIL = "demo@acme.com"
DEMO_PASSWORD = "demo1234"          # demo-only; change it before anything real
DEMO_NAME = "Demo Recruiter"
COMPANY_NAME = "Acme Corp"

SAMPLE_JOBS = [
    {
        "title": "Backend Engineer",
        "location": "Remote (India)",
        "employment_type": "Full-time",
        "description": "Build and scale the APIs behind our product. "
                       "Python/Flask, MySQL, and a bias for shipping.",
    },
    {
        "title": "Product Designer",
        "location": "Bengaluru",
        "employment_type": "Full-time",
        "description": "Own the end-to-end design of new features, from research "
                       "and wireframes to polished, shipped UI.",
    },
]


def main():
    db = dbstore.connect()
    if db is None:
        raise SystemExit(
            "DATABASE_URL is not set or the database is unreachable - nothing seeded."
        )

    # 1) demo user (the org admin)
    user_ref = db.collection("users").document(DEMO_EMAIL)
    if user_ref.get().exists:
        print(f"• user {DEMO_EMAIL} already exists - keeping it")
    else:
        user_ref.set({
            "username": DEMO_NAME,
            "email": DEMO_EMAIL,
            "password": generate_password_hash(DEMO_PASSWORD),
            "auth_provider": "password",
            "plan": "free",
            "created_at": dbstore.SERVER_TIMESTAMP,
        })
        print(f"• created user {DEMO_EMAIL}")

    # 2) employer organisation (idempotent on the user's membership)
    org = orgs.org_for_user(db, DEMO_EMAIL)
    if org:
        org_id = org["id"]
        print(f"• org already exists: {org['name']} ({org_id})")
    else:
        org_id = orgs.create_org(db, COMPANY_NAME, "employer", DEMO_EMAIL)
        print(f"• created employer org {COMPANY_NAME} ({org_id})")

    # 3) sample jobs (only if the org has none yet)
    if orgs.list_jobs(db, org_id):
        print("• jobs already present - not adding more")
    else:
        for job in SAMPLE_JOBS:
            orgs.create_job(db, org_id, job, DEMO_EMAIL)
        print(f"• added {len(SAMPLE_JOBS)} sample jobs")

    print("\nDone. Demo employer login:")
    print(f"    email:    {DEMO_EMAIL}")
    print(f"    password: {DEMO_PASSWORD}")
    print(f"    careers:  /careers/{org_id}")


if __name__ == "__main__":
    main()
