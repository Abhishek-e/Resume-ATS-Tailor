"""
Employer subscription tiers for the employer pricing page.

Prices are set ~10% below a market reference (India monthly recruiter / job-
posting plans, e.g. Naukri job packs and LinkedIn Recruiter Lite ~= ₹10k/mo).
The `market` value is shown struck-through so the 10%-lower price is visible.
These are estimates - verify current competitor pricing before quoting. The
paid tiers map to the order products in orgs.PRODUCTS (emp_growth / emp_pro),
both of which grant premium (unlimited jobs + candidate database) on payment.
"""

FREE_JOB_LIMIT = 5

PLANS = [
    {
        "slug": "free",
        "name": "Free",
        "price": "₹0",
        "period": "",
        "market": None,
        "product": None,
        "tagline": "Get started and hire your first few roles.",
        "features": [
            f"{FREE_JOB_LIMIT} active job posts",
            "Shareable careers page",
            "Applicant tracking",
            "1 recruiter seat",
        ],
        "popular": False,
    },
    {
        "slug": "emp_growth",
        "name": "Growth",
        "price": "₹2,699",
        "period": "/ mo",
        "market": "₹2,999",          # ~10% below
        "product": "emp_growth",
        "tagline": "For active hiring — unlimited roles and visibility.",
        "features": [
            "Unlimited job posts",
            "Featured listings on the jobs board",
            "Basic candidate search",
            "Up to 10 recruiter seats",
            "Applicant analytics",
        ],
        "popular": True,
    },
    {
        "slug": "emp_pro",
        "name": "Pro",
        "price": "₹7,199",
        "period": "/ mo",
        "market": "₹7,999",          # ~10% below
        "product": "emp_pro",
        "tagline": "Full recruiting toolkit and candidate database.",
        "features": [
            "Everything in Growth",
            "Full candidate database access",
            "Priority featured placement",
            "Advanced analytics",
            "Priority support",
        ],
        "popular": False,
    },
]


def list_plans():
    return PLANS
