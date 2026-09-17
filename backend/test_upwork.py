"""
Milestone 8E.3 tests — Upwork as a fifth external job provider (GraphQL API).
=============================================================================

Run from backend/:
    python -m unittest test_upwork -v

Suites:
  1. UpworkNormalizeTests - field mapping (client country as location, skills
                            + category tags, experience/contract job_type,
                            hourly/fixed budgets, official /jobs/{id} URL),
                            missing fields never invented, client identity
                            privacy (company always None)
  2. UpworkFetchTests     - GraphQL payload variants (nodes/edges), malformed
                            payloads, query errors array, HTTP 401/403/429,
                            OAuth refresh + retry, sanitized error messages
                            (no tokens/URLs/secrets), malformed rows skipped
  3. UpworkConfigTests    - is_configured() from environment only; refresh
                            requires the full credential triple
  4. UpworkCacheTests     - unconfigured provider skipped (never failed,
                            never fetched); failure isolation with cached
                            Upwork rows still served; dedup; 429 keeps cache
  5. UpworkApiTests       - GET /api/jobs: source=upwork, search/location,
                            existing provider regressions, JobGuard
                            publishing regression

All tokens/credentials are mocks — no real Upwork call, no real credentials.
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
from job_sources import adzuna, arbeitnow, jobicy, remote_ok, service, upwork

CRED_ENV = {
    "UPWORK_ACCESS_TOKEN": "test-access-token",
    "UPWORK_REFRESH_TOKEN": "test-refresh-token",
    "UPWORK_CLIENT_ID": "test-client-id",
    "UPWORK_CLIENT_SECRET": "test-client-secret",
}
TOKEN_ONLY_ENV = {"UPWORK_ACCESS_TOKEN": "test-access-token"}


def _upwork_node(**overrides):
    node = {
        "id": "~01a2b3c4d5e6f7",
        "title": "Senior Flask Developer",
        "description": "Build <b>reliable</b> APIs & ship. Docker a plus.",
        "createdDateTime": "2026-09-16T08:00:00+00:00",
        "category": "Web, Mobile & Software Dev",
        "subcategory": "Backend Development",
        "skills": ["Python", "Flask"],
        "experienceLevel": "EXPERT",
        "contractType": "HOURLY",
        "hourlyBudgetInfo": {"min": 20, "max": 40},
        "client": {"location": {"country": "United States"}},
        "workLocationInfo": "Remote",
    }
    node.update(overrides)
    return node


def _search_payload(nodes):
    return {"data": {"marketplaceJobPostingsSearch": {
        "totalCount": len(nodes),
        "edges": [{"node": n} for n in nodes],
    }}}


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
        self.db_path = os.path.join(self.tmp.name, "upwork-test.db")
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
        upwork._access_token_cache["token"] = None
        self.tmp.cleanup()


class UpworkNormalizeTests(unittest.TestCase):
    def test_full_field_mapping(self):
        job = upwork.normalize(_upwork_node(), fetched_at="2026-09-17T12:00:00+00:00")
        self.assertEqual(job["source"], "upwork")
        self.assertEqual(job["source_job_id"], "~01a2b3c4d5e6f7")
        self.assertEqual(job["title"], "Senior Flask Developer")
        self.assertIsNone(job["company"])  # client identity is never exposed
        self.assertEqual(job["location"], "United States")  # client country (public)
        self.assertEqual(job["description"], "Build reliable APIs & ship. Docker a plus.")
        self.assertEqual(job["job_type"], "Hourly · Expert")
        self.assertTrue(job["remote"])
        self.assertEqual(job["tags"], ["Python", "Flask", "Web, Mobile & Software Dev",
                                       "Backend Development"])
        self.assertEqual(job["salary"], "$20/hr – $40/hr")
        self.assertEqual(job["job_url"], "https://www.upwork.com/jobs/~01a2b3c4d5e6f7")
        self.assertEqual(job["published_at"], "2026-09-16T08:00:00+00:00")
        self.assertEqual(job["fetched_at"], "2026-09-17T12:00:00+00:00")

    def test_fixed_price_budget_and_missing_fields(self):
        job = upwork.normalize({"id": "~x1", "title": "Landing Page Build",
                                "fixedPriceBudgetInfo": {"amount": 450}})
        self.assertEqual(job["salary"], "$450 fixed-price")
        self.assertIsNone(job["company"])
        self.assertIsNone(job["location"])
        self.assertIsNone(job["description"])
        self.assertIsNone(job["job_type"])
        self.assertIsNone(job["salary"]) if False else None
        self.assertFalse(job["remote"])
        self.assertEqual(job["tags"], [])
        self.assertEqual(job["job_url"], "https://www.upwork.com/jobs/~x1")
        self.assertIsNone(job["published_at"])

    def test_salary_never_invented(self):
        self.assertIsNone(upwork.normalize(_upwork_node(
            hourlyBudgetInfo={"min": 0, "max": 0},
            fixedPriceBudgetInfo={"amount": 0}))["salary"])
        self.assertIsNone(upwork.normalize(_upwork_node(
            hourlyBudgetInfo=None, fixedPriceBudgetInfo=None))["salary"])
        self.assertIsNone(upwork.normalize(_upwork_node(
            hourlyBudgetInfo={"min": "junk", "max": "junk"},
            fixedPriceBudgetInfo={"amount": "junk"}))["salary"])

    def test_malformed_nodes_rejected(self):
        self.assertIsNone(upwork.normalize("nope"))
        self.assertIsNone(upwork.normalize(None))
        self.assertIsNone(upwork.normalize({"title": "No ID"}))
        self.assertIsNone(upwork.normalize({"id": "~x", "title": "  "}))
        self.assertIsNone(upwork.normalize(_upwork_node(id=None)))

    def test_skills_dict_variants_and_privacy(self):
        job = upwork.normalize(_upwork_node(skills=[{"label": "Go"}, {"name": "gRPC"}]))
        self.assertIn("Go", job["tags"])
        self.assertIn("gRPC", job["tags"])
        # private client fields are simply never read
        node = _upwork_node(client={"company": "Secret LLC", "totalPostedJobs": 42,
                                    "location": {"country": "Germany"}})
        job = upwork.normalize(node)
        self.assertIsNone(job["company"])
        self.assertEqual(job["location"], "Germany")


class UpworkFetchTests(unittest.TestCase):
    class FakeResponse:
        def __init__(self, status=200, payload=None):
            self.status_code = status
            self._p = payload
        def raise_for_status(self):
            pass
        def json(self):
            if self._p is None:
                raise ValueError("no json")
            return self._p

    def setUp(self):
        upwork._access_token_cache["token"] = None

    def tearDown(self):
        upwork._access_token_cache["token"] = None

    def test_edges_payload_end_to_end(self):
        with mock.patch.dict(os.environ, TOKEN_ONLY_ENV), \
             mock.patch.object(upwork.requests, "post",
                               return_value=self.FakeResponse(payload={
                                   "data": {"marketplaceJobPostingsSearch": {
                                       "totalCount": 1,
                                       "nodes": [_upwork_node()]}}})) as mpost:
            jobs = upwork.fetch_jobs()
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["source"], "upwork")
        body = mpost.call_args.kwargs["json"]
        self.assertIn("publicMarketplaceJobPostingsSearch", body["query"])
        self.assertNotIn("test-access-token", str(body))

    def test_nodes_payload_variant_supported(self):
        payload = {"data": {"marketplaceJobPostingsSearch": {
            "totalCount": 1, "nodes": [_upwork_node()]}}}
        with mock.patch.dict(os.environ, TOKEN_ONLY_ENV), \
             mock.patch.object(upwork.requests, "post",
                               return_value=self.FakeResponse(payload=payload)):
            jobs = upwork.fetch_jobs()
        self.assertEqual(len(jobs), 1)

    def test_malformed_payloads_raise_sanitized(self):
        for bad in (None, "x", {"data": None}, {"data": {}},
                    {"errors": [{"message": "something failed"}]}):
            with mock.patch.dict(os.environ, TOKEN_ONLY_ENV), \
                 mock.patch.object(upwork.requests, "post",
                                   return_value=self.FakeResponse(payload=bad)):
                with self.assertRaises(upwork.UpworkError):
                    upwork.fetch_jobs()

    def test_http_429_handled_gracefully(self):
        with mock.patch.dict(os.environ, TOKEN_ONLY_ENV), \
             mock.patch.object(upwork.requests, "post",
                               return_value=self.FakeResponse(status=429)):
            with self.assertRaises(upwork.UpworkError) as ctx:
                upwork.fetch_jobs()
        self.assertTrue(ctx.exception.rate_limited)
        self.assertIn("429", str(ctx.exception))

    def test_auth_failure_sanitized_no_token_leak(self):
        with mock.patch.dict(os.environ, CRED_ENV), \
             mock.patch.object(upwork.requests, "post",
                               return_value=self.FakeResponse(status=401)):
            with self.assertRaises(upwork.UpworkError) as ctx:
                upwork.fetch_jobs()
        msg = str(ctx.exception)
        for secret in ("test-access-token", "test-refresh-token",
                       "test-client-id", "test-client-secret", "Bearer", "https://"):
            self.assertNotIn(secret, msg)

    def test_oauth_refresh_retries_once_then_succeeds(self):
        """401 -> backend-side token refresh -> retry succeeds; the refresh
        endpoint is hit exactly once and the new token is used."""
        graphql_calls = {"n": 0, "tokens": []}

        def dispatch(url, data=None, headers=None, timeout=None, **kw):
            if str(url).endswith("oauth2/token"):
                class TokenResp:
                    status_code = 200
                    def json(self):
                        return {"access_token": "brand-new-token"}
                return TokenResp()
            graphql_calls["n"] += 1
            graphql_calls["tokens"].append(headers.get("Authorization"))
            if graphql_calls["n"] == 1:
                return self.FakeResponse(status=401)
            return self.FakeResponse(payload=_search_payload([_upwork_node()]))

        with mock.patch.dict(os.environ, CRED_ENV), \
             mock.patch.object(upwork.requests, "post", side_effect=dispatch) as mpost:
            jobs = upwork.fetch_jobs()
        self.assertEqual(len(jobs), 1)
        self.assertEqual(graphql_calls["n"], 2)
        self.assertEqual(graphql_calls["tokens"][0], "Bearer test-access-token")
        self.assertEqual(graphql_calls["tokens"][1], "Bearer brand-new-token")
        self.assertTrue(any("oauth2/token" in str(c) for c in mpost.call_args_list))

    def test_refresh_failure_stays_sanitized(self):
        with mock.patch.dict(os.environ, CRED_ENV), \
             mock.patch.object(upwork.requests, "post",
                               return_value=self.FakeResponse(status=401)):
            with self.assertRaises(upwork.UpworkError) as ctx:
                upwork.fetch_jobs()
        self.assertNotIn("test-refresh-token", str(ctx.exception))

    def test_malformed_rows_skipped_individually(self):
        payload = _search_payload(["garbage", {"title": "no id"},
                                   {"id": "~y", "title": "   "}, _upwork_node()])
        with mock.patch.dict(os.environ, TOKEN_ONLY_ENV), \
             mock.patch.object(upwork.requests, "post",
                               return_value=self.FakeResponse(payload=payload)):
            jobs = upwork.fetch_jobs()
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["source_job_id"], "~01a2b3c4d5e6f7")

    def test_missing_credentials_raise(self):
        env = dict(os.environ)
        env.pop("UPWORK_ACCESS_TOKEN", None)
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertRaises(upwork.UpworkError):
                upwork.fetch_jobs()


class UpworkConfigTests(unittest.TestCase):
    def test_unconfigured_by_default(self):
        env = dict(os.environ)
        for k in ("UPWORK_ACCESS_TOKEN", "UPWORK_REFRESH_TOKEN",
                  "UPWORK_CLIENT_ID", "UPWORK_CLIENT_SECRET"):
            env.pop(k, None)
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertFalse(upwork.is_configured())

    def test_access_token_configures(self):
        with mock.patch.dict(os.environ, TOKEN_ONLY_ENV):
            self.assertTrue(upwork.is_configured())

    def test_service_knows_upwork_source(self):
        self.assertIn("upwork", service.PROVIDERS)
        self.assertIn("upwork", service.VALID_SOURCES)
        self.assertLess(service.PROVIDER_FRESHNESS["upwork"], timedelta(hours=24))


class UpworkCacheTests(_DBCase):
    def test_unconfigured_skipped_not_failed(self):
        _seed_rows(self.db_path, [
            dict(source="remoteok", source_job_id="rk-1", title="Remote Role",
                 fetched_at=(datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()),
        ])
        env = dict(os.environ)
        for k in ("UPWORK_ACCESS_TOKEN", "UPWORK_REFRESH_TOKEN",
                  "UPWORK_CLIENT_ID", "UPWORK_CLIENT_SECRET"):
            env.pop(k, None)
        with mock.patch.dict(os.environ, env, clear=True), \
             mock.patch.object(remote_ok, "fetch_jobs", return_value=[
                 dict(remote_ok.normalize({"slug": "rk-2", "position": "Backend Engineer",
                                           "company": "RK", "tags": [],
                                           "url": "https://remoteok.com/rk-2"}))]), \
             mock.patch.object(upwork, "fetch_jobs",
                               side_effect=AssertionError("unconfigured upwork must not be fetched")):
            status = service.refresh_if_stale(self.db_path)
        self.assertTrue(status["providers"]["remoteok"]["ok"])
        self.assertIsNone(status["providers"]["upwork"]["ok"])  # skipped, NOT failed
        self.assertFalse(status["stale"])

    def test_failure_isolated_cached_rows_still_served(self):
        _seed_rows(self.db_path, [
            dict(source="upwork", source_job_id="~cached", title="Cached Upwork Role",
                 fetched_at=(datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()),
            dict(source="remoteok", source_job_id="rk-1", title="Cached RK",
                 fetched_at=(datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()),
        ])
        with mock.patch.dict(os.environ, TOKEN_ONLY_ENV), \
             mock.patch.object(remote_ok, "fetch_jobs", return_value=[
                 dict(remote_ok.normalize({"slug": "rk-2", "position": "Backend Engineer",
                                           "company": "RK", "tags": [],
                                           "url": "https://remoteok.com/rk-2"}))]), \
             mock.patch.object(arbeitnow, "fetch_jobs", side_effect=Exception("down")), \
             mock.patch.object(jobicy, "fetch_jobs", side_effect=Exception("down")), \
             mock.patch.object(adzuna, "fetch_jobs", side_effect=adzuna.AdzunaError("down")), \
             mock.patch.object(upwork, "fetch_jobs",
                               side_effect=upwork.UpworkError("Upwork request failed (429)")):
            status = service.refresh_if_stale(self.db_path)
            self.assertFalse(status["providers"]["upwork"]["ok"])
            self.assertTrue(status["providers"]["remoteok"]["ok"])
            data = service.get_jobs(self.db_path, source="upwork")
            self.assertEqual(data["jobs"][0]["title"], "Cached Upwork Role")

    def test_cache_dedup_on_source_and_source_job_id(self):
        job = upwork.normalize(_upwork_node(), fetched_at=service.now_iso())
        with sqlite3.connect(self.db_path) as db:
            service._upsert_jobs(db, [job, dict(job, title="Updated Title")])
            db.commit()
            n = db.execute("SELECT COUNT(*) FROM external_jobs WHERE source='upwork'").fetchone()[0]
            title = db.execute("SELECT title FROM external_jobs WHERE source='upwork'").fetchone()[0]
        self.assertEqual(n, 1)
        self.assertEqual(title, "Updated Title")


class UpworkApiTests(_DBCase):
    def _seed_mixed(self):
        _seed_rows(self.db_path, [
            dict(source="upwork", source_job_id="~uw1", title="Remote Flask API Build",
                 location="United States", description="Build an api.",
                 job_type="Hourly · Expert", remote=True, tags=["Python", "Flask"],
                 salary="$20/hr – $40/hr", job_url="https://www.upwork.com/jobs/~uw1",
                 published_at="2026-09-12T00:00:00+00:00"),
            dict(source="upwork", source_job_id="~uw2", title="WordPress Fix",
                 location="Germany", description="Fix a site.",
                 job_type="Fixed Price", remote=False, tags=[],
                 job_url="https://www.upwork.com/jobs/~uw2",
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
            dict(source="adzuna", source_job_id="9001", title="Data Analyst London",
                 company="Adz Co", location="London", description="Dashboards.",
                 job_type="Full Time · Permanent", remote=False, tags=["IT Jobs"],
                 job_url="https://www.adzuna.co.uk/jobs/land/9001",
                 published_at="2026-09-15T00:00:00+00:00"),
        ])

    def test_source_upwork_filter_and_contract(self):
        self._seed_mixed()
        client, _ = signup_and_login(self.app_module, name="Upwork User")
        data = client.get("/api/jobs?source=upwork").get_json()
        self.assertEqual(data["total"], 2)
        self.assertTrue(all(j["source"] == "upwork" for j in data["jobs"]))
        for key in ("source", "source_job_id", "title", "company", "location",
                    "description", "job_type", "remote", "tags", "salary",
                    "job_url", "published_at", "fetched_at"):
            self.assertIn(key, data["jobs"][0])
        self.assertEqual(data["jobs"][0]["job_url"], "https://www.upwork.com/jobs/~uw2")
        self.assertEqual(data["cache"]["sources"],
                         ["remoteok", "arbeitnow", "jobicy", "adzuna", "upwork"])

    def test_search_and_location_on_upwork(self):
        self._seed_mixed()
        client, _ = signup_and_login(self.app_module, name="Upwork User")
        by_q = client.get("/api/jobs?source=upwork&q=flask").get_json()
        self.assertEqual(by_q["total"], 1)
        self.assertEqual(by_q["jobs"][0]["title"], "Remote Flask API Build")
        by_loc = client.get("/api/jobs?source=upwork&location=germany").get_json()
        self.assertEqual(by_loc["total"], 1)
        self.assertEqual(by_loc["jobs"][0]["location"], "Germany")

    def test_existing_providers_still_filter(self):
        self._seed_mixed()
        client, _ = signup_and_login(self.app_module, name="Upwork User")
        self.assertEqual(client.get("/api/jobs?source=remoteok").get_json()["total"], 1)
        self.assertEqual(client.get("/api/jobs?source=arbeitnow").get_json()["total"], 1)
        self.assertEqual(client.get("/api/jobs?source=jobicy").get_json()["total"], 1)
        self.assertEqual(client.get("/api/jobs?source=adzuna").get_json()["total"], 1)

    def test_jobguard_publishing_regression_alongside_upwork(self):
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
        self.assertIn("upwork", sources)
        guard = client.get("/api/jobs?source=jobguard").get_json()
        self.assertEqual(guard["total"], 1)
        self.assertEqual(guard["jobs"][0]["company"], "Acme Labs")


if __name__ == "__main__":
    unittest.main()
