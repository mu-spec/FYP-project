"""
Milestone 7B tests — Job URL analysis: SSRF protection, fetching, extraction.
============================================================================

Run from backend/:
    python -m unittest test_url_analysis -v

Six suites:

  1. UrlValidationTests    - scheme/host/credentials checks (no network)
  2. DnsSecurityTests      - hostnames resolving to private/internal IPs are
                             blocked BEFORE any HTTP request is attempted
  3. RedirectSecurityTests - every redirect hop is re-validated; redirect
                             limit enforced; relative redirects resolved
  4. FetchGuardTests       - status codes, content-type, response-size cap,
                             connection/timeout/TLS failure handling
  5. ExtractionTests       - HTML -> readable job text (chrome removed,
                             entities decoded, article preference, threshold)
  6. PredictUrlApiTests    - Flask API behaviour: same validation/prediction/
                             history path as /api/predict, exactly one history
                             row, unchanged SQLite schema

No real network is required: HTTP interactions use a fake response object.
These tests do NOT retrain, fit, or modify the model / vectorizer / artifacts.
"""

import json
import unittest
from unittest import mock

from auth_test_utils import signup_and_login

import requests

import url_fetcher
from url_fetcher import UrlFetchError, extract_readable, validate_public_url


def _blocked(url, kind):
    """Assert url is rejected with the expected error kind."""
    try:
        validate_public_url(url)
    except UrlFetchError as exc:
        return exc.kind == kind
    return False


class UrlValidationTests(unittest.TestCase):
    def test_accepts_public_http_and_https(self):
        for url in (
            "http://example.com/jobs/senior-dev",
            "https://example.com/path?q=1#anchor",
            "https://8.8.8.8/",
            "http://[2606:4700::1111]/job",
            "http://172.32.0.1/",            # just outside the private range
        ):
            self.assertTrue(validate_public_url(url), url)

    def test_rejects_malformed_and_empty(self):
        for url in ("", "   ", "not a url", "http://", "example.com"):
            self.assertTrue(_blocked(url, "invalid_url"), url)

    def test_rejects_unsupported_schemes(self):
        for url in ("ftp://example.com/a", "file:///etc/passwd",
                    "javascript:alert(1)", "data:text/html,hello",
                    "gopher://example.com/"):
            self.assertTrue(_blocked(url, "unsupported_scheme"), url)

    def test_rejects_embedded_credentials(self):
        self.assertTrue(_blocked("http://user:pass@example.com/", "invalid_url"))
        self.assertTrue(_blocked("https://bot@jobs.example.com/x", "invalid_url"))

    def test_rejects_localhost_names(self):
        for url in ("http://localhost", "http://localhost:5000/api",
                    "http://sub.localhost/", "http://myserver.local/",
                    "http://db.internal/", "http://host.home.arpa/"):
            self.assertTrue(_blocked(url, "private_address"), url)

    def test_rejects_private_ipv4_ranges(self):
        for url in ("http://127.0.0.1/", "http://127.8.8.8/", "http://0.0.0.0/",
                    "http://10.0.0.1/", "http://10.255.255.255/",
                    "http://172.16.0.1/", "http://172.31.255.254/",
                    "http://192.168.0.10/", "http://192.168.100.7/",
                    "http://169.254.169.254/latest/meta-data/",
                    "http://100.64.0.1/"):
            self.assertTrue(_blocked(url, "private_address"), url)

    def test_rejects_private_ipv6_ranges(self):
        for url in ("http://[::1]/", "http://[::]/", "http://[fc00::1]/",
                    "http://[fd12:3456::1]/", "http://[fe80::1]/",
                    "http://[::ffff:10.0.0.1]/", "http://[::ffff:127.0.0.1]/"):
            self.assertTrue(_blocked(url, "private_address"), url)


class DnsSecurityTests(unittest.TestCase):
    """A public-looking host name must not bypass the IP checks via DNS."""

    def setUp(self):
        # Never allow a real HTTP request inside these tests.
        self.session_get = mock.patch("requests.Session.get")
        self.session_get.start()
        self.addCleanup(self.session_get.stop)

    def test_hostname_resolving_to_private_ip_is_blocked(self):
        with mock.patch.object(url_fetcher, "resolve_host",
                               return_value={"10.0.0.5"}):
            self.assertTrue(_blocked("http://careers.example.com/", "private_address"))

    def test_multi_address_host_blocked_if_any_ip_is_internal(self):
        with mock.patch.object(url_fetcher, "resolve_host",
                               return_value={"8.8.8.8", "192.168.1.10"}):
            self.assertTrue(_blocked("http://mixed.example.com/", "private_address"))

    def test_hostname_resolving_to_loopback_is_blocked(self):
        with mock.patch.object(url_fetcher, "resolve_host",
                               return_value={"127.0.0.1"}):
            self.assertTrue(_blocked("http://fake-internal.example/", "private_address"))

    def test_hostname_resolving_to_public_ip_passes_validation(self):
        with mock.patch.object(url_fetcher, "resolve_host",
                               return_value={"93.184.216.34"}):
            self.assertTrue(validate_public_url("http://public.example.com/"))


