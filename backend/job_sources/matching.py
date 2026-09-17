"""Milestone 8B.2 — deterministic, explainable preference matching.

No ML here: matching is plain, auditable text logic over the already-cached
normalized jobs. The scam-detection model is never involved.
"""

# Approved source values for preferences (canonical ids match job_sources).
APPROVED_SOURCES = ("any", "remoteok", "arbeitnow")

MAX_KEYWORDS = 120
MAX_LOCATION = 120

DEFAULT_PREFERENCES = {
    "keywords": "",
    "location": "",
    "remote_only": False,
    "source": "any",
}


def _job_haystacks(job):
    """Field -> lowercase text map used for keyword matching."""
    tags = job.get("tags") or []
    if isinstance(tags, str):
        tags = [tags]
    return {
        "title": (job.get("title") or "").lower(),
        "company": (job.get("company") or "").lower(),
        "description": (job.get("description") or "").lower(),
        "tags": " ".join(str(t) for t in tags).lower(),
    }


def match_job(job, preferences):
    """Decide whether one normalized job matches saved preferences.

    Deterministic rules, evaluated in a fixed order; every criterion reports
    why it passed or failed, so results are explainable:

    - keywords: EVERY whitespace-separated term must appear (case-insensitive)
      in at least one of title / company / description / tags.
    - location: preference text is a case-insensitive substring of the job's
      location (empty preference never filters).
    - remote_only: when true, the job must be flagged remote.
    - source: 'any' matches everything; otherwise exact provider id.

    Returns {"matched": bool, "reasons": [str, ...]} with one entry per
    criterion, always in the same order.
    """
    prefs = {**DEFAULT_PREFERENCES, **(preferences or {})}

    # --- keywords -----------------------------------------------------------
    reasons = []
    keywords_ok = True
    keywords = (prefs.get("keywords") or "").strip().lower()
    if not keywords:
        reasons.append("keywords: no preference (matches any job)")
    else:
        haystacks = _job_haystacks(job)
        terms = keywords.split()
        missing = [t for t in terms if not any(t in text for text in haystacks.values())]
        if missing:
            keywords_ok = False
            reasons.append(f"keywords: missing {', '.join(missing)}")
        else:
            hit_fields = [f for f, text in haystacks.items()
                          if any(t in text for t in terms)]
            reasons.append(f"keywords: all {len(terms)} term(s) found in {', '.join(hit_fields)}")

    # --- location -----------------------------------------------------------
    wanted_loc = (prefs.get("location") or "").strip().lower()
    job_loc = (job.get("location") or "").lower()
    if not wanted_loc:
        reasons.append("location: no preference (matches any location)")
    elif wanted_loc in job_loc:
        reasons.append(f"location: '{wanted_loc}' found in job location")
    else:
        reasons.append(f"location: '{wanted_loc}' not in job location '{job_loc}'")

    location_ok = (not wanted_loc) or (wanted_loc in job_loc)

    # --- remote only --------------------------------------------------------
    if prefs.get("remote_only"):
        remote_ok_flag = bool(job.get("remote"))
        reasons.append("remote_only: job is remote" if remote_ok_flag
                       else "remote_only: job is not remote")
    else:
        remote_ok_flag = True
        reasons.append("remote_only: not required")

    # --- source -------------------------------------------------------------
    wanted_src = (prefs.get("source") or "any").strip().lower()
    if wanted_src in ("", "any"):
        source_ok = True
        reasons.append("source: any source accepted")
    elif wanted_src == (job.get("source") or ""):
        source_ok = True
        reasons.append(f"source: matches {wanted_src}")
    else:
        source_ok = False
        reasons.append(f"source: wanted {wanted_src}, job is {job.get('source')}")

    matched = keywords_ok and location_ok and remote_ok_flag and source_ok
    return {"matched": matched, "reasons": reasons}


def filter_jobs(jobs, preferences):
    """Return [(job, reasons)] for every job matching the preferences."""
    results = []
    for job in jobs:
        verdict = match_job(job, preferences)
        if verdict["matched"]:
            results.append((job, verdict["reasons"]))
    return results
