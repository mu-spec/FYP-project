"""
Job-Post Input Validation
=========================
Application-level gate that runs BEFORE the existing ML prediction pipeline
(XGBoost / TF-IDF / engineered signals). Its job is to reject text that is
clearly NOT a usable job advertisement (empty, gibberish, random keystrokes,
or ordinary non-job prose) so that such input never reaches the classifier.

The XGBoost model only knows two classes (Legitimate / Scam), so feeding it
meaningless text forces an arbitrary answer. This module avoids that by
deciding "is this even a job description?" first.

Design principles
-----------------
* It is deliberately LENIENT. It must NOT reject short, genuine Upwork-style
  posts that lack boilerplate words such as "salary", "company" or "benefits".
* It uses several light-weight, fast, deterministic heuristics (no retraining,
  no dictionary downloads at request time) and returns a reason code for each
  rejection so behaviour is explainable and testable.
* It never touches the trained model, vectorizer or training data.

The rules below were calibrated against the acceptance cases in the task and
a set of obvious negatives.
"""

import re

# ------------------------------------------------------------------ Vocabularies
# A deliberately broad vocabulary of words that indicate work / job / skill /
# hiring context. Kept generous so terse gig posts still pass, while ordinary
# personal prose ("went to the market", "watch football") scores ~0.
_JOB_TERMS = {
    # roles & people
    "developer", "engineer", "engineering", "programmer", "coder",
    "fullstack", "full-stack", "backend", "back-end", "frontend", "front-end",
    "designer", "writer", "translator", "editor", "assistant", "manager",
    "recruiter", "consultant", "contractor", "analyst", "architect",
    "tester", "qa", "administrator", "admin", "agent", "expert", "lead",
    # skills / tech / domains
    "software", "web", "mobile", "app", "application", "apps", "android",
    "ios", "flutter", "react", "reactjs", "javascript", "js", "typescript",
    "html", "css", "api", "apis", "rest", "server", "database", "sql",
    "wordpress", "shopify", "django", "node", "nodejs", "python", "java",
    "spring", "graphql", "docker", "kubernetes", "design", "figma", "sketch",
    "ui", "ux", "graphic", "logo", "branding", "content", "seo", "marketing",
    "social", "photoshop", "illustrator", "excel", "word", "typing",
    "programming", "coding", "deploy", "deployment", "wireframe",
    # work context
    "job", "position", "role", "vacancy", "opening", "hire", "hiring",
    "recruit", "recruiting", "company", "team", "freelance", "contract",
    "part-time", "parttime", "full-time", "fulltime", "remote", "onsite",
    "project", "client", "budget", "hourly", "fixed", "payment", "paid",
    "compensation", "stipend", "internship", "vacancy", "posting", "advert",
    "advertisement", "experience", "skill", "skills", "portfolio", "resume",
    "cv", "candidate", "candidates", "interview", "salary", "benefits",
    "requirements", "responsibilities", "qualifications", "proficiency",
    "expertise", "knowledge", "deliverable", "timeline", "deadline",
    # action / task words common in job listings
    "build", "create", "develop", "developing", "fix", "fixing", "implement",
    "designing", "coding", "maintain", "migrate", "configure", "integrate",
    "launch", "manage", "setup", "deliver", "test", "testing", "writing",
    "editing", "support", "maintain", "research", "analyze",
}

# Explicit request / call-to-action words that signal an employment intent.
_INTENT = {
    "need", "needs", "needed", "looking", "seek", "seeking", "wanted",
    "hire", "hiring", "require", "required", "apply", "please", "help",
    "build", "create", "develop", "fix", "implement", "deliver", "want",
    "urgent", "urgently", "immediately", "immediate",
}

_UNION = _JOB_TERMS | _INTENT

# Any single whitespace token that is purely alphabetic and this long is
# essentially never a real word found in a job ad (real text keeps words
# separated by spaces). Catches random keystroke strings such as
# "asdfghjklqwertyuiopzxcvbnm" or the 70-letter example in the task.
_GIBBERISH_RUN_LEN = 25

# Minimum number of meaningful (alphabetic) words for a "complete" posting.
# Genuine ads are written as sentences; tiny inputs like "hello"/"test"/"abc"
# fall below this. We allow a small exception when the text is saturated with
# job vocabulary so a terse-but-real post ("Flutter developer needed") survives.
_MIN_WORDS = 4
_MIN_WORDS_CLEAR_JOB = 3   # job-vocab hits required to pass under _MIN_WORDS
_MIN_JOB_HITS = 2          # minimum job-vocabulary hits for a coherent text


def _meaningful_words(text: str) -> list:
    """Whitespace tokens reduced to their lowercase alphabetic core.

    Digits, punctuation and symbols are dropped (e.g. "$9000/week" -> none,
    "React," -> "react", "5+years" -> "years"), so URLs / numbers / symbols do
    not inflate the word count and cannot hide gibberish behind digits.
    """
    words = []
    for tok in text.split():
        core = re.sub(r"[^A-Za-z]+", "", tok)
        if core:
            words.append(core.lower())
    return words


def validate_job_text(text: str):
    """Return (is_valid: bool, reason: str).

    A rejected result never reaches the ML pipeline. Reason is a short stable
    code useful for logging / tests / the API response.
    """
    stripped = (text or "").strip()

    # 1) Empty / whitespace-only.
    if not stripped:
        return False, "empty_or_whitespace"

    # 2) Excessive unbroken alphabetic run -> random/gibberish keystrokes.
    for tok in stripped.split():
        if re.fullmatch(r"[A-Za-z]{%d,}" % _GIBBERISH_RUN_LEN, tok):
            return False, "gibberish_run"

    words = _meaningful_words(stripped)
    n = len(words)

    # 3) Nothing but numbers / symbols / punctuation (no alphabetic content).
    if n == 0:
        return False, "no_alphabetic_words"

    # Job-vocabulary presence.
    hits = sum(1 for w in words if w in _UNION)

    # 4) Extremely short / not a complete posting.
    if n < _MIN_WORDS and hits < _MIN_WORDS_CLEAR_JOB:
        return False, "too_short"

    # 5) Coherent prose but not job-related at all.
    if hits < _MIN_JOB_HITS:
        return False, "not_job_like"

    # Passed: looks like a usable job advertisement -> let existing pipeline run.
    return True, "valid"


# Reason codes mapped to a single user-friendly message used by the API.
REJECT_MESSAGE = (
    "The provided text does not appear to be a valid job description. "
    "Please paste a complete job advertisement."
)
