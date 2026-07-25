"""
Board configuration. Project/2 kept this in config.yaml; on Render there is no
writable config file to bootstrap, so the defaults live here and every value
can be overridden with an env var (comma-separated for the list settings).
"""
import os


def _csv(name: str, default: str) -> list[str]:
    raw = os.environ.get(name, default)
    return [part.strip() for part in raw.split(",") if part.strip()]


def _flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def load_config() -> dict:
    return {
        "usajobs": {
            # Needs a free key from https://developer.usajobs.gov/, so it is
            # off unless one is actually present.
            "enabled": _flag("USAJOBS_ENABLED", bool(os.environ.get("USAJOBS_API_KEY"))),
            "api_key": os.environ.get("USAJOBS_API_KEY", ""),
            "user_agent": os.environ.get("USAJOBS_USER_AGENT", ""),
            "keyword": os.environ.get("USAJOBS_KEYWORD", "software engineer"),
        },
        "remoteok": {
            "enabled": _flag("REMOTEOK_ENABLED", True),
        },
        "wwr": {
            "enabled": _flag("WWR_ENABLED", True),
            "category": os.environ.get("WWR_CATEGORY", "remote-programming-jobs"),
        },
        "greenhouse": {
            "enabled": _flag("GREENHOUSE_ENABLED", True),
            "boards": _csv("GREENHOUSE_BOARDS", "stripe,airbnb,figma"),
        },
        "lever": {
            "enabled": _flag("LEVER_ENABLED", True),
            # leverdemo is Lever's own public demo board - it keeps the apply
            # flow testable without sending anything to a real employer.
            "companies": _csv("LEVER_COMPANIES", "leverdemo"),
        },
        "fetch": {
            "request_delay_seconds": float(os.environ.get("FETCH_DELAY_SECONDS", "1.0")),
        },
    }
