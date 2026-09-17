"""
Milestone 8E.2 tests — Adzuna as a fourth external job provider.
===============================================================

Run from backend/:
    python -m unittest test_adzuna -v

Suites:
  1. AdzunaNormalizeTests - field mapping (company/location display_name,
                            category tag, contract join, redirect_url,
                            created), missing fields never invented,
                            salary normalization, HTML handling
  2. AdzunaFetchTests     - malformed payloads raise SANITIZED errors
                            (no credential-bearing URL in the message),
                            malformed rows skipped, missing credentials
                            raise AdzunaError
  3. AdzunaConfigTests    - is_configured() driven ONLY by environment
                            variables, ADZUNA_COUNTRY default + override
  4. AdzunaCacheTests     - unconfigured provider is SKIPPED (never marked
                            failed, never fetched); failure isolation with
                            cached Adzuna rows still served; dedup on
                            UNIQUE(source, source_job_id)
  5. AdzunaApiTests       - GET /api/jobs: source=adzuna, search + location
                            filters, existing provider + JobGuard publishing
                            regressions

All credentials/provider responses in automated tests are mocks — no real
Adzuna call is ever made, and no test depends on real credentials existing.
"""

import json
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from unittest import mock

import requests

from auth_test_utils import signup_and_login
from job_sources import adzuna, arbeitnow, jobicy, remote_ok, service

CRED_ENV = {"ADZUNA_APP_ID": "test-app-id", "ADZUNA_APP_KEY": "test-app-key"}


def _adzuna_result(**overrides):
    """A realistic Adzuna search result (mirrors the documented shape)."""
    element = {
        "id": "4785120391",
        "title": "Senior Python Developer",
        "company": {"display_name": "Acme Ltd"},
        "location": {"display_name": "London",
                     "area": ["UK", "England", "London"]},
        "description": "Build &amp; run services. <b>Python</b> and Flask.",
        "redirect_url": "https://www.adzuna.co.uk/jobs/land/4785120391",
        "created": "2026-09-16T10:00:00Z",
        "category": {"label": "IT Jobs"},
        "contract_type": "full_time",
        "contract_time": "permanent",
        "salary_min": 45000.0,
        "salary_max": 60000.0,
        "latitude": 51.5, "longitude": -0.1,
    }
    element.update(overrides)
    return element


def _seed_rows(db_path, rows):
    now = service.now_iso()
    with sqlite3.connect(db_path) as db:
        for r in rows:
            db.execute(
                "INSERT INTO external_jobs (source, source_job_id, title, company,"
                " location, description, job_type, remote, tags_json, salary,"
                " job_url, published_at, fetched_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (r["source"], r["source_job_id"], r["title"], r.get("company"),
                 r.get("location"), r.get("description"), r.get("job_type"),
                 1 if r.get("remote") else 0, json.dumps(r.get("tags", [])),
                 r.get("salary"), r.get("job_url"), r.get("published_at"),
                 r.get("fetched_at") or now),
            )
        db.commit()


class _DBCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp.name, "adzuna-test.db")
        import app
        self.app_module = app
        self.original_db = app.DB_PATH
        app.DB_PATH = self.db_path
        app.init_db()
        self._saved_refresh = dict(service._last_refresh, ok=dict(service._last_refresh["ok"]))
        service._last_refresh = {"at": None, "ok": {n: None for n in service.PROVIDERS}}

    def tearDown(self):
        self.app_module.DB_PATH = self.original_db
        service._last_refresh = self._saved_refresh
        self.tmp.cleanup()


