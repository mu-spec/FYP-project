"""
Milestone 8A.1 tests — Authentication core.
===========================================

Run from backend/:
    python -m unittest test_auth -v

Suites:
  1. SignupApiTests      - success, normalization, duplicates (case-insensitive),
                           invalid email, weak passwords, name required,
                           confirm-password match
  2. LoginLogoutTests    - login success (+ last_login_at), wrong password,
                           unknown email, identical generic error (no user
                           enumeration), logout, logout invalidates the session
  3. SessionMeTests      - /api/auth/me anonymous + authenticated, cookie
                           session persistence across requests
  4. ProtectedApiTests   - predict / predict-url / history GET+DELETE return
                           401 while logged out; health stays public; the
                           protected APIs work after signing in

Nothing here touches the ML pipeline: predictions only assert status codes,
and every run uses a throwaway SQLite database in a temp directory.
"""

import json
import os
import sqlite3
import tempfile
import unittest
from uuid import uuid4

from auth_test_utils import DEFAULT_TEST_PASSWORD, signup_and_login

GOOD_NAME = "Example User"
GOOD_EMAIL = "user@example.com"
GOOD_PASSWORD = DEFAULT_TEST_PASSWORD  # 8+ chars, upper, lower, number

WEAK_PASSWORDS = [
    "Sh0rt",            # too short
    "alllowercase1",    # no uppercase
    "ALLUPPERCASE1",    # no lowercase
    "NoDigitsHere",     # no number
    "",                 # empty
]


class AuthTestBase(unittest.TestCase):
    """Isolated app + throwaway DB + unauthenticated test client."""

    @classmethod
    def setUpClass(cls):
        import app
        cls.app_module = app
        cls.original_db_path = app.DB_PATH
        cls.temp_dir = tempfile.TemporaryDirectory()
        app.DB_PATH = os.path.join(cls.temp_dir.name, "auth-test.db")
        app.init_db()
        cls.client = app.app.test_client()

    @classmethod
    def tearDownClass(cls):
        cls.app_module.DB_PATH = cls.original_db_path
        cls.temp_dir.cleanup()

    def _unique_email(self):
        return f"user{uuid4().hex[:8]}@example.com"

    def _csrf_header(self):
        data = self.client.get("/api/auth/me").get_json()
        return {"X-CSRF-Token": (data or {}).get("csrf_token", "")}

    def _signup(self, email=None, name=GOOD_NAME, password=GOOD_PASSWORD,
                confirm=None, raw_email=None):
        payload = {"name": name, "email": raw_email if raw_email is not None else (email or self._unique_email()),
                   "password": password}
        if confirm is not None:
            payload["confirm"] = confirm
        return self.client.post("/api/auth/signup", json=payload)

    def _login(self, email=GOOD_EMAIL, password=GOOD_PASSWORD, raw_email=None):
        # Good default: the email that a fresh signup just created, when the
        # test stored one; explicit emails win.
        return self.client.post(
            "/api/auth/login",
            json={"email": raw_email if raw_email is not None else email,
                  "password": password},
        )


class SignupApiTests(AuthTestBase):
    def test_signup_success_creates_account_and_signs_in(self):
        email = self._unique_email()
        resp = self._signup(email=email)
        self.assertEqual(resp.status_code, 201)
        data = resp.get_json()
        self.assertTrue(data["authenticated"])
        self.assertEqual(data["user"]["name"], GOOD_NAME)
        self.assertEqual(data["user"]["email"], email)
        self.assertIsInstance(data["user"]["id"], int)
        # The password hash must never appear in any API response.
        self.assertNotIn("password_hash", json.dumps(data))

    def test_email_stored_normalized_lowercase(self):
        email = self._unique_email()
        resp = self._signup(raw_email=email.upper())
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.get_json()["user"]["email"], email)
        with sqlite3.connect(self.app_module.DB_PATH) as db:
            stored = db.execute(
                "SELECT email FROM users WHERE email = ?", (email,),
            ).fetchone()
        self.assertIsNotNone(stored)

    def test_signup_success_persists_hash_not_plaintext(self):
        email = self._unique_email()
        self._signup(email=email)
        with sqlite3.connect(self.app_module.DB_PATH) as db:
            db.row_factory = sqlite3.Row
            row = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        self.assertIsNotNone(row)
        self.assertNotEqual(row["password_hash"], GOOD_PASSWORD)
        self.assertTrue(row["password_hash"].startswith(("pbkdf2:", "scrypt:")))
        self.assertIsNotNone(row["created_at"])

    def test_duplicate_email_rejected(self):
        email = self._unique_email()
        self._signup(email=email)
        resp = self._signup(email=email, name="Second User")
        self.assertEqual(resp.status_code, 409)
        self.assertIn("field_errors", resp.get_json())

    def test_duplicate_email_rejected_case_insensitively(self):
        email = self._unique_email()
        self._signup(email=email)
        resp = self._signup(raw_email=email.upper())
        self.assertEqual(resp.status_code, 409)

    def test_invalid_email_rejected(self):
        for bad in ["not-an-email", "a@b", "spaces in@mail.com", "@nope.com", "user@"]:
            with self.subTest(email=bad):
                resp = self._signup(email=bad)
                self.assertEqual(resp.status_code, 400)
                self.assertIn("email", resp.get_json()["field_errors"])

    def test_weak_passwords_rejected(self):
        for weak in WEAK_PASSWORDS:
            with self.subTest(password=weak):
                resp = self._signup(password=weak)
                self.assertEqual(resp.status_code, 400)
                self.assertIn("password", resp.get_json()["field_errors"])

    def test_name_required(self):
        resp = self._signup(name="   ")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("name", resp.get_json()["field_errors"])

    def test_confirm_password_must_match(self):
        resp = self._signup(confirm="Different1A")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("confirm", resp.get_json()["field_errors"])

    def test_matching_confirm_accepted(self):
        resp = self._signup(confirm=GOOD_PASSWORD)
        self.assertEqual(resp.status_code, 201)


