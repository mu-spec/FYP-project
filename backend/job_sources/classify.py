"""Milestone 8E.4 — deterministic category / work-mode / job-type mapping.

A rules-first classifier for the unified Jobs filters. NO ML is involved:
every decision comes from transparent keyword tables that anyone can read
and audit, applied to the fields providers already give us (title, tags,
provider category, description).

Design contract
---------------
- category:         always decided ("other" when nothing matches) — the spec
                    defines Other as the honest fallback bucket.
- work_mode:        conservative. Only EXPLICIT signals count (a provider
                    remote flag, or "remote"/"on-site"/"hybrid" wording in the
                    title or tags). Unknown stays None and such jobs appear
                    only under the "Any" work mode — never falsely under
                    Remote/On-site/Hybrid. Descriptions are deliberately NOT
                    scanned (they mention "remote" for unrelated reasons far
                    too often to be trustworthy).
- normalized_job_type:
                    conservative. Provider-supplied type strings are mapped
                    onto the common set; a present-but-unmappable string
                    becomes "other"; no signal at all stays None and never
                    gets fabricated.

All three functions are pure and deterministic: the same inputs always
produce the same output, on the same provider row, on every run.
"""

import re

CATEGORY_OTHER = "other"
WORK_MODE_UNKNOWN = None      # unknown jobs are surfaced under "Any" only
JOB_TYPE_UNKNOWN = None

# ---------------------------------------------------------------------------
# Category keyword tables (ordered — ties break toward the earlier entry,
# so more specific disciplines are listed before broad adjacent ones).
# Patterns are case-insensitive with word boundaries; hyphens/spaces/
# underscores inside multi-word skills are interchangeable.
# ---------------------------------------------------------------------------
_CATEGORY_RULES = [
    ("full_stack", [
        r"full[\s_-]?stack", r"\bfullstack\b", r"\bmern\b", r"\bmean[\s_-]?stack\b",
    ]),
    ("frontend", [
        r"front[\s_-]?end", r"\breact\b(?![-\s]?native)", r"\bvue\b", r"\bangular\b",
        r"next\.?js", r"\bnuxt\b", r"\bsvelte\b", r"\bhtml\b", r"\bcss\b",
        r"tailwind", r"\bui\s+developer\b", r"\bweb\s+developer\b", r"web[\s_-]?dev",
        r"\bjavascript\b", r"\btypescript\b",
    ]),
    ("backend", [
        r"back[\s_-]?end", r"\bdjango\b", r"\bflask\b", r"fast[\s_-]?api",
        r"\bspring\b", r"\blaravel\b", r"\brails\b", r"node\.?js", r"\bphp\b",
        r"wordpress", r"\bgraphql\b", r"microservice", r"\bapi\b",
    ]),
    ("mobile", [
        r"\bflutter\b", r"\bandroid\b", r"\bios\b", r"react[\s_-]?native",
        r"\bswift\b", r"\bkotlin\b", r"\bmobile\b",
    ]),
    ("ai_ml", [
        r"machine[\s_-]?learning", r"\bai\b", r"artificial[\s_-]?intelligence",
        r"\bnlp\b", r"natural[\s_-]?language", r"computer[\s_-]?vision",
        r"\bllms?\b", r"deep[\s_-]?learning", r"pytorch", r"tensorflow",
        r"\bgenai\b", r"mlops",
    ]),
    ("data_science", [
        r"data[\s_-]?scien", r"data[\s_-]?analy", r"business[\s_-]?intelligence",
        r"power[\s_-]?bi", r"\bbi\b", r"tableau", r"big[\s_-]?data",
        r"data[\s_-]?engineer", r"\bdashboard",
    ]),
    ("cyber_security", [
        r"cyber[\s_-]?security", r"information[\s_-]?security", r"\binfosec\b",
        r"penetration[\s_-]?test", r"\bpentest", r"security[\s_-]"
        r"(analyst|engineer|researcher|specialist|consultant)",
        r"application[\s_-]?security", r"\bappsec\b", r"\bmalware\b",
        r"threat[\s_-]?intelligence", r"\bsoc\b", r"\bsecurity\b",
    ]),
    ("devops_cloud", [
        r"devops", r"\bsre\b", r"site[\s_-]?reliability", r"kubernetes", r"\bk8s\b",
        r"\bdocker\b", r"terraform", r"\baws\b", r"\bazure\b", r"\bgcp\b",
        r"google[\s_-]?cloud", r"\bcloud\b", r"ci/?cd", r"\bjenkins\b",
        r"\blinux\b", r"platform[\s_-]?engineer",
    ]),
    ("ui_ux", [
        r"ui/?ux", r"\bux\b", r"ui[\s_-]?designer", r"user[\s_-]?experience",
        r"user[\s_-]?interface", r"product[\s_-]?designer", r"\bfigma\b",
        r"interaction[\s_-]?design", r"ux[\s_-]?(research|engineer)",
    ]),
    ("graphic_design", [
        r"graphic[\s_-]?design", r"\bphotoshop\b", r"\billustrator\b", r"\bcanva\b",
        r"logo[\s_-]?design", r"brand[\s_-]?(identity|design)", r"motion[\s_-]?design",
        r"\billustration\b", r"creative[\s_-]?director", r"\bcreative\b",
    ]),
    ("marketing", [
        r"marketing", r"advertis", r"public[\s_-]?relations", r"\bseo\b", r"\bsem\b",
        r"\bppc\b", r"social[\s_-]?media", r"content[\s_-]?(writer|marketing|creator)",
        r"\bcopywrit", r"growth[\s_-]?(market|hack)", r"email[\s_-]?marketing",
    ]),
    ("sales", [
        r"\bsales\b", r"business[\s_-]?development", r"account[\s_-]?executive",
        r"lead[\s_-]?generation", r"\bbdr\b", r"\bsdr\b", r"pre[\s_-]?sales",
    ]),
    ("finance_accounting", [
        r"financ", r"accounting", r"\baccountant\b", r"accounts[\s_-]?(payable|receivable)",
        r"bookkeep", r"\bpayroll\b", r"\btaxes?\b", r"\baudit",
    ]),
    ("customer_support", [
        r"customer[\s_-]?(support|service|success)", r"help[\s_-]?desk", r"helpdesk",
        r"technical[\s_-]?support", r"support[\s_-]?(agent|specialist)",
        r"call[\s_-]?center", r"client[\s_-]?services", r"virtual[\s_-]?assistant",
    ]),
    ("human_resources", [
        r"human[\s_-]?resources", r"\bhr\b", r"recruit", r"talent[\s_-]?acquisition",
        r"people[\s_-]?(operations|partner)", r"\bhrbp\b",
    ]),
]

