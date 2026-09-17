"""Upwork provider (8E.3) — official GraphQL API only, never HTML scraping.

Endpoint: https://api.upwork.com/graphql (Upwork's current GraphQL gateway),
query `marketplaceJobPostingsSearch` — the current marketplace job-search
query available to approved developer keys with the official
marketplace job-posting read scope (jobs:read). Deprecated SOAP/legacy
endpoints are NOT used.

Credentials/tokens are read ONLY from environment variables
(UPWORK_ACCESS_TOKEN, UPWORK_REFRESH_TOKEN, UPWORK_CLIENT_ID,
UPWORK_CLIENT_SECRET) — never hard-coded, never committed, never sent to
React, never returned by /api/jobs, never logged. All exceptions raised here
are sanitized to the failure class only (tokens/URLs/query bodies never
appear in messages). The OAuth tokens belong to this provider integration,
not to JobGuard user accounts — no user-facing OAuth flow exists.

HTTP 429 is handled gracefully: the refresh is skipped this round, isolated
as a provider failure, and cached Upwork rows remain served. Cached data is
bounded by the per-provider freshness window (60 minutes, far below Upwork's
24-hour cache ceiling).
"""

import os

import requests

from .normalize import clean_str, clean_tags, now_iso, strip_html, to_iso_timestamp

SOURCE_NAME = "upwork"
GRAPHQL_URL = "https://api.upwork.com/graphql"
TOKEN_URL = "https://www.upwork.com/ab/account-security/oauth2/token"
TIMEOUT = (5, 20)  # (connect, read) seconds
RESULTS_PER_PAGE = 50

HEADERS = {"User-Agent": "JobGuard-FYP/1.0 (educational job-scam screening)",
           "Content-Type": "application/json", "Accept": "application/json"}

# Current marketplace job-postings search. Fields are read defensively —
# anything the approved key does not return simply stays None.
QUERY = """
query publicMarketplaceJobPostingsSearch($first: Int!) {
  marketplaceJobPostingsSearch(
    marketPlaceJobPostingsSearchType: JOB_SEARCH,
    first: $first
  ) {
    totalCount
    edges {
      node {
        id
        title
        description
        createdDateTime
        category
        subcategory
        skills
        experienceLevel
        contractType
        hourlyBudgetInfo { min }
        fixedPriceBudgetInfo { amount }
        client { location { country } }
        workLocationInfo
      }
    }
  }
}
"""


class UpworkError(Exception):
    """Sanitized provider failure — safe to surface, embeds no secrets."""

    def __init__(self, message):
        super().__init__(message)
        self.rate_limited = "429" in message


def _env(name):
    return (os.environ.get(name) or "").strip()


def _credentials():
    return {
        "access_token": _env("UPWORK_ACCESS_TOKEN"),
        "refresh_token": _env("UPWORK_REFRESH_TOKEN"),
        "client_id": _env("UPWORK_CLIENT_ID"),
        "client_secret": _env("UPWORK_CLIENT_SECRET"),
    }


def is_configured():
    """True only when an access token exists in the environment."""
    return bool(_credentials()["access_token"])


def _humanize(value):
    text = clean_str(value, limit=40)
    return " ".join(w.capitalize() for w in text.replace("_", " ").split()) if text else None


# In-memory refreshed token (never persisted, never logged, dies with the
# process; the environment remains the source of truth on restart).
_access_token_cache = {"token": None}


def _refresh_access_token():
    """Backend-side OAuth2 refresh — only when a refresh token is configured.

    Returns the new access token or None. Any failure is swallowed into a
    sanitized refresh failure (the caller surfaces the class, never details).
    """
    creds = _credentials()
    if not (creds["refresh_token"] and creds["client_id"] and creds["client_secret"]):
        return None
    try:
        resp = requests.post(
            TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": creds["refresh_token"],
                "client_id": creds["client_id"],
                "client_secret": creds["client_secret"],
            },
            headers={"User-Agent": HEADERS["User-Agent"], "Accept": "application/json"},
            timeout=TIMEOUT,
        )
        if resp.status_code != 200:
            return None
        payload = resp.json()
        token = payload.get("access_token")
        if token:
            _access_token_cache["token"] = token
            return token
        return None
    except Exception:
        return None


def _bearer():
    """Current access token: refreshed in-memory value first, then env."""
    return _access_token_cache["token"] or _credentials()["access_token"]


def _format_salary(node):
    """From Upwork's own budget fields only (amounts are USD per the API)."""
    hourly = node.get("hourlyBudgetInfo") or {}
    fixed = node.get("fixedPriceBudgetInfo") or {}
    lo, hi = hourly.get("min"), hourly.get("max")
    try:
        if lo is not None or hi is not None:
            lo_f = float(lo) if lo is not None else None
            hi_f = float(hi) if hi is not None else None
            lo_f = lo_f if lo_f and lo_f > 0 else None
            hi_f = hi_f if hi_f and hi_f > 0 else None
            if lo_f or hi_f:
                def fmt(v):
                    return f"${v:.0f}/hr"
                if lo_f and hi_f:
                    return f"{fmt(lo_f)} – {fmt(hi_f)}"
                return fmt(lo_f or hi_f)
    except (TypeError, ValueError):
        pass
    try:
        amount = fixed.get("amount")
        if amount is not None and float(amount) > 0:
            v = float(amount)
            return f"${v:.0f} fixed-price"
    except (TypeError, ValueError):
        pass
    return None


