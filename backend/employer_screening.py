"""Milestone 8C.3A — AI safety screening for employer job drafts.

Reuses the EXISTING JobGuard prediction engine (predict_one: unchanged
preprocessing, TF-IDF, 11 numeric features, XGBoost, 9 red-flag rules,
noisy-OR, 0.5 threshold) on text composed from the employer's draft plus
their company name. No new classifier, no second threshold.

Verdict mapping (the ONLY new decision, and it is 1:1 with the engine):
  Legitimate -> status 'ready'
  Scam       -> status 'flagged'

Screenings are stored in their OWN table (employer_job_screenings) — never in
the normal predictions table — so employer screening never appears in user
History or Insights. Old screening records are kept as historical audit data;
editing a job resets its status to 'draft' (invalidating the last screening
for publication eligibility).

Publishing is NOT part of this milestone, and a screening is not a guarantee:
the report never claims a company is verified or a job is 100% safe.
"""

import hashlib
import json
import sqlite3

from job_sources.service import now_iso


def content_hash(text):
    """sha256 fingerprint of the exact screening text (stale-screening guard).

    A job may publish only when the content that would go public is the same
    content that passed the safety check. The hash recorded at screening time
    is compared against a fresh composition at publish time.
    """
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def ensure_table(db_path):
    """Idempotent schema for employer_job_screenings (mirror of app.py)."""
    with sqlite3.connect(db_path) as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS employer_job_screenings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                employer_job_id INTEGER NOT NULL,
                prediction TEXT NOT NULL,
                probability REAL NOT NULL,
                confidence REAL NOT NULL,
                evidence_json TEXT,
                screened_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_screenings_job
                ON employer_job_screenings (employer_job_id);
            CREATE INDEX IF NOT EXISTS idx_screenings_screened_at
                ON employer_job_screenings (screened_at);
            """
        )
        # Milestone 8C.3B — safe in-place migration: text_hash (sha256 of the
        # exact screening text). Older rows keep NULL (status-based freshness
        # still applies to them); new screenings always store the hash so a
        # publish can prove the pass belongs to the CURRENT content.
        cols = {row[1] for row in db.execute("PRAGMA table_info(employer_job_screenings)")}
        if "text_hash" not in cols:
            db.execute("ALTER TABLE employer_job_screenings ADD COLUMN text_hash TEXT")
        db.commit()


def compose_screening_text(job, profile):
    """Build the screening text from the draft and the employer profile.

    Includes Job Title, Company Name, Location, Job Type, Salary, Description,
    Requirements, Benefits, Contact Email and Application URL — empty optional
    fields are skipped (nothing is invented). The job title is also passed to
    the engine separately as the display title.
    """
    lines = []
    if job.get("title"):
        lines.append(f"Job Title: {job['title']}")
    if profile.get("company_name"):
        lines.append(f"Company: {profile['company_name']}")
    if job.get("location"):
        lines.append(f"Location: {job['location']}")
    if job.get("job_type"):
        lines.append(f"Job Type: {job['job_type']}")
    if job.get("salary"):
        lines.append(f"Salary: {job['salary']}")

    if job.get("description"):
        lines.append("")
        lines.append(job["description"])

    if job.get("requirements"):
        lines.append("")
        lines.append(f"Requirements: {job['requirements']}")
    if job.get("benefits"):
        lines.append(f"Benefits: {job['benefits']}")
    if job.get("contact_email"):
        lines.append(f"Contact Email: {job['contact_email']}")
    if job.get("application_url"):
        lines.append(f"Application URL: {job['application_url']}")

    return "\n".join(lines).strip()


def record_screening(db_path, job_id, result, text_hash=None):
    """Persist one engine result as a screening audit record.

    `result` is the untouched dict returned by the existing predict_one().
    `text_hash` fingerprints the screened text (8C.3B stale-screening guard).
    Returns the stored screening dict (evidence parsed for the UI).
    """
    screened_at = now_iso()
    red_flags = result.get("red_flags", [])
    with sqlite3.connect(db_path) as db:
        cursor = db.execute(
            """
            INSERT INTO employer_job_screenings
                (employer_job_id, prediction, probability, confidence,
                 evidence_json, screened_at, text_hash)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (job_id,
             result.get("prediction"),
             float(result.get("probabilities", {}).get("scam", 0.0)),
             float(result.get("confidence", 0.0)),
             json.dumps(red_flags, ensure_ascii=False),
             screened_at,
             text_hash),
        )
        db.commit()
        screening_id = cursor.lastrowid
    return {
        "id": screening_id,
        "employer_job_id": job_id,
        "prediction": result.get("prediction"),
        "probability": float(result.get("probabilities", {}).get("scam", 0.0)),
        "confidence": float(result.get("confidence", 0.0)),
        "engine": result.get("engine", {}),
        "red_flags": red_flags,
        "screened_at": screened_at,
    }


def latest_screening(db_path, job_id):
    """The most recent screening for a job, or None (old records are kept)."""
    with sqlite3.connect(db_path) as db:
        db.row_factory = sqlite3.Row
        row = db.execute(
            "SELECT * FROM employer_job_screenings WHERE employer_job_id = ?"
            " ORDER BY id DESC LIMIT 1",
            (job_id,),
        ).fetchone()
    if row is None:
        return None
    try:
        red_flags = json.loads(row["evidence_json"] or "[]")
    except (TypeError, ValueError):
        red_flags = []
    return {
        "id": row["id"],
        "employer_job_id": row["employer_job_id"],
        "prediction": row["prediction"],
        "probability": row["probability"],
        "confidence": row["confidence"],
        "red_flags": red_flags,
        "screened_at": row["screened_at"],
        "text_hash": row["text_hash"],
    }
