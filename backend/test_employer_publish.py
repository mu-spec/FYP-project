"""
Milestone 8C.3B tests — safe publishing of screened jobs + public JobGuard
listings on the existing Jobs feed.
==========================================================================

Run from backend/:
    python -m unittest test_employer_publish -v

Suites:
  1. PublishSchemaTests  - published_at / text_hash in-place migrations
                           (fresh DB + legacy DB with existing rows)
  2. PublishApiTests     - ready -> published (explicit only), draft/flagged/
                           no-screening/stale-screening rejections, client
                           cannot force status, edit published -> draft +
                           hidden, delete published -> hidden
  3. PublishSecurityTests- anonymous 401, non-employer 403, missing/invalid
                           CSRF 403, foreign job 404
  4. PublicFeedTests     - only published employer jobs are public; tables
                           stay separate (external_jobs untouched);
                           source=jobguard / remoteok / arbeitnow filters;
                           merged feed totals + ordering; notifications feed
                           unaffected; "Analyze with JobGuard" creates a
                           NORMAL history row (never reuses the private
                           screening row)

The engine is UNCHANGED (predict_one verbatim); publishing is backend-decided
and requires status == 'ready' plus a screening whose recorded text hash
still matches the current job content.
"""

import json
import os
import sqlite3
import tempfile
import unittest
from uuid import uuid4

from auth_test_utils import signup_and_login
from test_employer_jobs import VALID as JOB_VALID, _register_employer

from job_sources import service as job_service

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


def _seed_external(db_path, rows):
    """Insert external_jobs rows with a FRESH fetched_at so the merged-feed
    tests never hit the live providers."""
    now = job_service.now_iso()
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
                 r.get("salary"), r.get("job_url"), r.get("published_at"), now),
            )
        db.commit()


