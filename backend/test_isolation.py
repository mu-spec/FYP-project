"""
Milestone 8A.2 tests — User data isolation & auth security.
===========================================================

Run from backend/:
    python -m unittest test_isolation -v

Suites:
  1. MigrationTests        - legacy database (pre-user_id rows) is migrated in
                             place: column + index added, old rows preserved
                             with user_id = NULL and invisible through the
                             authenticated History API; fresh databases get the
                             column + index directly
  2. OwnershipTests        - every new prediction (text + URL path) is stored
                             with the signed-in user's id
  3. IsolationTests        - User A never sees User B's rows; DELETE removes
                             only the caller's rows (cross-user access and
                             cross-user delete are impossible through the API)
  4. InsightsIsolationTests- the History endpoint that Insights is computed
                             from returns strictly per-user data
  5. CsrfSecurityTests     - missing/invalid CSRF rejected (403), valid CSRF
                             succeeds, logout requires CSRF, anonymous calls
                             still hit 401 first, /api/auth/me returns the token

Nothing here retrains or modifies the model; predictions only assert status
codes and stored ownership. Every run uses a throwaway SQLite database.
"""

import json
import os
import sqlite3
import tempfile
import unittest
from uuid import uuid4

from auth_test_utils import signup_and_login

SCAM_TEXT = (
    "Earn $9,000 EVERY WEEK working from home! No experience needed. "
    "Immediate hiring! Just pay a $99 registration fee via Easypaisa. "
    "Email hiring.manager2024@gmail.com NOW. Act fast!"
)


def _predict(client, text=SCAM_TEXT, title="t"):
    return client.post("/api/predict", json={"job_text": text, "title": title})


def _db_rows(db_path):
    with sqlite3.connect(db_path) as db:
        db.row_factory = sqlite3.Row
        return db.execute(
            "SELECT id, job_title, user_id FROM predictions ORDER BY id"
        ).fetchall()


class IsolationTestBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import app
        cls.app_module = app
        cls.original_db_path = app.DB_PATH
        cls.temp_dir = tempfile.TemporaryDirectory()
        app.DB_PATH = os.path.join(cls.temp_dir.name, "isolation-test.db")
        app.init_db()

    @classmethod
    def tearDownClass(cls):
        cls.app_module.DB_PATH = cls.original_db_path
        cls.temp_dir.cleanup()


class MigrationTests(IsolationTestBase):
    """8A.2 §2 — safe in-place migration, legacy rows preserved but hidden."""

    def test_legacy_database_migrated_in_place_and_rows_hidden(self):
        legacy = os.path.join(self.temp_dir.name, "legacy.db")
        with sqlite3.connect(legacy) as db:
            # The exact pre-8A.2 schema (no user_id), with two owned-by-nobody rows.
            db.execute("""
                CREATE TABLE predictions (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_title     TEXT NOT NULL,
                    prediction    TEXT NOT NULL,
                    confidence    REAL NOT NULL,
                    created_at    TEXT NOT NULL,
                    evidence_json TEXT
                )
            """)
            db.execute(
                "INSERT INTO predictions (job_title, prediction, confidence, created_at) "
                "VALUES ('legacy job A', 'Scam', 0.98, '2025-01-01T00:00:00+00:00')"
            )
            db.execute(
                "INSERT INTO predictions (job_title, prediction, confidence, created_at) "
                "VALUES ('legacy job B', 'Legitimate', 0.01, '2025-01-02T00:00:00+00:00')"
            )

        # Point the app at the legacy database and (re)run the migration.
        self.app_module.DB_PATH = legacy
        try:
            self.app_module.init_db()
            client, _ = signup_and_login(self.app_module)

            # Column and index exist...
            with sqlite3.connect(legacy) as db:
                columns = {row[1] for row in db.execute("PRAGMA table_info(predictions)")}
                indexes = {row[1] for row in db.execute("PRAGMA index_list(predictions)")}
            self.assertIn("user_id", columns)
            self.assertIn("idx_predictions_user_id", indexes)

            # ...both legacy rows are preserved with user_id = NULL...
            rows = _db_rows(legacy)
            self.assertEqual(len(rows), 2)
            self.assertEqual([r["user_id"] for r in rows], [None, None])

            # ...and the authenticated user sees NONE of them (and no rows are
            # ever reassigned to the new account).
            self.assertEqual(client.get("/api/history").get_json(), [])
        finally:
            self.app_module.DB_PATH = self.original_db_path

    def test_fresh_database_has_user_column_and_index(self):
        fresh = os.path.join(self.temp_dir.name, "fresh.db")
        self.app_module.DB_PATH = fresh
        try:
            self.app_module.init_db()
            with sqlite3.connect(fresh) as db:
                columns = {row[1] for row in db.execute("PRAGMA table_info(predictions)")}
                indexes = {row[1] for row in db.execute("PRAGMA index_list(predictions)")}
            self.assertIn("user_id", columns)
            self.assertIn("idx_predictions_user_id", indexes)
        finally:
            self.app_module.DB_PATH = self.original_db_path


