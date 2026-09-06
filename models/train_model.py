"""
Phase 3 — Model Training (PRD §7 ML Pipeline & §9 Model)
=========================================================
Pipeline: Dataset -> Cleaning -> Preprocessing -> Feature Engineering ->
          TF-IDF -> Train/Test Split -> XGBoost -> Evaluation -> Save Model

Reproducible end-to-end from the RAW dataset; preprocessing is imported
from backend/nlp_pipeline.py (single source of truth -> no train/serve skew).

Outputs (models/artifacts/):
    xgboost_model.joblib      trained classifier
    tfidf_vectorizer.joblib   fitted TF-IDF vectorizer
    metadata.joblib           metrics + feature order (used by API /health)
Outputs (models/reports/):
    metrics.json              full evaluation metrics (incl. baseline)
    confusion_matrix.png
    roc_curve.png

Run:  python train_model.py
"""

import json
import os
import sys
import time

import joblib
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.sparse import csr_matrix, hstack
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (accuracy_score, classification_report,
                             confusion_matrix, f1_score, precision_score,
                             recall_score, roc_auc_score, roc_curve)
from sklearn.model_selection import train_test_split
from xgboost import XGBClassifier

# ---- paths -----------------------------------------------------------------
ROOT    = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_CSV = os.path.join(ROOT, "data", "raw", "combined_job_scam_dataset.csv.gz")
ART_DIR = os.path.join(ROOT, "models", "artifacts")
REP_DIR = os.path.join(ROOT, "models", "reports")
os.makedirs(ART_DIR, exist_ok=True)
os.makedirs(REP_DIR, exist_ok=True)

