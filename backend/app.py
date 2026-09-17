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
