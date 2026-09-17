🛡️ AI-Based Job Scam Detection (FYP)
Machine-learning system that classifies a pasted job advertisement as
Scam or Legitimate, with confidence scores, a probability scale and
explainable red-flag indicators.

📁 Project Structure (matches PRD phases)
text

ai-job-scam-detector/
├── frontend/                      # PHASE 1 — React.js + Vite UI
│   ├── src/
│   │   ├── App.jsx                #    app shell + API wiring
│   │   ├── api.js                 #    REST client (/api/*)
│   │   ├── styles.css             #    responsive design system
│   │   └── components/
│   │       ├── Header.jsx         #    status pill (API/model state)
│   │       ├── Home.jsx            #    PRD 5.1  home + direct one-click analysis
│   │       ├── JobInput.jsx        #    PRD 5.2  job input module
│   │       ├── ResultCard.jsx      #    PRD 5.5/5.6 results, risk scale, evidence
│   │       └── History.jsx         #    PRD 5.7  history table + saved evidence
│   └── package.json
│
├── backend/                       # PHASE 2 — Flask REST API
│   ├── app.py                     #    endpoints + hybrid prediction engine
│   ├── nlp_pipeline.py            #    SHARED: PRD 5.3 cleaning, 5.4 features,
│   │                              #          5.6 red-flag rules (single source
│   │                              #          of truth for training + serving)
│   ├── predictions.db             #    SQLite history (auto-created)
│   └── requirements.txt
│
├── models/                        # PHASE 3 — ML training
│   ├── train_model.py             #    PRD §7 full pipeline trainer
│   ├── augment.py                 #    generalization augmentation + probes
│   ├── artifacts/                 #    xgboost_model.joblib, tfidf_vectorizer.joblib,
│   │                              #    metadata.joblib  (PRD: Joblib storage)
│   └── reports/
│       ├── metrics.json           #    PRD §10 all metrics + probes
│       ├── confusion_matrix.png
│       └── roc_curve.png
│
└── data/
    ├── raw/combined_job_scam_dataset.csv.gz   # 27,014 rows (source)
    ├── raw/DATASET_SOURCE.md
    └── processed/job_scam_clean.csv.gz        # cleaned snapshot
🚀 How to Run
Bash

# 1) Train (reproduces artifacts + reports)
cd models && python train_model.py

# 2) Backend  →  http://localhost:5000
cd backend && pip install -r requirements.txt && python app.py

# 3) Frontend → http://localhost:5173
cd frontend && npm install && npm run dev

Current analysis flow
---------------------
Home submits a valid pasted job post once and opens the result-only Analyze
view. The Analyze tab remains available for direct/manual submissions. Each
valid prediction is saved with its title, verdict, confidence, timestamp and
evidence map; the original full job description is intentionally not stored.

🧾 Technical summary
--------------------
The React/Vite frontend provides Home, direct/manual Analyze, Result, History,
Insights and About screens. The Python/Flask backend validates job-shaped text,
combines the existing XGBoost classifier's TF-IDF output with the existing
numeric signals and deterministic red-flag evidence, and stores valid result
summaries plus evidence in SQLite. No training or prediction occurs for
rejected input.

🎬 Final FYP demo examples
--------------------------
These examples are documentation-only. Paste each one exactly as shown; they
are not hard-coded into the application and do not change the model.

DEMO 1 — Clear scam
Earn $9,000 EVERY WEEK working from home! No experience needed. Immediate hiring! Just pay a $99 registration fee via Easypaisa. Email hiring.manager2024@gmail.com NOW. Act fast!
Expected current result: Scam; scam probability 98.09%; confidence 98.09%; four flags: FREE WEBMAIL, UPFRONT PAYMENT, URGENCY PRESSURE and EXCESSIVE PUNCTUATION.