_CATEGORY_COMPILED = [
    (slug, [re.compile(p, re.IGNORECASE) for p in patterns])
    for slug, patterns in _CATEGORY_RULES
]
VALID_CATEGORIES = {slug for slug, _ in _CATEGORY_RULES} | {CATEGORY_OTHER}

# Field priority for the category scan: the title is the strongest signal,
# the provider's own category label next, tags next, the description last
# (a single keyword there counts for the least).
_FIELD_WEIGHTS = (
    ("title", 4),
    ("provider_category", 3),
    ("tags", 2),
    ("description", 1),
)

# ---------------------------------------------------------------------------
# Work mode — explicit signals only.
# ---------------------------------------------------------------------------
_HYBRID_RE = re.compile(r"\bhybrid\b", re.IGNORECASE)
_ONSITE_RE = re.compile(r"on[\s_-]?site|on[\s_-]?prem", re.IGNORECASE)
_REMOTE_RE = re.compile(
    r"\bremote\b|work[\s_-]?from[\s_-]?home|\bwfh\b|\banywhere\b", re.IGNORECASE)
VALID_WORK_MODES = {"remote", "onsite", "hybrid"}

# ---------------------------------------------------------------------------
# Job type — first matching rule wins (internship before part-time, so an
# "Internship (part-time)" stays an internship; part-time before full-time;
# temporary before contract before full-time/permanent).
# ---------------------------------------------------------------------------
_JOB_TYPE_RULES = [
    ("internship", [r"\bintern(?:ship)?s?\b"]),
    ("part_time", [r"part[\s_-]?time", r"\bparttime\b"]),
    ("temporary", [r"temporar[yj]", r"\btemps?\b", r"\bseasonal\b", r"\bcasual\b"]),
    ("freelance", [r"freelanc"]),
    ("contract", [r"contract"]),
    ("full_time", [r"full[\s_-]?time", r"\bfulltime\b", r"\bpermanent\b"]),
]
_JOB_TYPE_COMPILED = [
    (value, [re.compile(p, re.IGNORECASE) for p in patterns])
    for value, patterns in _JOB_TYPE_RULES
]
VALID_JOB_TYPES = {"full_time", "part_time", "contract", "freelance",
                   "internship", "temporary", "other"}


