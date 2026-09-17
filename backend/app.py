"""
Phase 2 — Flask Backend (PRD §12 Application Layer)
===================================================
REST API that serves the XGBoost job scam classifier.

Endpoints
---------
GET    /api/health    -> service + model status (for frontend status pill)
POST   /api/predict   -> {job_text, title} -> prediction, confidence,
                          probabilities, evidence-enriched red flags,
                          extracted signals
                          (returns invalid_input=true 400 when the text is
                           rejected by the pre-ML job-post validator)
POST   /api/predict-url -> {url} -> fetches the PUBLIC page (SSRF-protected,
                          see url_fetcher.py), extracts the job text, then
                          runs the SAME validation -> predict_one() ->
                          history path as /api/predict. No second classifier.
GET    /api/history   -> last N predictions (PRD 5.7)
DELETE /api/history   -> clear prediction history

Milestone 8A.1 — Authentication (session-cookie based)
------------------------------------------------------
POST   /api/auth/signup -> {name, email, password[, confirm]} -> creates the
                          account (Werkzeug password hash) and signs in
POST   /api/auth/login  -> {email, password} -> generic error on failure
POST   /api/auth/logout -> destroys the server session
GET    /api/auth/me     -> {authenticated, user?} for the startup session check
GET    /api/health stays public; /api/predict, /api/predict-url and
/api/history (GET/DELETE) require an authenticated session (HTTP 401).

Run:  python app.py          (http://localhost:5000)
"""

import functools
import hmac
import json
import os
import re
import secrets
import sqlite3
import sys
import time
from datetime import datetime, timezone

import joblib
import numpy as np
from flask import Flask, g, jsonify, request, session
from flask_cors import CORS
from scipy.sparse import csr_matrix, hstack
from werkzeug.security import check_password_hash, generate_password_hash

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from nlp_pipeline import (NUMERIC_FEATURES, clean_text, detect_red_flags,
                          extract_signals, rule_score)
from input_validation import REJECT_MESSAGE, validate_job_text
import url_fetcher
from url_fetcher import UrlFetchError, analyze_url
from job_sources import service as job_service
from job_sources import alerts as job_alerts
import employer_profiles
import employer_jobs
import employer_screening
from job_sources.matching import APPROVED_SOURCES, MAX_KEYWORDS, MAX_LOCATION

# ------------------------------------------------------------------- Config
BASE_DIR     = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
ARTIFACTS    = os.path.join(PROJECT_ROOT, "models", "artifacts")
MODEL_PATH   = os.path.join(ARTIFACTS, "xgboost_model.joblib")
VECTOR_PATH  = os.path.join(ARTIFACTS, "tfidf_vectorizer.joblib")
META_PATH    = os.path.join(ARTIFACTS, "metadata.joblib")
DB_PATH      = os.path.join(BASE_DIR, "predictions.db")

app = Flask(__name__)
CORS(app)  # allow React dev server (localhost:5173) during development

# ---------------------------------------------- Session/auth configuration
# Milestone 8A.1. The secret key NEVER lives in the repository: it comes from
# the JOBGUARD_SECRET_KEY environment variable. Without it the app falls back
# to an ephemeral random key so local development still works (sessions reset
# on every restart until the variable is set).
_secret_key = os.environ.get("JOBGUARD_SECRET_KEY", "").strip()
if not _secret_key:
    _secret_key = secrets.token_hex(32)
    print("⚠️  JOBGARD_SECRET_KEY not set — using an ephemeral random key "
          "(sessions reset on restart). Set the env var for stable sessions.")
app.config["SECRET_KEY"] = _secret_key
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
# Production-aware: set JOBGUARD_COOKIE_SECURE=true when serving over HTTPS.
app.config["SESSION_COOKIE_SECURE"] = os.environ.get(
    "JOBGUARD_COOKIE_SECURE", "").strip().lower() in {"1", "true", "yes"}

# ------------------------------------------------------- Load model artifacts
model = vectorizer = metadata = None
model_error = None
try:
    model      = joblib.load(MODEL_PATH)
    vectorizer = joblib.load(VECTOR_PATH)
    metadata   = joblib.load(META_PATH) if os.path.exists(META_PATH) else {}
    print(f"✅ Model artifacts loaded (accuracy: {metadata.get('accuracy', 'n/a')})")
except Exception as exc:  # model not trained yet — API still starts
    model_error = str(exc)
    print(f"⚠️  Model artifacts not loaded: {exc}")
    print("    Train first:  cd models && python train_model.py")