def normalize(node, fetched_at=None):
    """One Upwork search node -> internal normalized job shape."""
    if not isinstance(node, dict):
        return None
    title = clean_str(node.get("title"), limit=200)
    if not title:
        return None

    raw_id = node.get("id")
    source_job_id = clean_str(raw_id if isinstance(raw_id, (str, int)) else None, limit=200)
    if not source_job_id:
        return None

    # Official public job URL format for a posting id (per Upwork's documented
    # URL behavior). redirect/apply URLs from the payload would win if present.
    job_url = clean_str(node.get("applyUrl") or node.get("url"), limit=500)
    if not job_url:
        job_url = f"https://www.upwork.com/jobs/{source_job_id}"

    # Public marketplace info only: client COUNTRY is public; client identity
    # (company name, history, ratings) is deliberately never mapped here.
    client = node.get("client") if isinstance(node.get("client"), dict) else {}
    client_loc = client.get("location") if isinstance(client.get("location"), dict) else {}
    location = clean_str(client_loc.get("country")) or None

    skills = node.get("skills")
    if isinstance(skills, list):
        skill_labels = [s.get("label") or s.get("name") if isinstance(s, dict) else s
                        for s in skills]
    else:
        skill_labels = []
    tag_values = list(skill_labels)
    for extra in (node.get("category"), node.get("subcategory")):
        if clean_str(extra, limit=60):
            tag_values.append(extra)
    tags = clean_tags(tag_values)

    parts = [_humanize(node.get("contractType")), _humanize(node.get("experienceLevel"))]
    job_type = " · ".join(p for p in parts if p) or None

    # Remote/on-site info only when the API actually returns it.
    remote = False
    for key in ("remoteJob",):
        if isinstance(node.get(key), bool):
            remote = node[key]
            break
    wli = node.get("workLocationInfo")
    if isinstance(wli, str) and wli.strip():
        remote = "remote" in wli.lower() or not wli.strip().lower() in ("on-site", "onsite", "hybrid") \
            if "remote" in wli.lower() else remote

    return {
        "source": SOURCE_NAME,
        "source_job_id": source_job_id,
        "title": title,
        "company": None,  # client identity is private — never exposed
        "location": location,
        "description": strip_html(node.get("description")),
        "job_type": job_type,
        "remote": remote,
        "tags": tags,
        "salary": _format_salary(node),
        "job_url": job_url,
        "published_at": to_iso_timestamp(node.get("createdDateTime")
                                         or node.get("publishedDateTime")),
        "fetched_at": fetched_at or now_iso(),
    }


def _extract_nodes(payload):
    """Defensive extraction across the documented response variants."""
    data = payload.get("data") if isinstance(payload, dict) else None
    search = data.get("marketplaceJobPostingsSearch") if isinstance(data, dict) else None
    if not isinstance(search, dict):
        return None
    nodes = search.get("nodes")
    if isinstance(nodes, list):
        return nodes
    edges = search.get("edges")
    if isinstance(edges, list):
        return [edge.get("node") for edge in edges if isinstance(edge, dict)]
    return []


def fetch_jobs():
    """Fetch + normalize one Upwork search page via the official GraphQL API."""
    creds = _credentials()
    if not creds["access_token"]:
        raise UpworkError("Upwork credentials are not configured")

    result = _graphql_search(creds["access_token"])
    if result["status"] in (401, 403):
        # one backend-side refresh + retry (only when a refresh token exists)
        token = _refresh_access_token()
        if token:
            result = _graphql_search(token)
    if result["status"] == 429:
        raise UpworkError("Upwork request failed (429)")  # graceful: cache serves
    if result["status"] in (401, 403):
        raise UpworkError(f"Upwork request failed ({result['status']})")
    if result["status"] != 200:
        raise UpworkError(f"Upwork request failed ({result['status']})")

    payload = result["payload"]
    if isinstance(payload, dict) and payload.get("errors"):
        raise UpworkError("Upwork: query errors in response")
    nodes = _extract_nodes(payload)
    if nodes is None:
        raise UpworkError("Upwork: unexpected payload shape")

    fetched_at = now_iso()
    jobs = []
    for node in nodes:
        try:
            job = normalize(node, fetched_at=fetched_at)
        except Exception:
            job = None  # one malformed row must not break the whole board
        if job:
            jobs.append(job)
    return jobs


def _graphql_search(token):
    """One POST to the GraphQL gateway. Returns {status, payload} — status
    handling (refresh/429/isolation) belongs to fetch_jobs. Network/JSON
    failures raise sanitized errors."""
    try:
        resp = requests.post(
            GRAPHQL_URL,
            json={"query": QUERY, "variables": {"first": RESULTS_PER_PAGE}},
            headers={**HEADERS, "Authorization": f"Bearer {token}"},
            timeout=TIMEOUT,
        )
        if resp.status_code == 200:
            try:
                return {"status": 200, "payload": resp.json()}
            except ValueError:
                raise UpworkError("Upwork: response was not JSON") from None
        return {"status": resp.status_code, "payload": None}
    except UpworkError:
        raise
    except requests.RequestException as exc:
        raise UpworkError(f"Upwork request failed ({exc.__class__.__name__})") from None