class _AppCase(unittest.TestCase):
    """Boilerplate: swap app.DB_PATH to a temp DB for the whole test."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp.name, "publish-test.db")
        import app
        self.app_module = app
        self.original_db = app.DB_PATH
        app.DB_PATH = self.db_path
        app.init_db()

    def tearDown(self):
        self.app_module.DB_PATH = self.original_db
        self.tmp.cleanup()


class PublishSchemaTests(_AppCase):
    def test_published_at_and_text_hash_columns_fresh_db(self):
        employer_jobs = self.app_module.employer_jobs
        employer_jobs.ensure_table(self.db_path)
        screening = self.app_module.employer_screening
        screening.ensure_table(self.db_path)
        with sqlite3.connect(self.db_path) as db:
            job_cols = {r[1] for r in db.execute("PRAGMA table_info(employer_jobs)")}
            scr_cols = {r[1] for r in db.execute("PRAGMA table_info(employer_job_screenings)")}
            indexes = " ".join(
                (r[4] or "") for r in
                db.execute("SELECT * FROM sqlite_master WHERE type='index'")
            )
        self.assertIn("published_at", job_cols)
        self.assertIn("idx_employer_jobs_published_at", indexes)
        self.assertIn("text_hash", scr_cols)

    def test_migration_preserves_existing_rows(self):
        """A pre-8C.3B database (no published_at / text_hash) migrates in
        place without losing any data; old columns get NULL for the new
        fields."""
        legacy = os.path.join(self.tmp.name, "legacy.db")  # NOT init_db'd
        self.db_path = legacy
        with sqlite3.connect(self.db_path) as db:
            db.executescript(
                """
                CREATE TABLE employer_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    employer_profile_id INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    location TEXT NOT NULL,
                    job_type TEXT NOT NULL,
                    salary TEXT,
                    description TEXT NOT NULL,
                    requirements TEXT NOT NULL,
                    benefits TEXT,
                    contact_email TEXT NOT NULL,
                    application_url TEXT,
                    closing_date TEXT,
                    status TEXT NOT NULL DEFAULT 'draft',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE employer_job_screenings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    employer_job_id INTEGER NOT NULL,
                    prediction TEXT NOT NULL,
                    probability REAL NOT NULL,
                    confidence REAL NOT NULL,
                    evidence_json TEXT,
                    screened_at TEXT NOT NULL
                );
                INSERT INTO employer_jobs (employer_profile_id, title, location,
                    job_type, description, requirements, contact_email, status,
                    created_at, updated_at)
                VALUES (7, 'Old Job', 'Lahore', 'Full Time', 'x', 'y',
                        'a@b.example', 'draft', '2026-01-01', '2026-01-01');
                INSERT INTO employer_job_screenings (employer_job_id, prediction,
                    probability, confidence, evidence_json, screened_at)
                VALUES (1, 'Legitimate', 0.07, 0.93, '[]', '2026-01-02');
                """
            )
            db.commit()
        self.app_module.employer_jobs.ensure_table(self.db_path)
        self.app_module.employer_screening.ensure_table(self.db_path)
        with sqlite3.connect(self.db_path) as db:
            db.row_factory = sqlite3.Row
            job = db.execute("SELECT * FROM employer_jobs").fetchone()
            scr = db.execute("SELECT * FROM employer_job_screenings").fetchone()
        self.assertEqual(job["title"], "Old Job")
        self.assertEqual(job["status"], "draft")
        self.assertIsNone(job["published_at"])
        self.assertEqual(scr["prediction"], "Legitimate")
        self.assertIsNone(scr["text_hash"])


class PublishApiTests(_AppCase):
    @classmethod
    def setUpClass(cls):
        pass  # per-test clients (fresh DBs keep literals simple)

    def _employer_with_job(self, description=LEGIT_TEXT):
        client, email = signup_and_login(self.app_module, name="Pub Employer")
        _register_employer(client)
        resp = client.post("/api/employer-jobs", json=_job_payload(description))
        self.assertEqual(resp.status_code, 201, resp.get_json())
        return client, resp.get_json()["job"]

    def _screen(self, client, job_id):
        resp = client.post(f"/api/employer-jobs/{job_id}/screen")
        self.assertEqual(resp.status_code, 200, resp.get_json())
        return resp.get_json()

    def test_ready_job_publishes_with_timestamp(self):
        client, job = self._employer_with_job()
        body = self._screen(client, job["id"])
        self.assertEqual(body["status"], "ready")
        resp = client.post(f"/api/employer-jobs/{job['id']}/publish")
        self.assertEqual(resp.status_code, 200, resp.get_json())
        data = resp.get_json()
        self.assertEqual(data["job"]["status"], "published")
        self.assertTrue(data["job"]["published_at"])
        self.assertEqual(data["published_at"], data["job"]["published_at"])

    def test_draft_publish_rejected(self):
        client, job = self._employer_with_job()
        resp = client.post(f"/api/employer-jobs/{job['id']}/publish")
        self.assertEqual(resp.status_code, 409, resp.get_json())
        self.assertEqual(resp.get_json()["job"]["status"]
                         if "job" in resp.get_json() else
                         client.get(f"/api/employer-jobs/{job['id']}").get_json()["job"]["status"],
                         "draft")

    def test_flagged_publish_rejected(self):
        client, job = self._employer_with_job(SCAM_TEXT)
        body = self._screen(client, job["id"])
        self.assertEqual(body["status"], "flagged")
        resp = client.post(f"/api/employer-jobs/{job['id']}/publish")
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(
            client.get(f"/api/employer-jobs/{job['id']}").get_json()["job"]["status"],
            "flagged")

    def test_no_screening_publish_rejected(self):
        client, job = self._employer_with_job()
        with sqlite3.connect(self.db_path) as db:
            db.execute("UPDATE employer_jobs SET status='ready' WHERE id=?", (job["id"],))
            db.commit()
        resp = client.post(f"/api/employer-jobs/{job['id']}/publish")
        self.assertEqual(resp.status_code, 409)
        self.assertIn("No safety screening", resp.get_json()["error"])

    def test_stale_screening_rejected_even_if_status_forged_ready(self):
        """The belt-and-braces guard: a pass on OLD text never publishes NEW
        text, even if the status column says 'ready'."""
        client, job = self._employer_with_job()
        self._screen(client, job["id"])
        with sqlite3.connect(self.db_path) as db:
            db.execute(
                "UPDATE employer_jobs SET title='Renamed After Screening',"
                " status='ready' WHERE id=?",
                (job["id"],),
            )
            db.commit()
        resp = client.post(f"/api/employer-jobs/{job['id']}/publish")
        self.assertEqual(resp.status_code, 409, resp.get_json())
        self.assertIn("out of date", resp.get_json()["error"])

    def test_client_cannot_force_published_status(self):
        client, _ = self._employer_with_job()
        payload = _job_payload(LEGIT_TEXT)
        payload["status"] = "published"
        created = client.post("/api/employer-jobs", json=payload)
        self.assertEqual(created.get_json()["job"]["status"], "draft")
        job_id = created.get_json()["job"]["id"]
        updated = client.put(f"/api/employer-jobs/{job_id}", json=payload)
        self.assertEqual(updated.get_json()["job"]["status"], "draft")

    def test_edit_published_resets_hides_and_republish_flow(self):
        client, job = self._employer_with_job()
        self._screen(client, job["id"])
        self.assertEqual(client.post(f"/api/employer-jobs/{job['id']}/publish")
                         .status_code, 200)
        visible = client.get("/api/jobs").get_json()
        self.assertEqual([j["source_job_id"] for j in visible["jobs"] if j["source"] == "jobguard"],
                         [str(job["id"])])

        # edit -> draft, publication stamp cleared, immediately hidden
        edited = client.put(f"/api/employer-jobs/{job['id']}",
                            json=_job_payload(LEGIT_TEXT, contact="hr2@acmelabs.example"))
        self.assertEqual(edited.get_json()["job"]["status"], "draft")
        self.assertIsNone(edited.get_json()["job"]["published_at"])
        visible = client.get("/api/jobs").get_json()
        self.assertEqual([j for j in visible["jobs"] if j["source"] == "jobguard"], [])

        # re-screen -> ready -> republish -> visible again
        self.assertEqual(self._screen(client, job["id"])["status"], "ready")
        republished = client.post(f"/api/employer-jobs/{job['id']}/publish")
        self.assertEqual(republished.status_code, 200)
        visible = client.get("/api/jobs").get_json()
        guard = [j for j in visible["jobs"] if j["source"] == "jobguard"]
        self.assertEqual(len(guard), 1)
        self.assertTrue(guard[0]["published_at"])

    def test_delete_published_hides_immediately(self):
        client, job = self._employer_with_job()
        self._screen(client, job["id"])
        client.post(f"/api/employer-jobs/{job['id']}/publish")
        self.assertEqual(len([j for j in client.get("/api/jobs").get_json()["jobs"]
                              if j["source"] == "jobguard"]), 1)
        self.assertEqual(client.delete(f"/api/employer-jobs/{job['id']}").status_code, 200)
        self.assertEqual([j for j in client.get("/api/jobs").get_json()["jobs"]
                          if j["source"] == "jobguard"], [])


class PublishSecurityTests(_AppCase):
    def setUp(self):
        super().setUp()
        self.client_a, _ = signup_and_login(self.app_module, name="Employer A")
        _register_employer(self.client_a)
        created = self.client_a.post("/api/employer-jobs",
                                     json=_job_payload(LEGIT_TEXT))
        self.job_a = created.get_json()["job"]
        self.client_a.post(f"/api/employer-jobs/{self.job_a['id']}/screen")

    def test_anonymous_publish_401(self):
        raw = self.app_module.app.test_client()
        resp = raw.post(f"/api/employer-jobs/{self.job_a['id']}/publish")
        self.assertEqual(resp.status_code, 401)

    def test_non_employer_publish_403(self):
        plain, _ = signup_and_login(self.app_module, name="Plain User")
        resp = plain.post(f"/api/employer-jobs/{self.job_a['id']}/publish")
        self.assertEqual(resp.status_code, 403)

    def test_missing_and_invalid_csrf_403(self):
        raw = self.app_module.app.test_client()
        raw.post("/api/auth/signup", json={
            "name": "Csrf User", "email": f"{uuid4().hex[:8]}@x.example",
            "password": "Passw0rd123", "confirm": "Passw0rd123"})
        missing = raw.post(f"/api/employer-jobs/{self.job_a['id']}/publish")
        self.assertEqual(missing.status_code, 403)
        bad = raw.post(f"/api/employer-jobs/{self.job_a['id']}/publish",
                       headers={"X-CSRF-Token": "forged"})
        self.assertEqual(bad.status_code, 403)

    def test_foreign_publish_404_and_no_side_effects(self):
        client_b, _ = signup_and_login(self.app_module, name="Employer B")
        _register_employer(client_b)
        with sqlite3.connect(self.db_path) as db:
            before = db.execute("SELECT COUNT(*) FROM employer_job_screenings").fetchone()[0]
        resp = client_b.post(f"/api/employer-jobs/{self.job_a['id']}/publish")
        self.assertEqual(resp.status_code, 404)
        with sqlite3.connect(self.db_path) as db:
            after = db.execute("SELECT COUNT(*) FROM employer_job_screenings").fetchone()[0]
            status = db.execute("SELECT status FROM employer_jobs WHERE id=?",
                                (self.job_a["id"],)).fetchone()[0]
        self.assertEqual(after, before)
        self.assertEqual(status, "ready")


class PublicFeedTests(_AppCase):
    @classmethod
    def setUpClass(cls):
        pass

    def setUp(self):
        super().setUp()
        _seed_external(self.db_path, [
            dict(source="remoteok", source_job_id="rk-1", title="Remote Ruby Dev",
                 company="RK Co", location="Worldwide", description="Ruby role.",
                 job_type="Full Time", remote=True, tags=["ruby"],
                 published_at="2026-09-10T00:00:00+00:00"),
            dict(source="arbeitnow", source_job_id="an-1", title="DevOps Engineer",
                 company="AN Co", location="Berlin", description="Kubernetes role.",
                 job_type="Full Time", remote=False, tags=[],
                 published_at="2026-09-11T00:00:00+00:00"),
        ])
        self.client_a, _ = signup_and_login(self.app_module, name="Feed Employer")
        _register_employer(self.client_a)
        # one job per status: draft / flagged / ready / published
        draft = self.client_a.post("/api/employer-jobs",
                                   json=_job_payload(LEGIT_TEXT, "d@acmelabs.example")
                                   ).get_json()["job"]
        flagged = self.client_a.post(
            "/api/employer-jobs",
            json=_job_payload(SCAM_TEXT, "f@acmelabs.example")).get_json()["job"]
        self.client_a.post(f"/api/employer-jobs/{flagged['id']}/screen")
        ready = self.client_a.post("/api/employer-jobs",
                                   json=_job_payload(LEGIT_TEXT, "r@acmelabs.example")
                                   ).get_json()["job"]
        self.client_a.post(f"/api/employer-jobs/{ready['id']}/screen")
        published = self.client_a.post(
            "/api/employer-jobs",
            json=_job_payload(LEGIT_TEXT, "p@acmelabs.example")).get_json()["job"]
        self.client_a.post(f"/api/employer-jobs/{published['id']}/screen")
        resp = self.client_a.post(f"/api/employer-jobs/{published['id']}/publish")
        self.assertEqual(resp.status_code, 200, resp.get_json())
        self.ids = {"draft": draft["id"], "flagged": flagged["id"],
                    "ready": ready["id"], "published": published["id"]}

    def _jobs(self, query=""):
        return self.client_a.get(f"/api/jobs{query}").get_json()

    def test_only_published_jobs_are_public(self):
        data = self._jobs()
        guard = [j for j in data["jobs"] if j["source"] == "jobguard"]
        self.assertEqual(len(guard), 1)
        self.assertEqual(guard[0]["source_job_id"], str(self.ids["published"]))
        self.assertEqual(guard[0]["title"], JOB_VALID["title"])
        self.assertEqual(guard[0]["company"], "Acme Labs")  # from the profile
        self.assertNotIn(guard[0]["source_job_id"],
                         {str(self.ids[k]) for k in ("draft", "flagged", "ready")})
        # tables stay separate: nothing copied into external_jobs
        with sqlite3.connect(self.db_path) as db:
            n_ext = db.execute("SELECT COUNT(*) FROM external_jobs").fetchone()[0]
        self.assertEqual(n_ext, 2)
        self.assertEqual(data["total"], 3)  # 2 external + 1 jobguard

    def test_source_jobguard_filter(self):
        data = self._jobs("?source=jobguard")
        self.assertEqual(data["total"], 1)
        self.assertTrue(all(j["source"] == "jobguard" for j in data["jobs"]))
        item = data["jobs"][0]
        self.assertIn("requirements", item)
        self.assertIn("benefits", item)
        self.assertIsNone(item["job_url"])
        self.assertIsNone(data["cache"])

    def test_source_remoteok_and_arbeitnow_still_work(self):
        rk = self._jobs("?source=remoteok")
        self.assertEqual(rk["total"], 1)
        self.assertEqual({j["source"] for j in rk["jobs"]}, {"remoteok"})
        an = self._jobs("?source=arbeitnow")
        self.assertEqual(an["total"], 1)
        self.assertEqual({j["source"] for j in an["jobs"]}, {"arbeitnow"})

    def test_merged_feed_orders_newest_first(self):
        data = self._jobs()
        sources = [(j["source"], j["source_job_id"]) for j in data["jobs"]]
        self.assertEqual(len(sources), 3)
        self.assertEqual(sources[0], ("jobguard", str(self.ids["published"])))

    def test_q_filter_spans_both_tables(self):
        data = self._jobs("?q=DevOps")
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["jobs"][0]["source"], "arbeitnow")
        data = self._jobs(f"?q={JOB_VALID['title']}")
        self.assertEqual([j["source"] for j in data["jobs"]], ["jobguard"])

    def test_analyze_with_jobguard_creates_normal_history(self):
        """The public card's Analyze button uses the normal /api/predict flow:
        a normal History row is created and the private pre-publish screening
        row is NOT reused or duplicated into History/Insights."""
        published = self.client_a.get(
            f"/api/employer-jobs/{self.ids['published']}").get_json()["job"]
        with sqlite3.connect(self.db_path) as db:
            scr_before = db.execute(
                "SELECT COUNT(*) FROM employer_job_screenings").fetchone()[0]
        resp = self.client_a.post("/api/predict",
                                  json={"job_text": published["description"],
                                        "title": published["title"]})
        self.assertEqual(resp.status_code, 200, resp.get_json())
        history = self.client_a.get("/api/history").get_json()
        self.assertEqual(len(history), 1)
        with sqlite3.connect(self.db_path) as db:
            scr_after = db.execute(
                "SELECT COUNT(*) FROM employer_job_screenings").fetchone()[0]
        self.assertEqual(scr_after, scr_before)


if __name__ == "__main__":
    unittest.main()