# ------------------------------------------------------- History DB (PRD 5.7)
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(_=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()

def init_db():
    with sqlite3.connect(DB_PATH) as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS predictions (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                job_title     TEXT    NOT NULL,
                prediction    TEXT    NOT NULL,
                confidence    REAL    NOT NULL,
                created_at    TEXT    NOT NULL,
                user_id       INTEGER,
                evidence_json TEXT
            )
        """)
        # Existing Milestone 1 databases have no evidence column. Add the
        # nullable column in place so old rows remain readable and valid.
        columns = {row[1] for row in db.execute("PRAGMA table_info(predictions)")}
        if "evidence_json" not in columns:
            db.execute("ALTER TABLE predictions ADD COLUMN evidence_json TEXT")
        # Milestone 8A.2 — per-user prediction history. Fresh databases create
        # the column directly; existing databases are migrated IN PLACE (no
        # drop/recreate): rows are preserved with user_id = NULL, which keeps
        # legacy rows stored but invisible to every authenticated user (they
        # are never reassigned to a new account).
        if "user_id" not in columns:
            db.execute("ALTER TABLE predictions ADD COLUMN user_id INTEGER")
        db.execute(
            "CREATE INDEX IF NOT EXISTS idx_predictions_user_id "
            "ON predictions(user_id)"
        )
        # Milestone 8A.1 — application users (never part of the prediction
        # schema). Only the Werkzeug hash is stored, never a plaintext
        # password and never a password hash in any API response.
        db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                name          TEXT NOT NULL,
                email         TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                created_at    TEXT NOT NULL,
                last_login_at TEXT
            )
        """)
        # Milestone 8B.1 — cached external job postings (Real Job Discovery).
        # DB-backed cache of the two approved public job APIs, normalized to
        # the internal shape; UNIQUE(source, source_job_id) deduplicates.
        db.execute("""
            CREATE TABLE IF NOT EXISTS external_jobs (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                source        TEXT    NOT NULL,
                source_job_id TEXT    NOT NULL,
                title         TEXT    NOT NULL,
                company       TEXT,
                location      TEXT,
                description   TEXT,
                job_type      TEXT,
                remote        INTEGER NOT NULL DEFAULT 0,
                tags_json     TEXT,
                salary        TEXT,
                job_url       TEXT,
                published_at  TEXT,
                fetched_at    TEXT    NOT NULL,
                UNIQUE(source, source_job_id)
            )
        """)

    # Milestone 8B.2 — per-user preferences + in-app notifications.
    job_alerts.ensure_tables(DB_PATH)

    # Milestone 8C.1 — employer registration (one profile per user, no
    # credentials stored; an extension of the existing account, not a
    # second authentication system).
    employer_profiles.ensure_table(DB_PATH)

    # Milestone 8C.2 — employer job drafts (separate table from external_jobs;
    # status is always 'draft' in this milestone — publishing comes later).
    employer_jobs.ensure_table(DB_PATH)

    # Milestone 8C.3A — AI safety screenings for employer drafts (own table,
    # never in the normal predictions/history).
    employer_screening.ensure_table(DB_PATH)


init_db()  # ensure table exists and old databases are migrated at startup

# ------------------------------------------------------- Authentication 8A.1
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

def _normalize_email(raw):
    """Lowercase/trim an email so comparison and storage are normalized."""
    return raw.strip().lower() if isinstance(raw, str) else ""

def _password_problems(password):
    """Return a list of human-readable failures for a candidate password."""
    problems = []
    if not isinstance(password, str) or len(password) < 8:
        problems.append("Password must be at least 8 characters long.")
        return problems
    if not re.search(r"[A-Z]", password):
        problems.append("Password must contain at least one uppercase letter.")
    if not re.search(r"[a-z]", password):
        problems.append("Password must contain at least one lowercase letter.")
    if not re.search(r"[0-9]", password):
        problems.append("Password must contain at least one number.")
    return problems

def _public_user(row):
    """The ONLY user shape ever returned by the API (never the hash)."""
    return {"id": row["id"], "name": row["name"], "email": row["email"]}

def _current_user_row():
    """Resolve the session identity to a users row, or None."""
    user_id = session.get("user_id")
    if not isinstance(user_id, int):
        return None
    row = get_db().execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if row is None:
        session.clear()  # stale session (user row vanished) — drop it
    return row

def require_auth(view):
    """Server-side gate for protected APIs. Anonymous calls get HTTP 401."""
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if _current_user_row() is None:
            return jsonify({
                "error": "Authentication required. Please sign in.",
                "authenticated": False,
            }), 401
        return view(*args, **kwargs)
    return wrapped

def _csrf_token():
    """Session-bound CSRF token (created lazily, lives in the session only)."""
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_hex(32)
        session["csrf_token"] = token
    return token

