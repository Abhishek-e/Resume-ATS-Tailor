"""
Company question bank.

Two sources feed one list per company:

  * A static bank imported from the ai-resume-agent project - 209 coding
    problems across 10 companies, with worked examples. Shipped as JSON in
    data/ and loaded once at import, because it never changes at runtime.
  * Questions the admin adds through the panel, stored in Firestore. These
    stack onto whichever company they name, creating it if it is new.

prepsets.py stays the owner of the interview-round material (the short Q&A
shown in the preview modal). This module owns the practice-desk questions.
"""
import json
import os
import re
import threading
import time
from urllib.parse import urlparse

_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')

QUESTION_TYPES = ["Coding", "MCQ", "Fill in the blank"]
DIFFICULTIES = ["Easy", "Medium", "Hard"]

# Display names and grouping for the imported companies, carried over from the
# source project so the roster reads the same as where the questions came from.
BANK_COMPANIES = {
    "meta": ("Meta", "FANG"),
    "amazon": ("Amazon", "FANG"),
    "netflix": ("Netflix", "FANG"),
    "google": ("Google", "FANG"),
    "infosys": ("Infosys", "Mass Recruiter"),
    "accenture": ("Accenture", "Mass Recruiter"),
    "capgemini": ("Capgemini", "Mass Recruiter"),
    "ibm": ("IBM", "Mass Recruiter"),
    "github": ("GitHub", "Other"),
    "anthropic": ("Anthropic", "Other"),
}

_lock = threading.Lock()
_custom_cache = None


def _load_json(name):
    path = os.path.join(_DATA_DIR, name)
    try:
        with open(path, encoding='utf-8') as fh:
            return json.load(fh)
    except (OSError, ValueError):
        # A missing or corrupt bank must not take the site down - the admin's
        # own questions still work, and the pages render with what they have.
        return {}


_RAW_BANK = _load_json('company_questions.json')
_EXAMPLES = _load_json('question_examples.json')

_EMPTY_EXAMPLE = {
    "input": "", "output": "",
    "explanation": "Example not yet available for this problem.",
}


def _slug_from_url(url: str) -> str:
    """LeetCode problem slug, which is how the examples file is keyed."""
    path = urlparse(url or "").path.strip('/')
    parts = [p for p in path.split('/') if p]
    return parts[-1] if parts else ""


def _build_bank():
    bank = {}
    for slug, questions in _RAW_BANK.items():
        rows = []
        for index, q in enumerate(questions):
            problem = _slug_from_url(q.get('url', ''))
            rows.append({
                "id": f"bank:{slug}:{index}",
                "source": "bank",
                "type": "Coding",
                "title": q.get('title', 'Untitled'),
                "difficulty": q.get('difficulty', 'Medium'),
                "url": q.get('url', ''),
                "acceptance_pct": q.get('acceptancePct'),
                "frequency_pct": q.get('frequencyPct'),
                "example": _EXAMPLES.get(problem, _EMPTY_EXAMPLE),
                "prompt": "",
                "options": [],
                "answer": "",
            })
        bank[slug] = rows
    return bank


_BANK = _build_bank()


def slugify(name: str) -> str:
    slug = re.sub(r'[^a-z0-9]+', '-', (name or '').strip().lower()).strip('-')
    return slug or 'company'


def bank_slugs() -> list[str]:
    return list(_BANK)


def bank_questions(slug: str) -> list[dict]:
    return _BANK.get(slug, [])


# --- admin-authored questions ----------------------------------------------

def invalidate():
    global _custom_cache
    with _lock:
        _custom_cache = None


def list_custom(db) -> list[dict]:
    """Every admin-added question, newest first. Cached; writes invalidate."""
    global _custom_cache
    if _custom_cache is not None:
        return _custom_cache

    rows = []
    if db is not None:
        try:
            for doc in db.collection('prep_questions').stream():
                row = doc.to_dict() or {}
                row['id'] = doc.id
                row['source'] = 'custom'
                rows.append(row)
        except Exception:
            rows = []

    rows.sort(key=lambda r: r.get('created_at', 0), reverse=True)
    with _lock:
        _custom_cache = rows
    return rows


