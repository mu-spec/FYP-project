"""
Job discovery service (8B.1) — DB-backed cache, resiliency, queries.

Strategy
--------
- External APIs are NEVER called per frontend render: a DB-backed cache in
  the `external_jobs` table is refreshed only when older than FRESHNESS.
- Each provider is refreshed independently: if one fails, the other still
  populates/updates and cached rows of the failed provider remain served.
- If both providers fail but cached rows exist, those rows are returned with
  `cache.stale = true` so the UI can label them.
- All queries are deterministic (ORDER BY published_at DESC, id DESC).
"""

import sqlite3
import threading
from datetime import datetime, timedelta, timezone

from . import arbeitnow, remote_ok
from .normalize import now_iso, strip_html

PAGE_SIZE = 20
FRESHNESS = timedelta(minutes=20)     # refresh window (8B.1: 15–30 min)
PRUNE_AFTER = timedelta(days=3)       # keep the cache bounded

PROVIDERS = {"remoteok": remote_ok, "arbeitnow": arbeitnow}
VALID_SOURCES = set(PROVIDERS)

_lock = threading.Lock()
_last_refresh = {"at": None, "ok": {name: None for name in PROVIDERS}}


def _upsert_jobs(db, jobs):
    """Insert new jobs / refresh existing ones on UNIQUE(source, source_job_id).

    Returns the rows that were genuinely NEW to the cache (with their internal
    id attached) so the alert layer can notify only about newly imported jobs.
    """
    import json as _json
    db.row_factory = sqlite3.Row  # the SELECT below accesses columns by name
    existing = {
        (row["source"], row["source_job_id"]): row["id"]
        for row in db.execute("SELECT id, source, source_job_id FROM external_jobs")
    }
    rows = []
    for job in jobs:
        row = dict(job)
        row["tags_json"] = _json.dumps(row.pop("tags", []), ensure_ascii=False)
        rows.append(row)
    db.executemany(
        """
        INSERT INTO external_jobs (
            source, source_job_id, title, company, location, description,
            job_type, remote, tags_json, salary, job_url, published_at, fetched_at
        ) VALUES (:source, :source_job_id, :title, :company, :location,
                  :description, :job_type, :remote, :tags_json, :salary,
                  :job_url, :published_at, :fetched_at)
        ON CONFLICT(source, source_job_id) DO UPDATE SET
            title=excluded.title,
            company=excluded.company,
            location=excluded.location,
            description=excluded.description,
            job_type=excluded.job_type,
            remote=excluded.remote,
            tags_json=excluded.tags_json,
            salary=excluded.salary,
            job_url=excluded.job_url,
            published_at=excluded.published_at,
            fetched_at=excluded.fetched_at
        """,
        rows,
    )
    new_jobs = []
    for job in jobs:
        key = (job["source"], job["source_job_id"])
        if key not in existing:
            row_id = db.execute(
                "SELECT id FROM external_jobs WHERE source = ? AND source_job_id = ?",
                key,
            ).fetchone()
            fresh = dict(job)
            fresh["id"] = row_id["id"]
            new_jobs.append(fresh)
    return new_jobs


def _parse_ts(text):
    try:
        return datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return None


