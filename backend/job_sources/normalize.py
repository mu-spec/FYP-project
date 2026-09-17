"""Shared normalization helpers for external job providers (8B.1)."""

from datetime import datetime, timezone
from html.parser import HTMLParser

MAX_DESCRIPTION_CHARS = 8000  # store enough for full analysis, bound the payload


class _SafeTextExtractor(HTMLParser):
    """Extracts visible text from third-party HTML; never re-emits markup."""

    _BLOCK_TAGS = {"p", "div", "br", "li", "ul", "ol", "tr", "table",
                   "h1", "h2", "h3", "h4", "h5", "h6", "section", "article"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip_depth += 1
        elif tag in self._BLOCK_TAGS:
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data):
        if not self._skip_depth:
            self.parts.append(data)


def strip_html(raw):
    """Third-party descriptions may contain HTML: convert to safe plain text.

    Returns None for empty input. The result is rendered by React as a plain
    text node (never via dangerouslySetInnerHTML), so no markup survives.
    """
    if raw is None:
        return None
    parser = _SafeTextExtractor()
    try:
        parser.feed(str(raw))
        parser.close()
    except Exception:
        # Malformed markup must never break ingestion — degrade to a crude strip.
        import re
        text = re.sub(r"<[^>]+>", " ", str(raw))
    else:
        text = "".join(parser.parts)
    text = " ".join(text.split())
    if len(text) > MAX_DESCRIPTION_CHARS:
        text = text[:MAX_DESCRIPTION_CHARS].rstrip() + "…"
    return text or None


def clean_str(value, limit=300):
    """Trimmed single-line string or None — never an invented placeholder."""
    if value is None:
        return None
    text = " ".join(str(value).split())
    if not text:
        return None
    return text[:limit]


def clean_tags(value):
    """List of clean tag strings, or [] when the provider gives nothing."""
    if not isinstance(value, list):
        return []
    tags = []
    for tag in value:
        text = clean_str(tag, limit=60)
        if text and text not in tags:
            tags.append(text)
    return tags


def to_iso_timestamp(value):
    """Unix seconds OR ISO string -> ISO-8601 UTC string, else None."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()
        except (OverflowError, OSError, ValueError):
            return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).isoformat()
    except ValueError:
        return None


def now_iso():
    return datetime.now(timezone.utc).isoformat()
