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
#
# Evidence metadata below is deliberately produced by the same deterministic
# matches that fire each rule. It explains a flag; it never participates in
# feature extraction, classification, or probability calculation.

def _severity_for_weight(weight: float) -> str:
    """Map the existing rule weight to a display-only severity label."""
    if weight >= 0.40:
        return "High"
    if weight >= 0.15:
        return "Medium"
    return "Low"


def _unique(values: list[str]) -> list[str]:
    """Keep evidence snippets in first-seen order without duplicates."""
    seen = set()
    result = []
    for value in values:
        cleaned = value.strip()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            result.append(cleaned)
    return result


def _snippet_for_span(text: str, start: int, end: int, max_len: int = 180) -> str:
    """Return a nearby raw-text snippet around a matched span.

    The returned value is always a substring of the submitted text. Prefer a
    complete sentence/line; use a bounded context window for long sentences.
    """
    separators = ".!?;:\n"
    left = max((text.rfind(separator, 0, start) for separator in separators), default=-1) + 1
    right_candidates = [text.find(separator, end) for separator in separators]
    right_candidates = [position for position in right_candidates if position >= 0]
    right = min(right_candidates, default=len(text)) + (1 if right_candidates else 0)

    if right - left > max_len:
        half = max_len // 2
        left = max(0, start - half)
        right = min(len(text), end + half)
        if left > 0:
            next_space = text.find(" ", left)
            if 0 <= next_space < start:
                left = next_space + 1
        if right < len(text):
            previous_space = text.rfind(" ", end, right)
            if previous_space > end:
                right = previous_space

    return text[left:right].strip()


def _evidence_for_matches(text: str, matches, limit: int = 4) -> list[str]:
    return _unique([
        _snippet_for_span(text, match.start(), match.end())
        for match in matches
    ])[:limit]


def _evidence_for_positions(text: str, positions, limit: int = 4) -> list[str]:
    return _unique([
        _snippet_for_span(text, position, position + 1)
        for position in positions
    ])[:limit]


def _flag(icon: str, weight: float, message: str, category: str,
          explanation: str, evidence: list[str]) -> dict:
    """Build a backwards-compatible flag with display-only evidence."""
    return {
        "icon": icon,
        "weight": weight,
        "message": message,
        "category": category,
        "severity": _severity_for_weight(weight),
        "explanation": explanation,
        "evidence": evidence,
    }


def detect_red_flags(text: str, signals: dict) -> list:
    """Human-readable red flags plus evidence from the submitted raw text."""
    t = str(text)
    lower = t.lower()
    flags = []

    free_mail_matches = [
        match for match in EMAIL_RE.finditer(t)
        if FREE_MAIL_RE.search(match.group(0))
    ]
    if FREE_MAIL_RE.search(t):
        flags.append(_flag(
            "📧", 0.15,
            "Free webmail contact (Gmail/Yahoo/etc.) instead of a corporate domain",
            "FREE WEBMAIL",
            "A free email address makes the employer harder to verify independently.",
            _evidence_for_matches(t, free_mail_matches or list(FREE_MAIL_RE.finditer(t)),
                                  limit=3),
        ))

    url_matches = list(URL_RE.finditer(t))
    if signals["url_count"] > 0:
        flags.append(_flag(
            "🔗", 0.10,
            f"External link(s) detected ({signals['url_count']}) — may redirect to a fake application site",
            "EXTERNAL LINK",
            "External links should be checked carefully before credentials or personal data are submitted.",
            _evidence_for_matches(t, url_matches),
        ))

    phone_matches = list(PHONE_RE.finditer(t))
    if signals["phone_count"] > 0:
        flags.append(_flag(
            "📱", 0.10,
            "Personal phone/WhatsApp contact listed in the posting",
            "PERSONAL CONTACT",
            "A personal contact channel can make the employer identity harder to verify.",
            _evidence_for_matches(t, phone_matches),
        ))

    fee_matches = list(FEE_RE.finditer(t))
    if FEE_RE.search(lower):
        flags.append(_flag(
            "💸", 0.45,
            "Requests money up front (registration/processing fee, deposit, gift card, Easypaisa/JazzCash)",
            "UPFRONT PAYMENT",
            "Requests for payment before employment are a strong warning sign.",
            _evidence_for_matches(t, fee_matches),
        ))

    urgency_matches = []
    for phrase in URGENCY_WORDS:
        urgency_matches.extend(re.finditer(re.escape(phrase), lower))
    if signals["urgency_count"] >= 2:
        flags.append(_flag(
            "⏰", 0.15,
            f"High-pressure urgency language ({signals['urgency_count']} hits: 'apply now', 'limited time', …)",
            "URGENCY PRESSURE",
            "Pressure to act immediately can discourage independent verification.",
            _evidence_for_matches(t, urgency_matches),
        ))

    no_experience_matches = list(re.finditer(r"no\s+experience", lower))
    salary_match = SALARY_RE.search(t)
    salary_matches = [salary_match] if salary_match else []
    if "no experience" in lower and signals["salary_mention"]:
        flags.append(_flag(
            "🤑", 0.15,
            "High salary promised with 'no experience' required",
            "HIGH PAY + NO EXPERIENCE",
            "High pay paired with no experience requirements deserves extra verification.",
            _evidence_for_matches(t, no_experience_matches + salary_matches),
        ))

    exclamation_matches = list(re.finditer(r"!", t))
    if signals["exclamation_count"] >= 3:
        flags.append(_flag(
            "❗", 0.05,
            f"Excessive exclamation marks ({signals['exclamation_count']})",
            "EXCESSIVE PUNCTUATION",
            "Repeated exclamation marks can be used to create excitement or pressure.",
            _evidence_for_matches(t, exclamation_matches),
        ))

    uppercase_positions = [index for index, character in enumerate(t) if character.isupper()]
    if signals["capital_pct"] > 8 and signals["text_length"] > 200:
        flags.append(_flag(
            "🔠", 0.05,
            f"Unusually high CAPITAL letter usage ({signals['capital_pct']}%)",
            "EXCESSIVE CAPITALIZATION",
            "Unusually frequent capitals can make a posting feel more promotional or urgent.",
            _evidence_for_positions(t, uppercase_positions),
        ))

    high_salary_matches = list(re.finditer(
        r"\$\s?\d{3,}\s*/?\s*(week|wk|day)", lower
    ))
    if high_salary_matches:
        flags.append(_flag(
            "💰", 0.20,
            "Unrealistically high salary for the role",
            "UNREALISTIC PAY",
            "Very high short-period pay should be verified against the employer and role.",
            _evidence_for_matches(t, high_salary_matches),
        ))

    return flags


def rule_score(flags: list) -> float:
    """Weighted, capped scam-likelihood from fired red flags (0..0.99)."""
    return min(0.99, sum(f.get("weight", 0.0) for f in flags))
