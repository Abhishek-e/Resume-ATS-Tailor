"""
Normalises the wildly different shapes each board reports a job's team in, so
the profile dashboard can group applications consistently.

Two axes:
  department - what the employer calls the team ("Engineering", "Growth").
               Taken from the board when it publishes one, else inferred.
  category   - a fixed bucket from CATEGORIES below, always inferred from the
               title. Fixed so the analytics chart has stable series across
               employers who name their departments differently.
"""
import html
import re
from urllib.parse import urlparse

# Boards leave placeholder rows in their feeds ("We don't currently have any
# open roles"), and demo boards are full of scratch postings. Neither should
# reach the user's job list or skew the dashboard analytics.
_JUNK_TITLE_RE = re.compile(
    r"^(test|test position|testing|blah|blah blah blah|asdf|untitled|sample|demo|"
    r"we don'?t currently have any open roles.*|https?[\s:].*)$",
    re.IGNORECASE,
)


def clean_text(value) -> str:
    """Feeds mix escaped and unescaped HTML; titles arrive as 'R&amp;D Lead'."""
    if not value:
        return ""
    return re.sub(r"\s+", " ", html.unescape(str(value))).strip()


# Pre-fill only works on the boards' own hosted application templates. Plenty
# of employers serve a Greenhouse/Lever job through their own careers domain
# (stripe.com/jobs/...), where the markup differs or the form sits in an iframe.
# Those postings keep their source but must not advertise assisted apply.
_HOSTED_APPLY_DOMAINS = {
    "greenhouse": ("boards.greenhouse.io", "job-boards.greenhouse.io"),
    "lever": ("jobs.lever.co",),
}


def hosted_ats_type(ats_type: str, url: str) -> str:
    """Returns the ats_type only if the posting is on that board's own hosted
    domain, else 'other' so the UI offers 'Open listing' instead."""
    domains = _HOSTED_APPLY_DOMAINS.get(ats_type)
    if not domains:
        return "other"
    host = urlparse(url or "").netloc.lower()
    return ats_type if any(host == d or host.endswith("." + d) for d in domains) else "other"


def is_real_posting(job: dict) -> bool:
    title = (job.get("title") or "").strip()
    if not title or not job.get("url"):
        return False
    return not _JUNK_TITLE_RE.match(title)

# Ordered: the first bucket whose keywords hit wins, so put the specific
# buckets ahead of the ones with broad keywords ("Engineering" last of the
# technical group, since "engineer" appears in data/security titles too).
CATEGORIES = [
    ("Data & Analytics", [
        "data scientist", "data science", "data analyst", "analytics", "machine learning",
        "ml engineer", "ai engineer", "data engineer", "bi ", "business intelligence",
        "statistician", "research scientist",
    ]),
    ("Security", [
        "security", "infosec", "appsec", "penetration", "cryptograph", "compliance engineer",
    ]),
    ("Infrastructure & DevOps", [
        "devops", "sre", "site reliability", "infrastructure", "platform engineer",
        "cloud engineer", "systems engineer", "network engineer", "database administrator",
    ]),
    ("Design", [
        "designer", "design", "ux", "ui ", "user experience", "user research", "creative",
    ]),
    ("Product", [
        "product manager", "product owner", "product management", "technical program manager",
        "program manager", "scrum master",
    ]),
    ("Marketing", [
        "marketing", "seo", "content writer", "copywriter", "brand", "communications",
        "social media", "growth",
    ]),
    ("Sales & Success", [
        "sales", "account executive", "account manager", "business development",
        "customer success", "customer support", "customer service", "customer experience",
        "solutions engineer", "partnerships", "support specialist", "csm", "sdr", "bdr",
    ]),
    ("Finance & Legal", [
        "finance", "accountant", "accounting", "controller", "auditor", "tax ",
        "legal", "counsel", "paralegal",
    ]),
    ("People & HR", [
        "recruiter", "recruiting", "talent", "human resources", "people ops", "hr ",
    ]),
    ("Operations", [
        "operations", "logistics", "supply chain", "procurement", "facilities",
        "administrative", "office manager", "executive assistant", "chief of staff",
        "coo", "chief operating", "implementation specialist",
    ]),
    ("Engineering", [
        "engineer", "developer", "programmer", "software", "full stack", "fullstack",
        "frontend", "front-end", "backend", "back-end", "mobile", "ios ", "android",
        "qa ", "test engineer", "architect",
    ]),
]

DEFAULT_CATEGORY = "Other"


def categorize(title: str, description: str = "") -> str:
    """Buckets a posting by title. Falls back to scanning the description only
    when the title alone is uninformative (e.g. "Member of Technical Staff")."""
    haystack = f" {(title or '').lower()} "
    for name, keywords in CATEGORIES:
        if any(kw in haystack for kw in keywords):
            return name

    haystack = f" {(description or '').lower()[:600]} "
    for name, keywords in CATEGORIES:
        if any(kw in haystack for kw in keywords):
            return name

    return DEFAULT_CATEGORY


def clean_department(raw, title: str = "", description: str = "") -> str:
    """Boards report departments as a string, a list of names, or a list of
    {id, name} dicts - and often not at all. Normalise all of that, and fall
    back to the inferred category so the dashboard never shows a blank slice."""
    name = ""
    if isinstance(raw, str):
        name = raw
    elif isinstance(raw, dict):
        name = raw.get("name") or ""
    elif isinstance(raw, (list, tuple)):
        parts = []
        for item in raw:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and item.get("name"):
                parts.append(item["name"])
        name = parts[0] if parts else ""

    name = re.sub(r"\s+", " ", (name or "")).strip(" -/,")
    # Greenhouse uses "No Department" as a literal placeholder on unassigned roles.
    if not name or name.lower() in {"no department", "none", "n/a", "other"}:
        return categorize(title, description)
    return name[:60]