DEMO 2 — Clear legitimate
We are hiring a backend engineer to join our product team. You will design APIs, review code, collaborate with designers, and improve application reliability. The role includes a clear development plan, paid leave, and access to health coverage. Candidates should share a portfolio and describe relevant projects.
Expected current result: Legitimate; scam probability 0.07%; confidence 99.93%; no red flags.

DEMO 3 — Borderline / educational
Customer Support Agent needed! Apply now! Join our company team and help customers!!! Requirements: communication skills, training provided, paid salary.
Expected current result: Legitimate; scam probability 38.30%; confidence 61.70%; one flag: EXCESSIVE PUNCTUATION.

🖥️ Exact live-demo procedure
-----------------------------
Use two terminals from the project root:

Terminal 1 — backend:
cd backend && python3 app.py

Terminal 2 — frontend:
cd frontend && npm install && npm run dev -- --host 0.0.0.0

Then open http://localhost:5173 and:
1. Open Home.
2. Paste DEMO 1 and click Analyze once.
3. Explain the Scam classification, probability and confidence.
4. Show the red flags and Evidence Map snippets.
5. Open History and show the saved result/evidence.
6. Return to Home or Analyze.
7. Paste DEMO 2 in the manual Analyze flow and compare the Legitimate result.
8. Use DEMO 3 only if a borderline/educational contrast is useful.

🧯 Demo recovery
----------------
- Backend not running: start Terminal 1 and refresh the browser.
- Port already in use: press Ctrl+C in the terminal that owns the prior demo process; do not stop an unknown process.
- Frontend cannot reach backend: confirm http://localhost:5000/api/health returns status ok, then restart the frontend from the frontend directory.
- Model fails to load: read the backend terminal error and verify the existing files under models/artifacts; do not retrain during the presentation.
- Browser needs refreshing: refresh the page. A refreshed Analyze route is intentionally manual, so paste the job again if needed.
- Old History records: use the visible Clear history action before the demo, then confirm the empty-history state.

🤖 Model (PRD §9) and the Hybrid Prediction Engine
XGBoost classifier on TF-IDF (10k features, 1–2 grams) + 11 engineered
scam signals (email/URL/phone counts, currency marks, salary mention,
capital %, exclamations, urgency keywords, text stats).
Test-set results (20% stratified hold-out): Accuracy 1.00, F1 1.00,
ROC-AUC 1.00 — see 
metrics.json
.
⚠️ Honest note on generalization (great viva talking point!)
The source dataset's scam examples are synthetically templated
("Earn $5000/week! … Contact now at gmail… Basic knowledge in…").
A plain model memorizes that wording (one bigram reached 0.70 feature
importance) and fails on identically-meaning scams written in new words —
verified experimentally: XGBoost-only prob was 0.033 on a novel scam.

Two defenses, both visible in the repo:


augment.py
 — lexically diverse scam templates (incl. Pakistani
payment rails: Easypaisa/JazzCash) + "hard" legitimate ads mentioning
salary/remote work. Probe set of 5 handwritten unseen cases.
Hybrid engine in 
app.py
 — model and rule evidence are
combined with noisy-OR: P = 1 − (1 − P_xgb)·(1 − P_rules), where the
rule layer scores the 9 red-flag behaviors (fees, free webmail, urgency,
unrealistic pay…). The API response exposes both sub-scores under engine
for transparency, and the combined score stays continuous (no artificial
round numbers).
🔌 API (Phase 2)
Method	Endpoint	Description
GET	/api/health	service + model status & metrics
POST	/api/predict	{job_text, title} → prediction, confidence, probabilities, engine breakdown, red_flags, signals, latency
POST	/api/predict-url	{url} → SSRF-protected fetch of a PUBLIC job posting page, text extraction, then the same validation → prediction → history path as /api/predict
GET	/api/history	prediction history with persisted evidence map (PRD 5.7; full job text is not stored)
DELETE	/api/history	clear history
📊 Evaluation (PRD §10)
Accuracy · Precision · Recall · F1 · ROC-AUC · Confusion Matrix
(+ generalization probes). Target ≥95%: MET on the hold-out set.
Prediction latency ≈ 2–3 ms (PRD NFR: < 2 s), model warmed at startup.

