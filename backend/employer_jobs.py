"""Milestone 8C.2 — Employer Job Creation & Draft Management.

Employer-created job advertisements live in their OWN table (employer_jobs),
completely separate from the external_jobs cache (Remote OK / Arbeitnow).
Every job created in this milestone is status='draft': the status is set by
the backend and can never be chosen or forced by the client. Publishing,
screening and public feeds are explicitly out of scope (8C.3).

Ownership: every read/update/delete is scoped through the employer_profile_id
derived from the AUTHENTICATED user's profile — one user can never touch
another user's drafts, and cross-user access returns 404 (identical to a
missing row, so no ownership information is revealed).
"""

import re
import sqlite3
from datetime import datetime, timezone
from urllib.parse import urlparse

from job_sources.service import now_iso
from employer_profiles import _EMAIL_RE

# Approved employment types (exact values; anything else is rejected).
JOB_TYPES = ("Full Time", "Part Time", "Contract", "Internship", "Temporary", "Other")

# Field limits. The description keeps a minimum length so a later milestone
# can run the existing JobGuard AI analysis on real content.
MAX_TITLE = 120
MAX_LOCATION = 120
MAX_SALARY = 120
MIN_DESCRIPTION = 30
MAX_DESCRIPTION = 20000
MAX_REQUIREMENTS = 8000
MAX_BENEFITS = 4000
MAX_CONTACT_EMAIL = 200
MAX_APPLICATION_URL = 500

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_NETLOC_RE = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?(:\d+)?$")


