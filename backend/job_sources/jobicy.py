"""Jobicy provider (8E.1) — official public API, no key, no HTML scraping.

https://jobicy.com/api/v2/remote-jobs returns {"jobs": [...]} with HTML
descriptions and ISO `pubDate` stamps. Per Jobicy's guidance the feed is
polled at most once per hour (see PROVIDER_FRESHNESS in service.py). Their
terms ask that Jobicy is credited as the source and that application buttons
redirect to the ORIGINAL job URL from the feed — both are preserved here
(source badge + job_url on every card; the URL is never rewritten).
"""

import requests

from .normalize import clean_str, clean_tags, now_iso, strip_html, to_iso_timestamp

SOURCE_NAME = "jobicy"
API_URL = "https://jobicy.com/api/v2/remote-jobs"
HEADERS = {
    "User-Agent": "JobGuard-FYP/1.0 (educational job-scam screening; links back to Jobicy)",
    "Accept": "application/json",
}
TIMEOUT = (5, 15)  # (connect, read) seconds


def _format_salary(element):
    """Human salary string from the provider's own numbers — never invented.

    Jobicy gives salaryMin/salaryMax/salaryCurrency/salaryPeriod (or none of
    them). Missing/invalid numbers -> None; missing currency -> plain numbers.
    """
    raw_min, raw_max = element.get("salaryMin"), element.get("salaryMax")
    try:
        lo, hi = float(raw_min), float(raw_max)
    except (TypeError, ValueError):
        if raw_min is None and raw_max is None:
            return None
        try:
            single = float(raw_min if raw_min is not None else raw_max)
        except (TypeError, ValueError):
            return None
        lo = hi = single
    if lo <= 0 and hi <= 0:
        return None

    currency = clean_str(element.get("salaryCurrency"), limit=6) or ""
    # Common codes shown as symbols for readable cards; anything else keeps
    # its code prefix. Formatting only — values are the provider's own.
    symbol = {"USD": "$", "EUR": "€", "GBP": "£", "CAD": "C$", "AUD": "A$"}.get(
        currency.upper(), currency
    )
    period = clean_str(element.get("salaryPeriod"), limit=20)

    def fmt(v):
        return f"{symbol}{v/1000:.0f}k" if v >= 1000 else f"{symbol}{v:.0f}"

    if lo > 0 and hi > 0 and lo != hi:
        salary = f"{fmt(lo)} – {fmt(hi)}"
    else:
        salary = fmt(max(lo, hi))
    if period and period.lower() not in ("yearly", "annual"):
        salary = f"{salary} ({period})"
    return salary


def normalize(element, fetched_at=None):
    """One Jobicy payload element -> internal normalized job shape."""
    if not isinstance(element, dict):
        return None
    title = clean_str(element.get("jobTitle"), limit=200)
    if not title:
        return None

    raw_id = element.get("id")
    source_job_id = clean_str(raw_id if isinstance(raw_id, (str, int)) else None, limit=200)
    if not source_job_id:
        return None

    job_types = element.get("jobType")
    job_type = " · ".join(t for t in (clean_str(x, limit=40) for x in job_types) if t) \
        if isinstance(job_types, list) else clean_str(job_types, limit=100)

    # Jobicy descriptions are HTML — strip to safe plain text (never re-emit
    # markup into React). jobExcerpt is the provider's own plain-text teaser,
    # used only when the full description is missing.
    description = strip_html(element.get("jobDescription"))
    if not description:
        description = strip_html(element.get("jobExcerpt"))

    return {
        "source": SOURCE_NAME,
        "source_job_id": source_job_id,
        "title": title,
        "company": clean_str(element.get("companyName"), limit=200),
        "location": clean_str(element.get("jobGeo")) or None,
        "description": description,
        "job_type": job_type or None,
        "remote": True,  # every listing on the remote-jobs endpoint is remote
        "tags": clean_tags(element.get("tags") or element.get("jobIndustry")),
        "salary": _format_salary(element),
        "job_url": clean_str(element.get("url"), limit=500),
        "published_at": to_iso_timestamp(element.get("pubDate")),
        "fetched_at": fetched_at or now_iso(),
    }


def fetch_jobs():
    """Fetch + normalize the newest Jobicy remote board page."""
    resp = requests.get(API_URL, headers=HEADERS, params={"count": 50}, timeout=TIMEOUT)
    resp.raise_for_status()
    payload = resp.json()
    data = payload.get("jobs") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        raise ValueError("Jobicy: unexpected payload shape")
    fetched_at = now_iso()
    jobs = []
    for element in data:
        try:
            job = normalize(element, fetched_at=fetched_at)
        except Exception:
            job = None  # one malformed row must not break the whole board
        if job:
            jobs.append(job)
    return jobs
