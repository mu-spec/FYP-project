"""Milestone 8B.2 — job preferences + in-app notification storage.

Data access for per-user job preferences and the notifications derived from
them. Everything is strictly scoped by user_id; the same external job can
never notify the same user twice (UNIQUE(user_id, external_job_id)).

Notifications reference the internal external_jobs.id — only real cached jobs
are ever used, and nothing is invented. When a cached job is later pruned the
notification survives with its title/message snapshot and is flagged so the
UI can explain that the listing is no longer cached.
"""

import sqlite3
from datetime import datetime, timedelta, timezone

from job_sources import matching
from job_sources.service import now_iso

# How far back the catch-up scan looks when preferences are saved or the
# notification list is opened (so already-cached jobs can still alert).
CATCHUP_WINDOW = timedelta(hours=48)
# Upper bound of notifications a single catch-up scan may create per user.
CATCHUP_LIMIT = 20
# Notifications returned by the list endpoint.
LIST_LIMIT = 50


def ensure_tables(db_path):
    """Idempotent schema for preferences + notifications (mirror of app.py)."""
    with sqlite3.connect(db_path) as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS job_preferences (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL UNIQUE,
                keywords TEXT,
                location TEXT,
                remote_only INTEGER NOT NULL DEFAULT 0,
                source TEXT NOT NULL DEFAULT 'any',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                external_job_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                message TEXT,
                is_read INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                UNIQUE (user_id, external_job_id)
            );
            CREATE INDEX IF NOT EXISTS idx_notifications_user
                ON notifications (user_id);
            CREATE INDEX IF NOT EXISTS idx_notifications_is_read
                ON notifications (is_read);
            CREATE INDEX IF NOT EXISTS idx_notifications_created_at
                ON notifications (created_at);
            """
        )
        db.commit()


# ---------------------------------------------------------------------------
# Preferences
# ---------------------------------------------------------------------------

def get_preferences(db_path, user_id):
    """Return the user's preference dict, or None when never configured."""
    with sqlite3.connect(db_path) as db:
        db.row_factory = sqlite3.Row
        row = db.execute(
            "SELECT keywords, location, remote_only, source, created_at, updated_at"
            " FROM job_preferences WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    if row is None:
        return None
    return {
        "keywords": row["keywords"] or "",
        "location": row["location"] or "",
        "remote_only": bool(row["remote_only"]),
        "source": row["source"] or "any",
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def save_preferences(db_path, user_id, keywords, location, remote_only, source):
    """Insert or update the single active preference record for the user.

    The caller (API layer) validates and trims; this is a pure upsert keyed by
    UNIQUE(user_id) — a user can only ever touch their own row.
    """
    now = now_iso()
    with sqlite3.connect(db_path) as db:
        db.execute(
            """
            INSERT INTO job_preferences
                (user_id, keywords, location, remote_only, source, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                keywords = excluded.keywords,
                location = excluded.location,
                remote_only = excluded.remote_only,
                source = excluded.source,
                updated_at = excluded.updated_at
            """,
            (user_id, keywords, location, int(bool(remote_only)), source, now, now),
        )
        db.commit()
    return get_preferences(db_path, user_id)


def iter_user_preferences(db_path):
    """Yield (user_id, preferences) for every user with saved preferences."""
    with sqlite3.connect(db_path) as db:
        db.row_factory = sqlite3.Row
        for row in db.execute(
            "SELECT user_id, keywords, location, remote_only, source"
            " FROM job_preferences"
        ):
            yield row["user_id"], {
                "keywords": row["keywords"] or "",
                "location": row["location"] or "",
                "remote_only": bool(row["remote_only"]),
                "source": row["source"] or "any",
            }


# ---------------------------------------------------------------------------
# Notification generation
# ---------------------------------------------------------------------------

def _notification_message(job):
    """Human-readable, honest message built only from normalized fields."""
    parts = []
    if job.get("company"):
        parts.append(job["company"])
    parts.append("Remote" if job.get("remote") else (job.get("location") or "On-site"))
    return " · ".join(str(p) for p in parts) + " — new job matches your preferences."


def generate_for_jobs(db_path, jobs):
    """Create notifications for saved preferences matching the given jobs.

    Called after a successful provider refresh with the jobs that were newly
    imported in that refresh. Deduplication is enforced by
    UNIQUE(user_id, external_job_id) + ON CONFLICT DO NOTHING, so re-runs and
    overlapping refreshes can never double-notify.
    """
    if not jobs:
        return 0
    ensure_tables(db_path)
    created = 0
    with sqlite3.connect(db_path) as db:
        for user_id, prefs in iter_user_preferences(db_path):
            for job, _reasons in matching.filter_jobs(jobs, prefs):
                cursor = db.execute(
                    """
                    INSERT INTO notifications
                        (user_id, external_job_id, title, message, is_read, created_at)
                    VALUES (?, ?, ?, ?, 0, ?)
                    ON CONFLICT(user_id, external_job_id) DO NOTHING
                    """,
                    (user_id, job["id"], job.get("title") or "New job",
                     _notification_message(job), now_iso()),
                )
                created += cursor.rowcount if cursor.rowcount > 0 else 0
        db.commit()
    return created


def run_user_matching(db_path, user_id,
                      window=CATCHUP_WINDOW, limit=CATCHUP_LIMIT):
    """Safe catch-up path: match the user's preferences against cached jobs.

    Used when the user opens notifications or saves preferences, so jobs that
    were cached before the preferences existed can still alert. Only real
    cached rows are considered, newest first, capped at `limit`, within the
    look-back `window`; UNIQUE(user_id, external_job_id) keeps it idempotent.
    """
    prefs = get_preferences(db_path, user_id)
    if prefs is None:
        return 0
    cutoff = (datetime.now(timezone.utc) - window).isoformat()
    with sqlite3.connect(db_path) as db:
        db.row_factory = sqlite3.Row
        rows = db.execute(
            "SELECT * FROM external_jobs WHERE fetched_at >= ?"
            " ORDER BY published_at DESC, id DESC",
            (cutoff,),
        ).fetchall()
    jobs = [dict(row) for row in rows]
    for job in jobs:
        tags = job.get("tags_json")
        if tags:
            import json
            try:
                job["tags"] = json.loads(tags)
            except (TypeError, ValueError):
                job["tags"] = []
    matches = matching.filter_jobs(jobs, prefs)[:limit]
    created = 0
    with sqlite3.connect(db_path) as db:
        for job, _reasons in matches:
            cursor = db.execute(
                """
                INSERT INTO notifications
                    (user_id, external_job_id, title, message, is_read, created_at)
                VALUES (?, ?, ?, ?, 0, ?)
                ON CONFLICT(user_id, external_job_id) DO NOTHING
                """,
                (user_id, job["id"], job.get("title") or "New job",
                 _notification_message(job), now_iso()),
            )
            created += cursor.rowcount if cursor.rowcount > 0 else 0
        db.commit()
    return created


# ---------------------------------------------------------------------------
# Notification reads (always user-scoped)
# ---------------------------------------------------------------------------

def list_notifications(db_path, user_id, limit=LIST_LIMIT):
    """Latest notifications for one user, newest first, with job availability."""
    with sqlite3.connect(db_path) as db:
        db.row_factory = sqlite3.Row
        rows = db.execute(
            """
            SELECT n.id, n.external_job_id, n.title, n.message, n.is_read,
                   n.created_at,
                   j.id AS job_present,
                   j.title AS job_title, j.company, j.location, j.description,
                   j.job_type, j.remote, j.tags_json, j.salary, j.job_url,
                   j.published_at, j.fetched_at, j.source, j.source_job_id
            FROM notifications n
            LEFT JOIN external_jobs j ON j.id = n.external_job_id
            WHERE n.user_id = ?
            ORDER BY n.created_at DESC, n.id DESC
            LIMIT ?
            """,
            (user_id, limit),
        ).fetchall()
        unread = db.execute(
            "SELECT COUNT(*) AS c FROM notifications WHERE user_id = ? AND is_read = 0",
            (user_id,),
        ).fetchone()["c"]
    import json
    items = []
    for row in rows:
        item = {
            "id": row["id"],
            "external_job_id": row["external_job_id"],
            "title": row["title"],
            "message": row["message"],
            "is_read": bool(row["is_read"]),
            "created_at": row["created_at"],
            "job": None,
        }
        if row["job_present"] is not None:
            tags = []
            try:
                tags = json.loads(row["tags_json"] or "[]")
            except (TypeError, ValueError):
                tags = []
            item["job"] = {
                "id": row["external_job_id"],
                "source": row["source"],
                "source_job_id": row["source_job_id"],
                "title": row["job_title"],
                "company": row["company"],
                "location": row["location"],
                "description": row["description"],
                "job_type": row["job_type"],
                "remote": bool(row["remote"]),
                "tags": tags,
                "salary": row["salary"],
                "job_url": row["job_url"],
                "published_at": row["published_at"],
                "fetched_at": row["fetched_at"],
            }
        items.append(item)
    return {"notifications": items, "unread": unread}


def unread_count(db_path, user_id):
    with sqlite3.connect(db_path) as db:
        db.row_factory = sqlite3.Row
        row = db.execute(
            "SELECT COUNT(*) AS c FROM notifications WHERE user_id = ? AND is_read = 0",
            (user_id,),
        ).fetchone()
        return row["c"]


def mark_read(db_path, user_id, notification_id):
    """Mark one notification read. Returns False when the row is not owned
    by this user (cross-user access attempt -> surfaced as 404 upstream)."""
    with sqlite3.connect(db_path) as db:
        cursor = db.execute(
            "UPDATE notifications SET is_read = 1"
            " WHERE id = ? AND user_id = ?",
            (notification_id, user_id),
        )
        db.commit()
        return cursor.rowcount > 0


def mark_all_read(db_path, user_id):
    with sqlite3.connect(db_path) as db:
        cursor = db.execute(
            "UPDATE notifications SET is_read = 1 WHERE user_id = ? AND is_read = 0",
            (user_id,),
        )
        db.commit()
        return cursor.rowcount