class LoginLogoutTests(AuthTestBase):
    def test_login_success_updates_last_login(self):
        email = self._unique_email()
        self._signup(email=email)
        resp = self._login(email=email)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json()["authenticated"])
        with sqlite3.connect(self.app_module.DB_PATH) as db:
            last = db.execute(
                "SELECT last_login_at FROM users WHERE email = ?", (email,)
            ).fetchone()[0]
        self.assertIsNotNone(last)

    def test_login_with_different_case_email_succeeds(self):
        email = self._unique_email()
        self._signup(email=email)
        resp = self._login(raw_email=email.upper())
        self.assertEqual(resp.status_code, 200)

    def test_wrong_password_generic_error(self):
        email = self._unique_email()
        self._signup(email=email)
        resp = self._login(email=email, password="WrongPass1")
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.get_json()["error"], "Invalid email or password.")

    def test_unknown_email_same_generic_error(self):
        resp = self._login(email="ghost@example.com")
        self.assertEqual(resp.status_code, 401)
        # Identical message for unknown email and wrong password: the endpoint
        # must not reveal whether an account exists.
        self.assertEqual(resp.get_json()["error"], "Invalid email or password.")

    def test_logout_clears_session(self):
        self._signup()
        self.assertEqual(self.client.get("/api/auth/me").get_json()["authenticated"], True)
        resp = self.client.post("/api/auth/logout", headers=self._csrf_header())
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.get_json()["authenticated"])
        self.assertFalse(self.client.get("/api/auth/me").get_json()["authenticated"])
        # A second logout attempt without the (now cleared) token is rejected.
        self.assertEqual(self.client.post("/api/auth/logout").status_code, 403)
        # And the protected APIs are closed again after logout.
        self.assertEqual(self.client.get("/api/history").status_code, 401)


class SessionMeTests(AuthTestBase):
    def test_me_anonymous_is_false_not_error(self):
        resp = self.client.get("/api/auth/me")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json(), {"authenticated": False})

    def test_me_returns_user_after_login(self):
        email = self._unique_email()
        self._signup(email=email)
        data = self.client.get("/api/auth/me").get_json()
        self.assertTrue(data["authenticated"])
        self.assertEqual(data["user"]["email"], email)
        self.assertNotIn("password_hash", json.dumps(data))

    def test_session_persists_across_requests(self):
        self._signup()
        for _ in range(3):
            data = self.client.get("/api/auth/me").get_json()
            self.assertTrue(data["authenticated"], "cookie session must persist")

    def test_stale_session_resolves_to_anonymous(self):
        with self.client.session_transaction() as sess:
            sess["user_id"] = 999999  # no such user
        data = self.client.get("/api/auth/me").get_json()
        self.assertFalse(data["authenticated"])


class ProtectedApiTests(AuthTestBase):
    def test_protected_apis_reject_anonymous_with_401(self):
        scam = {"job_text": "Earn $9,000 EVERY WEEK working from home! Pay a $99 "
                            "registration fee via Easypaisa. Email hire@gmail.com NOW!",
                "title": "t"}
        checks = [
            ("POST", "/api/predict", scam),
            ("POST", "/api/predict-url", {"url": "https://example.com/job"}),
            ("GET", "/api/history?limit=5", None),
            ("DELETE", "/api/history", None),
        ]
        for method, url, payload in checks:
            with self.subTest(f"{method} {url}"):
                resp = self.client.open(url, method=method, json=payload)
                self.assertEqual(resp.status_code, 401)
                self.assertFalse(resp.get_json()["authenticated"])

    def test_health_stays_public(self):
        resp = self.client.get("/api/health")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["status"], "ok")

    def test_protected_apis_work_after_signup_login(self):
        self._signup()
        scam = ("Earn $9,000 EVERY WEEK working from home! No experience needed. "
                "Immediate hiring! Just pay a $99 registration fee via Easypaisa. "
                "Email hiring.manager2024@gmail.com NOW. Act fast!")
        resp = self.client.post("/api/predict", json={"job_text": scam, "title": "t"},
                                headers=self._csrf_header())
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["prediction"], "Scam")
        self.assertEqual(len(self.client.get("/api/history").get_json()), 1)


if __name__ == "__main__":
    unittest.main()
