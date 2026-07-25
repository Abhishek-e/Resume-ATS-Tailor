"""
Assisted application without a browser.

This replaces the Playwright/headless-Chromium approach. That was dropped for
two reasons, the second of which is the decisive one:

  1. It forced a Docker deploy on the Playwright base image and a paid Render
     plan (Chromium does not fit the free tier's memory), plus a single
     gunicorn worker so apply sessions stayed reachable.
  2. Both boards CAPTCHA-gate the submit button - Lever ships an
     `h-captcha-response` field, Greenhouse loads reCAPTCHA. A headless browser
     would have been stopped at the final click just the same. Automating past
     that is not something this app will do.

So instead of pretending to submit, Resumify does every part it legitimately
can and hands a finished application to the user:

  * Greenhouse honours query-string prefill, so its form opens already filled.
  * Lever does not (its form hydrates client-side), so the values are handed
    over copy-ready instead.
  * The tailored CV is rendered to PDF and offered as a download either way.
  * The user submits on the employer's own page, then confirms, and Resumify
    records it in the tracker.

Pure stdlib - no browser, no extra services, and nothing that needs a
particular host. Deploys anywhere Python runs.
"""
# Boards whose hosted form we can point straight at the application step.
SUPPORTED_ATS = {"greenhouse", "lever"}

# Empty, and deliberately so. Query-string prefill was tried against both
# boards and neither honours it:
#   * Greenhouse now redirects boards.greenhouse.io -> job-boards.greenhouse.io
#     and drops the parameters; loading a posting with first_name/email set
#     leaves all 27 form inputs empty. (The values do appear in the HTML, but
#     only inside a canonical link - not as field values, which is what made
#     an HTTP-only check look like it worked.)
#   * Lever hydrates its form client-side and ignores the query string too.
# Kept as a named set so a board that does support it later slots in here
# without touching the rest of the flow.
PREFILL_ATS: set[str] = set()

# Human labels for the confirm screen, in the order they appear on a form.
FIELD_ORDER = [
    ("full_name", "Full name"),
    ("email", "Email"),
    ("phone", "Phone"),
    ("location", "Location"),
    ("linkedin", "LinkedIn"),
    ("github", "GitHub"),
    ("portfolio", "Portfolio"),
]


def _lever_apply_url(url: str) -> str:
    """Lever's posting page is the description; the form lives at /apply."""
    trimmed = url.rstrip("/")
    return trimmed if trimmed.endswith("/apply") else trimmed + "/apply"


def build_kit(job: dict, profile: dict, has_resume: bool = False) -> dict:
    """Assembles everything the user needs to finish one application."""
    ats = job.get("ats_type", "other")
    url = job.get("url", "")

    # Lever's posting page is the description, so skip straight to the form.
    # Everything else opens where the board put it.
    apply_url = _lever_apply_url(url) if ats == "lever" else url

    fields = [
        {"key": key, "label": label, "value": (profile.get(key) or "").strip()}
        for key, label in FIELD_ORDER
    ]
    fields = [f for f in fields if f["value"]]

    prefilled = ats in PREFILL_ATS
    if ats == "lever":
        note = ("Opens straight at the application form. Copy your details across, "
                "attach the CV, and submit.")
    else:
        note = ("Copy your details into the employer's form, attach the CV, "
                "and submit.")

    return {
        "job_id": job.get("id"),
        "title": job.get("title"),
        "company": job.get("company"),
        "ats_type": ats,
        "apply_url": apply_url,
        "prefilled": prefilled,
        "fields": fields,
        "has_resume": has_resume,
        "note": note,
        # Stated plainly in the UI: the employer's CAPTCHA is why the final
        # click is the user's, so nobody is left wondering why.
        "why_manual": ("This board protects its form with a CAPTCHA, so the final "
                       "submit has to be yours."),
    }
