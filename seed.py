"""Seed complete, repeatable demo accounts and organisation data."""
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash

import adminstore
import dbstore
import orgs

load_dotenv()

STUDENT_EMAIL = "user@demo.com"
STUDENT_PASSWORD = "User@2026"
COMPANY_EMAIL = "company@demo.com"
COMPANY_PASSWORD = "Company@2026"
ADMIN_EMAIL = "admin@demo.com"
ADMIN_PASSWORD = "Admin@2026"

STUDENT_PROFILE = {
    "full_name": "Demo User",
    "id_card_number": "STU-2026-001",
    "college_name": "Demo Institute of Technology",
    "location": "Bengaluru, India",
    "github": "https://github.com/demo-user",
    "linkedin": "https://www.linkedin.com/in/demo-user",
    "other": "https://portfolio.example.com/demo-user",
    "about_me": "Final-year computer science student building Python, machine-learning, and cloud applications. Seeking software and ML engineering opportunities.",
    "phone": "+91 90000 00001",
    "skills": "Python, Flask, Machine Learning, SQL, PostgreSQL, REST APIs, Git, Linux, Docker",
    "desired_titles": "Machine Learning Engineer, Python Developer, Backend Engineer",
    "recruiter_visible": True,
}

COMPANY_PROFILE = {
    "full_name": "Demo Company Recruiter",
    "id_card_number": "EMP-2026-001",
    "college_name": "Demo Technology Private Limited",
    "location": "Hyderabad, India",
    "github": "https://github.com/demo-company",
    "linkedin": "https://www.linkedin.com/company/demo-company",
    "other": "https://company.example.com",
    "about_me": "Talent acquisition lead hiring software, data, and machine-learning engineers for a product-focused technology company.",
    "phone": "+91 90000 00002",
    "skills": "Technical Recruiting, Talent Acquisition, Python Hiring, Data Hiring, Interview Coordination",
    "desired_titles": "Technical Recruiter, Talent Acquisition Lead",
    "recruiter_visible": False,
}

SAMPLE_JOBS = [
    {
        "title": "Python Backend Engineer",
        "location": "Hyderabad / Hybrid",
        "employment_type": "Full-time",
        "salary": "₹8–14 LPA",
        "experience": "1–3 years",
        "openings": 3,
        "deadline": "2027-01-31",
        "description": "Build Flask APIs and PostgreSQL-backed services for our product platform.",
    },
    {
        "title": "Machine Learning Engineer",
        "location": "Remote (India)",
        "employment_type": "Full-time",
        "salary": "₹10–18 LPA",
        "experience": "1–4 years",
        "openings": 2,
        "deadline": "2027-02-28",
        "description": "Develop, evaluate, and deploy practical machine-learning features and AI integrations.",
    },
]


def upsert_user(db, email, password, username, profile):
    db.collection("users").document(email).set({
        "username": username,
        "email": email,
        "password": generate_password_hash(password),
        "auth_provider": "password",
        "plan": "free",
        "details": profile,
        "created_at": dbstore.SERVER_TIMESTAMP,
    }, merge=True)


def ensure_org(db, email, name, org_type):
    org = orgs.org_for_user(db, email)
    if org and org.get("type") == org_type:
        return org["id"]
    if org:
        orgs.clear_membership(db, email)
    return orgs.create_org(db, name, org_type, email)


def main():
    db = dbstore.connect()
    if db is None:
        raise SystemExit("DATABASE_URL is not set or the database is unreachable.")

    upsert_user(db, STUDENT_EMAIL, STUDENT_PASSWORD, "Demo User", STUDENT_PROFILE)
    upsert_user(db, COMPANY_EMAIL, COMPANY_PASSWORD, "Demo Company Recruiter", COMPANY_PROFILE)
    adminstore.ensure_admin(db)
    adminstore.update_admin(db, ADMIN_EMAIL, ADMIN_PASSWORD)

    college_id = ensure_org(
        db, STUDENT_EMAIL, "Demo Institute Placement Cell", "college")
    company_id = ensure_org(
        db, COMPANY_EMAIL, "Demo Technology Private Limited", "employer")

    if not orgs.list_jobs(db, company_id):
        for job in SAMPLE_JOBS:
            orgs.create_job(db, company_id, job, COMPANY_EMAIL)

    print("Demo data ready")
    print(f"student={STUDENT_EMAIL} college={college_id}")
    print(f"company={COMPANY_EMAIL} company_org={company_id}")
    print(f"admin={ADMIN_EMAIL}")


if __name__ == "__main__":
    main()
