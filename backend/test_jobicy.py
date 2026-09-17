"""
Milestone 8E.1 tests — Jobicy as a third external job provider.
==============================================================

Run from backend/:
    python -m unittest test_jobicy -v

Suites:
  1. JobicyNormalizeTests  - field mapping into the common job shape,
                             missing fields stay None/[] (never invented),
                             HTML stripping (script/style dropped, entities
                             converted), original URL preserved, salary
                             formatting from the provider's own numbers
  2. JobicyFetchTests      - malformed payload shapes raise (board skipped),
                             malformed rows skipped one-by-one, live-shaped
                             payload normalizes end-to-end
  3. JobicyCacheTests      - DB-backed cache: Jobicy rows cached + deduped on
                             UNIQUE(source, source_job_id); per-provider
                             freshness (60-minute Jobicy window, Remote OK /
                             Arbeitnow keep 20 min; a fresh provider is never
                             re-fetched); Jobicy failure isolation with
                             cached Jobicy rows still served
  4. JobicyApiTests        - GET /api/jobs: source=jobicy filter, search +
                             location filtering, pagination contract,
                             original URL in the response, and JobGuard /
                             Remote OK / Arbeitnow regressions in the merged
                             feed

No test performs real network calls (requests are mocked; the one live
Jobicy check is performed outside the suite).
"""

import json
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from unittest import mock

from auth_test_utils import signup_and_login
from job_sources import arbeitnow, jobicy, remote_ok, service