def require_csrf(view):
    """Reject authenticated state-changing calls without a valid CSRF token.

    The token is issued inside the session (returned by /api/auth/me and the
    signup/login responses) and must be echoed in the X-CSRF-Token header.
    """
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        sent = request.headers.get("X-CSRF-Token", "")
        expected = session.get("csrf_token", "")
        if not expected or not hmac.compare_digest(sent, expected):
            return jsonify({
                "error": "Invalid or missing CSRF token.",
                "csrf_error": True,
            }), 403
        return view(*args, **kwargs)
    return wrapped

@app.post("/api/auth/signup")
def auth_signup():
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        data = {}

    name = (data.get("name") or "").strip() if isinstance(data.get("name"), str) else ""
    email = _normalize_email(data.get("email"))
    password = data.get("password")
    confirm = data.get("confirm")

    field_errors = {}
    if not name:
        field_errors["name"] = "Please enter your full name."
    elif len(name) > 120:
        field_errors["name"] = "Name is too long (max 120 characters)."
    if not email or not _EMAIL_RE.match(email) or len(email) > 200:
        field_errors["email"] = "Please enter a valid email address."
    pw_problems = _password_problems(password)
    if pw_problems:
        field_errors["password"] = " ".join(pw_problems)
    if confirm is not None and confirm != password:
        field_errors["confirm"] = "Passwords do not match."
    if field_errors:
        return jsonify({
            "error": next(iter(field_errors.values())),
            "field_errors": field_errors,
        }), 400

    if get_db().execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
        return jsonify({
            "error": "An account with this email already exists.",
            "field": "email",
            "field_errors": {"email": "An account with this email already exists."},
        }), 409

    now = datetime.now(timezone.utc).isoformat()
    cur = get_db().execute(
        "INSERT INTO users (name, email, password_hash, created_at, last_login_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (name, email, generate_password_hash(password), now, now),
    )
    get_db().commit()
    session.clear()
    session["user_id"] = cur.lastrowid
    csrf = _csrf_token()
    row = get_db().execute("SELECT * FROM users WHERE id = ?", (cur.lastrowid,)).fetchone()
    return jsonify({"authenticated": True, "user": _public_user(row), "csrf_token": csrf}), 201

@app.post("/api/auth/login")
def auth_login():
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        data = {}
    email = _normalize_email(data.get("email"))
    password = data.get("password")

    generic = {"error": "Invalid email or password."}
    if not email or not isinstance(password, str):
        return jsonify(generic), 401
    row = get_db().execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    # Same generic response whether the email exists or the password is wrong,
    # so the endpoint never reveals which emails are registered.
    if row is None or not check_password_hash(row["password_hash"], password):
        return jsonify(generic), 401

    get_db().execute(
        "UPDATE users SET last_login_at = ? WHERE id = ?",
        (datetime.now(timezone.utc).isoformat(), row["id"]),
    )
    get_db().commit()
    session.clear()
    session["user_id"] = row["id"]
    csrf = _csrf_token()
    return jsonify({"authenticated": True, "user": _public_user(row), "csrf_token": csrf})

@app.post("/api/auth/logout")
@require_csrf
def auth_logout():
    session.clear()
    return jsonify({"authenticated": False})

@app.get("/api/auth/me")
def auth_me():
    row = _current_user_row()
    if row is None:
        return jsonify({"authenticated": False})
    return jsonify({"authenticated": True, "user": _public_user(row), "csrf_token": _csrf_token()})

# --------------------------------------------------------------- Prediction
def build_features(raw_text: str):
    """Exactly mirrors training: TF-IDF on cleaned text + numeric signals."""
    cleaned = clean_text(raw_text)
    signals = extract_signals(raw_text)
    X_text   = vectorizer.transform([cleaned])
    X_num    = csr_matrix([[signals[f] for f in NUMERIC_FEATURES]], dtype=np.float32)
    X = hstack([X_text, X_num]).tocsr()
    return X, signals