🧰 Stack (PRD §11)
React.js · Flask · XGBoost · scikit-learn (TF-IDF) · NLTK · pandas/NumPy ·
Matplotlib · Joblib · SQLite

🖼️ Screenshot analysis (Milestone 7C)
The Home card's third input mode, Upload Screenshot, reads a job ad from a
PNG/JPG/JPEG/WEBP image (max 8 MB) using Tesseract.js OCR that runs entirely
in the browser (WASM + locally vendored worker/core/eng.traineddata via
`npm run prepare-ocr`, installed automatically on `npm install`) — no OS
binary, no server upload of the image, no paid API. Extracted text is
normalized (never invented), gated client-side, then pushed through the
EXISTING validate_job_text() → predict_one() → history pipeline, so all three
modes (Paste Text, Job URL, Upload Screenshot) share one classifier. A
collapsible "Extracted text" panel on the result view shows exactly what the
OCR produced. Unusable images (no text, too blurry, wrong format, oversize,
corrupt) fail gracefully before any prediction runs.

🔗 Job URL analysis (Milestone 7B)
The Home card now offers two input modes: Paste Text (existing flow) and
Job URL. A submitted public http(s) link is fetched by backend/url_fetcher.py
with hard SSRF protection — scheme allow-list (http/https only), localhost/
*.local/*.internal host rejection, DNS resolution checked so every resolved
address (IPv4 + IPv6, incl. IPv4-mapped) must be globally routable, every
redirect hop re-validated before it is followed (max 5), 6 s connect /
12 s read timeouts, 2 MB response cap, HTML-only content-type check, and TLS
verification never disabled. Readable text is extracted with the stdlib HTML
parser (scripts/styles/nav/header/footer/cookie-banner removed, <article>/<main>
preferred) and handed to the EXISTING validate_job_text() → predict_one() →
history pipeline — no second classifier and no schema change. Private,
blocked, unreachable, non-HTML or content-less pages fail gracefully and ask
the user to paste the job description instead. Known limits: extraction is
imperfect for JS-only job boards, bot-protected pages, paywalls and unusual
markup — for those, Paste Text remains the reliable path.
🔐 Accounts & per-user data (Milestone 8A)
JobGuard requires a free account. Sign Up / Sign In are served by a dedicated
screen; every account is a standard JobGuard user (no role selection yet).
Passwords are stored only as Werkzeug password hashes — never in plaintext,
and password hashes are never returned by any API. Sessions are server-side
Flask session cookies (HttpOnly, SameSite=Lax, Secure when
JOBGUARD_COOKIE_SECURE=true) — no tokens in localStorage. Set
JOBGUARD_SECRET_KEY in the environment before running backend/app.py; without
it the backend falls back to an ephemeral random key (sessions reset on every
restart), so always set it outside development.

👤 User-specific History & Insights (Milestone 8A.2)
Every prediction is stored with the signed-in user's id. History and the
Insights page (which is calculated live from that same History endpoint) are
strictly per-user: you only ever see, search and delete your own
analyses, and Clear History removes only your rows. The predictions table was
migrated in place — a nullable user_id column plus an index were added, old
rows are preserved but stay invisible (never reassigned) until 8B migrates
them explicitly.

🛡️ CSRF protection (Milestone 8A.2)
All authenticated state-changing requests (Analyze text/URL, Clear History,
Sign Out) must echo the session-bound CSRF token in the X-CSRF-Token header.
The token is issued inside the session (returned by /api/auth/me and by the
sign-up/sign-in responses) and is kept in frontend memory only — never in
localStorage. Missing or invalid tokens are rejected with HTTP 403;
authentication itself remains purely session-cookie based.