def add_question(db, data: dict, author: str) -> str:
    company_name = (data.get('company_name') or '').strip()
    slug = slugify(company_name)

    payload = {
        "company_slug": slug,
        "company_name": company_name,
        "type": data.get('type') if data.get('type') in QUESTION_TYPES else 'Coding',
        "difficulty": data.get('difficulty') if data.get('difficulty') in DIFFICULTIES else 'Medium',
        "title": (data.get('title') or '').strip(),
        "prompt": (data.get('prompt') or '').strip(),
        # Only meaningful for MCQ, but stored uniformly so one read serves
        # every type without branching at the call site.
        "options": [o for o in (data.get('options') or []) if o.strip()],
        "answer": (data.get('answer') or '').strip(),
        "explanation": (data.get('explanation') or '').strip(),
        "url": (data.get('url') or '').strip(),
        "created_by": author,
        "created_at": time.time(),
    }

    ref = db.collection('prep_questions').document()
    ref.set(payload)
    invalidate()
    return ref.id


def delete_question(db, question_id: str) -> None:
    db.collection('prep_questions').document(question_id).delete()
    invalidate()


def custom_for_slug(db, slug: str) -> list[dict]:
    return [q for q in list_custom(db) if q.get('company_slug') == slug]


# --- combined view ----------------------------------------------------------

def questions_for(db, slug: str) -> list[dict]:
    """
    Everything for one company: the imported bank first, then anything the
    admin has added on top. Admin questions come last so a freshly added one
    is not buried mid-list.
    """
    return bank_questions(slug) + custom_for_slug(db, slug)


def company_names(db) -> dict:
    """slug -> display name, across both sources."""
    names = {slug: label for slug, (label, _group) in BANK_COMPANIES.items()}
    for q in list_custom(db):
        slug = q.get('company_slug')
        if slug and slug not in names:
            names[slug] = q.get('company_name') or slug.title()
    return names


def total_questions(db) -> int:
    """Every practice question across every company, both sources."""
    return sum(len(questions_for(db, slug)) for slug in company_names(db))


def counts_for(db, slug: str) -> dict:
    questions = questions_for(db, slug)
    by_difficulty = {d: 0 for d in DIFFICULTIES}
    by_type = {t: 0 for t in QUESTION_TYPES}
    for q in questions:
        by_difficulty[q.get('difficulty', 'Medium')] = \
            by_difficulty.get(q.get('difficulty', 'Medium'), 0) + 1
        by_type[q.get('type', 'Coding')] = by_type.get(q.get('type', 'Coding'), 0) + 1
    return {
        "total": len(questions),
        "by_difficulty": by_difficulty,
        "by_type": by_type,
    }


def build_analytics(db) -> dict:
    """Everything the admin questionnaire dashboard reports."""
    names = company_names(db)

    per_company = []
    totals_difficulty = {d: 0 for d in DIFFICULTIES}
    totals_type = {t: 0 for t in QUESTION_TYPES}
    total = 0
    imported = 0
    authored = 0

    for slug, name in names.items():
        counts = counts_for(db, slug)
        bank_n = len(bank_questions(slug))
        custom_n = len(custom_for_slug(db, slug))
        imported += bank_n
        authored += custom_n
        total += counts['total']
        for key, value in counts['by_difficulty'].items():
            totals_difficulty[key] = totals_difficulty.get(key, 0) + value
        for key, value in counts['by_type'].items():
            totals_type[key] = totals_type.get(key, 0) + value

        per_company.append({
            "slug": slug,
            "name": name,
            "total": counts['total'],
            "imported": bank_n,
            "authored": custom_n,
            "by_difficulty": counts['by_difficulty'],
        })

    per_company.sort(key=lambda c: (-c['total'], c['name']))
    company_count = len(names)

    return {
        "companies": company_count,
        "questions": total,
        "imported": imported,
        "authored": authored,
        # Guarded so an install with no companies reads 0 rather than raising.
        "avg_per_company": round(total / company_count, 1) if company_count else 0,
        "by_difficulty": totals_difficulty,
        "by_type": totals_type,
        # Pre-shaped for the bar macro, which wants label/count rows.
        "by_type_rows": [{"label": k, "count": v} for k, v in totals_type.items()],
        "per_company": per_company,
        "recent": list_custom(db)[:10],
    }
