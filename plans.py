"""
Subscription plans (Free / Pro / Pro Annual).

Single source of truth for the pricing page, the plan chooser on the register
form, and the plan stored on a user. Prices and the feature matrix come from
the "Naukri Loge — Plans & Pricing" sheet. Nothing here charges money: choosing
a paid plan records the selection on the account; billing is not wired up.
"""

DEFAULT_PLAN = "free"

# Ordered so the pricing cards and the register chooser render Free -> Pro ->
# Annual left to right. `popular` puts the emphasised ring on the middle card.
PLANS = {
    "free": {
        "slug": "free",
        "name": "Free",
        "price": "₹0",
        "price_sub": "forever",
        "cycle": "No card required",
        "tagline": "Everything you need to get your first ATS-ready CV out the door.",
        "cta": "Start free",
        "popular": False,
        "highlights": [
            "5 CV generations / month",
            "5 cover letters / month",
            "5 ATS analyses / month",
            "Basic resume templates",
            "PDF export (watermarked)",
            "Full interview prep (270 Qs)",
        ],
    },
    "pro": {
        "slug": "pro",
        "name": "Pro",
        "price": "₹299",
        "price_sub": "/ 3 months",
        "cycle": "Billed quarterly · ~₹100/mo",
        "tagline": "Unlimited generations and premium templates for an active job hunt.",
        "cta": "Choose Pro",
        "popular": True,
        "highlights": [
            "Unlimited CV generations*",
            "Unlimited cover letters*",
            "Unlimited ATS analyses*",
            "All premium templates",
            "PDF + DOCX, no watermark",
            "Faster, better AI model",
        ],
    },
    "pro_annual": {
        "slug": "pro_annual",
        "name": "Pro Annual",
        "price": "₹999",
        "price_sub": "/ year",
        "cycle": "Billed yearly · ~₹83/mo",
        "tagline": "The same Pro features at the lowest effective monthly price.",
        "cta": "Choose Pro Annual",
        "popular": False,
        "highlights": [
            "Everything in Pro",
            "Unlimited CV generations*",
            "Unlimited cover letters*",
            "All premium templates",
            "PDF + DOCX, no watermark",
            "Best value per month",
        ],
    },
}

# Feature-by-feature comparison table (rows), values keyed by plan slug.
FEATURES = [
    ("CV / resume generations", {"free": "5 / month", "pro": "Unlimited*", "pro_annual": "Unlimited*"}),
    ("Cover letters", {"free": "5 / month", "pro": "Unlimited*", "pro_annual": "Unlimited*"}),
    ("Analyze & Tailor CV (ATS)", {"free": "5 / month", "pro": "Unlimited*", "pro_annual": "Unlimited*"}),
    ("Resume templates", {"free": "Basic only", "pro": "All premium", "pro_annual": "All premium"}),
    ("Export", {"free": "PDF (watermark)", "pro": "PDF + DOCX, no watermark", "pro_annual": "PDF + DOCX, no watermark"}),
    ("Interview prep (270 Qs)", {"free": "Full", "pro": "Full", "pro_annual": "Full"}),
    ("Plagiarism checker", {"free": "Free", "pro": "Free", "pro_annual": "Free"}),
    ("Job browsing / apply", {"free": "Yes", "pro": "Yes", "pro_annual": "Yes"}),
    ("Priority AI model", {"free": "Standard", "pro": "Faster / better", "pro_annual": "Faster / better"}),
]

FOOTNOTE = '“Unlimited” means a high fair-use ceiling (100/mo), enforced silently.'


def list_plans():
    """Plans in display order (Free, Pro, Pro Annual)."""
    return [PLANS[slug] for slug in ("free", "pro", "pro_annual")]


def get(slug):
    """The plan for a slug, or None if it isn't a real plan."""
    return PLANS.get(slug)


def normalize(slug):
    """Any input -> a valid plan slug, falling back to the default (free).

    Used on the register form and the change-plan endpoint so a hand-made
    request can never persist an unknown tier on an account.
    """
    slug = (slug or "").strip().lower()
    return slug if slug in PLANS else DEFAULT_PLAN


def display_name(slug):
    plan = PLANS.get(normalize(slug))
    return plan["name"] if plan else "Free"