class _FakeResponse:
    def __init__(self, status=200, headers=None, content=b"", chunks=None,
                 url="https://93.184.216.34/job"):
        self.status_code = status
        self.headers = headers or {}
        self._chunks = chunks if chunks is not None else [content]
        self.encoding = "utf-8"
        self.url = url
        self.closed = False

    def iter_content(self, chunk_size=1):
        for chunk in self._chunks:
            yield chunk

    def close(self):
        self.closed = True


JOB_HTML = (b"<html><head><title>React Developer Needed</title></head><body>"
            b"<article><h1>React Developer Needed</h1>"
            b"<p>We are hiring a React developer to build a responsive web "
            b"application. Requirements: JavaScript, REST APIs, CSS.</p>"
            b"<p>This is a full-time remote role with a friendly team.</p>"
            b"</article></body></html>")


class RedirectSecurityTests(unittest.TestCase):
    def _patch_get(self, responses):
        calls = []

        def fake_get(session, url, **kwargs):
            calls.append(url)
            return responses[min(len(calls) - 1, len(responses) - 1)]

        patcher = mock.patch("requests.Session.get", autospec=True,
                             side_effect=fake_get)
        patcher.start()
        self.addCleanup(patcher.stop)
        return calls

    def test_redirect_to_private_ip_blocked_before_fetch(self):
        responses = [_FakeResponse(302, {"Location": "http://10.9.9.9/steal"})]
        calls = self._patch_get(responses)
        with self.assertRaises(UrlFetchError) as ctx:
            url_fetcher.fetch_page("https://93.184.216.34/redirect")
        self.assertEqual(ctx.exception.kind, "private_address")
        # Only the first hop was requested; the private destination was never fetched.
        self.assertEqual(len(calls), 1)

    def test_redirect_to_localhost_blocked(self):
        responses = [_FakeResponse(302, {"Location": "http://localhost:8080/"})]
        self._patch_get(responses)
        with self.assertRaises(UrlFetchError) as ctx:
            url_fetcher.fetch_page("https://93.184.216.34/redirect")
        self.assertEqual(ctx.exception.kind, "private_address")

    def test_redirect_to_ftp_scheme_blocked(self):
        responses = [_FakeResponse(302, {"Location": "ftp://93.184.216.34/x"})]
        self._patch_get(responses)
        with self.assertRaises(UrlFetchError) as ctx:
            url_fetcher.fetch_page("https://93.184.216.34/redirect")
        self.assertEqual(ctx.exception.kind, "unsupported_scheme")

    def test_relative_redirect_to_public_target_is_followed(self):
        responses = [
            _FakeResponse(302, {"Location": "/job/2"}),
            _FakeResponse(200, {"Content-Type": "text/html; charset=utf-8"},
                          content=JOB_HTML),
        ]
        calls = self._patch_get(responses)
        page = url_fetcher.fetch_page("https://93.184.216.34/redirect")
        self.assertEqual(len(calls), 2)
        self.assertIn("React Developer", page["text"])

    def test_too_many_redirects_rejected(self):
        responses = [_FakeResponse(302, {"Location": "https://93.184.216.34/hop"})]
        self._patch_get(responses)
        with self.assertRaises(UrlFetchError) as ctx:
            url_fetcher.fetch_page("https://93.184.216.34/loop")
        self.assertEqual(ctx.exception.kind, "too_many_redirects")


