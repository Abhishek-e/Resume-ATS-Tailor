"""
Builds the weekly job-alert email from the aggregator's current listings.

Kept separate from sending (mailer.py) and from the admin route so the digest
can be previewed in the admin page with the exact markup that will be mailed.
The job dicts are the ones produced by the jobsources package and cached in
jobstore: title, company, location, url, source, category, score, posted_date.
"""
import html as _html
from datetime import datetime, timezone

DEFAULT_LIMIT = 15


def _fmt_source(source: str) -> str:
    labels = {
        "remoteok": "RemoteOK", "greenhouse": "Greenhouse", "lever": "Lever",
        "weworkremotely": "We Work Remotely", "wwr": "We Work Remotely",
        "usajobs": "USAJOBS",
    }
    return labels.get((source or "").lower(), (source or "").title() or "Job board")


def select_jobs(jobs, limit: int = DEFAULT_LIMIT) -> list:
    """Highest-scored first (score is set when a profile is known, else 0), then
    most recently posted, capped at `limit`."""
    def key(job):
        return (float(job.get("score") or 0), str(job.get("posted_date") or ""))
    return sorted(jobs, key=key, reverse=True)[:limit]


def build_digest(jobs, app_name: str = "Resumify", jobs_url: str = "",
                 limit: int = DEFAULT_LIMIT) -> dict:
    """Return {subject, text, html, count} for the current listings.

    `count` is how many jobs made it into the email (0 when the aggregator is
    empty) so the caller can refuse to send an empty digest.
    """
    picked = select_jobs(jobs, limit)
    today = datetime.now(timezone.utc).strftime("%d %b %Y")
    total = len(jobs)
    subject = f"{app_name}: {len(picked)} new job matches this week"

    # --- plain text -------------------------------------------------------
    text_lines = [
        f"{app_name} — Weekly Job Alert ({today})",
        f"{len(picked)} picks from {total} live listings.",
        "",
    ]
    for i, job in enumerate(picked, 1):
        text_lines.append(f"{i}. {job.get('title', 'Role')} — {job.get('company', '')}")
        meta = " · ".join(filter(None, [
            job.get("location", ""), _fmt_source(job.get("source")),
            job.get("category", ""),
        ]))
        if meta:
            text_lines.append(f"   {meta}")
        if job.get("url"):
            text_lines.append(f"   {job['url']}")
        text_lines.append("")
    if jobs_url:
        text_lines.append(f"Browse all jobs: {jobs_url}")
    text_body = "\n".join(text_lines)

    # --- html -------------------------------------------------------------
    def esc(value):
        return _html.escape(str(value or ""))

    rows = []
    for job in picked:
        meta = " · ".join(filter(None, [
            esc(job.get("location", "")), esc(_fmt_source(job.get("source"))),
            esc(job.get("category", "")),
        ]))
        url = esc(job.get("url", "")) or "#"
        rows.append(f"""
      <tr>
        <td style="padding:14px 16px;border-bottom:1px solid #eceef1;">
          <a href="{url}" style="color:#4263eb;text-decoration:none;font-weight:600;font-size:15px;">
            {esc(job.get('title', 'Role'))}
          </a>
          <div style="color:#495057;font-size:14px;margin-top:2px;">{esc(job.get('company', ''))}</div>
          <div style="color:#868e96;font-size:12px;margin-top:2px;">{meta}</div>
        </td>
      </tr>""")

    browse = ""
    if jobs_url:
        browse = f"""
      <tr><td style="padding:18px 16px;text-align:center;">
        <a href="{esc(jobs_url)}" style="background:#4263eb;color:#fff;text-decoration:none;
           padding:10px 20px;border-radius:6px;font-size:14px;display:inline-block;">
           Browse all {total} jobs</a>
      </td></tr>"""

    html_body = f"""<!DOCTYPE html>
<html><body style="margin:0;background:#f5f7fb;font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f5f7fb;padding:24px 0;">
    <tr><td align="center">
      <table role="presentation" width="600" cellpadding="0" cellspacing="0"
             style="background:#fff;border-radius:10px;overflow:hidden;max-width:600px;width:100%;">
        <tr><td style="padding:22px 16px;background:#1d2433;color:#fff;">
          <div style="font-size:18px;font-weight:700;">{esc(app_name)} — Weekly Job Alert</div>
          <div style="font-size:13px;color:#adb5bd;margin-top:2px;">
            {esc(today)} · {len(picked)} picks from {total} live listings
          </div>
        </td></tr>
        {''.join(rows)}
        {browse}
        <tr><td style="padding:16px;color:#adb5bd;font-size:11px;text-align:center;">
          You are receiving this because you have a {esc(app_name)} account.
        </td></tr>
      </table>
    </td></tr>
  </table>
</body></html>"""

    return {"subject": subject, "text": text_body, "html": html_body, "count": len(picked)}