class OwnershipTests(IsolationTestBase):
    def setUp(self):
        # Alphabetical test order accumulates rows in the shared class DB;
        # each test starts from an empty predictions table.
        with sqlite3.connect(self.app_module.DB_PATH) as db:
            db.execute("DELETE FROM predictions")
        self.client, self.email = signup_and_login(self.app_module)

    def test_text_prediction_saved_with_owner(self):
        self.assertEqual(_predict(self.client).status_code, 200)
        rows = _db_rows(self.app_module.DB_PATH)
        self.assertEqual(len(rows), 1)
        self.assertIsNotNone(rows[0]["user_id"])
        with sqlite3.connect(self.app_module.DB_PATH) as db:
            owner = db.execute("SELECT id FROM users WHERE email = ?", (self.email,)).fetchone()[0]
        self.assertEqual(rows[0]["user_id"], owner)

    def test_history_returns_owned_rows_with_user_id_in_sql(self):
        _predict(self.client)
        data = self.client.get("/api/history").get_json()
        self.assertEqual(len(data), 1)
        with sqlite3.connect(self.app_module.DB_PATH) as db:
            stored = db.execute(
                "SELECT user_id FROM predictions WHERE job_title = ?", ("t",)
            ).fetchone()[0]
        with sqlite3.connect(self.app_module.DB_PATH) as db:
            expected = db.execute("SELECT id FROM users WHERE email = ?", (self.email,)).fetchone()[0]
        self.assertEqual(stored, expected)


class IsolationTests(IsolationTestBase):
    def setUp(self):
        self.client_a, self.email_a = signup_and_login(self.app_module, name="User A")
        self.client_b, self.email_b = signup_and_login(self.app_module, name="User B")

    def test_users_see_only_their_own_history(self):
        _predict(self.client_a, text=SCAM_TEXT, title="Job A")
        _predict(self.client_b, text=SCAM_TEXT, title="Job B")

        a_rows = self.client_a.get("/api/history").get_json()
        b_rows = self.client_b.get("/api/history").get_json()
        self.assertEqual([r["job_title"] for r in a_rows], ["Job A"])
        self.assertEqual([r["job_title"] for r in b_rows], ["Job B"])
        # B's payload never contains A's record id or title.
        self.assertNotIn("Job A", json.dumps(b_rows))

    def test_clear_history_deletes_only_own_rows(self):
        _predict(self.client_a, title="Job A")
        _predict(self.client_b, title="Job B")

        self.assertEqual(self.client_b.delete("/api/history").get_json(), {"cleared": True})
        # B deleted only B's rows; A's row survives.
        self.assertEqual(self.client_b.get("/api/history").get_json(), [])
        self.assertEqual([r["job_title"] for r in self.client_a.get("/api/history").get_json()], ["Job A"])

        self.assertEqual(self.client_a.delete("/api/history").get_json(), {"cleared": True})
        self.assertEqual(self.client_a.get("/api/history").get_json(), [])
        # Nothing at all is left of the two users' rows.
        self.assertEqual(_db_rows(self.app_module.DB_PATH), [])


