"""
Milestone 7B — Job URL fetching with SSRF protection
====================================================

Fetches a PUBLIC job-posting web page and extracts the readable job text so
it can be handed to the EXISTING validation + prediction pipeline:

    URL -> safety validation -> HTTP(S) fetch (each redirect re-validated)
        -> readable text extraction
        -> existing validate_job_text()   (app.py)
        -> existing predict_one()         (app.py)
        -> existing result / evidence / history flow

This module deliberately contains NO classification logic — it only turns a
URL into job text. The classifier, thresholds, scoring and evidence rules are
untouched.

Security model (SSRF / replay protection)
-----------------------------------------
* Only http:// and https:// schemes are accepted (no file:, ftp:, data:, ...).
* localhost, *.localhost, *.local, *.internal and *.home.arpa host names are
  rejected outright.
* Every host name — including the destination of EVERY redirect hop — is
  resolved through DNS and ALL resolved addresses (IPv4 + IPv6) must be
  globally routable. Loopback, private (RFC1918), link-local, CGNAT
  (100.64/10), unique-local (fc00::/7), unspecified, multicast, reserved,
  documentation ranges and IPv4-mapped IPv6 (::ffff:10.0.0.1) are rejected.
  A host name can therefore never be used to reach an internal service.
* Redirects are followed manually (max 5) so each hop can be re-validated
  before it is fetched.
* Connection timeout 6 s, read timeout 12 s, hard response cap 2 MB,
  HTML/XHTML-only content-type check.
* TLS certificate verification is never disabled (requests default).
* URL embedded credentials (user:pass@host) are rejected.
"""

import ipaddress
import re
import socket
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

import requests

# ------------------------------------------------------------------ limits
CONNECT_TIMEOUT_S = 6          # time to establish the TCP/TLS connection
READ_TIMEOUT_S = 12            # time between response bytes
MAX_REDIRECTS = 5              # redirect hops allowed (each re-validated)
MAX_RESPONSE_BYTES = 2_000_000  # hard cap on downloaded page size (2 MB)
CHUNK_SIZE = 65_536

# Minimum extracted text before we hand anything to the pipeline.
MIN_TEXT_CHARS = 350
MIN_TEXT_WORDS = 50

ALLOWED_SCHEMES = {"http", "https"}
ALLOWED_CONTENT_PREFIXES = ("text/html", "application/xhtml")

USER_AGENT = (
    "Mozilla/5.0 (compatible; JobGuardAI-FYP/1.0; +educational job-scam "
    "screening project)"
)

BLOCKED_HOST_SUFFIXES = (".localhost", ".local", ".internal", ".home.arpa")


# ------------------------------------------------------------------ errors
class UrlFetchError(Exception):
    """User-facing URL analysis failure with a stable machine kind."""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind
        self.message = message


MESSAGES = {
    "invalid_url":
        "Please enter a valid web address starting with http:// or https://.",
    "unsupported_scheme":
        "Only http:// and https:// links can be analyzed. Please paste the job description instead.",
    "private_address":
        "This URL points to a private, internal or local address and cannot be fetched. "
        "Please paste the job description instead.",
    "dns_failure":
        "We couldn't resolve that web address. Please check the URL and try again.",
    "fetch_failed":
        "We couldn't reach that page. Please check the link or paste the job description instead.",
    "blocked_by_site":
        "That website blocked automated access. Please paste the job description instead.",
    "not_html":
        "That link doesn't point to a standard web page, so it can't be analyzed. "
        "Please paste the job description instead.",
    "too_large":
        "That page is too large to analyze. Please paste the job description instead.",
    "too_many_redirects":
        "That page redirected too many times, so it can't be analyzed. "
        "Please paste the job description instead.",
    "extraction_insufficient":
        "We couldn't extract enough job information from this page. "
        "Please paste the job description instead.",
}


def _fail(kind: str) -> UrlFetchError:
    return UrlFetchError(kind, MESSAGES[kind])


# ------------------------------------------------------------- IP checking
def _ensure_public_ip(ip_str: str) -> None:
    """Raise UrlFetchError unless ip_str is a globally routable address."""
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        raise _fail("private_address")  # unparseable address -> do not risk it
    # Unwrap IPv4-mapped IPv6 (::ffff:10.0.0.1) so mapped private addresses
    # can never slip through as "IPv6".
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    # is_global is False for loopback, RFC1918 private, link-local, CGNAT,
    # unique-local, unspecified, multicast, reserved and documentation space.
    if not ip.is_global:
        raise _fail("private_address")


def resolve_host(host: str) -> set:
    """Resolve host to ALL of its IPv4/IPv6 addresses (fail -> dns_failure)."""
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except OSError:
        raise _fail("dns_failure")
    addresses = {info[4][0] for info in infos}
    if not addresses:
        raise _fail("dns_failure")
    return addresses


