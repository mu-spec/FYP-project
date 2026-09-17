"""Milestone 8C.1 — Employer Registration Foundation.

Employer profiles are an extension of the EXISTING JobGuard account: there is
no second authentication system, no credentials here — just the company
details tied 1:1 to the signed-in user (user_id UNIQUE). Registration only:
nothing in this module publishes jobs or claims any third-party verification
of a company.

This milestone covers registration/editing only. Job creation, publishing and
screening are explicitly out of scope (next stage).
"""

import re
import sqlite3
from urllib.parse import urlparse

from job_sources.service import now_iso

# Field limits (sensible maximums; everything is trimmed before storing).
MAX_COMPANY_NAME = 120
MAX_CONTACT_NAME = 120
MAX_BUSINESS_EMAIL = 200
MAX_WEBSITE = 300
MAX_LOCATION = 120
MAX_DESCRIPTION = 2000

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

PROFILE_FIELDS = (
    "company_name", "contact_name", "business_email",
    "website", "location", "company_description",
)


def ensure_table(db_path):
    """Idempotent schema for employer_profiles (mirror of app.py)."""
    with sqlite3.connect(db_path) as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS employer_profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL UNIQUE,
                company_name TEXT NOT NULL,
                contact_name TEXT NOT NULL,
                business_email TEXT NOT NULL,
                website TEXT,
                location TEXT NOT NULL,
                company_description TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        db.commit()


def validate_profile_data(data):
    """Validate a registration/update payload.

    Returns (clean, field_errors): `clean` holds the trimmed values (website
    None when blank), `field_errors` maps field -> human message. Registration
    only — this does NOT verify the company with any third party.
    """
    if not isinstance(data, dict):
        data = {}
    field_errors = {}

    company_name = (data.get("company_name") or "").strip()
    contact_name = (data.get("contact_name") or "").strip()
    business_email = (data.get("business_email") or "").strip()
    website = (data.get("website") or "").strip()
    location = (data.get("location") or "").strip()
    company_description = (data.get("company_description") or "").strip()

    if not company_name:
        field_errors["company_name"] = "Please enter the company name."
    elif len(company_name) > MAX_COMPANY_NAME:
        field_errors["company_name"] = f"Company name is too long (max {MAX_COMPANY_NAME} characters)."

    if not contact_name:
        field_errors["contact_name"] = "Please enter the contact person's name."
    elif len(contact_name) > MAX_CONTACT_NAME:
        field_errors["contact_name"] = f"Contact name is too long (max {MAX_CONTACT_NAME} characters)."

    if not business_email:
        field_errors["business_email"] = "Please enter a business email."
    elif len(business_email) > MAX_BUSINESS_EMAIL:
        field_errors["business_email"] = f"Business email is too long (max {MAX_BUSINESS_EMAIL} characters)."
    elif not _EMAIL_RE.match(business_email):
        field_errors["business_email"] = "Please enter a valid business email address."

    if website:
        if len(website) > MAX_WEBSITE:
            field_errors["website"] = f"Website is too long (max {MAX_WEBSITE} characters)."
        else:
            # Only real HTTP/HTTPS web URLs pass. When the input carries a
            # scheme it must be http/https (javascript:, ftp: etc. rejected —
            # never stored, so the UI can never render it as a link later).
            # Without a scheme, https:// is assumed for bare domains.
            candidate = website if "://" in website else f"https://{website}"
            parsed = urlparse(candidate)
            netloc_ok = bool(parsed.netloc) and re.match(
                r"^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?(:\d+)?$", parsed.netloc)
            if parsed.scheme not in ("http", "https") or not netloc_ok:
                field_errors["website"] = "Website must be a valid HTTP or HTTPS URL."
            else:
                website = candidate
    else:
        website = None  # optional

    if not location:
        field_errors["location"] = "Please enter the company location."
    elif len(location) > MAX_LOCATION:
        field_errors["location"] = f"Location is too long (max {MAX_LOCATION} characters)."

    if not company_description:
        field_errors["company_description"] = "Please enter a company description."
    elif len(company_description) > MAX_DESCRIPTION:
        field_errors["company_description"] = f"Company description is too long (max {MAX_DESCRIPTION} characters)."

    clean = {
        "company_name": company_name,
        "contact_name": contact_name,
        "business_email": business_email,
        "website": website,
        "location": location,
        "company_description": company_description,
    }
    return clean, field_errors


def _row_to_profile(row):
    if row is None:
        return None
    return {
        "id": row["id"],
        "company_name": row["company_name"],
        "contact_name": row["contact_name"],
        "business_email": row["business_email"],
        "website": row["website"],
        "location": row["location"],
        "company_description": row["company_description"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def get_profile(db_path, user_id):
    """The caller's employer profile, or None when not registered."""
    with sqlite3.connect(db_path) as db:
        db.row_factory = sqlite3.Row
        row = db.execute(
            "SELECT * FROM employer_profiles WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    return _row_to_profile(row)


def create_profile(db_path, user_id, clean):
    """Create the single employer profile for the user.

    Returns (profile, None) on success or (None, "duplicate") when the user
    already has one — UNIQUE(user_id) is the hard guarantee.
    """
    now = now_iso()
    try:
        with sqlite3.connect(db_path) as db:
            db.execute(
                """
                INSERT INTO employer_profiles
                    (user_id, company_name, contact_name, business_email,
                     website, location, company_description, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (user_id, clean["company_name"], clean["contact_name"],
                 clean["business_email"], clean["website"], clean["location"],
                 clean["company_description"], now, now),
            )
            db.commit()
    except sqlite3.IntegrityError:
        return None, "duplicate"
    return get_profile(db_path, user_id), None


def update_profile(db_path, user_id, clean):
    """Update ONLY the caller's profile in place.

    id, user_id and created_at are preserved; updated_at is refreshed.
    Returns (profile, None), or (None, "missing") when the user has no
    profile yet (use POST to register first).
    """
    with sqlite3.connect(db_path) as db:
        cursor = db.execute(
            """
            UPDATE employer_profiles
               SET company_name = ?, contact_name = ?, business_email = ?,
                   website = ?, location = ?, company_description = ?,
                   updated_at = ?
             WHERE user_id = ?
            """,
            (clean["company_name"], clean["contact_name"], clean["business_email"],
             clean["website"], clean["location"], clean["company_description"],
             now_iso(), user_id),
        )
        db.commit()
        if cursor.rowcount == 0:
            return None, "missing"
    return get_profile(db_path, user_id), None