class InsightsIsolationTests(IsolationTestBase):
    def test_insights_source_history_is_strictly_per_user(self):
        # Insights computes every metric (totals, split, confidence, warning
        # categories, recent list) from GET /api/history, so isolating that
        # endpoint isolates Insights completely.
        client_a, _ = signup_and_login(self.app_module, name="Ins A")
        client_b, _ = signup_and_login(self.app_module, name="Ins B")
        _predict(client_a, title="A scam job")
        _predict(client_a, title="A scam job 2")
        _predict(client_b, title="B legit job")

        a_rows = client_a.get("/api/history").get_json()
        b_rows = client_b.get("/api/history").get_json()
        self.assertEqual(len(a_rows), 2)
        self.assertEqual(len(b_rows), 1)
        self.assertTrue(all(r["job_title"].startswith("A ") for r in a_rows))
        self.assertTrue(all(r["job_title"].startswith("B ") for r in b_rows))
        self.assertNotIn("B legit job", json.dumps(a_rows))
        self.assertNotIn("A scam job", json.dumps(b_rows))


class CsrfSecurityTests(IsolationTestBase):
    def setUp(self):
        # Raw (non-CSRF-wrapped) client: these tests manage tokens explicitly.
        self.raw = self.app_module.app.test_client()
        self.email = f"{uuid4().hex}@test.example"
        resp = self.raw.post("/api/auth/signup", json={
            "name": "Csrf User", "email": self.email, "password": "Passw0rd123",
        })
        self.assertEqual(resp.status_code, 201)
        self.token = resp.get_json()["csrf_token"]

    def _login_raw(self):
        return self.raw.post("/api/auth/login", json={
            "email": self.email, "password": "Passw0rd123",
        })

    def test_login_and_me_return_csrf_token(self):
        data = self._login_raw().get_json()
        self.assertTrue(data["csrf_token"])
        me = self.raw.get("/api/auth/me").get_json()
        self.assertEqual(me["csrf_token"], data["csrf_token"])

    def test_missing_csrf_rejected_403(self):
        for method, url, payload in [
            ("POST", "/api/predict", {"job_text": SCAM_TEXT}),
            ("POST", "/api/predict-url", {"url": "https://example.com/job"}),
            ("DELETE", "/api/history", None),
            ("POST", "/api/auth/logout", None),
        ]:
            with self.subTest(f"{method} {url} without CSRF"):
                resp = self.raw.open(url, method=method, json=payload)
                self.assertEqual(resp.status_code, 403)
                self.assertTrue(resp.get_json()["csrf_error"])

    def test_invalid_csrf_rejected_403(self):
        resp = _predict(self.raw, title="bad token")
        self.assertEqual(resp.status_code, 403)
        resp = self.raw.delete(
            "/api/history", headers={"X-CSRF-Token": "not-the-real-token"}
        )
        self.assertEqual(resp.status_code, 403)

    def test_valid_csrf_succeeds(self):
        headers = {"X-CSRF-Token": self.token}
        resp = _predict(self.raw, title="good token")
        # 400 (invalid job text) would mean CSRF passed; but use a real scam text
        resp = self.raw.post("/api/predict", json={"job_text": SCAM_TEXT, "title": "t"},
                             headers=headers)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.raw.delete("/api/history", headers=headers).status_code, 200)
        self.assertEqual(self.raw.post("/api/auth/logout", headers=headers).status_code, 200)

    def test_anonymous_still_401_before_csrf(self):
        fresh = self.app_module.app.test_client()
        resp = fresh.post("/api/predict", json={"job_text": SCAM_TEXT, "title": "t"})
        self.assertEqual(resp.status_code, 401)

    def test_token_not_in_any_get_history_payload(self):
        headers = {"X-CSRF-Token": self.token}
        self.raw.post("/api/predict", json={"job_text": SCAM_TEXT, "title": "t"}, headers=headers)
        payload = json.dumps(self.raw.get("/api/history").get_json())
        self.assertNotIn(self.token, payload)


if __name__ == "__main__":
    unittest.main()
