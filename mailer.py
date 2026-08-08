"""
Minimal SMTP sender, provider-agnostic.

Reads its configuration from the environment so any provider works without a
code change - Gmail SMTP, SendGrid/Mailgun SMTP, Amazon SES, etc.:

    SMTP_HOST   e.g. smtp.gmail.com          (required)
    SMTP_PORT   default 587
    SMTP_USER   login user                    (optional for open relays)
    SMTP_PASS   login password / app password (kept only in .env)
    SMTP_FROM   From address; defaults to SMTP_USER
    SMTP_TLS    "false" to disable STARTTLS (default on)

Nothing here is called at import time and no credentials are logged. Callers
check is_configured() first and surface a clear message when it is unset.
"""
import os
import smtplib
import ssl
from email.message import EmailMessage


def config() -> dict:
    return {
        "host": (os.environ.get("SMTP_HOST") or "").strip(),
        "port": int(os.environ.get("SMTP_PORT") or 587),
        "user": (os.environ.get("SMTP_USER") or "").strip(),
        "password": os.environ.get("SMTP_PASS") or "",
        "from": (os.environ.get("SMTP_FROM") or os.environ.get("SMTP_USER") or "").strip(),
        "use_tls": (os.environ.get("SMTP_TLS", "true").lower() != "false"),
    }


def is_configured() -> bool:
    cfg = config()
    return bool(cfg["host"] and cfg["from"])


def send(to_addrs, subject: str, text_body: str, html_body: str = None) -> int:
    """
    Send one message to many recipients, placed in Bcc so nobody sees the list.

    Returns the number of recipients. Raises RuntimeError with a readable
    message when SMTP is not configured or there are no recipients, and lets
    smtplib errors propagate for the caller to report.
    """
    cfg = config()
    if not cfg["host"] or not cfg["from"]:
        raise RuntimeError(
            "SMTP is not configured. Set SMTP_HOST and SMTP_FROM (and usually "
            "SMTP_USER / SMTP_PASS) in .env."
        )

    recipients = sorted({(a or "").strip() for a in to_addrs if (a or "").strip()})
    if not recipients:
        raise RuntimeError("No recipients to send to.")

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = cfg["from"]
    # Everyone goes in Bcc; To is just the sender so the header is well-formed
    # and recipient addresses are not disclosed to one another.
    msg["To"] = cfg["from"]
    msg["Bcc"] = ", ".join(recipients)
    msg.set_content(text_body)
    if html_body:
        msg.add_alternative(html_body, subtype="html")

    with smtplib.SMTP(cfg["host"], cfg["port"], timeout=30) as server:
        if cfg["use_tls"]:
            server.starttls(context=ssl.create_default_context())
        if cfg["user"]:
            server.login(cfg["user"], cfg["password"])
        server.send_message(msg)

    return len(recipients)
