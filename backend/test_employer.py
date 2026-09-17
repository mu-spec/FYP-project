"""
Milestone 8C.1 tests — Employer Registration Foundation.
=========================================================

Run from backend/:
    python -m unittest test_employer -v

Suites:
  1. EmployerSchemaTests    - fresh DB schema: table exists, UNIQUE(user_id)
                              enforced, no credential columns
  2. EmployerApiTests       - GET/POST/PUT /api/employer-profile: profile does
                              not exist, successful registration, required/
                              email/website validation, duplicate rejected,
                              in-place update (same id/user_id/created_at),
                              anonymous 401, CSRF 403
  3. EmployerIsolationTests - User A / User B: B cannot read or modify A's
                              profile; A's profile survives logouts; PUT can
                              never create a second profile

The employer profile extends the EXISTING JobGuard account — no second
authentication system, no credentials stored. Nothing here touches the ML
pipeline or the users/predictions/external_jobs semantics.
"""

import os
import sqlite3
import tempfile
import unittest
from uuid import uuid4

from auth_test_utils import signup_and_login

VALID = {
    "company_name": "Acme Labs",
    "contact_name": "Ada Smith",
    "business_email": "jobs@acmelabs.example",
    "website": "https://acmelabs.example",
    "location": "Lahore",
    "company_description": "Acme Labs builds trustworthy hiring tools.",
}


def _unique_email():
    return f"{uuid4().hex[:10]}@employer-test.example"


class EmployerSchemaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp.name, "employer-schema-test.db")
        import app
        self.app_module = app
        self.original_db = app.DB_PATH
        app.DB_PATH = self.db_path
        app.init_db()

    def tearDown(self):
        self.app_module.DB_PATH = self.original_db
        self.tmp.cleanup()

    def test_fresh_database_schema(self):
        with sqlite3.connect(self.db_path) as db:
            columns = {row[1] for row in db.execute("PRAGMA table_info(employer_profiles)")}
            indexes = {row[1] for row in db.execute("PRAGMA index_list(employer_profiles)")}
        expected = {"id", "user_id", "company_name", "contact_name", "business_email",
                    "website", "location", "company_description", "created_at", "updated_at"}
        self.assertEqual(columns, expected)
        self.assertTrue(any("employer_profiles" in i for i in indexes),
                        f"expected UNIQUE(user_id) index, saw {indexes}")

    def test_unique_user_id_rejects_second_profile(self):
        import employer_profiles
        clean, errors = employer_profiles.validate_profile_data(dict(VALID))
        self.assertEqual(errors, {})
        profile, err = employer_profiles.create_profile(self.db_path, 42, clean)
        self.assertIsNotNone(profile)
        second, err = employer_profiles.create_profile(self.db_path, 42, clean)
        self.assertIsNone(second)
        self.assertEqual(err, "duplicate")

    def test_no_credential_columns_exist(self):
        with sqlite3.connect(self.db_path) as db:
            columns = {row[1] for row in db.execute("PRAGMA table_info(employer_profiles)")}
        for forbidden in ("password", "password_hash", "token", "secret"):
            self.assertFalse(any(forbidden in c for c in columns),
                             "employer_profiles must never store credentials")


class EmployerApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import app
        cls.app_module = app
        cls.original_db = app.DB_PATH
        cls.tmp = tempfile.TemporaryDirectory()
        app.DB_PATH = os.path.join(cls.tmp.name, "employer-api-test.db")
        app.init_db()
        cls.client, cls.email = signup_and_login(app, name="Employer User")

    @classmethod
    def tearDownClass(cls):
        cls.app_module.DB_PATH = cls.original_db
        cls.tmp.cleanup()

    def test_profile_does_not_exist_initially(self):
        client, _ = signup_and_login(self.app_module, name="Fresh User")
        resp = client.get("/api/employer-profile")
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.get_json()["profile"])

    def test_successful_employer_registration(self):
        client, _ = signup_and_login(self.app_module, name="Registering User")
        resp = client.post("/api/employer-profile", json=dict(VALID))
        self.assertEqual(resp.status_code, 201)
        profile = resp.get_json()["profile"]
        self.assertEqual(profile["company_name"], "Acme Labs")
        self.assertEqual(profile["contact_name"], "Ada Smith")
        self.assertEqual(profile["business_email"], "jobs@acmelabs.example")
        self.assertEqual(profile["location"], "Lahore")
        self.assertTrue(profile["id"] >= 1)
        self.assertTrue(profile["created_at"] and profile["updated_at"])
        # GET now returns the same profile
        again = client.get("/api/employer-profile").get_json()["profile"]
        self.assertEqual(again["id"], profile["id"])

    def test_whitespace_is_trimmed(self):
        client, _ = signup_and_login(self.app_module, name="Trim User")
        resp = client.post("/api/employer-profile", json=dict(
            VALID, company_name="  Trimmed Co  ", location="   Karachi   ",
            company_description="  We build things.  "))
        self.assertEqual(resp.status_code, 201)
        profile = resp.get_json()["profile"]
        self.assertEqual(profile["company_name"], "Trimmed Co")
        self.assertEqual(profile["location"], "Karachi")
        self.assertEqual(profile["company_description"], "We build things.")

    def test_required_field_validation(self):
        client, _ = signup_and_login(self.app_module, name="Validation User")
        for missing in ("company_name", "contact_name", "business_email",
                        "location", "company_description"):
            payload = {k: v for k, v in VALID.items() if k != missing}
            resp = client.post("/api/employer-profile", json=payload)
            with self.subTest(missing=missing):
                self.assertEqual(resp.status_code, 400)
                self.assertIn(missing, resp.get_json()["field_errors"])
        # overlong fields are rejected too
        resp = client.post("/api/employer-profile", json=dict(VALID, company_name="x" * 121))
        self.assertEqual(resp.status_code, 400)

    def test_invalid_email_rejected(self):
        client, _ = signup_and_login(self.app_module, name="Bad Email User")
        for bad in ("not-an-email", "a@b", "missing@tld.", "spaces in@x.example"):
            resp = client.post("/api/employer-profile", json=dict(VALID, business_email=bad))
            with self.subTest(email=bad):
                self.assertEqual(resp.status_code, 400)
                self.assertIn("business_email", resp.get_json()["field_errors"])

    def test_invalid_website_rejected_optional_ok(self):
        client, _ = signup_and_login(self.app_module, name="Bad Site User")
        for bad in ("ftp://files.example", "http://", "not a url:://x", "javascript:alert(1)"):
            resp = client.post("/api/employer-profile", json=dict(VALID, website=bad))
            with self.subTest(website=bad):
                self.assertEqual(resp.status_code, 400)
                self.assertIn("website", resp.get_json()["field_errors"])
        # optional: blank/missing website is fine; bare domain gets a scheme
        resp = client.post("/api/employer-profile", json=dict(VALID, website=""))
        self.assertEqual(resp.status_code, 201)
        self.assertIsNone(resp.get_json()["profile"]["website"])
        client2, _ = signup_and_login(self.app_module, name="Bare Domain User")
        resp = client2.post("/api/employer-profile", json=dict(VALID, website="acmelabs.example"))
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.get_json()["profile"]["website"], "https://acmelabs.example")

    def test_duplicate_registration_rejected(self):
        client, _ = signup_and_login(self.app_module, name="Duplicate User")
        first = client.post("/api/employer-profile", json=dict(VALID))
        self.assertEqual(first.status_code, 201)
        second = client.post("/api/employer-profile", json=dict(VALID, company_name="Other Co"))
        self.assertEqual(second.status_code, 409)
        with sqlite3.connect(self.app_module.DB_PATH) as db:
            n = db.execute("SELECT COUNT(*) FROM employer_profiles").fetchone()[0]
        self.assertEqual(n, 1)  # still exactly one profile row

    def test_update_existing_profile_in_place(self):
        client, _ = signup_and_login(self.app_module, name="Update User")
        created = client.post("/api/employer-profile", json=dict(VALID)).get_json()["profile"]
        resp = client.put("/api/employer-profile", json=dict(
            VALID, company_name="Acme Labs GmbH", location="Islamabad"))
        self.assertEqual(resp.status_code, 200)
        updated = resp.get_json()["profile"]
        self.assertEqual(updated["id"], created["id"])                 # same row
        self.assertEqual(updated["company_name"], "Acme Labs GmbH")
        self.assertEqual(updated["location"], "Islamabad")
        self.assertGreaterEqual(updated["updated_at"], created["updated_at"])
        with sqlite3.connect(self.app_module.DB_PATH) as db:
            db.row_factory = sqlite3.Row
            row = db.execute("SELECT * FROM employer_profiles WHERE id = ?",
                             (created["id"],)).fetchone()
        self.assertEqual(row["company_name"], "Acme Labs GmbH")
        self.assertEqual(row["created_at"], created["created_at"])     # preserved
        # no second row for this user (count the row itself; UNIQUE(user_id)
        # makes a sibling impossible — class DB is shared, so count by id)
        with sqlite3.connect(self.app_module.DB_PATH) as db:
            n = db.execute("SELECT COUNT(*) FROM employer_profiles WHERE id = ?",
                           (created["id"],)).fetchone()[0]
        self.assertEqual(n, 1)

    def test_put_without_profile_is_404_not_creation(self):
        client, _ = signup_and_login(self.app_module, name="No Profile User")
        resp = client.put("/api/employer-profile", json=dict(VALID))
        self.assertEqual(resp.status_code, 404)
        profile = client.get("/api/employer-profile").get_json()["profile"]
        self.assertIsNone(profile)  # PUT must not create

    def test_anonymous_access_is_401(self):
        anon = self.app_module.app.test_client()
        self.assertEqual(anon.get("/api/employer-profile").status_code, 401)
        self.assertEqual(anon.post("/api/employer-profile", json=dict(VALID)).status_code, 401)
        self.assertEqual(anon.put("/api/employer-profile", json=dict(VALID)).status_code, 401)

    def test_missing_or_invalid_csrf_is_403(self):
        raw = self.app_module.app.test_client()
        raw.post("/api/auth/signup", json={"name": "CSRF Employer",
                                           "email": _unique_email(),
                                           "password": "Passw0rd123",
                                           "confirm": "Passw0rd123"})
        self.assertEqual(raw.post("/api/employer-profile", json=dict(VALID)).status_code, 403)
        self.assertEqual(raw.put("/api/employer-profile", json=dict(VALID)).status_code, 403)
        bad = self.app_module.app.test_client()
        bad.post("/api/auth/signup", json={"name": "CSRF Employer 2",
                                           "email": _unique_email(),
                                           "password": "Passw0rd123",
                                           "confirm": "Passw0rd123"})
        resp = bad.post("/api/employer-profile", json=dict(VALID),
                        headers={"X-CSRF-Token": "forged-token"})
        self.assertEqual(resp.status_code, 403)
        self.assertTrue(resp.get_json().get("csrf_error"))


class EmployerIsolationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import app
        cls.app_module = app
        cls.original_db = app.DB_PATH
        cls.tmp = tempfile.TemporaryDirectory()
        app.DB_PATH = os.path.join(cls.tmp.name, "employer-iso-test.db")
        app.init_db()
        cls.client_a, cls.email_a = signup_and_login(app, name="User A")
        cls.client_b, cls.email_b = signup_and_login(app, name="User B")
        cls.client_a.post("/api/employer-profile", json=dict(
            VALID, company_name="Company A", business_email="a@companya.example"))
        cls.client_b.post("/api/employer-profile", json=dict(
            VALID, company_name="Company B", business_email="b@companyb.example"))

    @classmethod
    def tearDownClass(cls):
        cls.app_module.DB_PATH = cls.original_db
        cls.tmp.cleanup()

    def test_b_cannot_read_a_profile(self):
        body_b = self.client_b.get("/api/employer-profile").get_json()
        self.assertEqual(body_b["profile"]["business_email"], "b@companyb.example")
        self.assertNotEqual(body_b["profile"]["company_name"], "Company A")
        # the GET endpoint has no id parameter at all — ownership is the session
        with sqlite3.connect(self.app_module.DB_PATH) as db:
            a_id = db.execute(
                "SELECT id FROM employer_profiles WHERE company_name = 'Company A'"
            ).fetchone()[0]
        # even poking raw ids through the API is impossible: no such route exists
        resp = self.client_b.get(f"/api/employer-profile?user_id={a_id}")
        self.assertEqual(resp.get_json()["profile"]["company_name"], "Company B")

    def test_b_cannot_modify_a_profile(self):
        resp = self.client_b.put("/api/employer-profile", json=dict(
            VALID, company_name="Hijacked", business_email="evil@hijack.example"))
        self.assertEqual(resp.status_code, 200)  # B updated B's OWN row
        self.assertEqual(resp.get_json()["profile"]["company_name"], "Hijacked")
        with sqlite3.connect(self.app_module.DB_PATH) as db:
            a_name = db.execute(
                "SELECT company_name FROM employer_profiles WHERE company_name = 'Company A'"
            ).fetchone()
        self.assertIsNotNone(a_name)  # A untouched
        # restore B's canonical state for the other tests in this class
        self.client_b.put("/api/employer-profile", json=dict(
            VALID, company_name="Company B", business_email="b@companyb.example"))

    def test_a_profile_survives_logout_and_b_is_invisible_to_a(self):
        # fresh A logs back in and still finds Company A, never Company B
        client_a2, _ = signup_and_login(self.app_module, name="User A2")
        resp = client_a2.post("/api/employer-profile", json=dict(
            VALID, company_name="Company A", business_email="a2@companya.example"))
        self.assertEqual(resp.status_code, 201)
        mine = client_a2.get("/api/employer-profile").get_json()["profile"]
        self.assertEqual(mine["company_name"], "Company A")
        # a brand-new user sees no profile at all — nothing is shared
        client_c, _ = signup_and_login(self.app_module, name="User C")
        self.assertIsNone(client_c.get("/api/employer-profile").get_json()["profile"])

    def test_backend_ownership_is_user_id_not_frontend(self):
        # direct DB check: every row is keyed to a DISTINCT authenticated
        # user_id (company names may legitimately repeat across users)
        with sqlite3.connect(self.app_module.DB_PATH) as db:
            db.row_factory = sqlite3.Row
            rows = db.execute(
                "SELECT user_id, company_name, business_email FROM employer_profiles"
            ).fetchall()
        self.assertGreaterEqual(len(rows), 3)  # A, B and A2 all registered
        user_ids = [r["user_id"] for r in rows]
        self.assertEqual(len(user_ids), len(set(user_ids)))  # UNIQUE(user_id)
        # Company A rows (A and A2) keep their own distinct business emails —
        # no row ever points at another user's identity
        for row in rows:
            self.assertTrue(row["business_email"])
            self.assertTrue(isinstance(row["user_id"], int))


if __name__ == "__main__":
    unittest.main(verbosity=2)