sys.path.insert(0, os.path.join(ROOT, "backend"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from nlp_pipeline import NUMERIC_FEATURES, clean_text, extract_signals  # noqa: E402
from augment import PROBES, make_hard_legit, make_scam, make_short_legit  # noqa: E402

RANDOM_STATE = 42
N_AUG_SCAM      = 3000   # lexically diverse scam posts
N_AUG_HARD      = 1500   # legit posts mentioning salary/remote (hard negatives)
N_AUG_SHORT     = 1200   # short newspaper-style legit ads (fixes length bias)

# ---- 1. Load + deduplicate --------------------------------------------------
print("=" * 60)
print("JOB SCAM DETECTION — MODEL TRAINING")
print("=" * 60)
df = pd.read_csv(RAW_CSV)
print(f"\n[1/6] Loaded raw data                 : {len(df):,} rows")
df = df.drop_duplicates(subset=["combined_text"]).reset_index(drop=True)
N_AFTER_DEDUP = len(df)
print(f"      After dedup on combined_text    : {N_AFTER_DEDUP:,} rows")

# ---- 1b. SPLIT FIRST (leakage fix): the test set must stay --------------- #
# pure held-out REAL data — never touched by fitting or augmentation.
train_df, test_df = train_test_split(
    df, test_size=0.20, stratify=df["fraudulent"], random_state=RANDOM_STATE)
print(f"      Split (pure): {len(train_df):,} train-real / {len(test_df):,} test-real")

# ---- 1c. Augment the TRAINING portion ONLY (leakage fix) -------------------
aug = pd.DataFrame(
    {"combined_text": [make_scam()       for _ in range(N_AUG_SCAM)] +
                      [make_hard_legit()  for _ in range(N_AUG_HARD)] +
                      [make_short_legit() for _ in range(N_AUG_SHORT)],
     "fraudulent":    [1] * N_AUG_SCAM + [0] * (N_AUG_HARD + N_AUG_SHORT)})
train_df = pd.concat([train_df, aug], ignore_index=True)
print(f"      + {len(aug):,} augmented rows added to TRAIN ONLY "
      f"({N_AUG_SCAM} scam / {N_AUG_HARD} hard legit / {N_AUG_SHORT} short legit)")

# ---- 2. Preprocess + feature engineering (stateless -> no leakage) --------
print("\n[2/6] Cleaning text & extracting signals (shared nlp_pipeline) …")
t0 = time.time()
def prep(frame):
    frame = frame.copy()
    frame["clean_text"] = frame["combined_text"].apply(clean_text)
    sigs = frame["combined_text"].apply(extract_signals).apply(pd.Series)
    frame = pd.concat([frame, sigs], axis=1)
    return frame[frame["clean_text"].str.len() > 10]

train_df = prep(train_df)
test_df  = prep(test_df)
print(f"      done in {time.time()-t0:.1f}s — train {len(train_df):,} / test {len(test_df):,}")

y_train = train_df["fraudulent"].astype(int).values
y_test  = test_df["fraudulent"].astype(int).values

# ---- 3. TF-IDF fitted on TRAIN only (leakage fix) --------------------------
print("\n[3/6] TF-IDF vectorization (fit on train only) + signal hstack …")
from sklearn.feature_extraction.text import TfidfVectorizer
vectorizer = TfidfVectorizer(
    max_features=10_000,
    ngram_range=(1, 2),
    min_df=3,
    max_df=0.95,
    sublinear_tf=True,
    dtype=np.float32,
)
X_train = hstack([vectorizer.fit_transform(train_df["clean_text"]),
                  csr_matrix(train_df[NUMERIC_FEATURES].astype(np.float32).values)]).tocsr()
X_test  = hstack([vectorizer.transform(test_df["clean_text"]),
                  csr_matrix(test_df[NUMERIC_FEATURES].astype(np.float32).values)]).tocsr()
print(f"      Train matrix: {X_train.shape[0]:,} x {X_train.shape[1]:,}  |  "
      f"Test matrix: {X_test.shape[0]:,} x {X_test.shape[1]:,}")

import gc
del train_df, test_df, df
gc.collect()

print(f"\n[4/6] Split: {X_train.shape[0]:,} train (incl. augmentation) / "
      f"{X_test.shape[0]:,} pure test (stratified)")


# ---- 5a. Baseline: Logistic Regression --------------------------------------
print("\n[5/6] Training models …")
t0 = time.time()
baseline = LogisticRegression(max_iter=1000, C=1.0, solver="liblinear",
                              random_state=RANDOM_STATE)
baseline.fit(X_train, y_train)
base_pred  = baseline.predict(X_test)
base_proba = baseline.predict_proba(X_test)[:, 1]
print(f"      Baseline (LogReg) trained in {time.time()-t0:.1f}s "
      f"— acc={accuracy_score(y_test, base_pred):.4f}")

# ---- 5b. Main model: XGBoost (PRD §9) ----------------------------------------
t0 = time.time()
model = XGBClassifier(
    n_estimators=300,
    max_depth=6,
    learning_rate=0.1,
    subsample=0.9,
    colsample_bytree=0.8,
    min_child_weight=3,
    reg_lambda=1.0,
    tree_method="hist",
    eval_metric="logloss",
    random_state=RANDOM_STATE,
    n_jobs=2,
)
model.fit(X_train, y_train)
pred  = model.predict(X_test)
proba = model.predict_proba(X_test)[:, 1]
train_s = time.time() - t0

# ---- 6. Evaluation (PRD §10) -------------------------------------------------
acc  = accuracy_score(y_test, pred)
prec = precision_score(y_test, pred)
rec  = recall_score(y_test, pred)
f1   = f1_score(y_test, pred)
auc  = roc_auc_score(y_test, proba)
cm   = confusion_matrix(y_test, pred)

print(f"      XGBoost trained in {train_s:.1f}s")
print("\n" + "=" * 60)
print("XGBOOST — TEST SET RESULTS")
print("=" * 60)
print(f"  Accuracy  : {acc:.4f}   (target >= 0.95: {'MET ✅' if acc >= 0.95 else 'not met ⚠️'})")
print(f"  Precision : {prec:.4f}")
print(f"  Recall    : {rec:.4f}")
print(f"  F1-Score  : {f1:.4f}")
print(f"  ROC-AUC   : {auc:.4f}")
print(f"\nConfusion matrix (rows=true, cols=pred):\n{cm}")
print("\n" + classification_report(y_test, pred, target_names=["Legitimate", "Scam"]))

# ---- 6b. Generalization probes (handwritten, NEVER seen in training) ---------
print("-" * 60)
print("GENERALIZATION PROBES (unseen handwritten samples)")
print("-" * 60)
probe_results = []
probe_texts  = [p[1] for p in PROBES]
probe_labels = [p[2] for p in PROBES]
Xp = hstack([vectorizer.transform([clean_text(t) for t in probe_texts]),
             csr_matrix(pd.DataFrame(
                 [extract_signals(t) for t in probe_texts]
             )[NUMERIC_FEATURES].astype(np.float32).values)]).tocsr()
probe_prob = model.predict_proba(Xp)[:, 1]
probe_ok = 0
for (name, _, truth), p in zip(PROBES, probe_prob):
    got = int(p >= 0.5); ok = (got == truth); probe_ok += ok
    probe_results.append({"name": name, "expected": "Scam" if truth else "Legitimate",
                          "p_scam": round(float(p), 4), "correct": bool(ok)})
    flag = "✅" if ok else "❌"
    print(f"  {flag} P(scam)={p:.3f}  expected={'Scam' if truth else 'Legit':5s}  {name}")
print(f"  Probe score: {probe_ok}/{len(PROBES)} correct")

# ---- plots: confusion matrix + ROC curve -------------------------------------
fig, ax = plt.subplots(figsize=(5, 4))
im = ax.imshow(cm, cmap="Blues")
ax.set(xticks=[0, 1], yticks=[0, 1], xticklabels=["Legit", "Scam"],
       yticklabels=["Legit", "Scam"], xlabel="Predicted", ylabel="Actual",
       title="Confusion Matrix — XGBoost")
for i in range(2):
    for j in range(2):
        ax.text(j, i, f"{cm[i, j]:,}", ha="center", va="center",
                color="white" if cm[i, j] > cm.max() / 2 else "black", fontsize=13)
fig.colorbar(im); fig.tight_layout()
fig.savefig(os.path.join(REP_DIR, "confusion_matrix.png"), dpi=150)
plt.close(fig)

fpr, tpr, _ = roc_curve(y_test, proba)
fig, ax = plt.subplots(figsize=(5, 4))
ax.plot(fpr, tpr, lw=2, label=f"XGBoost (AUC = {auc:.4f})")
bfpr, btpr, _ = roc_curve(y_test, base_proba)
bauc = roc_auc_score(y_test, base_proba)
ax.plot(bfpr, btpr, lw=1.5, ls="--", label=f"LogReg baseline (AUC = {bauc:.4f})")
ax.plot([0, 1], [0, 1], "k:", lw=1)
ax.set(xlabel="False Positive Rate", ylabel="True Positive Rate",
       title="ROC Curve"); ax.legend(loc="lower right"); fig.tight_layout()
fig.savefig(os.path.join(REP_DIR, "roc_curve.png"), dpi=150)
plt.close(fig)

# ---- metrics.json (for viva/report) ------------------------------------------
metrics = {
    "dataset": {"raw_rows": 27014, "after_dedup": N_AFTER_DEDUP,
                "train": int(len(y_train)), "test": int(len(y_test)),
                "features_tfidf": int(X_train.shape[1]) - len(NUMERIC_FEATURES),
                "features_numeric": len(NUMERIC_FEATURES)},
    "xgboost": {"accuracy": round(acc, 4), "precision": round(prec, 4),
                "recall": round(rec, 4), "f1": round(f1, 4),
                "roc_auc": round(auc, 4),
                "confusion_matrix": cm.tolist(), "train_seconds": round(train_s, 1)},
    "baseline_logreg": {"accuracy": round(accuracy_score(y_test, base_pred), 4),
                        "f1": round(f1_score(y_test, base_pred), 4),
                        "roc_auc": round(bauc, 4)},
    "generalization_probes": {"correct": probe_ok, "total": len(PROBES),
                              "details": probe_results},
    "augmentation": {"scam_variants": N_AUG_SCAM, "hard_legit": N_AUG_HARD,
                     "short_legit": N_AUG_SHORT,
                     "note": "Leakage-safe methodology: stratified split FIRST, "
                             "then augmentation applied to TRAIN ONLY, and "
                             "TF-IDF fitted on TRAIN only. Test set is pure "
                             "held-out real data never seen during fitting."},
}
with open(os.path.join(REP_DIR, "metrics.json"), "w") as f:
    json.dump(metrics, f, indent=2)

# ---- Save artifacts (PRD: Joblib storage) ------------------------------------
joblib.dump(model, os.path.join(ART_DIR, "xgboost_model.joblib"), compress=3)
joblib.dump(vectorizer, os.path.join(ART_DIR, "tfidf_vectorizer.joblib"), compress=3)
joblib.dump({"accuracy": round(acc, 4), "roc_auc": round(auc, 4),
             "f1": round(f1, 4), "precision": round(prec, 4),
             "recall": round(rec, 4),
             "numeric_features": NUMERIC_FEATURES,
             "trained_rows": int(len(y_train)),
             "tfidf_features": int(X_train.shape[1]) - len(NUMERIC_FEATURES)},
            os.path.join(ART_DIR, "metadata.joblib"))

print(f"\n✅ Artifacts saved  -> {ART_DIR}")
print(f"✅ Reports saved    -> {REP_DIR}")
print("Now start the API:  cd backend && python app.py")