def predict_one(job_text: str, title: str) -> dict:
    t0 = time.perf_counter()
    X, signals = build_features(job_text)

    proba = model.predict_proba(X)[0]          # [P(legit), P(scam)]
    xgb_legit, xgb_scam = float(proba[0]), float(proba[1])

    # HYBRID ENGINE: XGBoost learned dataset wording; the weighted rule
    # layer captures scam behavior and generalizes to novel phrasings.
    # Evidence is combined with noisy-OR:  P = 1-(1-xgb)(1-rule)
    # (standard for independent sources; also keeps outputs continuous,
    # avoiding suspiciously round numbers like exactly 90.00%).
    flags  = detect_red_flags(job_text, signals)
    rscore = rule_score(flags)
    p_scam  = 1.0 - (1.0 - xgb_scam) * (1.0 - rscore)
    p_legit = 1.0 - p_scam
    is_scam = p_scam >= 0.5

    latency_ms = (time.perf_counter() - t0) * 1000
    result = {
        "job_title":  title,
        "prediction": "Scam" if is_scam else "Legitimate",
        "label":      int(is_scam),
        "confidence": round(p_scam if is_scam else p_legit, 4),
        "probabilities": {
            "scam":       round(p_scam, 4),
            "legitimate": round(p_legit, 4),
        },
        "engine": {   # transparent breakdown for reports / viva
            "xgboost_scam_prob":  round(xgb_scam, 4),
            "rule_scam_score":    round(rscore, 4),
            "final": "noisy_or(xgboost, rules)",
        },
        "red_flags":  flags,
        "signals":    signals,
        "latency_ms": round(latency_ms, 1),   # PRD: prediction < 2 s
    }
    return result

# ------------------------------------------------------------------- Routes
def _store_history(result: dict, user_id=None) -> None:
    """PRD 5.7 — store a completed prediction in history (unchanged schema)."""
    db = get_db()
    db.execute(
        "INSERT INTO predictions "
        "(job_title, prediction, confidence, created_at, evidence_json, user_id) "
        "VALUES (?,?,?,?,?,?)",
        (result["job_title"], result["prediction"], result["confidence"],
         datetime.now(timezone.utc).isoformat(),
         json.dumps(result.get("red_flags", []), ensure_ascii=False),
         user_id),
    )
    db.commit()