def _tags_text(tags):
    if not tags:
        return ""
    if isinstance(tags, str):
        return tags
    return " ".join(str(t) for t in tags if t)


def classify_category(title=None, tags=None, description=None,
                      provider_category=None):
    """Deterministic category slug from the available text fields.

    Weighted scan: title (4) > provider category (3) > tags (2, per joined
    field) > description (1). Highest total wins; ties break toward the
    earlier category in the rule order. No match at all -> "other".
    """
    fields = {
        "title": title or "",
        "provider_category": provider_category or "",
        "tags": _tags_text(tags),
        "description": description or "",
    }
    best_slug, best_score = CATEGORY_OTHER, 0
    for slug, patterns in _CATEGORY_COMPILED:
        score = 0
        for field, weight in _FIELD_WEIGHTS:
            text = fields[field]
            if not text:
                continue
            if any(p.search(text) for p in patterns):
                score += weight
        if score > best_score:
            best_slug, best_score = slug, score
    return best_slug


def classify_work_mode(remote=None, title=None, tags=None):
    """Conservative work mode: explicit signals only, else None (unknown).

    A provider remote flag is authoritative for Remote. Otherwise the title
    and tags are scanned for explicit hybrid / on-site / remote wording —
    in that order, so a "hybrid remote" mention resolves to Hybrid.
    Descriptions are intentionally not scanned. remote=False carries no
    information about on-site/hybrid, so it never invents a mode.
    """
    if remote is True:
        return "remote"
    text = " ".join(part for part in (title or "", _tags_text(tags)) if part)
    if not text.strip():
        return WORK_MODE_UNKNOWN
    if _HYBRID_RE.search(text):
        return "hybrid"
    if _ONSITE_RE.search(text):
        return "onsite"
    if _REMOTE_RE.search(text):
        return "remote"
    return WORK_MODE_UNKNOWN


def classify_job_type(raw_type=None, title=None, source=None):
    """Map a provider type string (or title fallback) onto the common set.

    - Upwork marketplace postings are freelance engagements by definition,
      so source="upwork" resolves to "freelance" (never fabricated from
      unrelated wording).
    - A present but unmappable provider string becomes "other" (it WAS a
      type, we simply don't normalize it into the known six).
    - No signal at all stays None — nothing is invented from silence.
    """
    if source == "upwork":
        return "freelance"
    raw = (raw_type or "").strip()
    if raw:
        for value, patterns in _JOB_TYPE_COMPILED:
            if any(p.search(raw) for p in patterns):
                return value
        return "other"  # provider supplied a type we cannot normalize
    hay = (title or "").strip()
    if hay:
        for value, patterns in _JOB_TYPE_COMPILED:
            if any(p.search(hay) for p in patterns):
                return value
    return JOB_TYPE_UNKNOWN


def classify_fields(title=None, tags=None, description=None, job_type=None,
                    remote=None, source=None):
    """All three filter fields in one call (used by enrichment + backfill)."""
    return (
        classify_category(title=title, tags=tags, description=description),
        classify_work_mode(remote=remote, title=title, tags=tags),
        classify_job_type(raw_type=job_type, title=title, source=source),
    )


def enrich_job(job):
    """Return a copy of a normalized job with the three 8E.4 filter fields.

    Existing keys are preserved untouched; only category / work_mode /
    normalized_job_type are added.
    """
    row = dict(job)
    category, work_mode, job_type_norm = classify_fields(
        title=row.get("title"), tags=row.get("tags"),
        description=row.get("description"), job_type=row.get("job_type"),
        remote=row.get("remote"), source=row.get("source"),
    )
    row["category"] = category
    row["work_mode"] = work_mode
    row["normalized_job_type"] = job_type_norm
    return row