def _jobicy_element(**overrides):
    """A realistic Jobicy payload element (mirrors the live API shape)."""
    element = {
        "id": 153489,
        "url": "https://jobicy.com/jobs/153489-infrastructure-software-engineer-metadata-core",
        "jobSlug": "153489-infrastructure-software-engineer-metadata-core",
        "jobTitle": "Infrastructure Software Engineer, Metadata Core",
        "companyName": "Dropbox",
        "jobIndustry": ["Software Engineering"],
        "jobType": ["Full-Time"],
        "jobGeo": "Poland",
        "jobLevel": "Any",
        "jobExcerpt": "Role Description As a Software Engineer on the Metadata team…",
        "jobDescription": "<h3>Role Description</h3><p>Build large-scale databases.</p>",
        "pubDate": "2026-09-17T06:50:36+00:00",
        "salaryMin": 272000,
        "salaryMax": 368000,
        "salaryCurrency": "PLN",
        "salaryPeriod": "yearly",
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
        self.db_path = os.path.join(self.tmp.name, "jobicy-test.db")
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


class JobicyNormalizeTests(unittest.TestCase):
    def test_full_field_mapping(self):
        job = jobicy.normalize(_jobicy_element(), fetched_at="2026-09-17T12:00:00+00:00")
        self.assertEqual(job["source"], "jobicy")
        self.assertEqual(job["source_job_id"], "153489")
        self.assertEqual(job["title"], "Infrastructure Software Engineer, Metadata Core")
        self.assertEqual(job["company"], "Dropbox")
        self.assertEqual(job["location"], "Poland")
        self.assertEqual(job["job_type"], "Full-Time")
        self.assertTrue(job["remote"])  # the remote-jobs endpoint is all-remote
        self.assertEqual(job["tags"], ["Software Engineering"])
        self.assertEqual(job["job_url"],
                         "https://jobicy.com/jobs/153489-infrastructure-software-engineer-metadata-core")
        self.assertEqual(job["published_at"], "2026-09-17T06:50:36+00:00")
        self.assertEqual(job["fetched_at"], "2026-09-17T12:00:00+00:00")
        self.assertEqual(job["salary"], "PLN272k – PLN368k")
        self.assertNotIn("<", job["description"])
        self.assertIn("Build large-scale databases.", job["description"])

    def test_missing_fields_are_never_invented(self):
        job = jobicy.normalize({"id": 7, "jobTitle": "Minimal Role", "url": "https://jobicy.com/jobs/7-x"})
        self.assertIsNone(job["company"])
        self.assertIsNone(job["location"])
        self.assertIsNone(job["job_type"])
        self.assertIsNone(job["description"])
        self.assertIsNone(job["salary"])
        self.assertIsNone(job["published_at"])
        self.assertEqual(job["tags"], [])
        self.assertTrue(job["remote"])

    def test_html_stripped_including_script_style_and_entities(self):
        dirty = ("<h3>Role</h3><script>alert(1)</script><style>.x{}</style>"
                 "<p>Build &amp; ship <b>fast</b>.</p><img src=x onerror=alert(2)>")
        job = jobicy.normalize(_jobicy_element(jobDescription=dirty))
        desc = job["description"]
        self.assertNotIn("alert(1)", desc)
        self.assertNotIn("alert(2)", desc)
        self.assertNotIn("<h3>", desc)
        self.assertNotIn("<p>", desc)
        self.assertIn("Role", desc)
        self.assertIn("Build & ship fast.", desc)

    def test_excerpt_fallback_when_description_missing(self):
        job = jobicy.normalize(_jobicy_element(jobDescription=None,
                                               jobExcerpt="Short plain teaser"))
        self.assertEqual(job["description"], "Short plain teaser")

    def test_salary_needs_provider_numbers(self):
        self.assertIsNone(jobicy.normalize(_jobicy_element()).pop("salary") is None and None or
                          jobicy.normalize(_jobicy_element(salaryMin=None, salaryMax=None))["salary"])
        self.assertIsNone(jobicy.normalize(_jobicy_element(salaryMin="abc", salaryMax="def"))["salary"])
        self.assertIsNone(jobicy.normalize(_jobicy_element(salaryMin=0, salaryMax=0))["salary"])
        single = jobicy.normalize(_jobicy_element(salaryMin=90000, salaryMax=None,
                                                  salaryCurrency="USD", salaryPeriod="yearly"))
        self.assertEqual(single["salary"], "$90k")
        non_yearly = jobicy.normalize(_jobicy_element(salaryMin=40, salaryMax=60,
                                                      salaryCurrency="EUR", salaryPeriod="hourly"))
        self.assertEqual(non_yearly["salary"], "€40 – €60 (hourly)")

    def test_job_type_joined_from_list_and_rows_rejected_without_title_or_id(self):
        multi = jobicy.normalize(_jobicy_element(jobType=["Full-Time", "Part-Time"]))
        self.assertEqual(multi["job_type"], "Full-Time · Part-Time")
        self.assertIsNone(jobicy.normalize({"url": "https://jobicy.com/x"}))       # no title
        self.assertIsNone(jobicy.normalize({"jobTitle": "No ID"}))                  # no id
        self.assertIsNone(jobicy.normalize("not a dict"))
        self.assertIsNone(jobicy.normalize(None))


class JobicyFetchTests(unittest.TestCase):
    class FakeResponse:
        def __init__(self, payload):
            self._p = payload
        def raise_for_status(self):
            pass
        def json(self):
            return self._p

    def test_malformed_payload_shapes_raise_board_skipped(self):
        for bad in (None, [1, 2, 3], {"jobs": "nope"}, {}, {"data": []}):
            with mock.patch.object(jobicy.requests, "get",
                                   return_value=self.FakeResponse(bad)):
                with self.assertRaises((ValueError, AttributeError)):
                    jobicy.fetch_jobs()

    def test_malformed_rows_skipped_individually(self):
        payload = {"jobs": [
            "garbage",
            {"id": 1, "jobTitle": "  ", "url": "x"},          # blank title -> skipped
            {"jobTitle": "No ID Role", "url": "x"},            # missing id -> skipped
            _jobicy_element(),                                  # valid
        ]}
        with mock.patch.object(jobicy.requests, "get",
                               return_value=self.FakeResponse(payload)):
            jobs = jobicy.fetch_jobs()
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["source_job_id"], "153489")

    def test_network_error_propagates_for_isolation_layer(self):
        with mock.patch.object(jobicy.requests, "get",
                               side_effect=Exception("Jobicy unreachable")):
            with self.assertRaises(Exception):
                jobicy.fetch_jobs()

    def test_original_url_preserved_verbatim(self):
        url = "https://jobicy.com/jobs/153489-infrastructure-software-engineer-metadata-core"
        job = jobicy.normalize(_jobicy_element(url=url))
        self.assertEqual(job["job_url"], url)