class AdzunaNormalizeTests(unittest.TestCase):
    def test_full_field_mapping(self):
        job = adzuna.normalize(_adzuna_result(), fetched_at="2026-09-17T12:00:00+00:00")
        self.assertEqual(job["source"], "adzuna")
        self.assertEqual(job["source_job_id"], "4785120391")
        self.assertEqual(job["title"], "Senior Python Developer")
        self.assertEqual(job["company"], "Acme Ltd")                    # company.display_name
        self.assertEqual(job["location"], "London")                     # location.display_name
        self.assertEqual(job["description"], "Build & run services. Python and Flask.")
        self.assertEqual(job["job_type"], "Full Time · Permanent")      # contract_type+time
        self.assertFalse(job["remote"])                                 # unknown != remote
        self.assertEqual(job["tags"], ["IT Jobs"])                      # category label
        self.assertEqual(job["salary"], "45k – 60k")
        self.assertEqual(job["job_url"], "https://www.adzuna.co.uk/jobs/land/4785120391")
        self.assertEqual(job["published_at"], "2026-09-16T10:00:00+00:00")
        self.assertEqual(job["fetched_at"], "2026-09-17T12:00:00+00:00")

    def test_missing_fields_are_never_invented(self):
        job = adzuna.normalize({"id": 7, "title": "Minimal Role",
                                "redirect_url": "https://www.adzuna.co.uk/x"})
        self.assertIsNone(job["company"])
        self.assertIsNone(job["location"])
        self.assertIsNone(job["description"])
        self.assertIsNone(job["job_type"])
        self.assertIsNone(job["salary"])
        self.assertIsNone(job["published_at"])
        self.assertEqual(job["tags"], [])
        self.assertFalse(job["remote"])

    def test_salary_normalization_variants(self):
        both = adzuna.normalize(_adzuna_result(salary_min=30000, salary_max=42000))
        self.assertEqual(both["salary"], "30k – 42k")
        lo_only = adzuna.normalize(_adzuna_result(salary_min=25000, salary_max=None))
        self.assertEqual(lo_only["salary"], "25k")
        hi_only = adzuna.normalize(_adzuna_result(salary_min=None, salary_max=900))
        self.assertEqual(hi_only["salary"], "900")
        zeros = adzuna.normalize(_adzuna_result(salary_min=0, salary_max=0))
        self.assertIsNone(zeros["salary"])
        junk = adzuna.normalize(_adzuna_result(salary_min="abc", salary_max="def"))
        self.assertIsNone(junk["salary"])
        absent = adzuna.normalize(_adzuna_result(salary_min=None, salary_max=None))
        self.assertIsNone(absent["salary"])

    def test_original_url_preserved_verbatim(self):
        url = "https://www.adzuna.co.uk/jobs/land/4785120391?utm=x"
        job = adzuna.normalize(_adzuna_result(redirect_url=url))
        self.assertEqual(job["job_url"], url)

    def test_malformed_rows_rejected(self):
        self.assertIsNone(adzuna.normalize("not a dict"))
        self.assertIsNone(adzuna.normalize(None))
        self.assertIsNone(adzuna.normalize({"title": "No ID"}))
        self.assertIsNone(adzuna.normalize({"id": "x", "title": "   "}))


class AdzunaFetchTests(unittest.TestCase):
    class FakeResponse:
        def __init__(self, payload):
            self._p = payload
        def raise_for_status(self):
            pass
        def json(self):
            return self._p

    def test_missing_credentials_raise_sanitized_error(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ADZUNA_APP_ID", None)
            os.environ.pop("ADZUNA_APP_KEY", None)
            with self.assertRaises(adzuna.AdzunaError) as ctx:
                adzuna.fetch_jobs()
            self.assertNotIn("app_id", str(ctx.exception).lower())

    def test_malformed_payload_shapes_raise_sanitized(self):
        for bad in (None, [1, 2], {"results": "nope"}, {}, "x"):
            with mock.patch.dict(os.environ, CRED_ENV), \
                 mock.patch.object(adzuna.requests, "get",
                                   return_value=self.FakeResponse(bad)):
                with self.assertRaises(adzuna.AdzunaError):
                    adzuna.fetch_jobs()

    def test_network_failure_message_carries_no_url_or_credentials(self):
        with mock.patch.dict(os.environ, CRED_ENV), \
             mock.patch.object(adzuna.requests, "get",
                               side_effect=requests.exceptions.HTTPError(
                                   "400 Client Error for url: https://api.adzuna.com/v1/api/jobs/gb/search/1"
                                   "?app_id=test-app-id&app_key=test-app-key")):
            with self.assertRaises(adzuna.AdzunaError) as ctx:
                adzuna.fetch_jobs()
        msg = str(ctx.exception)
        self.assertNotIn("test-app-id", msg)
        self.assertNotIn("test-app-key", msg)
        self.assertNotIn("https://", msg)

    def test_malformed_rows_skipped_individually(self):
        payload = {"results": [
            "garbage",
            {"title": "No ID", "redirect_url": "x"},
            {"id": "1", "title": "  ", "redirect_url": "x"},
            _adzuna_result(),
        ]}
        with mock.patch.dict(os.environ, CRED_ENV), \
             mock.patch.object(adzuna.requests, "get",
                               return_value=self.FakeResponse(payload)):
            jobs = adzuna.fetch_jobs()
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["source_job_id"], "4785120391")

    def test_valid_payload_end_to_end(self):
        payload = {"count": 1, "results": [_adzuna_result()]}
        with mock.patch.dict(os.environ, CRED_ENV), \
             mock.patch.object(adzuna.requests, "get",
                               return_value=self.FakeResponse(payload)):
            jobs = adzuna.fetch_jobs()
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["source"], "adzuna")


