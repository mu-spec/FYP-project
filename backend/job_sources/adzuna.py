"""Adzuna provider (8E.2) — official API, backend-only, credentials via env.

https://api.adzuna.com/v1/api/jobs/{country}/search/{page} requires
ADZUNA_APP_ID + ADZUNA_APP_KEY (read ONLY from environment variables —
never hard-coded, never committed, never sent to React, never returned by
an API response, never logged). ADZUNA_COUNTRY selects the Adzuna country
site (their jobs index is per-country); default "gb" per Adzuna's own docs.

Without credentials the provider reports itself unconfigured: the service
skips it entirely and every other provider keeps working — users simply see
jobs from the remaining sources, with no internal error surfaced.

All exceptions raised here are sanitized: they carry the failure class only,
never the request URL (which would embed the credentials).
"""

import os

import requests

from .normalize import clean_str, clean_tags, now_iso, strip_html, to_iso_timestamp

SOURCE_NAME = "adzuna"
API_BASE = "https://api.adzuna.com/v1/api"
DEFAULT_COUNTRY = "gb"          # Adzuna docs' example country; override via ADZUNA_COUNTRY
RESULTS_PER_PAGE = 50
HEADERS = {"User-Agent": "JobGuard-FYP/1.0 (educational job-scam screening)", "Accept": "application/json"}
TIMEOUT = (5, 15)               # (connect, read) seconds


class AdzunaError(Exception):
    """Sanitized provider failure — safe to surface, embeds no credentials."""


def _credentials():
    app_id = (os.environ.get("ADZUNA_APP_ID") or "").strip()
    app_key = (os.environ.get("ADZUNA_APP_KEY") or "").strip()
    return app_id, app_key


def country():
    """Configured Adzuna country site (backend-side configuration only)."""
    return (os.environ.get("ADZUNA_COUNTRY") or DEFAULT_COUNTRY).strip().lower() or DEFAULT_COUNTRY


def is_configured():
    """True only when both credentials are present in the environment."""
    app_id, app_key = _credentials()
    return bool(app_id and app_key)


def _humanize(value):
    """'full_time' -> 'Full Time' (display formatting, not invention)."""
    text = clean_str(value, limit=40)
    return " ".join(w.capitalize() for w in text.split("_")) if text else None


def _format_salary(element):
    """Salary from the provider's own numbers; Adzuna gives no currency in
    search results, so none is invented — plain formatted numbers."""
    raw_min, raw_max = element.get("salary_min"), element.get("salary_max")
    if raw_min is None and raw_max is None:
        return None
    try:
        lo = float(raw_min) if raw_min is not None else None
        hi = float(raw_max) if raw_max is not None else None
    except (TypeError, ValueError):
        return None
    lo = lo if lo and lo > 0 else None
    hi = hi if hi and hi > 0 else None
    if not lo and not hi:
        return None

    def fmt(v):
        return f"{v/1000:.0f}k" if v >= 1000 else f"{v:.0f}"

    if lo and hi:
        return f"{fmt(lo)} – {fmt(hi)}"
    return fmt(lo or hi)


def normalize(element, fetched_at=None):
    """One Adzuna result -> internal normalized job shape."""
    if not isinstance(element, dict):
        return None
    title = clean_str(element.get("title"), limit=200)
    if not title:
        return None

    raw_id = element.get("id")
    source_job_id = clean_str(raw_id if isinstance(raw_id, (str, int)) else None, limit=200)
    if not source_job_id:
        return None

    company = element.get("company") if isinstance(element.get("company"), dict) else {}
    location = element.get("location") if isinstance(element.get("location"), dict) else {}
    category = element.get("category") if isinstance(element.get("category"), dict) else {}

    contract_parts = [
        _humanize(element.get("contract_type")),
        _humanize(element.get("contract_time")),
    ]
    job_type = " · ".join(p for p in contract_parts if p) or None

    # Adzuna exposes no reliable per-job remote flag — unknown stays False
    # (never invented); the Remote filter therefore simply doesn't match
    # Adzuna rows unless a future Adzuna field provides one.
    tags = clean_tags([category.get("label")] if category.get("label") else None)

    return {
        "source": SOURCE_NAME,
        "source_job_id": source_job_id,
        "title": title,
        "company": clean_str(company.get("display_name"), limit=200),
        "location": clean_str(location.get("display_name")) or None,
        "description": strip_html(element.get("description")),
        "job_type": job_type,
        "remote": False,
        "tags": tags,
        "salary": _format_salary(element),
        "job_url": clean_str(element.get("redirect_url"), limit=500),
        "published_at": to_iso_timestamp(element.get("created")),
        "fetched_at": fetched_at or now_iso(),
    }


def fetch_jobs():
    """Fetch + normalize the newest Adzuna board page for the configured country."""
    app_id, app_key = _credentials()
    if not (app_id and app_key):
        raise AdzunaError("Adzuna credentials are not configured")
    url = f"{API_BASE}/jobs/{country()}/search/1"
    try:
        resp = requests.get(
            url,
            params={
                "app_id": app_id,
                "app_key": app_key,
                "results_per_page": RESULTS_PER_PAGE,
                "content-type": "application/json",
            },
            headers=HEADERS,
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        payload = resp.json()
    except requests.RequestException as exc:
        # sanitized: class only — the underlying message would embed the
        # credential-bearing URL
        raise AdzunaError(f"Adzuna request failed ({exc.__class__.__name__})") from None
    except ValueError:
        raise AdzunaError("Adzuna: response was not JSON") from None

    results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(results, list):
        raise AdzunaError("Adzuna: unexpected payload shape")
    fetched_at = now_iso()
    jobs = []
    for element in results:
        try:
            job = normalize(element, fetched_at=fetched_at)
        except Exception:
            job = None  # one malformed row must not break the whole board
        if job:
            jobs.append(job)
    return jobs
