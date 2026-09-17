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

from . import adzuna, arbeitnow, jobicy, remote_ok, upwork
from .classify import (VALID_CATEGORIES, VALID_JOB_TYPES, VALID_WORK_MODES,
                       classify_fields, enrich_job)
from .normalize import now_iso, strip_html

PAGE_SIZE = 20
FRESHNESS = timedelta(minutes=20)     # refresh window (8B.1: 15–30 min)
PRUNE_AFTER = timedelta(days=3)       # keep the cache bounded

# Milestone 8E.1 — per-provider refresh windows. Jobicy asks that their feed
# not be polled more frequently than once per hour, so their window is 60
# minutes while Remote OK / Arbeitnow keep the existing 20-minute behavior.
PROVIDER_FRESHNESS = {
    "remoteok": FRESHNESS,
    "arbeitnow": FRESHNESS,
    "jobicy": timedelta(minutes=60),
    # 30 min sits comfortably inside Adzuna's free daily call quota
    "adzuna": FRESHNESS,
    # Upwork: conservative 60-min window (their 24h cache ceiling is never
    # approached; 429s fall back to the cached rows)
    "upwork": timedelta(minutes=60),
}

PROVIDERS = {"remoteok": remote_ok, "arbeitnow": arbeitnow, "jobicy": jobicy,
             "adzuna": adzuna, "upwork": upwork}
VALID_SOURCES = set(PROVIDERS)

_lock = threading.Lock()
_last_refresh = {"at": None, "ok": {name: None for name in PROVIDERS}}


def ensure_classification_columns(db_path):
    """Milestone 8E.4 — unified filter columns on the cached feed.

    Idempotent in-place migration: adds `category`, `work_mode` and
    `normalized_job_type` to `external_jobs` when missing (databases created
    before 8E.4), then backfills rows that have no category yet. Nothing is
    ever deleted: existing rows keep every value; the deterministic
    classifier fills the new fields from the already-stored job text.
    """
    import json as _json
    with sqlite3.connect(db_path) as db:
        cols = {row[1] for row in db.execute("PRAGMA table_info(external_jobs)")}
        for col in ("category", "work_mode", "normalized_job_type"):
            if col not in cols:
                db.execute(f"ALTER TABLE external_jobs ADD COLUMN {col} TEXT")
        pending = db.execute(
            "SELECT id, source, title, description, job_type, remote, tags_json"
            " FROM external_jobs WHERE category IS NULL"
        ).fetchall()
        for row in pending:
            try:
                tags = _json.loads(row[6] or "[]")
            except ValueError:
                tags = []
            category, work_mode, job_type_norm = classify_fields(
                title=row[2], tags=tags, description=row[3],
                job_type=row[4], remote=bool(row[5]), source=row[1],
            )
            db.execute(
                "UPDATE external_jobs SET category = ?, work_mode = ?,"
                " normalized_job_type = ? WHERE id = ?",
                (category, work_mode, job_type_norm, row[0]),
            )
        db.commit()


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
        # Milestone 8E.4 — every provider row flows through the same
        # deterministic classifier before it is cached.
        row = enrich_job(job)
        row["tags_json"] = _json.dumps(row.pop("tags", []), ensure_ascii=False)
        rows.append(row)
    db.executemany(
        """
        INSERT INTO external_jobs (
            source, source_job_id, title, company, location, description,
            job_type, remote, tags_json, salary, job_url, published_at,
            fetched_at, category, work_mode, normalized_job_type
        ) VALUES (:source, :source_job_id, :title, :company, :location,
                  :description, :job_type, :remote, :tags_json, :salary,
                  :job_url, :published_at, :fetched_at, :category,
                  :work_mode, :normalized_job_type)
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
            fetched_at=excluded.fetched_at,
            category=excluded.category,
            work_mode=excluded.work_mode,
            normalized_job_type=excluded.normalized_job_type
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
            fresh = enrich_job(dict(job))
            fresh["id"] = row_id["id"]
            new_jobs.append(fresh)
    return new_jobs


def _parse_ts(text):
    try:
        return datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return None


def refresh_if_stale(db_path):
    """Refresh each provider whose own cache is older than its freshness window.

    Milestone 8E.1: staleness is evaluated PER PROVIDER (Jobicy is polled at
    most once per hour, per their guidance; Remote OK / Arbeitnow keep the
    20-minute window). A fresh provider is never re-fetched just because a
    sibling expired. Provider failures are isolated: recorded, never raised.
    """
    with _lock:
        with sqlite3.connect(db_path) as db:
            db.row_factory = sqlite3.Row
            last_by_source = {
                row["source"]: row["t"]
                for row in db.execute(
                    "SELECT source, MAX(fetched_at) AS t FROM external_jobs GROUP BY source"
                )
            }
            newest_dt = _parse_ts(
                db.execute("SELECT MAX(fetched_at) AS t FROM external_jobs").fetchone()["t"]
            )
        now = datetime.now(timezone.utc)

        def _is_stale(name):
            last_dt = _parse_ts(last_by_source.get(name))
            if last_dt is None:
                # Provider has no cached rows yet — follow the cache-wide
                # clock so an absent/empty provider is not re-polled on
                # every request (it is fetched when the cache itself is stale).
                last_dt = newest_dt
            return last_dt is None or \
                now - last_dt.astimezone(timezone.utc) >= PROVIDER_FRESHNESS[name]

        stale_providers = [name for name in PROVIDERS if _is_stale(name)]
        cache_fresh = not stale_providers

        newly_imported = []
        for name in stale_providers:
            provider = PROVIDERS[name]
            if not provider.is_configured():
                # Milestone 8E.2 — a provider without its credentials (e.g.
                # Adzuna env vars absent) is SKIPPED, not failed: other
                # providers keep working and the UI shows no degraded banner.
                continue
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
        if stale_providers:
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
             limit=None, category=None, work_mode=None, job_type=None):
    """Deterministic, filtered, paginated job list for GET /api/jobs.

    `limit` (Milestone 8C.3B) overrides the page size for a single call —
    used by the merged public feed to fetch all matching external rows before
    combining them with published JobGuard jobs. Default keeps 8B.1 behavior.

    Milestone 8E.4 — `category`, `work_mode` and `job_type` join the filter
    set (AND semantics with the existing parameters). Recognized values are
    the canonical slugs from job_sources.classify; unknown/blank values are
    ignored so they never silently empty the feed. Work-mode unknowns
    (NULL) only ever surface when no explicit mode is requested.
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
    if category in VALID_CATEGORIES:
        where.append("category = ?")
        params.append(category)
    if work_mode in VALID_WORK_MODES:
        where.append("work_mode = ?")
        params.append(work_mode)
    if job_type in VALID_JOB_TYPES:
        where.append("normalized_job_type = ?")
        params.append(job_type)
    clause = f"WHERE {' AND '.join(where)}" if where else ""

    with sqlite3.connect(db_path) as db:
        db.row_factory = sqlite3.Row
        total = db.execute(f"SELECT COUNT(*) AS n FROM external_jobs {clause}", params).fetchone()["n"]
        offset = (max(1, page) - 1) * PAGE_SIZE
        rows = db.execute(
            f"""SELECT id, source, source_job_id, title, company, location, description,
                       job_type, remote, tags_json, salary, job_url, published_at, fetched_at,
                       category, work_mode, normalized_job_type
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