def ensure_table(db_path):
    """Idempotent schema for employer_jobs (mirror of app.py)."""
    with sqlite3.connect(db_path) as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS employer_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                employer_profile_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                location TEXT NOT NULL,
                job_type TEXT NOT NULL,
                salary TEXT,
                description TEXT NOT NULL,
                requirements TEXT NOT NULL,
                benefits TEXT,
                contact_email TEXT NOT NULL,
                application_url TEXT,
                closing_date TEXT,
                status TEXT NOT NULL DEFAULT 'draft',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_employer_jobs_profile
                ON employer_jobs (employer_profile_id);
            CREATE INDEX IF NOT EXISTS idx_employer_jobs_status
                ON employer_jobs (status);
            CREATE INDEX IF NOT EXISTS idx_employer_jobs_created_at
                ON employer_jobs (created_at);
            """
        )
        # Milestone 8C.3B — safe in-place migration: published_at (NULL until
        # the job is published). Existing rows keep every value; the added
        # column is simply NULL for them.
        cols = {row[1] for row in db.execute("PRAGMA table_info(employer_jobs)")}
        if "published_at" not in cols:
            db.execute("ALTER TABLE employer_jobs ADD COLUMN published_at TEXT")
        db.execute(
            "CREATE INDEX IF NOT EXISTS idx_employer_jobs_published_at"
            " ON employer_jobs (published_at)"
        )
        db.commit()


def validate_job_data(data):
    """Validate a create/update payload.

    Returns (clean, field_errors). `status` is deliberately NOT read from the
    payload — drafts can never be forced into another state through this API.
    Nothing is invented: optional fields stay empty/None when absent.
    """
    if not isinstance(data, dict):
        data = {}
    field_errors = {}

    title = (data.get("title") or "").strip()
    location = (data.get("location") or "").strip()
    job_type = (data.get("job_type") or "").strip()
    salary = (data.get("salary") or "").strip()
    description = (data.get("description") or "").strip()
    requirements = (data.get("requirements") or "").strip()
    benefits = (data.get("benefits") or "").strip()
    contact_email = (data.get("contact_email") or "").strip()
    application_url = (data.get("application_url") or "").strip()
    closing_date = (data.get("closing_date") or "").strip()

    if not title:
        field_errors["title"] = "Please enter the job title."
    elif len(title) > MAX_TITLE:
        field_errors["title"] = f"Job title is too long (max {MAX_TITLE} characters)."

    if not location:
        field_errors["location"] = "Please enter the job location."
    elif len(location) > MAX_LOCATION:
        field_errors["location"] = f"Location is too long (max {MAX_LOCATION} characters)."

    if not job_type:
        field_errors["job_type"] = "Please choose a job type."
    elif job_type not in JOB_TYPES:
        field_errors["job_type"] = "Job type must be one of: " + ", ".join(JOB_TYPES) + "."

    if salary and len(salary) > MAX_SALARY:
        field_errors["salary"] = f"Salary is too long (max {MAX_SALARY} characters)."

    if not description:
        field_errors["description"] = "Please enter a job description."
    elif len(description) < MIN_DESCRIPTION:
        field_errors["description"] = (
            f"Please describe the role in at least {MIN_DESCRIPTION} characters — "
            "the description is what JobGuard will analyze later.")
    elif len(description) > MAX_DESCRIPTION:
        field_errors["description"] = f"Description is too long (max {MAX_DESCRIPTION} characters)."

    if not requirements:
        field_errors["requirements"] = "Please enter the job requirements."
    elif len(requirements) > MAX_REQUIREMENTS:
        field_errors["requirements"] = f"Requirements are too long (max {MAX_REQUIREMENTS} characters)."

    if benefits and len(benefits) > MAX_BENEFITS:
        field_errors["benefits"] = f"Benefits are too long (max {MAX_BENEFITS} characters)."

    if not contact_email:
        field_errors["contact_email"] = "Please enter a contact email."
    elif len(contact_email) > MAX_CONTACT_EMAIL:
        field_errors["contact_email"] = f"Contact email is too long (max {MAX_CONTACT_EMAIL} characters)."
    elif not _EMAIL_RE.match(contact_email):
        field_errors["contact_email"] = "Please enter a valid contact email address."

    if application_url:
        if len(application_url) > MAX_APPLICATION_URL:
            field_errors["application_url"] = f"Application URL is too long (max {MAX_APPLICATION_URL} characters)."
        else:
            # HTTP/HTTPS only — javascript:/ftp: etc. are rejected so nothing
            # unsafe can ever be stored or rendered as an application link.
            candidate = application_url if "://" in application_url else f"https://{application_url}"
            parsed = urlparse(candidate)
            netloc_ok = bool(parsed.netloc) and _NETLOC_RE.match(parsed.netloc)
            if parsed.scheme not in ("http", "https") or not netloc_ok:
                field_errors["application_url"] = "Application URL must be a valid HTTP or HTTPS URL."
            else:
                application_url = candidate

    if closing_date:
        if not _DATE_RE.match(closing_date):
            field_errors["closing_date"] = "Closing date must use the YYYY-MM-DD format."
        else:
            try:
                datetime.strptime(closing_date, "%Y-%m-%d")
            except ValueError:
                field_errors["closing_date"] = "Please enter a valid closing date."

    clean = {
        "title": title,
        "location": location,
        "job_type": job_type,
        "salary": salary or None,
        "description": description,
        "requirements": requirements,
        "benefits": benefits or None,
        "contact_email": contact_email,
        "application_url": application_url or None,
        "closing_date": closing_date or None,
    }
    return clean, field_errors


def _row_to_job(row):
    if row is None:
        return None
    return {
        "id": row["id"],
        "employer_profile_id": row["employer_profile_id"],
        "title": row["title"],
        "location": row["location"],
        "job_type": row["job_type"],
        "salary": row["salary"],
        "description": row["description"],
        "requirements": row["requirements"],
        "benefits": row["benefits"],
        "contact_email": row["contact_email"],
        "application_url": row["application_url"],
        "closing_date": row["closing_date"],
        "status": row["status"],
        "published_at": row["published_at"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


_JOB_COLS = ("title, location, job_type, salary, description, requirements,"
             " benefits, contact_email, application_url, closing_date")
_JOB_SET = ("title = ?, location = ?, job_type = ?, salary = ?, description = ?,"
            " requirements = ?, benefits = ?, contact_email = ?, application_url = ?,"
            " closing_date = ?")


# Screening join: latest record per job (audit history kept).
_SCREENING_JOIN = (
    " LEFT JOIN employer_job_screenings s"
    "   ON s.employer_job_id = j.id"
    "  AND s.id = (SELECT MAX(s2.id) FROM employer_job_screenings s2"
    "              WHERE s2.employer_job_id = j.id)"
)


def _attach_screening(job_row):
    job = _row_to_job(job_row)
    if job_row["scr_prediction"] is None:
        job["screening"] = None
    else:
        job["screening"] = {
            "prediction": job_row["scr_prediction"],
            "probability": job_row["scr_probability"],
            "confidence": job_row["scr_confidence"],
            "screened_at": job_row["scr_screened_at"],
        }
    return job


def list_jobs(db_path, employer_profile_id):
    """The employer's own jobs, newest update first (strictly scoped), each
    with its latest screening summary (or None when never screened)."""
    with sqlite3.connect(db_path) as db:
        db.row_factory = sqlite3.Row
        rows = db.execute(
            "SELECT j.*, s.prediction AS scr_prediction,"
            " s.probability AS scr_probability, s.confidence AS scr_confidence,"
            " s.screened_at AS scr_screened_at"
            " FROM employer_jobs j" + _SCREENING_JOIN +
            " WHERE j.employer_profile_id = ?"
            " ORDER BY j.updated_at DESC, j.id DESC",
            (employer_profile_id,),
        ).fetchall()
    return [_attach_screening(row) for row in rows]


def get_job(db_path, job_id, employer_profile_id):
    """One job, owned by this employer profile — else None (never leaks).
    Includes the latest screening summary (or None when never screened)."""
    with sqlite3.connect(db_path) as db:
        db.row_factory = sqlite3.Row
        row = db.execute(
            "SELECT j.*, s.prediction AS scr_prediction,"
            " s.probability AS scr_probability, s.confidence AS scr_confidence,"
            " s.screened_at AS scr_screened_at"
            " FROM employer_jobs j" + _SCREENING_JOIN +
            " WHERE j.id = ? AND j.employer_profile_id = ?",
            (job_id, employer_profile_id),
        ).fetchone()
    if row is None:
        return None
    return _attach_screening(row)


def create_job(db_path, employer_profile_id, clean):
    """Create a draft. The status is ALWAYS 'draft' — decided here, not by
    the client (any client-supplied status is ignored upstream)."""
    now = now_iso()
    with sqlite3.connect(db_path) as db:
        cursor = db.execute(
            f"""
            INSERT INTO employer_jobs
                (employer_profile_id, {_JOB_COLS}, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'draft', ?, ?)
            """,
            (employer_profile_id, clean["title"], clean["location"], clean["job_type"],
             clean["salary"], clean["description"], clean["requirements"],
             clean["benefits"], clean["contact_email"], clean["application_url"],
             clean["closing_date"], now, now),
        )
        db.commit()
        job_id = cursor.lastrowid
    return get_job(db_path, job_id, employer_profile_id)


def update_job(db_path, job_id, employer_profile_id, clean):
    """Update the employer's own draft in place.

    id, employer_profile_id and created_at are preserved; updated_at is
    refreshed. Milestone 8C.3A: ANY edit resets the status to 'draft' — a
    previously screened (ready/flagged) job must be screened again, since its
    content changed. Old screening records are kept as audit history.
    Returns None when the draft does not belong to this employer profile.
    """
    with sqlite3.connect(db_path) as db:
        cursor = db.execute(
            f"""
            UPDATE employer_jobs
               SET {_JOB_SET},
                   status = 'draft',
                   published_at = NULL,
                   updated_at = ?
             WHERE id = ? AND employer_profile_id = ?
            """,
            (clean["title"], clean["location"], clean["job_type"], clean["salary"],
             clean["description"], clean["requirements"], clean["benefits"],
             clean["contact_email"], clean["application_url"], clean["closing_date"],
             now_iso(), job_id, employer_profile_id),
        )
        db.commit()
        if cursor.rowcount == 0:
            return None
    return get_job(db_path, job_id, employer_profile_id)


def delete_job(db_path, job_id, employer_profile_id):
    """Delete the employer's own draft. Returns False when the row does not
    belong to this employer profile (surfaced as 404 upstream)."""
    with sqlite3.connect(db_path) as db:
        cursor = db.execute(
            "DELETE FROM employer_jobs WHERE id = ? AND employer_profile_id = ?",
            (job_id, employer_profile_id),
        )
        db.commit()
        return cursor.rowcount > 0


def publish_job(db_path, job_id, employer_profile_id, published_at):
    """Milestone 8C.3B — publish the employer's own READY job.

    The transition is only possible from status='ready' (a passed safety
    screening with unchanged content). Returns True on success, False when
    the row is missing, foreign, or not in 'ready' state.
    """
    with sqlite3.connect(db_path) as db:
        cursor = db.execute(
            """
            UPDATE employer_jobs
               SET status = 'published', published_at = ?, updated_at = ?
             WHERE id = ? AND employer_profile_id = ? AND status = 'ready'
            """,
            (published_at, published_at, job_id, employer_profile_id),
        )
        db.commit()
        return cursor.rowcount > 0


def public_listings(db_path, q=None, location=None, remote=False,
                    category=None, work_mode=None, job_type=None):
    """Published employer jobs in the public Jobs-page normalized shape.

    ONLY status='published' rows leave this module — draft/flagged/ready are
    never exposed. The table stays separate from external_jobs (nothing is
    copied into it). Company always comes from the employer profile.

    Milestone 8E.4 — each published listing flows through the SAME
    deterministic classifier as external providers (category / work_mode /
    normalized_job_type computed from the stored text, never stored), and the
    optional unified-filter arguments apply the same AND semantics. The
    arguments are read-path only: creating, editing, screening and publishing
    jobs are untouched.
    """
    from job_sources.classify import classify_fields

    where = ["j.status = 'published'"]
    params = []
    if q:
        like = f"%{q}%"
        where.append("(j.title LIKE ? OR p.company_name LIKE ? OR j.description LIKE ?)")
        params += [like, like, like]
    if location:
        where.append("j.location LIKE ?")
        params.append(f"%{location}%")
    if remote:
        where.append("LOWER(j.job_type) LIKE '%remote%'")
    clause = "WHERE " + " AND ".join(where)
    with sqlite3.connect(db_path) as db:
        db.row_factory = sqlite3.Row
        rows = db.execute(
            f"""
            SELECT j.id, j.title, j.location, j.description, j.job_type,
                   j.salary, j.requirements, j.benefits, j.published_at,
                   p.company_name
            FROM employer_jobs j
            JOIN employer_profiles p ON p.id = j.employer_profile_id
            {clause}
            ORDER BY j.published_at DESC, j.id DESC
            """,
            params,
        ).fetchall()
    listings = []
    for row in rows:
        # The long-standing JobGuard work flag stays exactly as it was
        # (type text contains "remote"); the classifier may only ADD the
        # conservative work_mode field, never change this flag.
        work_flag = "remote" in (row["job_type"] or "").lower()
        job_category, job_work_mode, job_type_norm = classify_fields(
            title=row["title"], tags=[], description=row["description"],
            job_type=row["job_type"], remote=work_flag, source="jobguard",
        )
        listing = {
            "id": row["id"],
            "source": "jobguard",
            "source_job_id": str(row["id"]),
            "title": row["title"],
            "company": row["company_name"],
            "location": row["location"],
            "description": row["description"],
            "job_type": row["job_type"],
            "remote": work_flag,
            "tags": [],
            "salary": row["salary"],
            "job_url": None,
            "published_at": row["published_at"],
            "fetched_at": None,
            "requirements": row["requirements"],
            "benefits": row["benefits"],
            "category": job_category,
            "work_mode": job_work_mode,
            "normalized_job_type": job_type_norm,
        }
        # Unified filter contract (8E.4) — AND semantics, applied on the
        # computed fields so employer rows match the external behavior.
        if category and listing["category"] != category:
            continue
        if work_mode and listing["work_mode"] != work_mode:
            continue
        if job_type and listing["normalized_job_type"] != job_type:
            continue
        listings.append(listing)
    return listings
