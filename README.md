🛡️ AI-Based Job Scam Detection (FYP)
Machine-learning system that classifies a pasted job advertisement as
Scam or Legitimate, with confidence scores, a probability graph and
explainable red-flag indicators.

📁 Project Structure (matches PRD phases)
text

ai-job-scam-detector/
├── frontend/                      # PHASE 1 — React.js + Vite UI
│   ├── src/
│   │   ├── App.jsx                #    app shell + API wiring
│   │   ├── api.js                 #    REST client (/api/*)
│   │   ├── styles.css             #    dark-theme design system
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
GET	/api/history	prediction history with persisted evidence map (PRD 5.7; full job text is not stored)
DELETE	/api/history	clear history
📊 Evaluation (PRD §10)
Accuracy · Precision · Recall · F1 · ROC-AUC · Confusion Matrix
(+ generalization probes). Target ≥95%: MET on the hold-out set.
Prediction latency ≈ 2–3 ms (PRD NFR: < 2 s), model warmed at startup.

🧰 Stack (PRD §11)
React.js · Flask · XGBoost · scikit-learn (TF-IDF) · NLTK · pandas/NumPy ·
Matplotlib · Joblib · SQLite