@app.get("/api/jobs")
@require_auth
def list_jobs():
    """Milestone 8B.1 — real external job discovery (cached, read-only).

    Query params: q, location, source (remoteok|arbeitnow), remote=true, page.
    Jobs come from the DB-backed cache in external_jobs; providers are
    refreshed server-side only when stale (20-minute window), with per-provider
    failure isolation and stale-cache fallback.
    """
    q = (request.args.get("q") or "").strip()[:100]
    location = (request.args.get("location") or "").strip()[:100]
    source = (request.args.get("source") or "").strip().lower()
    remote = request.args.get("remote", "").lower() == "true"
    try:
        page = max(1, int(request.args.get("page", 1)))
    except ValueError:
        page = 1

    # Milestone 8C.3B — published JobGuard jobs join the SAME feed, without
    # touching external_jobs. Only status='published' employer rows are ever
    # returned here; draft/flagged/ready stay private to the employer.
    employer_jobs.ensure_table(DB_PATH)
    if source == "jobguard":
        listings = employer_jobs.public_listings(DB_PATH, q=q or None,
                                                 location=location or None,
                                                 remote=remote)
        total = len(listings)
        start = (page - 1) * job_service.PAGE_SIZE
        return jsonify({
            "jobs": listings[start:start + job_service.PAGE_SIZE],
            "total": total,
            "page": page,
            "page_size": job_service.PAGE_SIZE,
            "pages": max(1, -(-total // job_service.PAGE_SIZE)),
            "cache": None,  # no external provider refresh for this filter
        })

    fetch_all = source == "" and not remote
    result = job_service.get_jobs(
        DB_PATH, q=q or None, location=location or None,
        source=source or None, remote=remote, page=1,
        limit=10 ** 6 if fetch_all else None,
    )
    if not fetch_all:
        # explicit external provider filter (or remote-only): 8B.1 behavior
        return jsonify(result)

    external_jobs = result["jobs"]
    guard_jobs = employer_jobs.public_listings(DB_PATH, q=q or None,
                                               location=location or None)
    combined = sorted(
        external_jobs + guard_jobs,
        key=lambda j: ((j.get("published_at") or ""), j.get("id") or 0),
        reverse=True,
    )
    total = result["total"] + len(guard_jobs)
    start = (page - 1) * job_service.PAGE_SIZE
    return jsonify({
        "jobs": combined[start:start + job_service.PAGE_SIZE],
        "total": total,
        "page": page,
        "page_size": job_service.PAGE_SIZE,
        "pages": max(1, -(-total // job_service.PAGE_SIZE)),
        "cache": result["cache"],
    })


# ---------------------------------------------------------------------------
# Milestone 8B.2 — personalized job preferences + in-app notifications
# ---------------------------------------------------------------------------

@app.get("/api/job-preferences")
@require_auth
def read_job_preferences():
    """The signed-in user's saved job preferences (or null when unset)."""
    prefs = job_alerts.get_preferences(DB_PATH, _current_user_row()["id"])
    return jsonify({"preferences": prefs})


@app.put("/api/job-preferences")
@require_auth
@require_csrf
def save_job_preferences():
    """Create/update the caller's single active preference record.

    Validates server-side: trimmed strings, maximum lengths, approved source
    values, boolean remote_only. UNIQUE(user_id) guarantees a user can only
    ever store their own record. Saving also runs a safe catch-up match over
    recently cached jobs so alerts start immediately (deduped, capped).
    """
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        data = {}
    keywords = (data.get("keywords") or "").strip()
    location = (data.get("location") or "").strip()
    remote_only = bool(data.get("remote_only"))
    source = (data.get("source") or "any").strip().lower()

    if len(keywords) > MAX_KEYWORDS:
        return jsonify({"error": f"Keywords are too long (max {MAX_KEYWORDS} characters)."}), 400
    if len(location) > MAX_LOCATION:
        return jsonify({"error": f"Location is too long (max {MAX_LOCATION} characters)."}), 400
    if source not in APPROVED_SOURCES:
        return jsonify({"error": "Source must be one of: any, remoteok, arbeitnow."}), 400

    prefs = job_alerts.save_preferences(
        DB_PATH, _current_user_row()["id"],
        keywords=keywords, location=location,
        remote_only=remote_only, source=source,
    )
    matched = job_alerts.run_user_matching(DB_PATH, _current_user_row()["id"])
    return jsonify({"preferences": prefs, "matched_cached_jobs": matched})


@app.get("/api/notifications")
@require_auth
def list_notifications():
    """The caller's notifications, newest first, plus unread count.

    Opening the list also runs the safe catch-up match over recently cached
    jobs (deduped by UNIQUE(user_id, external_job_id), capped), so existing
    cached jobs can still surface. Rows always filter by the session user_id.
    """
    user_id = _current_user_row()["id"]
    job_alerts.ensure_tables(DB_PATH)
    job_alerts.run_user_matching(DB_PATH, user_id)
    body = job_alerts.list_notifications(DB_PATH, user_id)
    body["has_preferences"] = job_alerts.get_preferences(DB_PATH, user_id) is not None
    return jsonify(body)


@app.get("/api/notifications/unread-count")
@require_auth
def notifications_unread_count():
    """Unread badge count, scoped to the signed-in user."""
    job_alerts.ensure_tables(DB_PATH)
    return jsonify({"unread": job_alerts.unread_count(DB_PATH, _current_user_row()["id"])})


@app.post("/api/notifications/<int:notification_id>/read")
@require_auth
@require_csrf
def notification_mark_read(notification_id):
    """Mark one of the caller's notifications read.

    The UPDATE is filtered by user_id AND id, so User A marking User B's
    notification id is a 404, never a modification.
    """
    ok = job_alerts.mark_read(DB_PATH, _current_user_row()["id"], notification_id)
    if not ok:
        return jsonify({"error": "Notification not found."}), 404
    return jsonify({
        "ok": True,
        "unread": job_alerts.unread_count(DB_PATH, _current_user_row()["id"]),
    })


@app.post("/api/notifications/read-all")
@require_auth
@require_csrf
def notifications_mark_all_read():
    """Mark every notification of the caller read (user-scoped UPDATE)."""
    marked = job_alerts.mark_all_read(DB_PATH, _current_user_row()["id"])
    return jsonify({"ok": True, "marked": marked, "unread": 0})


# ---------------------------------------------------------------------------
# Milestone 8C.1 — employer registration (registration only; no job posting)
# ---------------------------------------------------------------------------

def _employer_payload_response(profile):
    return jsonify({"profile": profile})


@app.get("/api/employer-profile")
@require_auth
def read_employer_profile():
    """The signed-in user's employer profile, or null when not registered."""
    employer_profiles.ensure_table(DB_PATH)
    profile = employer_profiles.get_profile(DB_PATH, _current_user_row()["id"])
    return _employer_payload_response(profile)


@app.post("/api/employer-profile")
@require_auth
@require_csrf
def create_employer_profile():
    """Register the caller's employer profile (one per user, ever).

    This is REGISTRATION ONLY: no job is created or published, and no third
    party has verified the company. Ownership is the session's user_id —
    UNIQUE(user_id) rejects a second profile for the same account.
    """
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        data = {}
    clean, field_errors = employer_profiles.validate_profile_data(data)
    if field_errors:
        return jsonify({
            "error": next(iter(field_errors.values())),
            "field_errors": field_errors,
        }), 400

    profile, err = employer_profiles.create_profile(DB_PATH, _current_user_row()["id"], clean)
    if err == "duplicate":
        return jsonify({"error": "An employer profile already exists for this account."}), 409
    return _employer_payload_response(profile), 201


@app.put("/api/employer-profile")
@require_auth
@require_csrf
def update_employer_profile():
    """Update the caller's existing employer profile in place.

    The UPDATE is filtered by the session user_id: id, user_id and
    created_at are preserved, updated_at refreshed. A second profile can
    never be created through this route; users without a profile get 404.
    """
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        data = {}
    clean, field_errors = employer_profiles.validate_profile_data(data)
    if field_errors:
        return jsonify({
            "error": next(iter(field_errors.values())),
            "field_errors": field_errors,
        }), 400

    profile, err = employer_profiles.update_profile(DB_PATH, _current_user_row()["id"], clean)
    if err == "missing":
        return jsonify({"error": "No employer profile to update. Please register first."}), 404
    return _employer_payload_response(profile)


# ---------------------------------------------------------------------------
# Milestone 8C.2 — employer job drafts (create/edit/delete/manage; the status
# is ALWAYS 'draft' here — publishing belongs to a later milestone)
# ---------------------------------------------------------------------------

def _current_employer_profile():
    """(profile, error_response): the caller must have an employer profile."""
    profile = employer_profiles.get_profile(DB_PATH, _current_user_row()["id"])
    if profile is None:
        return None, (jsonify({
            "error": "An employer profile is required. Please register as an employer first.",
        }), 403)
    return profile, None


@app.get("/api/employer-jobs")
@require_auth
def list_employer_jobs():
    """The caller's own job drafts, newest update first."""
    employer_jobs.ensure_table(DB_PATH)
    profile, err = _current_employer_profile()
    if err:
        return err
    jobs = employer_jobs.list_jobs(DB_PATH, profile["id"])
    return jsonify({"jobs": jobs, "count": len(jobs)})


@app.post("/api/employer-jobs")
@require_auth
@require_csrf
def create_employer_job():
    """Create a job draft for the signed-in employer.

    Validation errors return 400 with a field_errors map. The status is set
    to 'draft' by the backend and any client-supplied status value is ignored
    — it can never be 'published' through this endpoint.
    """
    employer_jobs.ensure_table(DB_PATH)
    profile, err = _current_employer_profile()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        data = {}
    clean, field_errors = employer_jobs.validate_job_data(data)
    if field_errors:
        return jsonify({
            "error": next(iter(field_errors.values())),
            "field_errors": field_errors,
        }), 400
    job = employer_jobs.create_job(DB_PATH, profile["id"], clean)
    return jsonify({"job": job}), 201


@app.get("/api/employer-jobs/<int:job_id>")
@require_auth
def read_employer_job(job_id):
    """One of the caller's drafts. Another employer's id is a plain 404 —
    identical to a missing row, so no ownership information is revealed."""
    employer_jobs.ensure_table(DB_PATH)
    profile, err = _current_employer_profile()
    if err:
        return err
    job = employer_jobs.get_job(DB_PATH, job_id, profile["id"])
    if job is None:
        return jsonify({"error": "Job draft not found."}), 404
    return jsonify({"job": job})


@app.put("/api/employer-jobs/<int:job_id>")
@require_auth
@require_csrf
def update_employer_job(job_id):
    """Edit the caller's own draft in place (id, employer_profile_id and
    created_at preserved; updated_at refreshed; status stays 'draft').
    A foreign or missing id is the same 404."""
    employer_jobs.ensure_table(DB_PATH)
    profile, err = _current_employer_profile()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        data = {}
    clean, field_errors = employer_jobs.validate_job_data(data)
    if field_errors:
        return jsonify({
            "error": next(iter(field_errors.values())),
            "field_errors": field_errors,
        }), 400
    job = employer_jobs.update_job(DB_PATH, job_id, profile["id"], clean)
    if job is None:
        return jsonify({"error": "Job draft not found."}), 404
    return jsonify({"job": job})


@app.delete("/api/employer-jobs/<int:job_id>")
@require_auth
@require_csrf
def delete_employer_job(job_id):
    """Delete the caller's own draft. A foreign or missing id is the same
    404, and deleting never touches another employer's rows."""
    employer_jobs.ensure_table(DB_PATH)
    profile, err = _current_employer_profile()
    if err:
        return err
    deleted = employer_jobs.delete_job(DB_PATH, job_id, profile["id"])
    if not deleted:
        return jsonify({"error": "Job draft not found."}), 404
    return jsonify({"ok": True})


@app.post("/api/employer-jobs/<int:job_id>/screen")
@require_auth
@require_csrf
def screen_employer_job(job_id):
    """Run the EXISTING JobGuard engine on the caller's own draft.

    The screening text is composed from the draft fields plus the employer's
    company name (empty optionals skipped) and passed unchanged through the
    same predict_one() path as /api/predict — preprocessing, TF-IDF, 11
    numeric features, XGBoost, 9 red-flag rules, noisy-OR and the 0.5
    threshold are all reused; there is no new classifier or threshold.

    Verdict mapping (1:1 with the engine): Legitimate -> 'ready',
    Scam -> 'flagged'. The screening is stored in its own audit table — it
    never touches the normal predictions table, so employer screening never
    appears in History or Insights. Publishing is NOT part of this milestone.
    Foreign/missing job -> 404.
    """
    employer_jobs.ensure_table(DB_PATH)
    employer_screening.ensure_table(DB_PATH)
    profile, err = _current_employer_profile()
    if err:
        return err
    job = employer_jobs.get_job(DB_PATH, job_id, profile["id"])
    if job is None:
        return jsonify({"error": "Job draft not found."}), 404

    screening_text = employer_screening.compose_screening_text(job, profile)
    result = predict_one(screening_text, job["title"])  # unchanged existing engine

    new_status = "flagged" if result["prediction"] == "Scam" else "ready"
    with sqlite3.connect(DB_PATH) as db:
        db.execute(
            "UPDATE employer_jobs SET status = ? WHERE id = ? AND employer_profile_id = ?",
            (new_status, job_id, profile["id"]),
        )
        db.commit()

    screening = employer_screening.record_screening(
        DB_PATH, job_id, result,
        text_hash=employer_screening.content_hash(screening_text),
    )
    updated_job = employer_jobs.get_job(DB_PATH, job_id, profile["id"])
    return jsonify({
        "job": updated_job,
        "screening": screening,
        "status": new_status,
        "text_chars": len(screening_text),
    })


@app.get("/api/employer-jobs/<int:job_id>/screening")
@require_auth
def read_employer_job_screening(job_id):
    """The latest safety screening (with evidence) for the caller's own job.

    Ownership-scoped like every other employer-jobs route: a foreign job is
    the same 404, so no screening data of another employer is ever revealed.
    Read-only, so no CSRF is required.
    """
    employer_jobs.ensure_table(DB_PATH)
    employer_screening.ensure_table(DB_PATH)
    profile, err = _current_employer_profile()
    if err:
        return err
    job = employer_jobs.get_job(DB_PATH, job_id, profile["id"])
    if job is None:
        return jsonify({"error": "Job draft not found."}), 404
    screening = employer_screening.latest_screening(DB_PATH, job_id)
    if screening is None:
        return jsonify({"error": "This job has not been screened yet."}), 404
    return jsonify({"job_id": job_id, "screening": screening})


@app.post("/api/employer-jobs/<int:job_id>/publish")
@require_auth
@require_csrf
def publish_employer_job(job_id):
    """Milestone 8C.3B — publish the caller's own screened job.

    Explicit, employer-only action. Eligibility (all enforced here, never by
    the client): authenticated user, employer profile, ownership (foreign or
    missing -> 404), valid CSRF, status == 'ready', and a latest screening
    whose recorded text hash still matches the CURRENT job content (a pass on
    old text never publishes new text). Success sets status='published' and
    published_at (UTC); the job then appears in the public /api/jobs feed.
    """
    employer_jobs.ensure_table(DB_PATH)
    employer_screening.ensure_table(DB_PATH)
    profile, err = _current_employer_profile()
    if err:
        return err
    job = employer_jobs.get_job(DB_PATH, job_id, profile["id"])
    if job is None:
        return jsonify({"error": "Job draft not found."}), 404

    if job["status"] != "ready":
        return jsonify({
            "error": "Only a job whose safety check passed can be published."
                     " Run the Safety Check first."
        }), 409

    latest = employer_screening.latest_screening(DB_PATH, job_id)
    if latest is None:
        return jsonify({"error": "No safety screening was found for this job."}), 409

    current_text = employer_screening.compose_screening_text(job, profile)
    recorded_hash = latest.get("text_hash")
    if recorded_hash and recorded_hash != employer_screening.content_hash(current_text):
        return jsonify({
            "error": "The safety screening is out of date — the job changed"
                     " after it was screened. Run the Safety Check again."
        }), 409

    published_at = employer_screening.now_iso()
    if not employer_jobs.publish_job(DB_PATH, job_id, profile["id"], published_at):
        return jsonify({"error": "Only a job whose safety check passed can be"
                                 " published."}), 409
    updated_job = employer_jobs.get_job(DB_PATH, job_id, profile["id"])
    return jsonify({"job": updated_job, "published_at": published_at})


@app.get("/api/health")
def health():
    return jsonify({
        "status": "ok",
        "model_loaded": model is not None,
        "model_error": model_error,
        "metrics": {
            "accuracy": metadata.get("accuracy"),
            "roc_auc":  metadata.get("roc_auc"),
        } if metadata else None,
    })

@app.post("/api/predict")
@require_auth
@require_csrf
def predict():
    if model is None:
        return jsonify({"error": "Model not trained. Run models/train_model.py first."}), 503

    data = request.get_json(silent=True) or {}
    # A valid request body must be a JSON object. Treat other JSON values like
    # an empty malformed submission so the existing validation response is
    # returned instead of raising AttributeError and producing HTTP 500.
    if not isinstance(data, dict):
        data = {}
    raw_job_text = data.get("job_text")
    job_text = raw_job_text.strip() if isinstance(raw_job_text, str) else ""
    raw_title = data.get("title")
    title = raw_title.strip()[:200] if isinstance(raw_title, str) else "Untitled job"

    # ---- Job-Post Input Validation (application-level gate) -----------------
    # Runs BEFORE preprocessing / feature extraction / XGBoost. Rejected input
    # returns immediately and predict_one() (and the SQLite history insert) is
    # never reached for it.
    is_valid, reason = validate_job_text(job_text)
    if not is_valid:
        return jsonify({
            "invalid_input": True,
            "error": REJECT_MESSAGE,
            "reason": reason,
        }), 400

    if len(job_text) > 50_000:
        return jsonify({"error": "Job description too long (max 50,000 chars)."}), 400

    result = predict_one(job_text, title)
    _store_history(result, session.get("user_id"))

    return jsonify(result)


@app.post("/api/predict-url")
@require_auth
@require_csrf
def predict_url():
    """Milestone 7B — analyze a public job-posting URL.

    Architecture (no second prediction system):
        URL -> url_fetcher.analyze_url (SSRF-validated fetch + text extraction)
            -> existing validate_job_text()
            -> existing predict_one()  (XGBoost + hybrid engine, untouched)
            -> existing history insert (unchanged SQLite schema)
    """
    if model is None:
        return jsonify({"error": "Model not trained. Run models/train_model.py first."}), 503

    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        data = {}
    raw_url = data.get("url")
    url = raw_url.strip() if isinstance(raw_url, str) else ""
    if not url:
        return jsonify({"error": "Please paste a job posting URL.", "url_error": "invalid_url"}), 400

    raw_title = data.get("title")
    title = raw_title.strip()[:200] if isinstance(raw_title, str) else ""

    # ---- SSRF-protected fetch + readable text extraction -------------------
    try:
        page = analyze_url(url)
    except UrlFetchError as exc:
        # Nothing was fetched for blocked/private URLs (rejected pre-flight),
        # and no prediction/history ever runs for URL failures.
        return jsonify({"error": exc.message, "url_error": exc.kind}), 400

    job_text = page["text"].strip()

    # ---- the SAME job-post validation gate as text mode --------------------
    is_valid, reason = validate_job_text(job_text)
    if not is_valid:
        return jsonify({
            "invalid_input": True,
            "error": REJECT_MESSAGE,
            "reason": reason,
            "url_error": "not_job_like",
        }), 400

    if len(job_text) > 50_000:
        return jsonify({"error": "Extracted job description too long (max 50,000 chars)."}), 400

    # Fall back to the page <title> / host for the history record title.
    if not title:
        title = (page["title"] or "").strip()[:200] or "Job posting from URL"

    result = predict_one(job_text, title)
    _store_history(result, session.get("user_id"))

    return jsonify(result)


@app.get("/api/history")
@require_auth
def history():
    limit = min(int(request.args.get("limit", 50)), 200)
    rows = get_db().execute(
        "SELECT id, job_title, prediction, confidence, created_at, evidence_json "
        "FROM predictions WHERE user_id = ? ORDER BY id DESC LIMIT ?",
        (session.get("user_id"), limit),
    ).fetchall()
    history_rows = []
    for row in rows:
        item = dict(row)
        raw_evidence = item.pop("evidence_json", None)
        try:
            item["evidence"] = json.loads(raw_evidence) if raw_evidence else []
        except (TypeError, json.JSONDecodeError):
            # Keep old/corrupt rows usable without failing the whole history.
            item["evidence"] = []
        history_rows.append(item)
    return jsonify(history_rows)

@app.delete("/api/history")
@require_auth
@require_csrf
def clear_history():
    db = get_db()
    db.execute("DELETE FROM predictions WHERE user_id = ?", (session.get("user_id"),))
    db.commit()
    return jsonify({"cleared": True})


# Warm up the model so the FIRST real prediction also meets PRD's <2s NFR
if model is not None:
    _WARM = ("Software Engineer needed. 5+ years experience. Health insurance, "
             "provident fund, annual bonus. Apply via careers portal.")
    predict_one(_WARM, "warmup")
    print("✅ Warm-up prediction done")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
