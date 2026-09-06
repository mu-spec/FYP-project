"""
Phase 2 — Flask Backend (PRD §12 Application Layer)
===================================================
REST API that serves the XGBoost job scam classifier.

Endpoints
---------
GET    /api/health    -> service + model status (for frontend status pill)
POST   /api/predict   -> {job_text, title} -> prediction, confidence,
                          probabilities, red flags, extracted signals
                          (returns invalid_input=true 400 when the text is
                           rejected by the pre-ML job-post validator)
GET    /api/history   -> last N predictions (PRD 5.7)
DELETE /api/history   -> clear prediction history

Run:  python app.py          (http://localhost:5000)
"""

import os
import sqlite3
import sys
import time
from datetime import datetime, timezone

import joblib
import numpy as np
from flask import Flask, g, jsonify, request
from flask_cors import CORS
from scipy.sparse import csr_matrix, hstack

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from nlp_pipeline import (NUMERIC_FEATURES, clean_text, detect_red_flags,
                          extract_signals, rule_score)
from input_validation import REJECT_MESSAGE, validate_job_text

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
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                job_title   TEXT    NOT NULL,
                prediction  TEXT    NOT NULL,
                confidence  REAL    NOT NULL,
                created_at  TEXT    NOT NULL
            )
        """)

init_db()  # ensure table exists at startup

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
def predict():
    if model is None:
        return jsonify({"error": "Model not trained. Run models/train_model.py first."}), 503

    data = request.get_json(silent=True) or {}
    job_text = (data.get("job_text") or "").strip()
    title    = (data.get("title") or "Untitled job").strip()[:200]

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

    # PRD 5.7 — store prediction history
    db = get_db()
    db.execute(
        "INSERT INTO predictions (job_title, prediction, confidence, created_at) VALUES (?,?,?,?)",
        (result["job_title"], result["prediction"], result["confidence"],
         datetime.now(timezone.utc).isoformat()),
    )
    db.commit()

    return jsonify(result)

@app.get("/api/history")
def history():
    limit = min(int(request.args.get("limit", 50)), 200)
    rows = get_db().execute(
        "SELECT id, job_title, prediction, confidence, created_at "
        "FROM predictions ORDER BY id DESC LIMIT ?", (limit,),
    ).fetchall()
    return jsonify([dict(r) for r in rows])

@app.delete("/api/history")
def clear_history():
    db = get_db()
    db.execute("DELETE FROM predictions")
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