# -------------------------------------------------------------- URL checks
def validate_public_url(raw_url) -> str:
    """Return the URL string if it is a fetchable public http(s) address.

    Raises UrlFetchError otherwise. Used for the initial URL AND for every
    redirect destination before it is fetched.
    """
    if not isinstance(raw_url, str):
        raise _fail("invalid_url")
    url = raw_url.strip()
    if not url:
        raise _fail("invalid_url")

    parts = urlsplit(url)
    scheme = (parts.scheme or "").lower()

    if not scheme:
        raise _fail("invalid_url")
    if scheme not in ALLOWED_SCHEMES:
        raise _fail("unsupported_scheme")
    if not parts.netloc:
        raise _fail("invalid_url")

    # Reject embedded credentials (user:pass@host) — never needed for a job ad.
    if parts.username or parts.password:
        raise _fail("invalid_url")

    # Validate the port early (urlsplit raises ValueError for bad ports).
    try:
        _ = parts.port
    except ValueError:
        raise _fail("invalid_url")

    host = (parts.hostname or "").strip().lower()
    if not host:
        raise _fail("invalid_url")

    # Obvious internal host names — reject before DNS is even consulted.
    if host == "localhost" or host.endswith(BLOCKED_HOST_SUFFIXES):
        raise _fail("private_address")

    # DNS must resolve to public/global addresses ONLY. A host that resolves
    # to any internal address is rejected (DNS-rebinding / numeric-IP bypass).
    for address in resolve_host(host):
        _ensure_public_ip(address)

    return url


# ----------------------------------------------------- readable text extraction
_BLOCK_TAGS = {
    "p", "div", "br", "li", "ul", "ol", "tr", "table", "thead", "tbody",
    "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "blockquote",
    "pre", "hr", "dd", "dt", "dl", "figure", "figcaption", "main", "address",
    "fieldset", "caption",
}

_SKIP_TAGS = {
    "script", "style", "noscript", "template", "svg", "canvas", "iframe",
    "object", "embed", "select", "option", "button", "label", "form",
    "input", "textarea", "nav", "header", "footer", "aside", "dialog",
}

_VOID_TAGS = {"br", "hr", "img", "input", "meta", "link", "source", "wbr"}

# Elements/attributes that mark obvious page chrome (cookie banners,
# navigation wrappers, menus) when present on generic containers.
_CHROME_ATTR_MARKERS = ("cookie", "consent", "banner")
_CHROME_ROLES = {"navigation", "banner", "contentinfo", "menubar", "search"}

_WS_RE = re.compile(r"[ \t\r\f\v\xa0]+")


def _clean_lines(raw: str) -> list:
    lines = []
    for line in raw.split("\n"):
        line = _WS_RE.sub(" ", line).strip()
        if line:
            lines.append(line)
    # Collapse immediate duplicates (repeated menu/link items).
    deduped = []
    for line in lines:
        if not deduped or line != deduped[-1]:
            deduped.append(line)
    return deduped


