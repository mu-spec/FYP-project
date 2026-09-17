"""
Milestone 8B.2 tests — Personalized Job Preferences & Notifications.
====================================================================

Run from backend/:
    python -m unittest test_job_alerts -v

Suites:
  1. MatchingTests          - deterministic keyword/location/remote/source
                              matching (explainable reasons, no ML involved)
  2. PreferencesApiTests    - GET/PUT /api/job-preferences: auth 401, CSRF
                              403, validation, upsert on UNIQUE(user_id),
                              strict ownership
  3. AlertGenerationTests   - notifications generated on refresh for matching
                              users only, duplicate prevention via
                              UNIQUE(user_id, external_job_id), only real
                              cached jobs, provider-down resilience, safe
                              catch-up matching
  4. NotificationsApiTests  - GET list / unread-count / mark read /
                              read-all: auth 401, CSRF 403, cross-user
                              isolation (foreign id -> 404, never modified)

All HTTP is mocked; nothing here touches the ML pipeline or the existing
users/predictions/external_jobs semantics.
"""

import json
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock
from uuid import uuid4

from auth_test_utils import signup_and_login
from job_sources import alerts, matching, service
from test_job_sources import ARBEITNOW_RAW, REMOTEOK_RAW, FakeResponse, _seed_rows


def _unique_email():
    return f"{uuid4().hex[:10]}@alerts-test.example.com"


def _save_pref_raw(db_path, user_id, keywords, location="", remote_only=0, source="any"):
    """Seed a preference row directly (no HTTP) for matching tests."""
    alerts.ensure_tables(db_path)
    now = service.now_iso()
    with sqlite3.connect(db_path) as db:
        db.execute(
            "INSERT INTO job_preferences (user_id, keywords, location, remote_only,"
            " source, created_at, updated_at) VALUES (?,?,?,?,?,?,?)"
            " ON CONFLICT(user_id) DO UPDATE SET keywords=excluded.keywords,"
            " location=excluded.location, remote_only=excluded.remote_only,"
            " source=excluded.source, updated_at=excluded.updated_at",
            (user_id, keywords, location, remote_only, source, now, now),
        )
        db.commit()


def _notifications_for(db_path, user_id):
    with sqlite3.connect(db_path) as db:
        return db.execute(
            "SELECT n.title, n.message, n.is_read, j.source_job_id FROM notifications n"
            " JOIN external_jobs j ON j.id = n.external_job_id WHERE n.user_id = ?"
            " ORDER BY n.id",
            (user_id,),
        ).fetchall()


class MatchingTests(unittest.TestCase):
    """Pure matching logic — deterministic and explainable, no ML."""

    JOB = {
        "id": 1, "source": "remoteok", "source_job_id": "swe-1",
        "title": "Senior Software Engineer", "company": "TechCo",
        "location": "Remote — Lahore", "description": "Build APIs with Python and Flask.",
        "tags": ["python", "flask"], "remote": 1,
    }

    def test_keywords_match_each_field(self):
        for field, keyword, job in [
            ("title", "engineer", dict(self.JOB, description="", tags=[])),
            ("company", "techco", dict(self.JOB, title="x", description="", tags=[])),
            ("description", "flask", dict(self.JOB, title="x", tags=[])),
            ("tags", "python", dict(self.JOB, title="x", description="", tags=["Python"])),
        ]:
            with self.subTest(field=field):
                verdict = matching.match_job(job, {"keywords": keyword})
                self.assertTrue(verdict["matched"], verdict["reasons"])

    def test_keywords_are_case_insensitive_and_all_required(self):
        self.assertTrue(matching.match_job(self.JOB, {"keywords": "SOFTWARE engineer"})["matched"])
        # AND semantics: one missing term fails the match, and says why
        verdict = matching.match_job(self.JOB, {"keywords": "software golang"})
        self.assertFalse(verdict["matched"])
        self.assertTrue(any("golang" in r for r in verdict["reasons"]))

    def test_location_matches_case_insensitively(self):
        self.assertTrue(matching.match_job(self.JOB, {"location": "lahore"})["matched"])
        self.assertFalse(matching.match_job(self.JOB, {"location": "Karachi"})["matched"])

    def test_remote_only_requires_remote_flag(self):
        self.assertTrue(matching.match_job(self.JOB, {"remote_only": True})["matched"])
        self.assertFalse(matching.match_job(dict(self.JOB, remote=0), {"remote_only": True})["matched"])
        # not required -> onsite job still passes
        self.assertTrue(matching.match_job(dict(self.JOB, remote=0), {"remote_only": False})["matched"])

    def test_source_filter(self):
        self.assertTrue(matching.match_job(self.JOB, {"source": "any"})["matched"])
        self.assertTrue(matching.match_job(self.JOB, {"source": "remoteok"})["matched"])
        self.assertFalse(matching.match_job(self.JOB, {"source": "arbeitnow"})["matched"])

    def test_empty_preferences_match_everything_with_stable_reasons(self):
        verdict = matching.match_job(self.JOB, {})
        self.assertTrue(verdict["matched"])
        self.assertEqual(len(verdict["reasons"]), 4)
        for prefix in ("keywords:", "location:", "remote_only:", "source:"):
            self.assertTrue(any(r.startswith(prefix) for r in verdict["reasons"]), verdict["reasons"])

    def test_full_preference_stack(self):
        prefs = {"keywords": "python flask", "location": "LAHORE",
                 "remote_only": True, "source": "remoteok"}
        self.assertTrue(matching.match_job(self.JOB, prefs)["matched"])
        # a real Arbeitnow-style row: marketing job, onsite, other source
        other = {"id": 2, "source": "arbeitnow", "title": "Marketing Manager",
                 "company": "Media Haus", "location": "Hamburg",
                 "description": "Social media campaigns.", "tags": [], "remote": 0}
        self.assertFalse(matching.match_job(other, prefs)["matched"])


class PreferencesApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import app
        cls.app_module = app
        cls.original_db = app.DB_PATH
        cls.tmp = tempfile.TemporaryDirectory()
        app.DB_PATH = os.path.join(cls.tmp.name, "prefs-api-test.db")
        app.init_db()
        cls.client, cls.own_email = signup_and_login(app, name="Prefs User")
        cls.other_client, _ = signup_and_login(app, name="Prefs Other")

    @classmethod
    def tearDownClass(cls):
        cls.app_module.DB_PATH = cls.original_db
        cls.tmp.cleanup()

    def test_anonymous_gets_401(self):
        anon = self.app_module.app.test_client()
        self.assertEqual(anon.get("/api/job-preferences").status_code, 401)
        self.assertEqual(anon.put("/api/job-preferences", json={}).status_code, 401)

    def test_put_requires_csrf(self):
        raw = self.app_module.app.test_client()
        raw.post("/api/auth/signup", json={
            "email": _unique_email(), "password": "Passw0rd123",
            "name": "CSRF Prefs", "confirm": "Passw0rd123",
        })
        resp = raw.put("/api/job-preferences", json={"keywords": "x"})
        self.assertEqual(resp.status_code, 403)
        self.assertTrue(resp.get_json().get("csrf_error"))

    def test_save_and_read_roundtrip_trims_input(self):
        resp = self.client.put("/api/job-preferences", json={
            "keywords": "  Software Engineer  ", "location": " Lahore ",
            "remote_only": True, "source": "remoteok",
        })
        self.assertEqual(resp.status_code, 200)
        prefs = resp.get_json()["preferences"]
        self.assertEqual(prefs["keywords"], "Software Engineer")
        self.assertEqual(prefs["location"], "Lahore")
        self.assertIs(prefs["remote_only"], True)
        self.assertEqual(prefs["source"], "remoteok")
        read_back = self.client.get("/api/job-preferences").get_json()["preferences"]
        self.assertEqual(read_back, prefs)

    def test_validation_rejects_bad_source_and_overlong_strings(self):
        bad_source = self.client.put("/api/job-preferences", json={"source": "indeed"})
        self.assertEqual(bad_source.status_code, 400)
        too_long = self.client.put("/api/job-preferences", json={"keywords": "x" * 121})
        self.assertEqual(too_long.status_code, 400)
        long_loc = self.client.put("/api/job-preferences", json={"location": "y" * 121})
        self.assertEqual(long_loc.status_code, 400)

    def test_upsert_keeps_single_active_record(self):
        self.client.put("/api/job-preferences", json={"keywords": "first"})
        self.client.put("/api/job-preferences", json={"keywords": "second", "source": "arbeitnow"})
        with sqlite3.connect(self.app_module.DB_PATH) as db:
            user_id = db.execute(
                "SELECT id FROM users WHERE email = ?", (self.own_email,)).fetchone()[0]
            n, latest = db.execute(
                "SELECT COUNT(*), MAX(keywords) FROM job_preferences WHERE user_id = ?",
                (user_id,)).fetchone()
        self.assertEqual(n, 1)  # UNIQUE(user_id): one active record
        self.assertEqual(latest, "second")
        prefs = self.client.get("/api/job-preferences").get_json()["preferences"]
        self.assertEqual(prefs["source"], "arbeitnow")

    def test_preferences_belong_to_their_user_only(self):
        self.client.put("/api/job-preferences", json={"keywords": "software"})
        self.other_client.put("/api/job-preferences", json={"keywords": "marketing"})
        mine = self.client.get("/api/job-preferences").get_json()["preferences"]
        theirs = self.other_client.get("/api/job-preferences").get_json()["preferences"]
        self.assertEqual(mine["keywords"], "software")
        self.assertEqual(theirs["keywords"], "marketing")

    def test_get_returns_null_when_never_configured(self):
        client, _ = signup_and_login(self.app_module, name="Prefs Fresh")
        body = client.get("/api/job-preferences").get_json()
        self.assertIsNone(body["preferences"])


class AlertGenerationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp.name, "alerts-test.db")
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

    @staticmethod
    def _make_cache_stale(db_path):
        old = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        with sqlite3.connect(db_path) as db:
            db.execute("UPDATE external_jobs SET fetched_at = ?", (old,))
            db.commit()

    @classmethod
    def _normalized_fixtures(cls):
        import job_sources.remote_ok as remote_ok
        import job_sources.arbeitnow as arbeitnow
        remoteok = [remote_ok.normalize(e) for e in REMOTEOK_RAW]
        remoteok = [j for j in remoteok if j]
        arbeitnow_payload = [arbeitnow.normalize(e) for e in ARBEITNOW_RAW["data"]]
        return remoteok, [j for j in arbeitnow_payload if j]

    def _refresh_with_mocks(self):
        remoteok, arbeitnow_jobs = self._normalized_fixtures()
        import job_sources.remote_ok as remote_ok_mod
        import job_sources.arbeitnow as arbeitnow_mod
        with mock.patch.object(remote_ok_mod, "fetch_jobs", return_value=remoteok), \
             mock.patch.object(arbeitnow_mod, "fetch_jobs", return_value=arbeitnow_jobs):
            return service.refresh_if_stale(self.db_path)

    def test_notifications_generated_for_matching_users_only(self):
        _, email_a = signup_and_login(self.app_module, name="User A")
        _, email_b = signup_and_login(self.app_module, name="User B")
        with sqlite3.connect(self.db_path) as db:
            user_a = db.execute("SELECT id FROM users WHERE email = ?", (email_a,)).fetchone()[0]
            user_b = db.execute("SELECT id FROM users WHERE email = ?", (email_b,)).fetchone()[0]

        _save_pref_raw(self.db_path, user_a, "python")
        _save_pref_raw(self.db_path, user_b, "marketing")

        status = self._refresh_with_mocks()
        self.assertTrue(any(status["providers"][p]["ok"] for p in status["providers"]))

        notifs_a = _notifications_for(self.db_path, user_a)
        notifs_b = _notifications_for(self.db_path, user_b)
        # RemoteOK payload: Senior Developer (Acme) + Support Agent; Arbeitnow:
        # Backend Engineer + Marketing Manager. "software" only matches the
        # dev/engineering roles; "marketing" only the marketing role.
        self.assertEqual([n[3] for n in notifs_a], ["remote-senior-dev-acme-111", "backend-engineer-berlin-1"])
        self.assertEqual([n[3] for n in notifs_b], ["marketing-hamburg-2"])
        # no cross-user rows
        all_rows = _notifications_for(self.db_path, user_a) + _notifications_for(self.db_path, user_b)
        self.assertTrue(all("marketing" not in (n[3] or "") or n[3] == "marketing-hamburg-2" for n in all_rows))

    def test_duplicate_notifications_prevented_across_refreshes(self):
        _, email = signup_and_login(self.app_module, name="Dup User")
        with sqlite3.connect(self.db_path) as db:
            user_id = db.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()[0]
        _save_pref_raw(self.db_path, user_id, "developer")

        self._refresh_with_mocks()
        first = _notifications_for(self.db_path, user_id)
        self.assertTrue(first)

        # cache goes stale again, providers return the SAME jobs (updates) —
        # nothing new may notify
        self._make_cache_stale(self.db_path)
        service._last_refresh = {"at": None, "ok": {n: None for n in service.PROVIDERS}}
        self._refresh_with_mocks()
        second = _notifications_for(self.db_path, user_id)
        self.assertEqual(len(first), len(second))

    def test_only_real_cached_jobs_notify_and_pruned_jobs_keep_snapshot(self):
        _, email = signup_and_login(self.app_module, name="Snapshot User")
        with sqlite3.connect(self.db_path) as db:
            user_id = db.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()[0]
        _save_pref_raw(self.db_path, user_id, "developer")
        self._refresh_with_mocks()
        # prune the cached job the notification points at
        with sqlite3.connect(self.db_path) as db:
            db.execute("DELETE FROM external_jobs WHERE source_job_id = 'remote-senior-dev-acme-111'")
            db.commit()
        body = alerts.list_notifications(self.db_path, user_id)
        target = [n for n in body["notifications"] if n["title"] == "Senior Developer"]
        self.assertTrue(target)
        self.assertIsNone(target[0]["job"])          # listing no longer cached
        self.assertTrue(target[0]["title"])          # snapshot survives

    def test_provider_down_matching_still_uses_available_cache(self):
        c, email = signup_and_login(self.app_module, name="Down User")
        with sqlite3.connect(self.db_path) as db:
            user_id = db.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()[0]
        _save_pref_raw(self.db_path, user_id, "engineer", remote_only=1, source="arbeitnow")
        self._make_cache_stale(self.db_path)
        _, arbeitnow_jobs = self._normalized_fixtures()
        import job_sources.remote_ok as remote_ok_mod
        import job_sources.arbeitnow as arbeitnow_mod
        with mock.patch.object(remote_ok_mod, "fetch_jobs", side_effect=Exception("down")), \
             mock.patch.object(arbeitnow_mod, "fetch_jobs", return_value=arbeitnow_jobs):
            status = service.refresh_if_stale(self.db_path)
        self.assertFalse(status["providers"]["remoteok"]["ok"])
        self.assertTrue(status["providers"]["arbeitnow"]["ok"])
        notifs = _notifications_for(self.db_path, user_id)
        self.assertEqual([n[3] for n in notifs], ["backend-engineer-berlin-1"])  # remote Arbeitnow match

    def test_catchup_matching_after_preferences_saved(self):
        # jobs are cached FIRST, preferences saved later -> opening the list
        # (safe check path) must surface cached matches, idempotently
        self._refresh_with_mocks()
        c, email = signup_and_login(self.app_module, name="Late User")
        with sqlite3.connect(self.db_path) as db:
            user_id = db.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()[0]
        _save_pref_raw(self.db_path, user_id, "support")
        created_first = alerts.run_user_matching(self.db_path, user_id)
        created_second = alerts.run_user_matching(self.db_path, user_id)
        self.assertGreaterEqual(created_first, 1)
        self.assertEqual(created_second, 0)  # UNIQUE(user_id, external_job_id)


class NotificationsApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import app
        cls.app_module = app
        cls.original_db = app.DB_PATH
        cls.tmp = tempfile.TemporaryDirectory()
        app.DB_PATH = os.path.join(cls.tmp.name, "notif-api-test.db")
        app.init_db()
        cls.client_a, cls.email_a = signup_and_login(app, name="Notif A")
        cls.client_b, cls.email_b = signup_and_login(app, name="Notif B")
        with sqlite3.connect(app.DB_PATH) as db:
            cls.user_a = db.execute("SELECT id FROM users WHERE email = ?", (cls.email_a,)).fetchone()[0]
            cls.user_b = db.execute("SELECT id FROM users WHERE email = ?", (cls.email_b,)).fetchone()[0]
            cls.job_ids = {}
            for sid, title in [("n-1", "Python Dev"), ("n-2", "QA Lead"),
                               ("n-3", "DevOps Eng"), ("n-4", "Support Spec")]:
                db.execute("INSERT INTO external_jobs (source, source_job_id, title, company,"
                           " location, description, job_type, remote, tags_json, salary, job_url,"
                           " published_at, fetched_at) VALUES ('remoteok',?,?,'Acme',"
                           "'Remote','desc',NULL,1,'[]',NULL,?, ?,?)",
                           (sid, title, f"https://remoteok.com/{sid}",
                            service.now_iso(), service.now_iso()))
                cls.job_ids[sid] = db.execute(
                    "SELECT id FROM external_jobs WHERE source_job_id = ?", (sid,)).fetchone()[0]
            db.commit()
            cls.job_id = cls.job_ids["n-1"]  # used by the catch-up test

    @classmethod
    def tearDownClass(cls):
        cls.app_module.DB_PATH = cls.original_db
        cls.tmp.cleanup()

    def _notify(self, user_id, title="Software Engineer", job_key="n-2"):
        with sqlite3.connect(self.app_module.DB_PATH) as db:
            db.execute(
                "INSERT INTO notifications (user_id, external_job_id, title, message,"
                " is_read, created_at) VALUES (?,?,?,?,0,?)"
                " ON CONFLICT(user_id, external_job_id) DO NOTHING",
                (user_id, self.job_ids[job_key], title,
                 "Acme · Remote — new job matches your preferences.", service.now_iso()),
            )
            db.commit()

    def test_anonymous_gets_401_everywhere(self):
        anon = self.app_module.app.test_client()
        self.assertEqual(anon.get("/api/notifications").status_code, 401)
        self.assertEqual(anon.get("/api/notifications/unread-count").status_code, 401)
        self.assertEqual(anon.post("/api/notifications/1/read", json={}).status_code, 401)
        self.assertEqual(anon.post("/api/notifications/read-all", json={}).status_code, 401)

    def test_list_returns_own_notifications_with_job_data(self):
        self._notify(self.user_a, title="Role for A")
        body = self.client_a.get("/api/notifications").get_json()
        mine = [n for n in body["notifications"] if n["title"] == "Role for A"]
        self.assertTrue(mine)
        self.assertEqual(mine[0]["external_job_id"], self.job_ids["n-2"])
        self.assertEqual(mine[0]["job"]["source_job_id"], "n-2")
        self.assertEqual(mine[0]["job"]["title"], "QA Lead")
        self.assertFalse(mine[0]["is_read"])
        # B never sees A's row
        body_b = self.client_b.get("/api/notifications").get_json()
        self.assertFalse(any(n["title"] == "Role for A" for n in body_b["notifications"]))

    def test_unread_count_and_mark_read(self):
        self._notify(self.user_a, title="Unread counter", job_key="n-4")
        before = self.client_a.get("/api/notifications/unread-count").get_json()["unread"]
        rows = [n for n in self.client_a.get("/api/notifications").get_json()["notifications"]
                if n["title"] == "Unread counter"]
        self.assertTrue(rows)
        notif_id = rows[0]["id"]
        resp = self.client_a.post(f"/api/notifications/{notif_id}/read")
        self.assertEqual(resp.status_code, 200)
        after = resp.get_json()["unread"]
        self.assertEqual(after, before - 1)
        # marking again is idempotent
        self.assertEqual(self.client_a.post(f"/api/notifications/{notif_id}/read").status_code, 200)

    def test_cross_user_access_is_404_and_never_modifies(self):
        self._notify(self.user_a, title="A-only row", job_key="n-3")
        notif_id = None
        for n in self.client_a.get("/api/notifications").get_json()["notifications"]:
            if n["title"] == "A-only row":
                notif_id = n["id"]
        resp = self.client_b.post(f"/api/notifications/{notif_id}/read")
        self.assertEqual(resp.status_code, 404)
        with sqlite3.connect(self.app_module.DB_PATH) as db:
            is_read = db.execute(
                "SELECT is_read FROM notifications WHERE id = ?", (notif_id,)).fetchone()[0]
        self.assertEqual(is_read, 0)  # untouched

    def test_state_changes_require_csrf(self):
        self._notify(self.user_a, title="CSRF target")
        raw = self.app_module.app.test_client()
        raw.post("/api/auth/login", json={"email": self.email_a, "password": "Passw0rd123"})
        notif_id = self.client_a.get("/api/notifications").get_json()["notifications"][0]["id"]
        self.assertEqual(raw.post(f"/api/notifications/{notif_id}/read").status_code, 403)
        self.assertEqual(raw.post("/api/notifications/read-all").status_code, 403)

    def test_mark_all_read_scoped_to_caller(self):
        self._notify(self.user_a, title="Bulk A")
        self._notify(self.user_b, title="Bulk B")
        resp = self.client_a.post("/api/notifications/read-all")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["unread"], 0)
        with sqlite3.connect(self.app_module.DB_PATH) as db:
            a_unread = db.execute(
                "SELECT COUNT(*) FROM notifications WHERE user_id = ? AND is_read = 0",
                (self.user_a,)).fetchone()[0]
            b_unread = db.execute(
                "SELECT COUNT(*) FROM notifications WHERE user_id = ? AND is_read = 0",
                (self.user_b,)).fetchone()[0]
        self.assertEqual(a_unread, 0)
        self.assertGreater(b_unread, 0)  # B untouched

    def test_list_triggers_safe_catchup_matching(self):
        # A has prefs + a cached matching job but no notification yet -> opening
        # the list runs the deduped catch-up scan
        self.client_a.put("/api/job-preferences", json={"keywords": "python dev"})
        body = self.client_a.get("/api/notifications").get_json()
        self.assertTrue(any(n["job"] and n["job"]["title"] == "Python Dev"
                            for n in body["notifications"]))

    def test_no_preferences_means_no_notifications(self):
        client, email = signup_and_login(self.app_module, name="No Pref")
        body = client.get("/api/notifications").get_json()
        self.assertEqual(body["notifications"], [])
        self.assertEqual(body["unread"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
