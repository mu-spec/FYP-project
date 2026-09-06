"""
Shared NLP pipeline — SINGLE SOURCE OF TRUTH for text preprocessing and
feature engineering (PRD 5.3 & 5.4).

Used by:
  • backend/app.py          (inference)
  • models/train_model.py   (training)

Keeping one module guarantees train/serve consistency.
"""

import re
import string

# ---------------------------------------------------------------- NLTK setup
import nltk
from nltk.corpus import stopwords
from nltk.stem import WordNetLemmatizer

for _res in ("stopwords", "wordnet", "omw-1.4"):
    try:
        nltk.data.find(f"corpora/{_res}")
    except LookupError:
        nltk.download(_res, quiet=True)

_STOP = set(stopwords.words("english"))
_LEM = WordNetLemmatizer()
_PUNCT_TABLE = str.maketrans("", "", string.punctuation)

# ---------------------------------------------------------------- Regexes
HTML_RE     = re.compile(r"<[^>]+>")
URL_RE      = re.compile(r"(https?://\S+|www\.\S+)", re.I)
EMAIL_RE    = re.compile(r"[\w\.\-]+@[\w\-]+\.[\w\.\-]+")
PHONE_RE    = re.compile(r"(\+?\d[\d\s\-\(\)]{7,}\d)")
NUMBER_RE   = re.compile(r"\d+")
CURRENCY_RE = re.compile(r"[\$\u20ac\u00a3\u00a5]|usd|dollars?|euros?|pkr|rs\.?", re.I)
SALARY_RE   = re.compile(r"salary|per\s*(hour|week|month|year)|/hr|/week|k/month|paid", re.I)
FREE_MAIL_RE = re.compile(r"@(gmail|yahoo|hotmail|outlook|aol|proton|mail)\.", re.I)
FEE_RE      = re.compile(r"(registration|processing|training|application|verification)\s*fee|"
                         r"pay\s+\$|deposit|western\s*union|wire\s*transfer|"
                         r"gift\s*card|bitcoin|easypaisa|jazz\s?cash|"
                         r"mobile\s*wallet|advance\s*payment", re.I)

URGENCY_WORDS = [
    "urgent", "immediately", "immediate", "hurry", "asap",
    "apply now", "act fast", "limited time", "instant",
    "guaranteed", "easy money", "no experience", "work from home",
    "earn cash", "risk free", "no fee", "right away", "today only",
    "positions filling", "act now", "don't miss",
]

# Feature names in the exact order used for model input
NUMERIC_FEATURES = [
    "email_count", "url_count", "phone_count", "number_count",
    "currency_count", "salary_mention", "capital_pct",
    "exclamation_count", "urgency_count", "text_length",
    "avg_word_length",
]


# ------------------------------------------------- PRD 5.3 — Preprocessing
def clean_text(text: str) -> str:
    """lowercase -> HTML strip -> URL/email strip -> punctuation strip ->
    digit strip -> stopword removal -> lemmatization."""
    t = str(text).lower()
    t = HTML_RE.sub(" ", t)
    t = URL_RE.sub(" ", t)
    t = EMAIL_RE.sub(" ", t)
    t = t.translate(_PUNCT_TABLE)
    t = re.sub(r"\d+", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    tokens = [_LEM.lemmatize(w) for w in t.split() if w not in _STOP and len(w) > 2]
    return " ".join(tokens)


# ---------------------------------------------- PRD 5.4 — Engineered signals
def extract_signals(text: str) -> dict:
    """Extract numeric scam-signal features from RAW text
    (must be called BEFORE cleaning, which destroys ! and $)."""
    t = str(text)
    letters = [c for c in t if c.isalpha()]
    caps = sum(1 for c in letters if c.isupper())
    words = t.split()
    word_lens = [len(w) for w in words] or [0]
    lower = t.lower()
    return {
        "email_count":       len(EMAIL_RE.findall(t)),
        "url_count":         len(URL_RE.findall(t)),
        "phone_count":       len(PHONE_RE.findall(t)),
        "number_count":      len(NUMBER_RE.findall(t)),
        "currency_count":    len(CURRENCY_RE.findall(t)),
        "salary_mention":    int(bool(SALARY_RE.search(t))),
        "capital_pct":       round(caps / len(letters) * 100, 2) if letters else 0.0,
        "exclamation_count": t.count("!"),
        "urgency_count":     sum(lower.count(w) for w in URGENCY_WORDS),
        "text_length":       len(t),
        "avg_word_length":   round(sum(word_lens) / len(word_lens), 2),
    }


# -------------------------------------------- PRD 5.6 — Scam indicator rules
# Each rule also carries a WEIGHT used by the hybrid prediction engine.
# Rationale: XGBoost learned template wording from the (synthetic) dataset;
# the weighted rule layer captures scam *behavior* and generalizes to
# novel phrasings. Serving score = max(xgb_prob, rule_score).
def detect_red_flags(text: str, signals: dict) -> list:
    """Human-readable red flags, matched against scam patterns."""
    t = str(text)
    lower = t.lower()
    flags = []

    if FREE_MAIL_RE.search(t):
        flags.append({"icon": "📧", "weight": 0.15,
                      "message": "Free webmail contact (Gmail/Yahoo/etc.) instead of a corporate domain"})
    if signals["url_count"] > 0:
        flags.append({"icon": "🔗", "weight": 0.10,
                      "message": f"External link(s) detected ({signals['url_count']}) — may redirect to a fake application site"})
    if signals["phone_count"] > 0:
        flags.append({"icon": "📱", "weight": 0.10,
                      "message": "Personal phone/WhatsApp contact listed in the posting"})
    if FEE_RE.search(lower):
        flags.append({"icon": "💸", "weight": 0.45,
                      "message": "Requests money up front (registration/processing fee, deposit, gift card, Easypaisa/JazzCash)"})
    if signals["urgency_count"] >= 2:
        flags.append({"icon": "⏰", "weight": 0.15,
                      "message": f"High-pressure urgency language ({signals['urgency_count']} hits: 'apply now', 'limited time', …)"})
    if "no experience" in lower and signals["salary_mention"]:
        flags.append({"icon": "🤑", "weight": 0.15,
                      "message": "High salary promised with 'no experience' required"})
    if signals["exclamation_count"] >= 3:
        flags.append({"icon": "❗", "weight": 0.05,
                      "message": f"Excessive exclamation marks ({signals['exclamation_count']})"})
    if signals["capital_pct"] > 8 and signals["text_length"] > 200:
        flags.append({"icon": "🔠", "weight": 0.05,
                      "message": f"Unusually high CAPITAL letter usage ({signals['capital_pct']}%)"})
    if re.search(r"\$\s?\d{3,}\s*/?\s*(week|wk|day)", lower):
        flags.append({"icon": "💰", "weight": 0.20,
                      "message": "Unrealistically high salary for the role"})

    return flags


def rule_score(flags: list) -> float:
    """Weighted, capped scam-likelihood from fired red flags (0..0.99)."""
    return min(0.99, sum(f.get("weight", 0.0) for f in flags))