class FetchGuardTests(unittest.TestCase):
    def _patch_get(self, response):
        return mock.patch("requests.Session.get", autospec=True,
                          return_value=response)

    def test_blocked_by_site_403(self):
        response = _FakeResponse(403, {"Content-Type": "text/html"})
        with self._patch_get(response):
            with self.assertRaises(UrlFetchError) as ctx:
                url_fetcher.fetch_page("https://93.184.216.34/job")
            self.assertEqual(ctx.exception.kind, "blocked_by_site")
            self.assertIn("paste the job description", ctx.exception.message)

    def test_non_html_content_type_rejected(self):
        for ctype in ("application/pdf", "application/rss+xml", "image/png",
                      "text/plain", "application/json"):
            response = _FakeResponse(200, {"Content-Type": ctype}, content=b"data")
            with self._patch_get(response), self.subTest(ctype=ctype):
                with self.assertRaises(UrlFetchError) as ctx:
                    url_fetcher.fetch_page("https://93.184.216.34/file")
                self.assertEqual(ctx.exception.kind, "not_html")

    def test_oversized_content_length_rejected_without_download(self):
        response = _FakeResponse(200, {"Content-Type": "text/html",
                                       "Content-Length": "5000000"})
        with self._patch_get(response):
            with self.assertRaises(UrlFetchError) as ctx:
                url_fetcher.fetch_page("https://93.184.216.34/huge")
            self.assertEqual(ctx.exception.kind, "too_large")

    def test_streamed_response_over_cap_rejected(self):
        chunk = b"x" * 65536
        response = _FakeResponse(200, {"Content-Type": "text/html"},
                                 chunks=[chunk] * 40)  # 2.6 MB total
        with self._patch_get(response):
            with self.assertRaises(UrlFetchError) as ctx:
                url_fetcher.fetch_page("https://93.184.216.34/stream")
            self.assertEqual(ctx.exception.kind, "too_large")

    def test_connection_failures_are_friendly(self):
        for exc in (requests.exceptions.ConnectionError("boom"),
                    requests.exceptions.ConnectTimeout(),
                    requests.exceptions.ReadTimeout(),
                    requests.exceptions.RequestException("x")):
            with self.subTest(exc=type(exc).__name__):
                with mock.patch("requests.Session.get", autospec=True, side_effect=exc):
                    with self.assertRaises(UrlFetchError) as ctx:
                        url_fetcher.fetch_page("https://93.184.216.34/down")
                    self.assertEqual(ctx.exception.kind, "fetch_failed")
                    self.assertIn("paste the job description", ctx.exception.message)

    def test_tls_failure_is_friendly(self):
        with mock.patch("requests.Session.get", autospec=True,
                        side_effect=requests.exceptions.SSLError("cert")):
            with self.assertRaises(UrlFetchError) as ctx:
                url_fetcher.fetch_page("https://93.184.216.34/badcert")
            self.assertEqual(ctx.exception.kind, "fetch_failed")
            self.assertIn("TLS", ctx.exception.message)


class ExtractionTests(unittest.TestCase):
    def test_scripts_styles_and_chrome_removed(self):
        html = """<html><head><title>Backend Engineer — Acme</title>
        <style>.a{color:red}</style><script>analytics();</script></head>
        <body><nav><a>Home</a><a>Jobs</a><a>Sign in</a></nav>
        <div class="cookie-banner">We use cookies</div>
        <article><h1>Backend Engineer</h1>
        <p>We are hiring a backend engineer to design REST APIs and improve
        reliability of our payment platform.</p>
        <p>Requirements: 5+ years experience with Python, SQL and Docker.
        Health insurance and remote work included.</p></article>
        <footer>© Acme 2026</footer></body></html>"""
        title, text = extract_readable(html)
        self.assertEqual(title, "Backend Engineer — Acme")
        self.assertNotIn("analytics", text)
        self.assertNotIn("color:red", text)
        self.assertNotIn("Sign in", text)
        self.assertNotIn("cookies", text)
        self.assertNotIn("© Acme", text)
        self.assertIn("backend engineer", text)
        self.assertIn("Requirements", text)

    def test_entities_decoded_and_blocks_separated(self):
        title, text = extract_readable(
            "<p>React &amp; Node developer needed</p><p>Apply&nbsp;now</p>")
        self.assertIn("&", text)
        self.assertNotIn("&amp;", text)
        self.assertIn("React & Node developer needed", text.splitlines()[0])

    def test_article_content_preferred_over_chrome(self):
        html = ("<body><article><p>" + "Senior Django developer building web "
                "applications with Python. " * 8 + "</p></article>"
                "<p>Menu item one</p><p>Menu item two</p></body>")
        _, text = extract_readable(html)
        self.assertIn("Senior Django developer", text)
        self.assertNotIn("Menu item one", text)

    def test_analyze_url_threshold_insufficient(self):
        with mock.patch.object(url_fetcher, "fetch_page", return_value={
            "final_url": "https://93.184.216.34/x", "title": "t",
            "text": "Too short text.",
        }):
            with self.assertRaises(UrlFetchError) as ctx:
                url_fetcher.analyze_url("https://93.184.216.34/x")
            self.assertEqual(ctx.exception.kind, "extraction_insufficient")
            self.assertIn("paste the job description", ctx.exception.message)


class PredictUrlApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import app
        cls.app_module = app
        # 8A.1: the API now requires a session — sign the test client in.
        cls.client, cls.test_email = signup_and_login(cls.app_module)

    def _post(self, url, **extra):
        return self.client.post(
            "/api/predict-url",
            data=json.dumps({"url": url, **extra}),
            content_type="application/json",
        )

    def _history_ids(self):
        return [row["id"] for row in self.client.get("/api/history").get_json()]

    def test_empty_url_rejected(self):
        for payload in ({}, {"url": ""}, {"url": "   "}):
            with self.subTest(payload=payload):
                r = self.client.post("/api/predict-url", data=json.dumps(payload),
                                     content_type="application/json")
                self.assertEqual(r.status_code, 400)
                self.assertEqual(r.get_json()["url_error"], "invalid_url")

    def test_ssrf_blocked_before_any_fetch_or_prediction(self):
        before = self._history_ids()
        with mock.patch.object(self.app_module, "analyze_url") as analyze_mock, \
             mock.patch.object(self.app_module, "predict_one") as predict_mock:
            # Simulate the pre-flight SSRF rejection from url_fetcher.
            analyze_mock.side_effect = UrlFetchError(
                "private_address", url_fetcher.MESSAGES["private_address"])
            r = self._post("http://169.254.169.254/latest/meta-data/")
        self.assertEqual(r.status_code, 400)
        body = r.get_json()
        self.assertEqual(body["url_error"], "private_address")
        self.assertIn("private, internal or local", body["error"])
        self.assertNotIn("invalid_input", body)
        predict_mock.assert_not_called()
        self.assertEqual(self._history_ids(), before)

    def test_fetch_failure_returns_friendly_error_without_history(self):
        before = self._history_ids()
        with mock.patch.object(self.app_module, "analyze_url") as analyze_mock, \
             mock.patch.object(self.app_module, "predict_one") as predict_mock:
            analyze_mock.side_effect = UrlFetchError(
                "blocked_by_site", url_fetcher.MESSAGES["blocked_by_site"])
            r = self._post("https://93.184.216.34/forbidden")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.get_json()["url_error"], "blocked_by_site")
        predict_mock.assert_not_called()
        self.assertEqual(self._history_ids(), before)

    def test_non_job_extracted_text_rejected_by_existing_validator(self):
        before = self._history_ids()
        with mock.patch.object(self.app_module, "analyze_url") as analyze_mock, \
             mock.patch.object(self.app_module, "predict_one") as predict_mock:
            analyze_mock.return_value = {
                "text": ("ha da la " * 300).strip(),   # long but not job-like
                "title": "Random blog", "final_url": "https://93.184.216.34/blog",
            }
            r = self._post("https://93.184.216.34/blog")
        self.assertEqual(r.status_code, 400)
        body = r.get_json()
        self.assertTrue(body["invalid_input"])
        self.assertEqual(body["error"], self.app_module.REJECT_MESSAGE)
        predict_mock.assert_not_called()
        self.assertEqual(self._history_ids(), before)

    def test_valid_url_job_uses_existing_classifier_and_history(self):
        job_text = (
            "Acme Software is hiring a Senior Full-Stack Engineer to join our "
            "product team. You will build scalable web applications with React "
            "and Node.js. Requirements: 5+ years experience, strong REST API "
            "design. We offer a competitive salary, health insurance and full "
            "remote work. Apply through our careers portal."
        )
        before = len(self.client.get("/api/history").get_json())
        with mock.patch.object(self.app_module, "analyze_url") as analyze_mock:
            analyze_mock.return_value = {
                "text": job_text, "title": "Senior Full-Stack Engineer",
                "final_url": "https://93.184.216.34/job/1",
            }
            r = self._post("https://93.184.216.34/job/1")
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        # Same response shape / engine as the text endpoint (no second system).
        self.assertIn(body["prediction"], ("Scam", "Legitimate"))
        self.assertIn("probabilities", body)
        self.assertIn("red_flags", body)
        self.assertIn("engine", body)
        self.assertEqual(body["job_title"], "Senior Full-Stack Engineer")
        # Exactly one normal history row was created (unchanged schema).
        rows = self.client.get("/api/history").get_json()
        self.assertEqual(len(rows), before + 1)
        self.assertEqual(rows[0]["job_title"], "Senior Full-Stack Engineer")
        self.assertIsInstance(rows[0]["evidence"], list)

    def test_sqlite_schema_unchanged(self):
        import sqlite3
        with sqlite3.connect(self.app_module.DB_PATH) as db:
            columns = [row[1] for row in db.execute("PRAGMA table_info(predictions)")]
        self.assertEqual(
            columns,
            ["id", "job_title", "prediction", "confidence", "created_at",
             "evidence_json"],
        )


if __name__ == "__main__":
    unittest.main()
