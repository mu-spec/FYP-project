"""
Milestone 8C.2 tests — Employer Job Creation & Draft Management.
================================================================

Run from backend/:
    python -m unittest test_employer_jobs -v

Suites:
  1. EmployerJobsSchemaTests - fresh DB schema (columns, draft default,
                               indexes), external_jobs untouched, no leakage
                               into the external feed/alerts
  2. EmployerJobsApiTests    - employer required, create draft, required
                               fields, invalid email/URL/job type/date,
                               short description, forced 'published' rejected
                               (ignored), edit in place, delete, list order
  3. EmployerJobsIsolationTests - User A / User B drafts: cross-user list/GET/
                               PUT/DELETE all 404 and never modify; CSRF
                               missing/invalid 403; anonymous 401; a normal
                               account without an employer profile is
                               forbidden; deleting own draft never affects
                               the other employer

Employer drafts live in their OWN table and never appear in external_jobs,
the Jobs feed, alerts or notifications. Nothing here touches the ML pipeline.
"""

import json
import os
import sqlite3
import tempfile
import unittest
from uuid import uuid4

from auth_test_utils import signup_and_login

VALID = {
    "title": "Backend Engineer",
    "location": "Lahore",
    "job_type": "Full Time",
    "salary": "180k PKR / month",
    "description": "Build and maintain the Python services that power JobGuard screening.",
    "requirements": "3 years of Python experience, SQL, REST APIs.",
    "benefits": "Annual bonus, hybrid work.",
    "contact_email": "hr@acme.example",
    "application_url": "https://acme.example/apply",
    "closing_date": "2026-11-30",
}

REQUIRED_FIELDS = ("title", "location", "job_type", "description",
                   "requirements", "contact_email")


def _unique_email():
    return f"{uuid4().hex[:10]}@jobs-test.example"


def _register_employer(client):
    payload = {
        "company_name": "Acme Labs", "contact_name": "Ada Smith",
        "business_email": f"{uuid4().hex[:8]}@acme.example",
        "website": "https://acme.example", "location": "Lahore",
        "company_description": "Acme Labs builds trustworthy hiring tools.",
    }
    resp = client.post("/api/employer-profile", json=payload)
    assert resp.status_code == 201, resp.get_json()


class EmployerJobsSchemaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp.name, "jobs-schema-test.db")
        import app
        self.app_module = app
        self.original_db = app.DB_PATH
        app.DB_PATH = self.db_path
        app.init_db()

    def tearDown(self):
        self.app_module.DB_PATH = self.original_db
        self.tmp.cleanup()

    def test_table_created_with_draft_default_and_indexes(self):
        with sqlite3.connect(self.db_path) as db:
            columns = {row[1] for row in db.execute("PRAGMA table_info(employer_jobs)")}
            defaults = {row[1]: row[4] for row in db.execute("PRAGMA table_info(employer_jobs)")}
            indexes = " ".join(
                row[4] or "" for row in db.execute("SELECT * FROM sqlite_master WHERE type='index'")
            )
        expected = {"id", "employer_profile_id", "title", "location", "job_type",
                    "salary", "description", "requirements", "benefits",
                    "contact_email", "application_url", "closing_date",
                    "status", "created_at", "updated_at",
                    "published_at"}  # 8C.3B: publication stamp (NULL until published)
        self.assertEqual(columns, expected)
        self.assertEqual(defaults["status"], "'draft'")
        self.assertIn("employer_profile_id", indexes)
        self.assertIn("status", indexes)
        self.assertIn("created_at", indexes)

    def test_external_jobs_table_untouched(self):
        # 8B.1/8B.2 semantics unchanged: same columns as before, no draft rows
        with sqlite3.connect(self.db_path) as db:
            ext_columns = {row[1] for row in db.execute("PRAGMA table_info(external_jobs)")}
            n = db.execute("SELECT COUNT(*) FROM external_jobs").fetchone()[0]
        self.assertIn("source_job_id", ext_columns)
        self.assertIn("salary", ext_columns)
        self.assertEqual(n, 0)  # employer drafts never land in the cache

    def test_employer_drafts_never_enter_external_feed_or_alerts(self):
        import employer_jobs
        from unittest import mock
        from job_sources import service, remote_ok, arbeitnow, jobicy
        saved = dict(service._last_refresh, ok=dict(service._last_refresh["ok"]))
        service._last_refresh = {"at": None, "ok": {n: None for n in service.PROVIDERS}}
        clean, _ = employer_jobs.validate_job_data(dict(VALID))
        employer_jobs.create_job(self.db_path, 99, clean)
        try:
            # providers mocked empty: no live network, feed stays empty and
            # the employer draft must not appear in it either way
            with mock.patch.object(remote_ok, "fetch_jobs", return_value=[]), \
                 mock.patch.object(arbeitnow, "fetch_jobs", return_value=[]), \
                 mock.patch.object(jobicy, "fetch_jobs", return_value=[]):
                result = service.get_jobs(self.db_path)
        finally:
            service._last_refresh = saved
        with sqlite3.connect(self.db_path) as db:
            n_ext = db.execute("SELECT COUNT(*) FROM external_jobs").fetchone()[0]
        self.assertEqual(n_ext, 0)
        self.assertEqual(result["total"], 0)  # invisible to the jobs feed
        titles = [j["title"] for j in result["jobs"]]
        self.assertNotIn(VALID["title"], titles)


class EmployerJobsApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import app
        cls.app_module = app
        cls.original_db = app.DB_PATH
        cls.tmp = tempfile.TemporaryDirectory()
        app.DB_PATH = os.path.join(cls.tmp.name, "jobs-api-test.db")
        app.init_db()
        cls.client, _ = signup_and_login(app, name="Employer Recruiter")
        _register_employer(cls.client)
        cls.plain_client, _ = signup_and_login(app, name="Plain User")

    @classmethod
    def tearDownClass(cls):
        cls.app_module.DB_PATH = cls.original_db
        cls.tmp.cleanup()

    def _count_own_rows(self):
        with sqlite3.connect(self.app_module.DB_PATH) as db:
            return db.execute("SELECT COUNT(*) FROM employer_jobs").fetchone()[0]

    def test_employer_profile_required(self):
        for method, path, kwargs in [
            ("get", "/api/employer-jobs", {}),
            ("post", "/api/employer-jobs", {"json": dict(VALID)}),
            ("get", "/api/employer-jobs/1", {}),
            ("put", "/api/employer-jobs/1", {"json": dict(VALID)}),
            ("delete", "/api/employer-jobs/1", {}),
        ]:
            with self.subTest(method=method):
                resp = getattr(self.plain_client, method)(path, **kwargs)
                self.assertEqual(resp.status_code, 403)
                self.assertIn("employer profile", resp.get_json()["error"])

    def test_anonymous_access_is_401(self):
        anon = self.app_module.app.test_client()
        self.assertEqual(anon.get("/api/employer-jobs").status_code, 401)
        self.assertEqual(anon.post("/api/employer-jobs", json=dict(VALID)).status_code, 401)
        self.assertEqual(anon.get("/api/employer-jobs/1").status_code, 401)
        self.assertEqual(anon.put("/api/employer-jobs/1", json=dict(VALID)).status_code, 401)
        self.assertEqual(anon.delete("/api/employer-jobs/1").status_code, 401)

    def test_create_draft_returns_draft(self):
        resp = self.client.post("/api/employer-jobs", json=dict(VALID))
        self.assertEqual(resp.status_code, 201)
        job = resp.get_json()["job"]
        self.assertEqual(job["status"], "draft")
        self.assertEqual(job["title"], "Backend Engineer")
        self.assertEqual(job["salary"], "180k PKR / month")
        self.assertTrue(job["id"] >= 1)
        self.assertTrue(job["created_at"] and job["updated_at"])

    def test_required_fields_validated(self):
        for missing in REQUIRED_FIELDS:
            payload = {k: v for k, v in VALID.items() if k != missing}
            resp = self.client.post("/api/employer-jobs", json=payload)
            with self.subTest(missing=missing):
                self.assertEqual(resp.status_code, 400)
                self.assertIn(missing, resp.get_json()["field_errors"])

    def test_invalid_contact_email_rejected(self):
        for bad in ("not-an-email", "missing@tld", "user@domain."):
            resp = self.client.post("/api/employer-jobs", json=dict(VALID, contact_email=bad))
            with self.subTest(email=bad):
                self.assertEqual(resp.status_code, 400)
                self.assertIn("contact_email", resp.get_json()["field_errors"])

    def test_invalid_application_url_rejected_optional_ok(self):
        # bare domains are legal (get https:// prepended, as with profiles);
        # non-HTTP schemes and scheme-less empty hosts are rejected
        for bad in ("javascript:alert(1)", "ftp://files.example", "http://", "://missing"):
            resp = self.client.post("/api/employer-jobs", json=dict(VALID, application_url=bad))
            with self.subTest(url=bad):
                self.assertEqual(resp.status_code, 400)
                self.assertIn("application_url", resp.get_json()["field_errors"])
        # blank is fine (optional)
        resp = self.client.post("/api/employer-jobs", json=dict(VALID, application_url=""))
        self.assertEqual(resp.status_code, 201)
        self.assertIsNone(resp.get_json()["job"]["application_url"])

    def test_invalid_job_type_rejected(self):
        for bad in ("published", "full-time", "Freelance", ""):
            resp = self.client.post("/api/employer-jobs", json=dict(VALID, job_type=bad))
            with self.subTest(job_type=bad):
                self.assertEqual(resp.status_code, 400)
                self.assertIn("job_type", resp.get_json()["field_errors"])

    def test_invalid_closing_date_rejected(self):
        for bad in ("30-11-2026", "2026-13-40", "tomorrow"):
            resp = self.client.post("/api/employer-jobs", json=dict(VALID, closing_date=bad))
            with self.subTest(date=bad):
                self.assertEqual(resp.status_code, 400)
                self.assertIn("closing_date", resp.get_json()["field_errors"])

    def test_short_description_rejected_for_future_analysis(self):
        resp = self.client.post("/api/employer-jobs", json=dict(VALID, description="too short"))
        self.assertEqual(resp.status_code, 400)
        self.assertIn("description", resp.get_json()["field_errors"])

    def test_forced_published_status_is_never_honored(self):
        resp = self.client.post("/api/employer-jobs",
                                json=dict(VALID, status="published"))
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.get_json()["job"]["status"], "draft")
        # PUT cannot flip it either
        job_id = resp.get_json()["job"]["id"]
        resp = self.client.put(f"/api/employer-jobs/{job_id}",
                               json=dict(VALID, status="published"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["job"]["status"], "draft")

    def test_optional_fields_are_not_invented(self):
        payload = {k: v for k, v in VALID.items()
                   if k not in ("salary", "benefits", "application_url", "closing_date")}
        resp = self.client.post("/api/employer-jobs", json=payload)
        self.assertEqual(resp.status_code, 201)
        job = resp.get_json()["job"]
        self.assertIsNone(job["salary"])
        self.assertIsNone(job["benefits"])
        self.assertIsNone(job["application_url"])
        self.assertIsNone(job["closing_date"])

    def test_edit_draft_in_place(self):
        created = self.client.post("/api/employer-jobs", json=dict(VALID)).get_json()["job"]
        resp = self.client.put(f"/api/employer-jobs/{created['id']}", json=dict(
            VALID, title="Senior Backend Engineer", location="Islamabad"))
        self.assertEqual(resp.status_code, 200)
        job = resp.get_json()["job"]
        self.assertEqual(job["id"], created["id"])                    # same row
        self.assertEqual(job["employer_profile_id"], created["employer_profile_id"])
        self.assertEqual(job["title"], "Senior Backend Engineer")
        self.assertEqual(job["location"], "Islamabad")
        self.assertEqual(job["created_at"], created["created_at"])    # preserved
        self.assertGreaterEqual(job["updated_at"], created["updated_at"])
        self.assertEqual(job["status"], "draft")                      # stays draft

    def test_delete_own_draft(self):
        created = self.client.post("/api/employer-jobs", json=dict(VALID)).get_json()["job"]
        resp = self.client.delete(f"/api/employer-jobs/{created['id']}")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json()["ok"])
        # gone: GET returns 404, deleting again is 404
        self.assertEqual(self.client.get(f"/api/employer-jobs/{created['id']}").status_code, 404)
        self.assertEqual(self.client.delete(f"/api/employer-jobs/{created['id']}").status_code, 404)

    def test_list_returns_only_own_jobs_newest_first(self):
        first = self.client.post("/api/employer-jobs", json=dict(VALID)).get_json()["job"]
        second = self.client.post(
            "/api/employer-jobs", json=dict(VALID, title="Second Role")).get_json()["job"]
        jobs = self.client.get("/api/employer-jobs").get_json()["jobs"]
        self.assertEqual([j["id"] for j in jobs][:2], [second["id"], first["id"]])
        self.assertTrue(all(j["status"] == "draft" for j in jobs))


class EmployerJobsIsolationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import app
        cls.app_module = app
        cls.original_db = app.DB_PATH
        cls.tmp = tempfile.TemporaryDirectory()
        app.DB_PATH = os.path.join(cls.tmp.name, "jobs-iso-test.db")
        app.init_db()
        cls.client_a, cls.email_a = signup_and_login(app, name="Employer A")
        cls.client_b, cls.email_b = signup_and_login(app, name="Employer B")
        _register_employer(cls.client_a)
        _register_employer(cls.client_b)
        cls.draft_a = cls.client_a.post("/api/employer-jobs", json=dict(
            VALID, title="Draft A")).get_json()["job"]
        cls.draft_b = cls.client_b.post("/api/employer-jobs", json=dict(
            VALID, title="Draft B")).get_json()["job"]

    @classmethod
    def tearDownClass(cls):
        cls.app_module.DB_PATH = cls.original_db
        cls.tmp.cleanup()

    def test_b_cannot_list_a_drafts(self):
        jobs = self.client_b.get("/api/employer-jobs").get_json()["jobs"]
        self.assertEqual([j["title"] for j in jobs], ["Draft B"])

    def test_b_cannot_get_a_draft_by_id(self):
        resp = self.client_b.get(f"/api/employer-jobs/{self.draft_a['id']}")
        self.assertEqual(resp.status_code, 404)

    def test_b_cannot_put_a_draft(self):
        resp = self.client_b.put(f"/api/employer-jobs/{self.draft_a['id']}",
                                 json=dict(VALID, title="Hijacked"))
        self.assertEqual(resp.status_code, 404)
        mine = self.client_a.get(f"/api/employer-jobs/{self.draft_a['id']}").get_json()["job"]
        self.assertEqual(mine["title"], "Draft A")  # untouched

    def test_b_cannot_delete_a_draft(self):
        resp = self.client_b.delete(f"/api/employer-jobs/{self.draft_a['id']}")
        self.assertEqual(resp.status_code, 404)
        mine = self.client_a.get(f"/api/employer-jobs/{self.draft_a['id']}")
        self.assertEqual(mine.status_code, 200)  # still there

    def test_deleting_own_draft_never_affects_the_other(self):
        temp = self.client_b.post("/api/employer-jobs", json=dict(
            VALID, title="Temp B")).get_json()["job"]
        self.assertEqual(self.client_b.delete(f"/api/employer-jobs/{temp['id']}").status_code, 200)
        self.assertEqual(self.client_a.get(
            f"/api/employer-jobs/{self.draft_a['id']}").status_code, 200)
        self.assertEqual(self.client_b.get(
            f"/api/employer-jobs/{self.draft_b['id']}").status_code, 200)

    def test_missing_and_invalid_csrf_are_403(self):
        raw = self.app_module.app.test_client()
        raw.post("/api/auth/login", json={"email": self.email_b, "password": "Passw0rd123"})
        # missing token
        resp = raw.post("/api/employer-jobs", json=dict(VALID))
        self.assertEqual(resp.status_code, 403)
        self.assertTrue(resp.get_json().get("csrf_error"))
        # invalid token
        resp = raw.post("/api/employer-jobs", json=dict(VALID),
                        headers={"X-CSRF-Token": "forged"})
        self.assertEqual(resp.status_code, 403)
        # valid token succeeds
        resp = self.client_b.post("/api/employer-jobs", json=dict(
            VALID, title="CSRF OK Draft"))
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.get_json()["job"]["status"], "draft")

    def test_a_relogin_still_sees_draft_a_and_not_b(self):
        client_a2, _ = signup_and_login(self.app_module, name="Employer A2")
        _register_employer(client_a2)  # different user, own profile
        # the ORIGINAL A account (same email) logs back in via a new session
        client_a_new = self.app_module.app.test_client()
        client_a_new.post("/api/auth/login", json={"email": self.email_a,
                                                   "password": "Passw0rd123"})
        jobs = client_a_new.get("/api/employer-jobs").get_json()["jobs"]
        self.assertIn("Draft A", [j["title"] for j in jobs])
        self.assertNotIn("Draft B", [j["title"] for j in jobs])


if __name__ == "__main__":
    unittest.main(verbosity=2)
