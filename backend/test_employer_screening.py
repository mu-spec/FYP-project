"""
Milestone 8C.3A tests — AI safety screening for employer job drafts.
====================================================================

Run from backend/:
    python -m unittest test_employer_screening -v

Suites:
  1. ScreeningSchemaTests   - fresh DB schema (table + indexes), screenings
                              kept separately from predictions
  2. ScreeningApiTests      - legitimate -> ready, scam -> flagged, evidence
                              stored, text composition (empty optionals
                              skipped), edit invalidation (status -> draft,
                              audit records kept), History/Insights never
                              polluted
  3. ScreeningSecurityTests - anonymous 401, non-employer 403, missing/
                              invalid CSRF 403, foreign job 404 (screen +
                              screening read), cross-user isolation, and the
                              employer profile does not soften the engine
                              (same text still flags)

The engine itself is UNCHANGED: predict_one() (TF-IDF + 11 numeric features +
XGBoost + 9 red-flag rules + noisy-OR + 0.5 threshold) is reused verbatim.
"""

import json
import os
import sqlite3
import tempfile
import unittest
from uuid import uuid4

from auth_test_utils import signup_and_login
from test_employer_jobs import VALID as JOB_VALID, _register_employer

LEGIT_TEXT = (
    "We are hiring a backend engineer to join our product team. You will "
    "design APIs, review code, collaborate with designers, and improve "
    "application reliability. The role includes a clear development plan, "
    "paid leave, and access to health coverage. Candidates should share a "
    "portfolio and describe relevant projects."
)
SCAM_TEXT = (
    "Earn $9,000 EVERY WEEK working from home! No experience needed. "
    "Immediate hiring! Just pay a $99 registration fee via Easypaisa. "
    "Email hiring.manager2024@gmail.com NOW. Act fast!"
)


def _job_payload(description, contact="hr@acmelabs.example"):
    return dict(JOB_VALID, description=description, contact_email=contact)


class ScreeningSchemaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp.name, "screen-schema-test.db")
        import app
        self.app_module = app
        self.original_db = app.DB_PATH
        app.DB_PATH = self.db_path
        app.init_db()

    def tearDown(self):
        self.app_module.DB_PATH = self.original_db
        self.tmp.cleanup()

    def test_screening_schema_fresh_db(self):
        with sqlite3.connect(self.db_path) as db:
            columns = {row[1] for row in db.execute("PRAGMA table_info(employer_job_screenings)")}
            indexes = " ".join(
                (row[4] or "") for row in
                db.execute("SELECT * FROM sqlite_master WHERE type='index'")
            )
        expected = {"id", "employer_job_id", "prediction", "probability",
                    "confidence", "evidence_json", "screened_at",
                    "text_hash"}  # 8C.3B: stale-screening fingerprint
        self.assertEqual(columns, expected)
        self.assertIn("employer_job_id", indexes)
        self.assertIn("screened_at", indexes)
        # kept separate from normal predictions
        with sqlite3.connect(self.db_path) as db:
            n_pred = db.execute("SELECT COUNT(*) FROM predictions").fetchone()[0]
        self.assertEqual(n_pred, 0)

    def test_screenings_stay_out_of_predictions_table(self):
        import employer_screening, employer_jobs
        ej_clean, _ = employer_jobs.validate_job_data(_job_payload(LEGIT_TEXT))
        job = employer_jobs.create_job(self.db_path, 42, ej_clean)
        fake = {"prediction": "Legitimate", "probabilities": {"scam": 0.07, "legitimate": 0.93},
                "confidence": 0.93, "red_flags": [], "engine": {"final": "noisy_or(xgboost, rules)"}}
        employer_screening.record_screening(self.db_path, job["id"], fake)
        employer_screening.record_screening(self.db_path, job["id"], fake)
        with sqlite3.connect(self.db_path) as db:
            n_screen = db.execute("SELECT COUNT(*) FROM employer_job_screenings").fetchone()[0]
            n_pred = db.execute("SELECT COUNT(*) FROM predictions").fetchone()[0]
        self.assertEqual(n_screen, 2)   # audit history kept
        self.assertEqual(n_pred, 0)     # normal History untouched


class ScreeningApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import app
        cls.app_module = app
        cls.original_db = app.DB_PATH
        cls.tmp = tempfile.TemporaryDirectory()
        app.DB_PATH = os.path.join(cls.tmp.name, "screen-api-test.db")
        app.init_db()
        cls.client, _ = signup_and_login(app, name="Screen Employer")
        _register_employer(cls.client)
        cls.profile = cls.client.get("/api/employer-profile").get_json()["profile"]

    @classmethod
    def tearDownClass(cls):
        cls.app_module.DB_PATH = cls.original_db
        cls.tmp.cleanup()

    def _create(self, payload):
        resp = self.client.post("/api/employer-jobs", json=payload)
        assert resp.status_code == 201, resp.get_json()
        return resp.get_json()["job"]

    def _predictions_count(self):
        with sqlite3.connect(self.app_module.DB_PATH) as db:
            return db.execute("SELECT COUNT(*) FROM predictions").fetchone()[0]

    def test_text_composition_skips_empty_optionals(self):
        import employer_screening
        payload = {k: v for k, v in _job_payload(LEGIT_TEXT).items()
                   if k not in ("salary", "benefits", "application_url", "closing_date")}
        job = self._create(payload)
        text = employer_screening.compose_screening_text(job, self.profile)
        self.assertIn(f"Job Title: {job['title']}", text)
        self.assertIn(f"Company: {self.profile['company_name']}", text)
        self.assertIn(f"Location: {job['location']}", text)
        self.assertIn(LEGIT_TEXT, text)
        self.assertIn(f"Contact Email: {job['contact_email']}", text)
        self.assertNotIn("Salary:", text)
        self.assertNotIn("Benefits:", text)
        self.assertNotIn("Application URL:", text)
        self.assertNotIn("None", text)

    def test_legitimate_job_becomes_ready_with_report(self):
        job = self._create(_job_payload(LEGIT_TEXT))
        resp = self.client.post(f"/api/employer-jobs/{job['id']}/screen")
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["status"], "ready")
        self.assertEqual(body["job"]["status"], "ready")
        screening = body["screening"]
        self.assertEqual(screening["prediction"], "Legitimate")
        self.assertLess(screening["probability"], 0.5)
        self.assertGreaterEqual(screening["confidence"], 0.5)
        self.assertEqual(screening["engine"]["final"], "noisy_or(xgboost, rules)")
        # status survives a refetch
        again = self.client.get(f"/api/employer-jobs/{job['id']}").get_json()["job"]
        self.assertEqual(again["status"], "ready")
        self.assertEqual(again["screening"]["prediction"], "Legitimate")

    def test_scam_job_becomes_flagged_with_evidence(self):
        job = self._create(_job_payload(SCAM_TEXT, contact="hiring.manager2024@gmail.com"))
        resp = self.client.post(f"/api/employer-jobs/{job['id']}/screen")
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["status"], "flagged")
        screening = body["screening"]
        self.assertEqual(screening["prediction"], "Scam")
        self.assertGreater(screening["probability"], 0.5)
        self.assertTrue(screening["red_flags"])          # evidence present
        categories = " ".join(f.get("category", "") for f in screening["red_flags"])
        self.assertIn("UPFRONT PAYMENT", categories)
        # evidence snippets are stored and readable back
        with sqlite3.connect(self.app_module.DB_PATH) as db:
            raw = db.execute(
                "SELECT evidence_json FROM employer_job_screenings WHERE id = ?",
                (screening["id"],)).fetchone()[0]
        stored = json.loads(raw)
        self.assertIsInstance(stored, list)
        self.assertTrue(any(f.get("evidence") for f in stored))

    def test_history_and_insights_never_polluted(self):
        # /api/history returns a bare list for the signed-in user
        before = len(self.client.get("/api/history?limit=100").get_json())
        preds_before = self._predictions_count()
        job = self._create(_job_payload(LEGIT_TEXT))
        self.client.post(f"/api/employer-jobs/{job['id']}/screen")
        self.client.post(f"/api/employer-jobs/{job['id']}/screen")  # twice
        self.assertEqual(self._predictions_count(), preds_before)
        self.assertEqual(len(self.client.get("/api/history?limit=100").get_json()), before)

    def test_edit_after_screening_resets_to_draft_keeps_audit(self):
        job = self._create(_job_payload(LEGIT_TEXT))
        first = self.client.post(f"/api/employer-jobs/{job['id']}/screen").get_json()
        self.assertEqual(first["status"], "ready")
        # edit -> draft again (invalidated for publication eligibility)
        resp = self.client.put(f"/api/employer-jobs/{job['id']}",
                               json=_job_payload(LEGIT_TEXT, ) | {"title": "Renamed Role"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["job"]["status"], "draft")
        # the old screening record survives as audit data
        with sqlite3.connect(self.app_module.DB_PATH) as db:
            n = db.execute(
                "SELECT COUNT(*) FROM employer_job_screenings WHERE employer_job_id = ?",
                (job["id"],)).fetchone()[0]
        self.assertEqual(n, 1)
        # and the job's attached screening summary is still the historical one
        fetched = self.client.get(f"/api/employer-jobs/{job['id']}").get_json()["job"]
        self.assertEqual(fetched["status"], "draft")
        self.assertEqual(fetched["screening"]["prediction"], "Legitimate")

    def test_re_screen_after_edit_updates_verdict_and_appends_audit(self):
        job = self._create(_job_payload(SCAM_TEXT, contact="hiring.manager2024@gmail.com"))
        first = self.client.post(f"/api/employer-jobs/{job['id']}/screen").get_json()
        self.assertEqual(first["status"], "flagged")
        self.client.put(f"/api/employer-jobs/{job['id']}", json=_job_payload(LEGIT_TEXT))
        second = self.client.post(f"/api/employer-jobs/{job['id']}/screen").get_json()
        self.assertEqual(second["status"], "ready")
        self.assertGreater(second["screening"]["id"], first["screening"]["id"])
        with sqlite3.connect(self.app_module.DB_PATH) as db:
            n = db.execute(
                "SELECT COUNT(*) FROM employer_job_screenings WHERE employer_job_id = ?",
                (job["id"],)).fetchone()[0]
        self.assertEqual(n, 2)  # both kept (audit trail)

    def test_profile_does_not_soften_the_engine(self):
        # the SAME scam text still flags even though the employer profile is
        # a fully registered (trusted-looking) company — no leniency is added
        job = self._create(_job_payload(SCAM_TEXT, contact="hiring.manager2024@gmail.com"))
        body = self.client.post(f"/api/employer-jobs/{job['id']}/screen").get_json()
        self.assertEqual(body["screening"]["prediction"], "Scam")
        self.assertEqual(body["status"], "flagged")


class ScreeningSecurityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import app
        cls.app_module = app
        cls.original_db = app.DB_PATH
        cls.tmp = tempfile.TemporaryDirectory()
        app.DB_PATH = os.path.join(cls.tmp.name, "screen-sec-test.db")
        app.init_db()
        cls.client_a, cls.email_a = signup_and_login(app, name="Employer A")
        cls.client_b, cls.email_b = signup_and_login(app, name="Employer B")
        _register_employer(cls.client_a)
        _register_employer(cls.client_b)
        cls.job_a = cls.client_a.post("/api/employer-jobs",
                                      json=_job_payload(LEGIT_TEXT)).get_json()["job"]

    @classmethod
    def tearDownClass(cls):
        cls.app_module.DB_PATH = cls.original_db
        cls.tmp.cleanup()

    def test_anonymous_is_401(self):
        anon = self.app_module.app.test_client()
        self.assertEqual(anon.post(f"/api/employer-jobs/{self.job_a['id']}/screen").status_code, 401)

    def test_non_employer_is_403(self):
        plain, _ = signup_and_login(self.app_module, name="Plain Non Employer")
        resp = plain.post(f"/api/employer-jobs/{self.job_a['id']}/screen")
        self.assertEqual(resp.status_code, 403)
        self.assertIn("employer profile", resp.get_json()["error"])

    def test_missing_and_invalid_csrf_are_403(self):
        raw = self.app_module.app.test_client()
        raw.post("/api/auth/login", json={"email": self.email_a, "password": "Passw0rd123"})
        resp = raw.post(f"/api/employer-jobs/{self.job_a['id']}/screen")
        self.assertEqual(resp.status_code, 403)
        self.assertTrue(resp.get_json().get("csrf_error"))
        resp = raw.post(f"/api/employer-jobs/{self.job_a['id']}/screen",
                        headers={"X-CSRF-Token": "forged"})
        self.assertEqual(resp.status_code, 403)

    def test_foreign_job_is_404_and_not_screened(self):
        with sqlite3.connect(self.app_module.DB_PATH) as db:
            baseline = db.execute(
                "SELECT COUNT(*) FROM employer_job_screenings WHERE employer_job_id = ?",
                (self.job_a["id"],)).fetchone()[0]
        status_before = self.client_a.get(
            f"/api/employer-jobs/{self.job_a['id']}").get_json()["job"]["status"]
        resp = self.client_b.post(f"/api/employer-jobs/{self.job_a['id']}/screen")
        self.assertEqual(resp.status_code, 404)
        with sqlite3.connect(self.app_module.DB_PATH) as db:
            n = db.execute(
                "SELECT COUNT(*) FROM employer_job_screenings WHERE employer_job_id = ?",
                (self.job_a["id"],)).fetchone()[0]
        self.assertEqual(n, baseline)  # nothing recorded for A's job via B's call
        # A's job status untouched by B's rejected attempt
        mine = self.client_a.get(f"/api/employer-jobs/{self.job_a['id']}").get_json()["job"]
        self.assertEqual(mine["status"], status_before)

    def test_b_cannot_access_a_screening(self):
        self.client_a.post(f"/api/employer-jobs/{self.job_a['id']}/screen")
        body = self.client_b.get("/api/employer-jobs").get_json()
        self.assertEqual(body["jobs"], [])           # B lists nothing of A's
        resp = self.client_b.get(f"/api/employer-jobs/{self.job_a['id']}")
        self.assertEqual(resp.status_code, 404)      # screening rides the owned job

    def test_missing_job_id_is_404(self):
        resp = self.client_a.post("/api/employer-jobs/999999/screen")
        self.assertEqual(resp.status_code, 404)


if __name__ == "__main__":
    unittest.main(verbosity=2)
