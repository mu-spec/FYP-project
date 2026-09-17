"""Remote OK provider (8B.1) — official public API, no HTML scraping.

https://remoteok.com/api returns a JSON array whose FIRST element is a
legal/terms notice (not a job) and whose remaining elements are jobs.
Their terms require linking back to the original Remote OK URL and naming
Remote OK as the source — both are enforced by this integration (source
badge + job_url on every card).
"""

import requests

from .normalize import clean_str, clean_tags, now_iso, strip_html, to_iso_timestamp

SOURCE_NAME = "remoteok"
API_URL = "https://remoteok.com/api"
# RemoteOK rejects default library user agents; send an honest project UA.
HEADERS = {
    "User-Agent": "JobGuard-FYP/1.0 (educational job-scam screening; links back to Remote OK)",
    "Accept": "application/json",
}
TIMEOUT = (5, 15)  # (connect, read) seconds


def is_configured():
    """remote_ok needs no credentials — always available."""
    return True


def normalize(element, fetched_at=None):
    """One RemoteOK payload element -> internal normalized job shape."""
    if not isinstance(element, dict):
        return None
    title = clean_str(element.get("position") or element.get("title"), limit=200)
    if not title:
        return None  # not a job element (legal notice) or unusable row

    source_job_id = clean_str(element.get("slug") or element.get("id"), limit=200)
    if not source_job_id:
        return None

    salary_min, salary_max = element.get("salary_min"), element.get("salary_max")
    salary = None
    try:
        lo, hi = float(salary_min), float(salary_max)
        if lo > 0 or hi > 0:
            def fmt(v):
                return f"${v/1000:.0f}k" if v and v >= 1000 else f"${v:.0f}"
            salary = f"{fmt(lo)} – {fmt(hi)}" if lo > 0 and hi > 0 else fmt(max(lo, hi))
    except (TypeError, ValueError):
        salary = None

    job_url = clean_str(element.get("url") or element.get("apply_url"), limit=500)

    return {
        "source": SOURCE_NAME,
        "source_job_id": source_job_id,
        "title": title,
        "company": clean_str(element.get("company"), limit=200),
        "location": clean_str(element.get("location")) or None,
        "description": strip_html(element.get("description")),
        "job_type": clean_str(element.get("job_type"), limit=100),
        "remote": True,  # every Remote OK listing is a remote position
        "tags": clean_tags(element.get("tags")),
        "salary": salary,
        "job_url": job_url,
        "published_at": to_iso_timestamp(element.get("date")),
        "fetched_at": fetched_at or now_iso(),
    }


def fetch_jobs():
    """Fetch + normalize the current Remote OK board. Raises on network errors."""
    resp = requests.get(API_URL, headers=HEADERS, timeout=TIMEOUT)
    resp.raise_for_status()
    payload = resp.json()
    if not isinstance(payload, list):
        raise ValueError("RemoteOK: unexpected payload shape")
    fetched_at = now_iso()
    jobs = []
    for element in payload:
        try:
            job = normalize(element, fetched_at=fetched_at)
        except Exception:
            job = None  # one malformed row must not break the whole board
        if job:
            jobs.append(job)
    return jobs
