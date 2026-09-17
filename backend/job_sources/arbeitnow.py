"""Arbeitnow provider (8B.1) — public job-board API, no key, no scraping.

https://www.arbeitnow.com/api/job-board-api returns {"data": [...]} with
slug-keyed job objects (HTML descriptions, unix `created_at`).
"""

import requests

from .normalize import clean_str, clean_tags, now_iso, strip_html, to_iso_timestamp

SOURCE_NAME = "arbeitnow"
API_URL = "https://www.arbeitnow.com/api/job-board-api"
HEADERS = {"User-Agent": "JobGuard-FYP/1.0 (educational job-scam screening)", "Accept": "application/json"}
TIMEOUT = (5, 15)  # (connect, read) seconds


def normalize(element, fetched_at=None):
    """One Arbeitnow payload element -> internal normalized job shape."""
    if not isinstance(element, dict):
        return None
    title = clean_str(element.get("title"), limit=200)
    slug = clean_str(element.get("slug"), limit=200)
    if not title or not slug:
        return None

    job_types = element.get("job_types")
    job_type = " · ".join(t for t in (clean_str(x, limit=40) for x in job_types) if t) \
        if isinstance(job_types, list) else None

    job_url = clean_str(element.get("url"), limit=500)

    return {
        "source": SOURCE_NAME,
        "source_job_id": slug,
        "title": title,
        "company": clean_str(element.get("company_name"), limit=200),
        "location": clean_str(element.get("location")) or None,
        "description": strip_html(element.get("description")),
        "job_type": job_type,
        "remote": bool(element.get("remote")),
        "tags": clean_tags(element.get("tags")),
        "salary": None,  # Arbeitnow publishes no salary field — never invent one
        "job_url": job_url,
        "published_at": to_iso_timestamp(element.get("created_at")),
        "fetched_at": fetched_at or now_iso(),
    }


def fetch_jobs():
    """Fetch + normalize the first (newest) Arbeitnow board page."""
    resp = requests.get(API_URL, headers=HEADERS, timeout=TIMEOUT)
    resp.raise_for_status()
    payload = resp.json()
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        raise ValueError("Arbeitnow: unexpected payload shape")
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