class JobicyCacheTests(_DBCase):
    def test_jobicy_rows_cached_and_deduplicated(self):
        job = jobicy.normalize(_jobicy_element(), fetched_at=service.now_iso())
        with sqlite3.connect(self.db_path) as db:
            service._upsert_jobs(db, [job, dict(job, title="Updated Title")])
            db.commit()
            n = db.execute("SELECT COUNT(*) FROM external_jobs WHERE source='jobicy'").fetchone()[0]
            title = db.execute("SELECT title FROM external_jobs WHERE source='jobicy'").fetchone()[0]
        self.assertEqual(n, 1)  # UNIQUE(source, source_job_id)
        self.assertEqual(title, "Updated Title")

    def test_fresh_jobicy_not_refetched_within_its_window(self):
        recent = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
        _seed_rows(self.db_path, [
            dict(source="jobicy", source_job_id="jcy-1", title="Fresh Jobicy", fetched_at=recent),
            dict(source="remoteok", source_job_id="rk-old", title="Old RK",
                 fetched_at=(datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()),
        ])
        with mock.patch.object(remote_ok, "fetch_jobs", return_value=[]), \
             mock.patch.object(arbeitnow, "fetch_jobs", return_value=[]), \
             mock.patch.object(jobicy, "fetch_jobs",
                               side_effect=AssertionError("jobicy refetched inside 60-min window")):
            service.refresh_if_stale(self.db_path)  # remoteok stale -> fetched; jobicy 30min < 60min -> skipped

    def test_jobicy_refetched_after_its_hour_regardless_of_siblings(self):
        hour_ago = (datetime.now(timezone.utc) - timedelta(minutes=61)).isoformat()
        fresh = service.now_iso()
        _seed_rows(self.db_path, [
            dict(source="jobicy", source_job_id="jcy-1", title="Old Jobicy", fetched_at=hour_ago),
            dict(source="remoteok", source_job_id="rk-new", title="Fresh RK", fetched_at=fresh),
        ])
        calls = {"jobicy": 0, "remoteok": 0}
        def _count(name):
            def _f():
                calls[name] += 1
                return []
            return _f
        with mock.patch.object(remote_ok, "fetch_jobs", side_effect=_count("remoteok")), \
             mock.patch.object(arbeitnow, "fetch_jobs", side_effect=_count("arbeitnow")), \
             mock.patch.object(jobicy, "fetch_jobs", side_effect=_count("jobicy")):
            service.refresh_if_stale(self.db_path)
        self.assertEqual(calls["jobicy"], 1)     # 61 min >= its 60-min window
        self.assertEqual(calls["remoteok"], 0)   # fresh sibling untouched

    def test_jobicy_failure_isolated_cached_rows_still_served(self):
        _seed_rows(self.db_path, [
            dict(source="jobicy", source_job_id="jcy-1", title="Cached Jobicy Role",
                 fetched_at=(datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()),
        ])
        with mock.patch.object(remote_ok, "fetch_jobs", return_value=[
            dict(remote_ok.normalize({"slug": "rk-1", "position": "Backend Engineer",
                                      "company": "RK Co", "tags": [],
                                      "url": "https://remoteok.com/rk-1"}))]), \
             mock.patch.object(arbeitnow, "fetch_jobs", return_value=[
            dict(arbeitnow.normalize(ARBEITNOW_ROW))]), \
             mock.patch.object(jobicy, "fetch_jobs", side_effect=Exception("Jobicy down")):
            status = service.refresh_if_stale(self.db_path)
            self.assertFalse(status["providers"]["jobicy"]["ok"])
            self.assertTrue(status["providers"]["remoteok"]["ok"])
            self.assertTrue(status["providers"]["arbeitnow"]["ok"])
            # serve from cache INSIDE the mocks — no real network in tests
            data = service.get_jobs(self.db_path, source="jobicy")
            titles = {j["title"] for j in data["jobs"]}
            self.assertIn("Cached Jobicy Role", titles)      # cached jobicy served
            all_data = service.get_jobs(self.db_path)
            all_titles = {j["title"] for j in all_data["jobs"]}
            self.assertIn("Backend Engineer", titles | all_titles)   # remoteok still works
            self.assertIn("DevOps Engineer", titles | all_titles)    # arbeitnow still works
            self.assertIn("Backend Engineer", all_titles)
            self.assertIn("DevOps Engineer", all_titles)


ARBEITNOW_ROW = {"slug": "an-1", "title": "DevOps Engineer", "company_name": "AN Co",
                 "location": "Berlin", "description": "Kubernetes role.",
                 "job_types": ["Full-Time"], "tags": [], "url": "https://www.arbeitnow.com/an-1",
                 "created_at": 1757500000}


class JobicyApiTests(_DBCase):
    @classmethod
    def setUpClass(cls):
        pass

    def _client(self):
        client, _ = signup_and_login(self.app_module, name="Jobicy User")
        return client

    def _seed_mixed(self):
        _seed_rows(self.db_path, [
            dict(source="jobicy", source_job_id="101", title="Remote Python Engineer",
                 company="Jcy Co", location="Poland", description="Build apis.",
                 job_type="Full-Time", remote=True, tags=["python"],
                 salary="$90k – $120k",
                 job_url="https://jobicy.com/jobs/101-remote-python-engineer",
                 published_at="2026-09-12T00:00:00+00:00"),
            dict(source="jobicy", source_job_id="102", title="Designer in München",
                 company="Jcy Design", location="Germany", description="Make ui.",
                 job_type="Contract", remote=True, tags=[],
                 job_url="https://jobicy.com/jobs/102-designer",
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
        ])

    def test_source_jobicy_filter_and_contract(self):
        self._seed_mixed()
        data = self._client().get("/api/jobs?source=jobicy").get_json()
        self.assertEqual(data["total"], 2)
        self.assertTrue(all(j["source"] == "jobicy" for j in data["jobs"]))
        for key in ("source", "source_job_id", "title", "company", "location",
                    "description", "job_type", "remote", "tags", "salary",
                    "job_url", "published_at", "fetched_at"):
            self.assertIn(key, data["jobs"][0])
        top = data["jobs"][0]
        self.assertEqual(top["job_url"], "https://jobicy.com/jobs/102-designer")  # newest first
        self.assertEqual(data["cache"]["sources"], ["remoteok", "arbeitnow", "jobicy"])

    def test_existing_sources_still_filter(self):
        self._seed_mixed()
        client = self._client()
        rk = client.get("/api/jobs?source=remoteok").get_json()
        self.assertEqual(rk["total"], 1)
        self.assertEqual(rk["jobs"][0]["source"], "remoteok")
        an = client.get("/api/jobs?source=arbeitnow").get_json()
        self.assertEqual(an["total"], 1)
        self.assertEqual(an["jobs"][0]["source"], "arbeitnow")

    def test_jobicy_search_and_location_filters(self):
        self._seed_mixed()
        client = self._client()
        by_q = client.get("/api/jobs?source=jobicy&q=python").get_json()
        self.assertEqual(by_q["total"], 1)
        self.assertEqual(by_q["jobs"][0]["title"], "Remote Python Engineer")
        by_loc = client.get("/api/jobs?source=jobicy&location=poland").get_json()
        self.assertEqual(by_loc["total"], 1)
        self.assertEqual(by_loc["jobs"][0]["location"], "Poland")
        # cross-source search still spans every provider
        remote_only = client.get("/api/jobs?remote=true&q=remote").get_json()
        self.assertGreaterEqual(remote_only["total"], 2)

    def test_jobguard_listing_regression_alongside_jobicy(self):
        """JobGuard employer publishing semantics unchanged: a published job
        still appears in the merged feed next to Jobicy/RemoteOK/Arbeitnow."""
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
        self.assertIn("jobicy", sources)
        guard = client.get("/api/jobs?source=jobguard").get_json()
        self.assertEqual(guard["total"], 1)
        self.assertEqual(guard["jobs"][0]["company"], "Acme Labs")  # from profile


if __name__ == "__main__":
    unittest.main()