class AdzunaConfigTests(unittest.TestCase):
    def test_unconfigured_by_default(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ADZUNA_APP_ID", None)
            os.environ.pop("ADZUNA_APP_KEY", None)
            self.assertFalse(adzuna.is_configured())

    def test_configured_from_environment_only(self):
        with mock.patch.dict(os.environ, CRED_ENV):
            self.assertTrue(adzuna.is_configured())
            self.assertEqual(adzuna.country(), "gb")  # documented default

    def test_country_override_and_partial_credentials(self):
        with mock.patch.dict(os.environ, dict(CRED_ENV, ADZUNA_COUNTRY=" PK ")):
            self.assertEqual(adzuna.country(), "pk")
        with mock.patch.dict(os.environ, {"ADZUNA_APP_ID": "only-id"}):
            os.environ.pop("ADZUNA_APP_KEY", None)
            self.assertFalse(adzuna.is_configured())
        with mock.patch.dict(os.environ, {"ADZUNA_APP_KEY": "only-key"}):
            os.environ.pop("ADZUNA_APP_ID", None)
            self.assertFalse(adzuna.is_configured())

    def test_service_knows_adzuna_source(self):
        self.assertIn("adzuna", service.PROVIDERS)
        self.assertIn("adzuna", service.VALID_SOURCES)


class AdzunaCacheTests(_DBCase):
    def test_unconfigured_provider_skipped_not_failed(self):
        """No credentials: Adzuna is skipped entirely — never marked failed,
        never fetched; other providers still refresh and no degraded state."""
        _seed_rows(self.db_path, [
            dict(source="remoteok", source_job_id="rk-1", title="Remote Role",
                 fetched_at=(datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()),
        ])
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ADZUNA_APP_ID", None)
            os.environ.pop("ADZUNA_APP_KEY", None)
            with mock.patch.object(remote_ok, "fetch_jobs", return_value=[
                    dict(remote_ok.normalize({"slug": "rk-2", "position": "Backend Engineer",
                                              "company": "RK", "tags": [],
                                              "url": "https://remoteok.com/rk-2"}))]), \
                 mock.patch.object(adzuna, "fetch_jobs",
                                   side_effect=AssertionError("unconfigured adzuna must not be fetched")):
                status = service.refresh_if_stale(self.db_path)
        self.assertTrue(status["providers"]["remoteok"]["ok"])
        self.assertIsNone(status["providers"]["adzuna"]["ok"])   # skipped, NOT False
        self.assertFalse(status["stale"])

    def test_failure_isolated_cached_rows_still_served(self):
        _seed_rows(self.db_path, [
            dict(source="adzuna", source_job_id="adz-1", title="Cached Adzuna Role",
                 fetched_at=(datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()),
            dict(source="remoteok", source_job_id="rk-1", title="Cached RK",
                 fetched_at=(datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()),
        ])
        with mock.patch.dict(os.environ, CRED_ENV), \
             mock.patch.object(remote_ok, "fetch_jobs", return_value=[
                 dict(remote_ok.normalize({"slug": "rk-2", "position": "Backend Engineer",
                                           "company": "RK", "tags": [],
                                           "url": "https://remoteok.com/rk-2"}))]), \
             mock.patch.object(arbeitnow, "fetch_jobs", side_effect=Exception("arbeitnow down")), \
             mock.patch.object(jobicy, "fetch_jobs", side_effect=Exception("jobicy down")), \
             mock.patch.object(adzuna, "fetch_jobs", side_effect=adzuna.AdzunaError("Adzuna down")):
            status = service.refresh_if_stale(self.db_path)
            self.assertFalse(status["providers"]["adzuna"]["ok"])
            self.assertTrue(status["providers"]["remoteok"]["ok"])
            data = service.get_jobs(self.db_path, source="adzuna")   # cached rows served
            self.assertEqual(data["jobs"][0]["title"], "Cached Adzuna Role")

    def test_cache_dedup_on_source_and_source_job_id(self):
        job = adzuna.normalize(_adzuna_result(), fetched_at=service.now_iso())
        with sqlite3.connect(self.db_path) as db:
            service._upsert_jobs(db, [job, dict(job, title="Updated Title")])
            db.commit()
            n = db.execute("SELECT COUNT(*) FROM external_jobs WHERE source='adzuna'").fetchone()[0]
            title = db.execute("SELECT title FROM external_jobs WHERE source='adzuna'").fetchone()[0]
        self.assertEqual(n, 1)
        self.assertEqual(title, "Updated Title")


class AdzunaApiTests(_DBCase):
    def _seed_mixed(self):
        _seed_rows(self.db_path, [
            dict(source="adzuna", source_job_id="9001", title="Data Analyst London",
                 company="Adz Co", location="London", description="Build dashboards.",
                 job_type="Full Time · Permanent", remote=False, tags=["IT Jobs"],
                 salary="30k – 40k", job_url="https://www.adzuna.co.uk/jobs/land/9001",
                 published_at="2026-09-12T00:00:00+00:00"),
            dict(source="adzuna", source_job_id="9002", title="Sales ManagerManchester",
                 company="Sales Co", location="Manchester", description="Grow sales.",
                 job_type="Full Time", remote=False, tags=["Sales Jobs"],
                 job_url="https://www.adzuna.co.uk/jobs/land/9002",
                 published_at="2026-09-13T00:00:00+00:00"),
            dict(source="remoteok", source_job_id="rk-1", title="Remote Ruby Dev",
                 company="RK Co", location="Worldwide", description="Ruby.",
                 job_type="Full Time", remote=True, tags=[],
                 job_url="https://remoteok.com/rk-1",
                 published_at="2026-09-10T00:00:00+00:00"),
            dict(source="arbeitnow", source_job_id="an-1", title="DevOps Engineer",
                 company="AN Co", location="Berlin", description="Kubernetes.",
                 job_type="Full-Time", remote=False, tags=[],
                 job_url="https://www.arbeitnow.com/an-1",
                 published_at="2026-09-11T00:00:00+00:00"),
            dict(source="jobicy", source_job_id="153489", title="Remote Python Engineer",
                 company="Jcy Co", location="Poland", description="Build apis.",
                 job_type="Full-Time", remote=True, tags=["python"],
                 job_url="https://jobicy.com/jobs/153489",
                 published_at="2026-09-14T00:00:00+00:00"),
        ])

    def test_source_adzuna_filter_and_contract(self):
        self._seed_mixed()
        client, _ = signup_and_login(self.app_module, name="Adzuna User")
        data = client.get("/api/jobs?source=adzuna").get_json()
        self.assertEqual(data["total"], 2)
        self.assertTrue(all(j["source"] == "adzuna" for j in data["jobs"]))
        for key in ("source", "source_job_id", "title", "company", "location",
                    "description", "job_type", "remote", "tags", "salary",
                    "job_url", "published_at", "fetched_at"):
            self.assertIn(key, data["jobs"][0])
        top = data["jobs"][0]
        self.assertEqual(top["job_url"], "https://www.adzuna.co.uk/jobs/land/9002")  # newest first
        self.assertEqual(data["cache"]["sources"],
                         ["remoteok", "arbeitnow", "jobicy", "adzuna"])

    def test_search_and_location_filters_on_adzuna(self):
        self._seed_mixed()
        client, _ = signup_and_login(self.app_module, name="Adzuna User")
        by_q = client.get("/api/jobs?source=adzuna&q=dashboards").get_json()
        self.assertEqual(by_q["total"], 1)
        self.assertEqual(by_q["jobs"][0]["title"], "Data Analyst London")
        by_loc = client.get("/api/jobs?source=adzuna&location=london").get_json()
        self.assertEqual(by_loc["total"], 1)
        self.assertEqual(by_loc["jobs"][0]["location"], "London")

    def test_existing_providers_still_filter(self):
        self._seed_mixed()
        client, _ = signup_and_login(self.app_module, name="Adzuna User")
        self.assertEqual(client.get("/api/jobs?source=remoteok").get_json()["total"], 1)
        self.assertEqual(client.get("/api/jobs?source=arbeitnow").get_json()["total"], 1)
        self.assertEqual(client.get("/api/jobs?source=jobicy").get_json()["total"], 1)

    def test_jobguard_publishing_regression_alongside_adzuna(self):
        from test_employer_jobs import VALID as JOB_VALID, _register_employer
        self._seed_mixed()
        client, _ = signup_and_login(self.app_module, name="Pub Employer")
        _register_employer(client)
        payload = dict(JOB_VALID, description=(
            "We are hiring a backend engineer to join our product team. You will design "
            "APIs, review code, collaborate with designers, and improve application "
            "reliability. The role includes a clear development plan, paid leave, and "
            "access to health coverage. Candidates should share a portfolio."),)
        created = client.post("/api/employer-jobs", json=payload).get_json()["job"]
        client.post(f"/api/employer-jobs/{created['id']}/screen")
        self.assertEqual(client.post(f"/api/employer-jobs/{created['id']}/publish").status_code, 200)
        merged = client.get("/api/jobs").get_json()
        sources = {j["source"] for j in merged["jobs"]}
        self.assertIn("jobguard", sources)
        self.assertIn("adzuna", sources)
        guard = client.get("/api/jobs?source=jobguard").get_json()
        self.assertEqual(guard["total"], 1)
        self.assertEqual(guard["jobs"][0]["company"], "Acme Labs")


if __name__ == "__main__":
    unittest.main()
