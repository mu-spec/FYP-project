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
#    optional but recommended — a stable secret keeps sessions across restarts:
#    JOBGUARD_SECRET_KEY=<random string> python app.py
#
#    Optional — Adzuna job source (8E.2). Without these the app works fine and
#    simply shows the other providers; set them only if you want Adzuna jobs:
#    ADZUNA_APP_ID=<your id> ADZUNA_APP_KEY=<your key> python app.py
#    ADZUNA_COUNTRY defaults to "gb" (Adzuna's jobs index is per-country);
#    keep credentials out of git — environment variables only.

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

🔎 Real Job Discovery (Milestone 8B.1)
The Jobs page ("Real Job Opportunities") shows real external job postings from
four official public APIs — Remote OK (https://remoteok.com/api), Arbeitnow
(https://www.arbeitnow.com/api/job-board-api), Jobicy (https://jobicy.com/api/v2/remote-jobs,
(https://www.arbeitnow.com/api/job-board-api). No scraping and no API keys are
used, and job APIs are only ever called by the Flask backend (never from
React). Postings are normalized into a shared shape (source, source_job_id,
title, company, location, description, job_type, remote, tags, salary, job_url,
published_at, fetched_at — missing fields become null/[] and are never
invented), stripped of provider HTML before storage, and cached in the
external_jobs SQLite table with UNIQUE(source, source_job_id). The cache
refreshes at most once every 20 minutes; if one provider fails the other's
jobs (plus cached rows) are still served, and if both fail the cached list is
shown with an explicit "cached" note — the page never crashes and never shows
raw provider errors.

GET /api/jobs (authenticated; anonymous requests get 401) accepts q, location,
source and remote=true filters plus page-based pagination (20 per page) and
returns normalized jobs plus cache metadata. Every card visibly names its
source ("Source: Remote OK" / "Source: Arbeitnow" / "Source: Jobicy") and links
back to the
original listing (Remote OK jobs always link to their remoteok.com URL, as
their terms require). HTML is stripped server-side; descriptions are rendered
as plain text only. "Analyze with JobGuard" sends the listing through the
existing one-click analysis pipeline (same validator, XGBoost + rules engine,
per-user History) with no scoring changes.

🔔 Personalized Job Alerts (Milestone 8B.2)
Every signed-in user can save one active job preference record (Keywords /
Job Title, Preferred Location, Remote Only, Preferred Source — Any, Remote OK
or Arbeitnow) from the "Job Preferences" panel on the Jobs page. Preferences
live in the job_preferences table with UNIQUE(user_id) and belong strictly to
the authenticated user. Matching is deterministic and explainable — plain text
logic over the cached external jobs (every keyword term must appear in title,
company, description or tags; case-insensitive location substring; optional
remote-only; optional source filter). No ML is used for matching and the
scam-detection model is untouched.

Notifications are generated in-app only (no email/push) when a provider
refresh imports NEW jobs: each saved preference set is matched against the
newly imported rows and matching jobs create a notification that references
the internal external_jobs.id. UNIQUE(user_id, external_job_id) guarantees the
same job never notifies the same user twice, and a safe catch-up scan (last
48 hours of cached jobs, capped) runs when preferences are saved or the
notification list is opened. If a cached listing is later pruned, the
notification keeps its title/message snapshot and is flagged
"listing no longer cached". The navbar bell shows the unread count (hidden at
zero), opens a scrollable panel with View Job / Mark as Read per item plus
Mark All as Read, and View Job opens the job detail on the Jobs page with the
original "View Original Job" and "Analyze with JobGuard" actions preserved.

New authenticated APIs: GET/PUT /api/job-preferences (PUT requires the
X-CSRF-Token header; strings are trimmed, length-capped and the source must be
an approved value) and GET /api/notifications, GET
/api/notifications/unread-count, POST /api/notifications/<id>/read, POST
/api/notifications/read-all (the two POSTs require CSRF). Every query and
update is filtered by the session user_id — one user can never read, mark or
change another user's notifications or preferences, even by guessing ids.

🏢 Employer Registration (Milestone 8C.1)
A signed-in JobGuard user can choose "Post a Job" in the navigation and
register an employer profile — one profile per account, stored in the
employer_profiles table with UNIQUE(user_id) and linked to the existing
authenticated user. There is no second authentication system and no
credentials are stored in this table. Registration collects Company Name,
Contact Person Name, Business Email, Company Website (optional), Location and
Company Description; all values are trimmed, length-capped and validated on
both the client and the server (valid email; website must be a real HTTP/HTTPS
URL when provided). This feature is registration only — it does not create or
publish jobs and it is NOT a third-party verification of any company.

Authenticated APIs: GET /api/employer-profile (returns profile:null before
registration), POST /api/employer-profile (creates the profile; duplicate
registration is rejected with 409) and PUT /api/employer-profile (updates the
caller's profile in place — id, user_id and created_at are preserved,
updated_at refreshed). POST and PUT require the session and the X-CSRF-Token
header. All reads and writes are scoped to the session user_id server-side:
one user can never read or modify another user's employer profile. Before
registration the Post a Job screen shows "Become an Employer"; after
registration it shows the employer summary ("Employer profile ready") with
edit support, and notes that job publishing will be enabled in the next stage.

📝 Employer Job Drafts (Milestone 8C.2)
Registered employers (users with an employer profile) can create and manage
their own job advertisements from the Post a Job screen: "Create Job Post"
opens a draft form (Job Title, Location, Job Type from a fixed list — Full
Time, Part Time, Contract, Internship, Temporary, Other — Salary/Compensation
optional, Job Description, Requirements, Benefits optional, Contact Email,
Application URL optional and HTTP/HTTPS-only, Closing Date optional and
validated). Everything is trimmed and length-capped and validated on both the
client and the server; nothing is invented — optional fields stay empty. The
description requires real content (at least 30 characters) so the JobGuard AI
analysis of a later stage has substance to work with.

Drafts are stored in the dedicated employer_jobs table — completely separate
from the external_jobs cache — with indexes on employer_profile_id, status and
created_at. Every created job has status='draft': the status is decided by the
backend and cannot be chosen or forced by the client. Authenticated endpoints:
GET /api/employer-jobs (own drafts, newest update first), POST
/api/employer-jobs, GET/PUT/DELETE /api/employer-jobs/<id> (POST/PUT/DELETE
require the X-CSRF-Token header). Every read, update and delete is scoped
through the authenticated user's employer profile — another employer's draft
id is a plain 404, identical to a missing row, so no ownership information is
revealed. A signed-in account without an employer profile is rejected (403).

The Post a Job screen shows "Create Job Post" plus a "My Job Posts" list
(title, location, job type, Draft badge, last updated) with View / Edit /
Delete per draft, a read-only detail view (company from the employer profile —
no credentials are duplicated into the job record) and a delete confirmation
("This action cannot be undone."). Drafts are private: they never appear in
the external Jobs feed, job alerts or notifications for other users. There is
no publish action anywhere in this milestone — publishing comes after the
JobGuard AI screening stage.

Employer drafts can now be checked by the same JobGuard AI that powers the
public Analyze flow. "Run Safety Check" on a draft composes one screening text
from the job fields (Job Title, Company, Location, Job Type, Salary, the
description, then Requirements, Benefits, Contact Email and Application URL —
empty optional fields are skipped) and feeds it through the existing prediction
path unchanged: the same preprocessing, TF-IDF features, 11 numeric signals,
XGBoost model, 9 red-flag rules, noisy-OR combination and the existing 0.5
threshold. A Legitimate verdict marks the draft Ready; a Scam verdict marks it
Flagged. There is no second threshold and no special leniency for registered
employers — the engine treats a job draft exactly like any pasted listing.

The status (draft / flagged / ready) is decided only by the backend. Any edit
to a screened job resets it to draft, so results always describe the current
text; previous screening rows are kept as audit history in the dedicated
employer_job_screenings table — separate from the public predictions table, so
screenings never appear in History or Insights. POST
/api/employer-jobs/<id>/screen and GET /api/employer-jobs/<id>/screening are
session-authenticated, employer-only, CSRF-protected and user-scoped (another
employer's job is a plain 404). The Safety Report reuses the Evidence Map
presentation and states plainly what the check is: automated screening only —
JobGuard does not verify companies and no result is a guarantee. Flagged jobs
show "Publishing blocked"; Ready jobs are ready for publishing in the next
stage. There is still no publish action in this milestone.

Milestone 8C.3B completes the pipeline: a job that passed the safety screening
(status Ready) can be PUBLISHED with an explicit, confirmed action — passing
the check never publishes automatically. POST /api/employer-jobs/<id>/publish
requires the authenticated employer, their own job, a valid CSRF token, status
'ready' and a valid latest screening; a fingerprint (sha256) of the exact
screened text is stored with each screening and re-checked at publish time,
so a pass on old text can never publish new text. Success stamps
published_at (UTC) on the employer_jobs row (added by a safe in-place
migration). Any later edit resets the job to draft, clears the stamp and
removes it from the public feed instantly; deleting a published job removes
it immediately.

Published employer jobs appear on the existing Jobs page alongside RemoteOK
and Arbeitnow listings with source 'jobguard' — the tables stay separate and
nothing is copied into external_jobs. The Source filter gains a JobGuard
option; JobGuard cards carry a Source: JobGuard badge and the line
"Screened by JobGuard — automated risk screening, not a company
verification." (never "100% Safe", "Verified Company" or "Guaranteed
Legitimate"). "Analyze with JobGuard" on a public card uses the normal
analysis flow and creates a normal History record — the employer's private
pre-publish screening is never reused as user history. Personalized alerts
are unchanged: they still match external provider jobs only.

⚠️ Limitations
--------------------------
- JobGuard is an automated risk SCREEN, not a verification: it estimates how
  similar a posting is to known scam patterns. A "Legitimate" result is not a
  guarantee, and a "Scam" result is a strong warning, not proof.
- Companies are never verified — an employer account only proves someone
  registered; the AI safety check screens the job TEXT before publishing.
- Published JobGuard jobs come from self-registered employers; use the same
  caution you would with any listing (never pay fees, verify independently).
- OCR quality depends on the screenshot; blurry images are rejected rather
  than guessed.
- External job feeds (RemoteOK, Arbeitnow, Jobicy) can be temporarily unreachable —
  the app then serves its recent cache and says so. JobGuard listings and
  external listings are stored separately.
- Alerts are in-app only, by design (no emails are sent).
