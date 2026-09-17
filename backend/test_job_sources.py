"""
Milestone 8B.1 tests — Real Job Discovery (providers, cache, API).
==================================================================

Run from backend/:
    python -m unittest test_job_sources -v

Suites:
  1. RemoteOkTests          - normalization of the real payload shape (legal
                              banner skipped, salary formatting, defaults)
  2. ArbeitnowTests         - normalization (slug id, job_types join, unix
                              timestamps, no invented salary)
  3. SafetyTests            - HTML stripped to safe plain text (scripts/styles
                              removed), malformed rows never break ingestion
  4. CacheTests             - DB-backed cache: upsert/dedup on
                              UNIQUE(source, source_job_id), freshness window
                              prevents refetch, stale window triggers it,
                              per-provider failure isolation + stale fallback
  5. JobsApiTests           - authenticated endpoint: 401 anonymous, search,
                              location/source/remote filters, pagination,
                              response contract (jobs/total/page/cache)

All HTTP is mocked (fake response objects — no real network in tests).
Nothing here touches the ML pipeline or the users/predictions behavior.
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
from job_sources import arbeitnow, jobicy, remote_ok, service

INTERNAL_KEYS = {"source", "source_job_id", "title", "company", "location",
                 "description", "job_type", "remote", "tags", "salary",
                 "job_url", "published_at", "fetched_at"}


class FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests as _rq
            raise _rq.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


REMOTEOK_RAW = [
    {"last_updated": 1789585202, "legal": "API Terms: link back to Remote OK"},
    {"slug": "remote-senior-dev-acme-111", "id": "111",
     "date": "2026-09-15T10:00:00+00:00", "position": "Senior Developer",
     "company": "Acme", "location": "", "description": "<p>Build <b>things</b>.</p>",
     "tags": ["python", "web dev"], "job_type": None, "salary_min": "50000",
     "salary_max": "80000", "url": "https://remoteok.com/remote-jobs/remote-senior-dev-acme-111"},
    {"slug": "remote-support-zen-222", "id": "222",
     "date": "2026-09-14T09:00:00+00:00", "position": "Support Agent",
     "company": "Zenly", "location": "Worldwide", "description": "Help users.",
     "tags": [], "job_type": "customer-support", "salary_min": "0", "salary_max": "0",
     "url": "https://remoteok.com/remote-jobs/remote-support-zen-222"},
]

ARBEITNOW_RAW = {"data": [
    {"slug": "backend-engineer-berlin-1", "company_name": "Muster GmbH",
     "title": "Backend Engineer", "description": "<p>Python + <a href='x'>Postgres</a>.</p>",
     "remote": True, "url": "https://www.arbeitnow.com/jobs/muster/backend-engineer-berlin-1",
     "tags": ["python"], "job_types": ["Full Time"], "location": "Berlin",
     "created_at": 1789612812},
    {"slug": "marketing-hamburg-2", "company_name": "Media Haus",
     "title": "Marketing Manager", "description": "Campaigns.",
     "remote": False, "url": "https://www.arbeitnow.com/jobs/media/marketing-hamburg-2",
     "tags": [], "job_types": [], "location": "Hamburg", "created_at": 1789526412},
]}


def _seed_rows(db_path, rows):
    with sqlite3.connect(db_path) as db:
        for r in rows:
            db.execute(
                "INSERT INTO external_jobs (source, source_job_id, title, company, location,"
                " description, job_type, remote, tags_json, salary, job_url, published_at, fetched_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (r["source"], r["source_job_id"], r["title"], r.get("company"),
                 r.get("location"), r.get("description"), r.get("job_type"),
                 1 if r.get("remote") else 0, json.dumps(r.get("tags", [])),
                 r.get("salary"), r.get("job_url"), r.get("published_at"),
                 r.get("fetched_at") or service.now_iso()),
            )
        db.commit()


class RemoteOkTests(unittest.TestCase):
    def test_normalizes_real_shape_and_skips_legal_banner(self):
        jobs = [remote_ok.normalize(e) for e in REMOTEOK_RAW]
        jobs = [j for j in jobs if j]
        self.assertEqual(len(jobs), 2)  # legal banner dropped
        job = jobs[0]
        self.assertEqual(set(job.keys()), INTERNAL_KEYS)
        self.assertEqual(job["source"], "remoteok")
        self.assertEqual(job["title"], "Senior Developer")
        self.assertEqual(job["company"], "Acme")
        self.assertEqual(job["description"], "Build things.")          # HTML stripped
        self.assertEqual(job["salary"], "$50k – $80k")
        self.assertTrue(job["remote"])                                  # board is remote
        self.assertEqual(job["published_at"], "2026-09-15T10:00:00+00:00")
        self.assertIn("remoteok.com/remote-jobs/", job["job_url"])
        self.assertEqual(job["location"], None)                        # '' -> None, never invented
        self.assertEqual(jobs[1]["salary"], None)                      # 0/0 -> no salary

    def test_zero_salary_and_missing_fields_stay_clean(self):
        job = remote_ok.normalize(REMOTEOK_RAW[2])
        self.assertIsNone(job["salary"])
        self.assertEqual(job["tags"], [])
        self.assertEqual(job["location"], "Worldwide")

    def test_fetch_jobs_uses_public_api_and_normalizes(self):
        with mock.patch.object(remote_ok.requests, "get",
                               return_value=FakeResponse(REMOTEOK_RAW)) as mget:
            jobs = remote_ok.fetch_jobs()
        self.assertEqual(len(jobs), 2)
        self.assertIn("remoteok.com/api", mget.call_args.args[0])


class ArbeitnowTests(unittest.TestCase):
    def test_normalizes_real_shape(self):
        jobs = [arbeitnow.normalize(e) for e in ARBEITNOW_RAW["data"]]
        jobs = [j for j in jobs if j]
        self.assertEqual(len(jobs), 2)
        job = jobs[0]
        self.assertEqual(set(job.keys()), INTERNAL_KEYS)
        self.assertEqual(job["source"], "arbeitnow")
        self.assertEqual(job["source_job_id"], "backend-engineer-berlin-1")
        self.assertEqual(job["title"], "Backend Engineer")
        self.assertEqual(job["company"], "Muster GmbH")
        self.assertEqual(job["job_type"], "Full Time")                 # list joined
        self.assertTrue(job["remote"])
        self.assertFalse(jobs[1]["remote"])
        self.assertEqual(job["salary"], None)                          # provider has none
        self.assertTrue(job["published_at"].startswith("2026-"))       # unix -> ISO
        self.assertEqual(job["description"], "Python + Postgres.")

    def test_missing_fields_never_invented(self):
        job = arbeitnow.normalize({"slug": "x-1", "title": "Bare Job"})
        self.assertIsNone(job["company"])
        self.assertIsNone(job["location"])
        self.assertIsNone(job["description"])
        self.assertIsNone(job["job_type"])
        self.assertIsNone(job["job_url"])
        self.assertEqual(job["tags"], [])

    def test_fetch_jobs_uses_public_api(self):
        with mock.patch.object(arbeitnow.requests, "get",
                               return_value=FakeResponse(ARBEITNOW_RAW)) as mget:
            jobs = arbeitnow.fetch_jobs()
        self.assertEqual(len(jobs), 2)
        self.assertIn("arbeitnow.com/api/job-board-api", mget.call_args.args[0])


class SafetyTests(unittest.TestCase):
    def test_html_stripped_to_safe_text(self):
        dirty = "<p>Hello <b>world</b></p><script>alert('xss')</script>" \
                "<style>p{}</style><a href='http://evil'>link</a> tail"
        clean = service.strip_html(dirty)
        self.assertNotIn("<", clean)
        self.assertNotIn("script", clean)
        self.assertNotIn("alert", clean)
        self.assertIn("Hello world", clean)
        self.assertIn("link tail", clean)

    def test_malformed_provider_rows_skipped_not_fatal(self):
        raw = [None, 42, {"position": None}, "junk",
               {"slug": "ok-1", "position": "Fine Job", "company": "C"}]
        jobs = [remote_ok.normalize(e) for e in raw]
        jobs = [j for j in jobs if j]
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["title"], "Fine Job")

    def test_fetch_survives_garbage_payload_rows(self):
        garbage = REMOTEOK_RAW[:1] + [{"slug": None}, {"position": "OK", "slug": "ok-9"}]
        with mock.patch.object(remote_ok.requests, "get", return_value=FakeResponse(garbage)):
            jobs = remote_ok.fetch_jobs()
        self.assertEqual([j["title"] for j in jobs], ["OK"])


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp.name, "jobs-test.db")
        import app
        self.app_module = app
        self.original_db = app.DB_PATH
        app.DB_PATH = self.db_path
        app.init_db()
        # isolate the service's freshness state per test
        self._saved_refresh = dict(service._last_refresh, ok=dict(service._last_refresh["ok"]))
        service._last_refresh = {"at": None, "ok": {n: None for n in service.PROVIDERS}}

    def tearDown(self):
        self.app_module.DB_PATH = self.original_db
        service._last_refresh = self._saved_refresh
        self.tmp.cleanup()

    def test_external_jobs_table_has_uniqueness_rule(self):
        job = remote_ok.normalize(REMOTEOK_RAW[1])
        with sqlite3.connect(self.db_path) as db:
            service._upsert_jobs(db, [job, dict(job, title="Senior Developer II")])
            db.commit()
            n = db.execute("SELECT COUNT(*) FROM external_jobs").fetchone()[0]
            indexes = {row[1] for row in db.execute("PRAGMA index_list(external_jobs)")}
        self.assertEqual(n, 1)  # deduplicated on (source, source_job_id)
        unique_indexes = {i for i in indexes if "sqlite_autoindex" in i or "unique" in i}
        self.assertTrue(any("sqlite_autoindex_external_jobs" in i for i in indexes),
                        f"expected UNIQUE index, saw {indexes}")

    @staticmethod
    def _make_cache_stale(db_path):
        old = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        with sqlite3.connect(db_path) as db:
            db.execute("UPDATE external_jobs SET fetched_at = ?", (old,))
            db.commit()

    def test_providers_refresh_independently_and_fallback_to_cache(self):
        _seed_rows(self.db_path, [dict(source="remoteok", source_job_id="cached-1",
                                       title="Cached Remote Job", tags=[])])
        self._make_cache_stale(self.db_path)  # fresh seed would skip the refresh

        an_job = dict(arbeitnow.normalize(ARBEITNOW_RAW["data"][0]))
        with mock.patch.object(remote_ok, "fetch_jobs",
                               side_effect=Exception("RemoteOK down")), \
             mock.patch.object(arbeitnow, "fetch_jobs",
                               return_value=[an_job]), \
             mock.patch.object(jobicy, "fetch_jobs",
                               side_effect=Exception("Jobicy down")):
            status = service.refresh_if_stale(self.db_path)

        self.assertFalse(status["providers"]["remoteok"]["ok"])
        self.assertTrue(status["providers"]["arbeitnow"]["ok"])
        with sqlite3.connect(self.db_path) as db:
            titles = {r[0] for r in db.execute("SELECT title FROM external_jobs")}
        self.assertIn("Cached Remote Job", titles)     # failed provider keeps cache
        self.assertIn("Backend Engineer", titles)      # healthy provider refreshed

        # both fail -> cached rows served, stale flag set (get_jobs stays
        # inside the mocks: the sandbox has live internet, so an unpatched
        # call would really hit the providers)
        self._make_cache_stale(self.db_path)  # re-stale so the retry really runs
        with mock.patch.object(remote_ok, "fetch_jobs", side_effect=Exception("x")), \
             mock.patch.object(arbeitnow, "fetch_jobs", side_effect=Exception("y")), \
             mock.patch.object(jobicy, "fetch_jobs", side_effect=Exception("z")):
            service._last_refresh = {"at": None, "ok": {n: None for n in service.PROVIDERS}}
            status = service.refresh_if_stale(self.db_path)
            self.assertTrue(status["stale"])
            result = service.get_jobs(self.db_path)
        self.assertTrue(result["cache"]["stale"])
        self.assertGreater(result["total"], 0)

    def test_fresh_cache_not_refetched(self):
        _seed_rows(self.db_path, [dict(source="remoteok", source_job_id="c-1",
                                       title="Cached", tags=[])])
        service.refresh_if_stale(self.db_path)  # marks cache fresh
        with mock.patch.object(remote_ok.requests, "get", side_effect=AssertionError("refetched!")) as m1, \
             mock.patch.object(arbeitnow.requests, "get", side_effect=AssertionError("refetched!")) as m2, \
             mock.patch.object(jobicy.requests, "get", side_effect=AssertionError("refetched!")) as m3:
            service.refresh_if_stale(self.db_path)
            service.get_jobs(self.db_path)
        m1.assert_not_called()
        m2.assert_not_called()
        m3.assert_not_called()

    def test_stale_cache_triggers_refresh(self):
        old = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        _seed_rows(self.db_path, [dict(source="remoteok", source_job_id="old-1",
                                       title="Old Row", tags=[], fetched_at=old)])
        an_job = dict(arbeitnow.normalize(ARBEITNOW_RAW["data"][0]))
        rk_jobs = [j for j in (remote_ok.normalize(e) for e in REMOTEOK_RAW) if j]
        with mock.patch.object(remote_ok, "fetch_jobs", return_value=rk_jobs), \
             mock.patch.object(arbeitnow, "fetch_jobs", return_value=[an_job]), \
             mock.patch.object(jobicy, "fetch_jobs", return_value=[]):
            service.refresh_if_stale(self.db_path)
        with sqlite3.connect(self.db_path) as db:
            n = db.execute("SELECT COUNT(*) FROM external_jobs").fetchone()[0]
        self.assertGreaterEqual(n, 3)  # old row updated/kept + fresh rows added


class JobsApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import app
        cls.app_module = app
        cls.original_db = app.DB_PATH
        cls.tmp = tempfile.TemporaryDirectory()
        app.DB_PATH = os.path.join(cls.tmp.name, "jobs-api-test.db")
        app.init_db()
        cls.client, cls.email = signup_and_login(app, name="Jobs User")

    @classmethod
    def tearDownClass(cls):
        cls.app_module.DB_PATH = cls.original_db
        cls.tmp.cleanup()

    def test_anonymous_gets_401(self):
        anon = self.app_module.app.test_client()
        resp = anon.get("/api/jobs")
        self.assertEqual(resp.status_code, 401)

    def test_contract_and_pagination(self):
        with sqlite3.connect(self.app_module.DB_PATH) as db:
            db.execute("DELETE FROM external_jobs")
            for i in range(25):
                db.execute(
                    "INSERT INTO external_jobs (source, source_job_id, title, company, location,"
                    " description, job_type, remote, tags_json, salary, job_url, published_at, fetched_at)"
                    " VALUES ('remoteok', ?, ?, 'C', 'Berlin', 'desc', NULL, 1, '[]', NULL,"
                    " 'https://remoteok.com/x', ?, ?)",
                    (f"job-{i}", f"Job {i}", f"2026-09-{(i % 28) + 1:02d}T00:00:00+00:00",
                     service.now_iso()),
                )
            db.commit()
        data = self.client.get("/api/jobs?page=2").get_json()
        self.assertEqual(data["page"], 2)
        self.assertEqual(data["total"], 25)
        self.assertEqual(data["pages"], 2)
        self.assertEqual(data["cache"]["sources"], ["remoteok", "arbeitnow", "jobicy"])
        self.assertEqual(len(data["jobs"]), 5)
        self.assertIn("cache", data)
        job = data["jobs"][0]
        for key in ["source", "source_job_id", "title", "company", "job_url", "tags"]:
            self.assertIn(key, job)

    def test_search_and_filters(self):
        with sqlite3.connect(self.app_module.DB_PATH) as db:
            db.execute("DELETE FROM external_jobs")
            db.commit()
        _seed_rows(self.app_module.DB_PATH, [
            dict(source="remoteok", source_job_id="s-1", title="Python Developer",
                 company="Acme", location="Remote", description="flask api work",
                 tags=["python"], remote=True),
            dict(source="arbeitnow", source_job_id="s-2", title="Data Analyst",
                 company="Beta", location="München", description="sql dashboards",
                 tags=[], remote=False),
            dict(source="arbeitnow", source_job_id="s-3", title="DevOps Engineer",
                 company="Gamma", location="Remote", description="kubernetes",
                 tags=["devops"], remote=True),
        ])
        # q across title/description/tags
        titles = lambda d: [j["title"] for j in d["jobs"]]
        r = self.client.get("/api/jobs?q=flask").get_json()
        self.assertEqual(titles(r), ["Python Developer"])
        # location filter
        r = self.client.get("/api/jobs?location=münchen").get_json()
        self.assertEqual(titles(r), ["Data Analyst"])
        # source filter
        r = self.client.get("/api/jobs?source=arbeitnow").get_json()
        self.assertEqual(set(titles(r)), {"Data Analyst", "DevOps Engineer"})
        # remote filter
        r = self.client.get("/api/jobs?remote=true").get_json()
        self.assertIn("Python Developer", titles(r))
        self.assertNotIn("Data Analyst", titles(r))
        # response carries normalized jobs only — no raw provider envelope
        sample = self.client.get("/api/jobs?q=flask").get_json()
        self.assertNotIn("data", sample)
        self.assertTrue(all("data" not in job and "attributes" not in job for job in sample["jobs"]))


if __name__ == "__main__":
    unittest.main()