def refresh_if_stale(db_path):
    """Refresh provider data when the cache is older than FRESHNESS.

    Returns the cache-status dict used in the /api/jobs response. Provider
    failures are isolated: recorded, never raised.
    """
    with _lock:
        with sqlite3.connect(db_path) as db:
            db.row_factory = sqlite3.Row
            newest = db.execute("SELECT MAX(fetched_at) AS t FROM external_jobs").fetchone()["t"]
        newest_dt = _parse_ts(newest)
        cache_fresh = newest_dt is not None and \
            datetime.now(timezone.utc) - newest_dt.astimezone(timezone.utc) < FRESHNESS

        newly_imported = []
        if not cache_fresh:
            for name, provider in PROVIDERS.items():
                try:
                    jobs = provider.fetch_jobs()
                    with sqlite3.connect(db_path) as db:
                        newly_imported.extend(_upsert_jobs(db, jobs))
                        cutoff = (datetime.now(timezone.utc) - PRUNE_AFTER).isoformat()
                        db.execute("DELETE FROM external_jobs WHERE fetched_at < ?", (cutoff,))
                        db.commit()
                    _last_refresh["ok"][name] = True
                except Exception:
                    _last_refresh["ok"][name] = False  # keep previous rows
            _last_refresh["at"] = now_iso()

            # Milestone 8B.2 — after a successful (partial counts too) import,
            # notify users whose saved preferences match the NEW jobs. Lazy
            # import avoids a circular dependency; a failure here must never
            # break job serving.
            if any(_last_refresh["ok"].values()) and newly_imported:
                try:
                    import job_sources.alerts as alerts  # noqa: circular-safe
                    alerts.ensure_tables(db_path)
                    alerts.generate_for_jobs(db_path, newly_imported)
                except Exception:
                    pass

        with sqlite3.connect(db_path) as db:
            db.row_factory = sqlite3.Row
            per_source = {
                row["source"]: {"jobs": row["n"], "last_fetched_at": row["t"]}
                for row in db.execute(
                    "SELECT source, COUNT(*) AS n, MAX(fetched_at) AS t "
                    "FROM external_jobs GROUP BY source"
                )
            }

    ok = dict(_last_refresh["ok"])
    any_ok = any(ok.get(name) for name in PROVIDERS)
    has_data = bool(per_source)
    return {
        "fresh": cache_fresh or any(ok.get(name) for name in PROVIDERS),
        "stale": (not any_ok) and has_data,   # both failed, cached rows served
        "last_refresh_at": _last_refresh["at"],
        "sources": list(PROVIDERS),           # canonical source ids, in refresh order
        "providers": {name: {"ok": ok.get(name), **per_source.get(name, {"jobs": 0, "last_fetched_at": None})}
                      for name in PROVIDERS},
    }


def get_jobs(db_path, q=None, location=None, source=None, remote=False, page=1,
             limit=None):
    """Deterministic, filtered, paginated job list for GET /api/jobs.

    `limit` (Milestone 8C.3B) overrides the page size for a single call —
    used by the merged public feed to fetch all matching external rows before
    combining them with published JobGuard jobs. Default keeps 8B.1 behavior.
    """
    cache = refresh_if_stale(db_path)

    where, params = [], []
    if q:
        like = f"%{q}%"
        where.append("(title LIKE ? OR company LIKE ? OR description LIKE ? OR tags_json LIKE ?)")
        params += [like, like, like, like]
    if location:
        where.append("location LIKE ?")
        params.append(f"%{location}%")
    if source in VALID_SOURCES:
        where.append("source = ?")
        params.append(source)
    if remote:
        where.append("remote = 1")
    clause = f"WHERE {' AND '.join(where)}" if where else ""

    with sqlite3.connect(db_path) as db:
        db.row_factory = sqlite3.Row
        total = db.execute(f"SELECT COUNT(*) AS n FROM external_jobs {clause}", params).fetchone()["n"]
        offset = (max(1, page) - 1) * PAGE_SIZE
        rows = db.execute(
            f"""SELECT id, source, source_job_id, title, company, location, description,
                       job_type, remote, tags_json, salary, job_url, published_at, fetched_at
                FROM external_jobs {clause}
                ORDER BY published_at DESC, id DESC
                LIMIT ? OFFSET ?""",
            params + [limit or PAGE_SIZE, offset],
        ).fetchall()

    jobs = []
    for row in rows:
        item = dict(row)
        try:
            import json as _json
            item["tags"] = _json.loads(item.pop("tags_json") or "[]")
        except ValueError:
            item["tags"] = []
        item["remote"] = bool(item["remote"])
        jobs.append(item)

    safe_page = max(1, page)
    return {
        "jobs": jobs,
        "total": total,
        "page": safe_page,
        "page_size": PAGE_SIZE,
        "pages": max(1, -(-total // PAGE_SIZE)),
        "cache": cache,
    }