class _ReadableTextParser(HTMLParser):
    """Stdlib HTML -> visible text. No external parser dependency.

    * skips script/style/nav/header/footer/aside/forms/media + cookie banners
    * block tags become line boundaries, entities are decoded
    * captures <title> and, separately, the text inside <article>/<main> so
      job-post content can be preferred over leftover page chrome
    * never raises on malformed markup
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._parts = []
        self._focus_parts = []          # text inside article/main containers
        self._title_parts = []
        self._open_skip = []            # stack of tags whose content we skip
        self._title_depth = 0
        self._focus_depth = 0

    # -- helpers
    def _is_chrome_attrs(self, attrs) -> bool:
        for name, value in attrs:
            name = (name or "").lower()
            value = (value or "").lower()
            if name == "role" and value in _CHROME_ROLES:
                return True
            if name in ("id", "class") and any(m in value for m in _CHROME_ATTR_MARKERS):
                return True
        return False

    # -- parser events
    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if self._open_skip:
            if tag in _SKIP_TAGS and tag not in _VOID_TAGS:
                self._open_skip.append(tag)
            return
        if tag in _SKIP_TAGS and tag not in _VOID_TAGS:
            self._open_skip.append(tag)
            return
        if self._is_chrome_attrs(attrs):
            self._open_skip.append(tag)
            return
        if tag == "title":
            self._title_depth += 1
            return
        if tag in ("article", "main") and tag not in _VOID_TAGS:
            self._focus_depth += 1
        if tag in _BLOCK_TAGS:
            self._parts.append("\n")
            self._focus_parts.append("\n")

    def handle_endtag(self, tag):
        tag = tag.lower()
        if self._open_skip:
            if tag in self._open_skip:
                while self._open_skip and self._open_skip.pop() != tag:
                    pass
            return
        if tag == "title":
            self._title_depth = max(0, self._title_depth - 1)
            return
        if tag in ("article", "main"):
            self._focus_depth = max(0, self._focus_depth - 1)
        if tag in _BLOCK_TAGS:
            self._parts.append("\n")
            self._focus_parts.append("\n")

    def handle_startendtag(self, tag, attrs):
        tag = tag.lower()
        if not self._open_skip and tag in _BLOCK_TAGS:
            self._parts.append("\n")
            self._focus_parts.append("\n")

    def handle_data(self, data):
        if self._open_skip:
            return
        if self._title_depth:
            self._title_parts.append(data)
            return
        text = data
        if text.strip():
            self._parts.append(text)
            if self._focus_depth:
                self._focus_parts.append(text)

    # -- results
    def title(self) -> str:
        return _WS_RE.sub(" ", " ".join(self._title_parts)).strip()[:200]

    def text(self) -> str:
        full = "\n".join(_clean_lines("".join(self._parts)))
        focus = "\n".join(_clean_lines("".join(self._focus_parts)))
        # Prefer article/main content when it is substantial relative to the
        # whole page — this drops leftover page chrome "where practical".
        if len(focus) >= MIN_TEXT_CHARS and len(focus) >= 0.5 * len(full):
            return focus
        return full


def extract_readable(html: str):
    """Return (title, text) extracted from an HTML document string."""
    parser = _ReadableTextParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception:  # malformed markup — use whatever was captured
        pass
    return parser.title(), parser.text()


# ------------------------------------------------------------------- fetch
def _build_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.5",
        "Accept-Language": "en",
    })
    return session


def fetch_page(raw_url: str) -> dict:
    """Validate, fetch (with per-hop SSRF re-validation) and extract text.

    Returns {'final_url', 'title', 'text'}. Raises UrlFetchError with a
    user-facing message on every failure path.
    """
    # Gate 1 — validate BEFORE the first request is even attempted.
    current_url = validate_public_url(raw_url)
    session = _build_session()
    response = None
    try:
        for _hop in range(MAX_REDIRECTS + 1):
            try:
                response = session.get(
                    current_url,
                    timeout=(CONNECT_TIMEOUT_S, READ_TIMEOUT_S),
                    stream=True,
                    allow_redirects=False,   # redirects handled + validated manually
                    verify=True,             # TLS certificate verification ON
                )
            except requests.exceptions.SSLError:
                raise UrlFetchError(
                    "fetch_failed",
                    "The secure connection (TLS) failed for that address. "
                    "Please paste the job description instead.")
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout,
                    requests.exceptions.RequestException):
                raise _fail("fetch_failed")

            if response.status_code in (301, 302, 303, 307, 308):
                location = (response.headers.get("Location") or "").strip()
                response.close()
                response = None
                if not location:
                    raise _fail("fetch_failed")
                # Gate 2 — validate the redirect destination BEFORE following.
                current_url = urljoin(current_url, location)
                validate_public_url(current_url)
                continue
            break
        else:
            raise _fail("too_many_redirects")

        # --- final response checks --------------------------------------
        if response is None:
            raise _fail("fetch_failed")
        status = response.status_code
        if status in (401, 403, 429):
            raise _fail("blocked_by_site")
        if status >= 400:
            raise UrlFetchError(
                "fetch_failed",
                f"The site returned HTTP {status} for that link. "
                "Please check the URL or paste the job description instead.")

        content_type = (response.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if not content_type.startswith(ALLOWED_CONTENT_PREFIXES):
            raise _fail("not_html")

        declared_length = (response.headers.get("Content-Length") or "").strip()
        if declared_length.isdigit() and int(declared_length) > MAX_RESPONSE_BYTES:
            raise _fail("too_large")

        chunks = bytearray()
        for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
            if not chunk:
                continue
            chunks.extend(chunk)
            if len(chunks) > MAX_RESPONSE_BYTES:
                raise _fail("too_large")

        html = bytes(chunks).decode(response.encoding or "utf-8", errors="replace")
        title, text = extract_readable(html)
        final_url = str(response.url)
        if not title:
            title = urlsplit(final_url).hostname or ""
        return {"final_url": final_url, "title": title, "text": text}
    finally:
        if response is not None:
            response.close()
        session.close()


def analyze_url(raw_url: str) -> dict:
    """Full URL -> job-text pipeline entry point used by app.py."""
    page = fetch_page(raw_url)
    text = (page["text"] or "").strip()
    if len(text) < MIN_TEXT_CHARS or len(text.split()) < MIN_TEXT_WORDS:
        raise _fail("extraction_insufficient")
    return {
        "text": text,
        "title": (page["title"] or "").strip(),
        "final_url": page["final_url"],
    }
