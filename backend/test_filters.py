"""
Milestone 8E.4 tests — unified Category / Work Mode / Job Type filters.
=======================================================================

Run from backend/:
    python -m unittest test_filters -v

Suites:
  1. CategoryRuleTests     - deterministic keyword mapping for every
                             category, field priority (title > provider
                             category > tags > description), unknown -> Other
  2. WorkModeRuleTests     - explicit signals only; unknown stays None and
                             never masquerades as remote/onsite/hybrid
  3. JobTypeRuleTests      - provider strings -> canonical set; Upwork is
                             freelance; junk -> other; silence -> None
  4. EnrichmentTests       - service-layer enrichment + pre-8E.4 database
                             migration/backfill (idempotent)
  5. FilterQueryTests      - get_jobs AND combinations, source+category,
                             location+work_mode, unknown-mode visibility,
                             pagination after filtering, legacy remote=true
  6. FiltersApiTests       - authenticated /api/jobs with the new params,
                             16-key contract, JobGuard published listings,
                             six-source regression

All HTTP is mocked or avoided (seeded rows carry a fresh fetched_at, so the
refresh window never triggers a live provider call). Nothing here touches
the ML pipeline; the notification matcher is only exercised through the
existing regression suites.
"""

import os
import sqlite3
import tempfile
import unittest

from auth_test_utils import signup_and_login
from job_sources import service
from job_sources.classify import (classify_category, classify_fields,
                                  classify_job_type, classify_work_mode,
                                  enrich_job)

NEW_KEYS = {"category", "work_mode", "normalized_job_type"}


# ---------------------------------------------------------------------------
# 1 — category rules
# ---------------------------------------------------------------------------
class CategoryRuleTests(unittest.TestCase):
    def test_frontend_keywords(self):
        for title in ("Senior React Developer", "UI Developer",
                      "Front-end Engineer", "Vue.js Web Developer"):
            self.assertEqual(classify_category(title=title), "frontend", title)

    def test_backend_keywords(self):
        for title in ("Django Developer", "Flask API Engineer",
                      "Backend Developer", "REST API Developer"):
            self.assertEqual(classify_category(title=title), "backend", title)

    def test_full_stack_beats_frontend_on_tie(self):
        # Both match the title equally; the earlier (more specific) rule wins.
        self.assertEqual(classify_category(title="Full Stack React Developer"),
                         "full_stack")

    def test_mobile_keywords(self):
        for title in ("Flutter Developer", "Android Engineer",
                      "iOS Developer", "React Native Developer"):
            self.assertEqual(classify_category(title=title), "mobile", title)

    def test_ai_ml_keywords(self):
        for title in ("Machine Learning Engineer", "NLP Engineer",
                      "AI Researcher", "Deep Learning Scientist"):
            self.assertEqual(classify_category(title=title), "ai_ml", title)

    def test_data_science_keywords(self):
        for title in ("Data Scientist", "Data Analyst", "BI Analyst"):
            self.assertEqual(classify_category(title=title), "data_science", title)

    def test_cyber_security_keywords(self):
        for title in ("Penetration Tester", "Security Analyst",
                      "Cyber Security Engineer", "SOC Analyst"):
            self.assertEqual(classify_category(title=title), "cyber_security", title)

    def test_devops_cloud_keywords(self):
        for title in ("DevOps Engineer", "Kubernetes Administrator",
                      "AWS Cloud Engineer", "Site Reliability Engineer"):
            self.assertEqual(classify_category(title=title), "devops_cloud", title)

    def test_ui_ux_keywords(self):
        for title in ("UX Designer", "UI/UX Designer", "Product Designer",
                      "UX Researcher"):
            self.assertEqual(classify_category(title=title), "ui_ux", title)

    def test_graphic_design_keywords(self):
        for title in ("Graphic Designer", "Photoshop Specialist",
                      "Logo Designer"):
            self.assertEqual(classify_category(title=title), "graphic_design", title)

    def test_business_categories(self):
        cases = {
            "SEO Specialist": "marketing",
            "Digital Marketing Manager": "marketing",
            "Sales Representative": "sales",
            "Accountant": "finance_accounting",
            "Payroll Officer": "finance_accounting",
            "Customer Support Agent": "customer_support",
            "Help Desk Technician": "customer_support",
            "Technical Recruiter": "human_resources",
            "HR Operations Specialist": "human_resources",
        }
        for title, expected in cases.items():
            self.assertEqual(classify_category(title=title), expected, title)

    def test_unknown_becomes_other(self):
        self.assertEqual(classify_category(title="Barista"), "other")
        self.assertEqual(classify_category(title="Warehouse Picker"), "other")
        self.assertEqual(classify_category(), "other")

    def test_field_priority_title_beats_description(self):
        self.assertEqual(
            classify_category(title="Sales Manager",
                              description="You will build Python APIs."),
            "sales")

    def test_tags_and_provider_category_contribute(self):
        self.assertEqual(classify_category(title="Developer", tags=["react"]),
                         "frontend")
        self.assertEqual(classify_category(title="Specialist",
                                           provider_category="Sales Jobs"),
                         "sales")
        # description alone is the weakest signal but still decides when
        # nothing else matches
        self.assertEqual(classify_category(description="Kubernetes cluster work"),
                         "devops_cloud")


# ---------------------------------------------------------------------------
# 2 — work mode rules
# ---------------------------------------------------------------------------
class WorkModeRuleTests(unittest.TestCase):
    def test_remote_flag_is_authoritative(self):
        self.assertEqual(classify_work_mode(remote=True, title="Cook"), "remote")

    def test_explicit_title_wording(self):
        self.assertEqual(classify_work_mode(title="Designer (Remote)"), "remote")
        self.assertEqual(classify_work_mode(title="Work from home writer"),
                         "remote")

    def test_explicit_hybrid_and_onsite(self):
        self.assertEqual(classify_work_mode(title="Hybrid Product Manager"),
                         "hybrid")
        self.assertEqual(classify_work_mode(title="On-site Supervisor"),
                         "onsite")
        self.assertEqual(classify_work_mode(title="Onsite Supervisor"),
                         "onsite")

    def test_hybrid_wins_over_remote_mention(self):
        self.assertEqual(classify_work_mode(title="Hybrid remote role"),
                         "hybrid")

    def test_remote_false_is_unknown_not_onsite(self):
        self.assertIsNone(classify_work_mode(remote=False, title="Accountant"))

    def test_no_signal_stays_unknown(self):
        self.assertIsNone(classify_work_mode(title="Accountant", tags=[]))
        self.assertIsNone(classify_work_mode())
        self.assertEqual(classify_work_mode(tags=["Remote"]), "remote")


# ---------------------------------------------------------------------------
# 3 — job type rules
# ---------------------------------------------------------------------------
class JobTypeRuleTests(unittest.TestCase):
    def test_full_time_variants(self):
        for raw in ("Full Time", "full_time", "Permanent · Full-time",
                    "permanent", "Full-Time"):
            self.assertEqual(classify_job_type(raw_type=raw), "full_time", raw)

    def test_part_time_variants(self):
        for raw in ("part-time", "Part Time", "parttime"):
            self.assertEqual(classify_job_type(raw_type=raw), "part_time", raw)

    def test_contract_variants(self):
        for raw in ("Contract", "contractor", "C2C contract"):
            self.assertEqual(classify_job_type(raw_type=raw), "contract", raw)

    def test_freelance_temporary_internship(self):
        self.assertEqual(classify_job_type(raw_type="freelance"), "freelance")
        self.assertEqual(classify_job_type(raw_type="Temporary"), "temporary")
        self.assertEqual(classify_job_type(raw_type="Internship"), "internship")

    def test_unmappable_string_is_other(self):
        self.assertEqual(classify_job_type(raw_type="Volunteer"), "other")

    def test_silence_stays_unknown(self):
        self.assertIsNone(classify_job_type(raw_type=None, title=None))
        self.assertIsNone(classify_job_type(raw_type=None, title="Barista"))

    def test_title_fallback(self):
        self.assertEqual(classify_job_type(raw_type=None, title="Marketing Intern"),
                         "internship")
        self.assertEqual(classify_job_type(raw_type=None, title="Part-time Barista"),
                         "part_time")

    def test_upwork_is_always_freelance(self):
        self.assertEqual(classify_job_type(raw_type="Hourly · Expert",
                                           source="upwork"), "freelance")
        self.assertEqual(classify_job_type(raw_type="Fixed Price",
                                           source="upwork"), "freelance")
        self.assertEqual(classify_job_type(raw_type=None, source="upwork"),
                         "freelance")

    def test_internship_before_part_time(self):
        self.assertEqual(classify_job_type(raw_type="Internship (part-time)"),
                         "internship")

    def test_classify_fields_bundle(self):
        category, mode, jtype = classify_fields(
            title="Remote Django Developer", job_type="Full Time", remote=True)
        self.assertEqual((category, mode, jtype),
                         ("backend", "remote", "full_time"))


# ---------------------------------------------------------------------------
# 4 — enrichment + migration
# ---------------------------------------------------------------------------
class _DBCase(unittest.TestCase):
    """Shared fixture: temp DB + swapped app.DB_PATH (mirrors 8E.x tests)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp.name, "filters-test.db")
        import app
        self.app_module = app
        self.original_db = app.DB_PATH
        app.DB_PATH = self.db_path
        app.init_db()
        self._saved_refresh = dict(service._last_refresh,
                                   ok=dict(service._last_refresh["ok"]))
        service._last_refresh = {"at": None,
                                 "ok": {n: None for n in service.PROVIDERS}}

    def tearDown(self):
        self.app_module.DB_PATH = self.original_db
        service._last_refresh = self._saved_refresh
        self.tmp.cleanup()


class EnrichmentTests(_DBCase):
    def test_enrich_job_adds_three_fields_and_preserves_existing(self):
        job = {
            "source": "remoteok", "source_job_id": "rk-1",
            "title": "Senior React Developer", "company": "Acme",
            "location": "Worldwide", "description": "Build interfaces.",
            "job_type": "full_time", "remote": True, "tags": ["react"],
            "salary": None, "job_url": "https://remoteok.com/rk-1",
            "published_at": "2026-09-16T00:00:00+00:00",
            "fetched_at": service.now_iso(),
        }
        enriched = enrich_job(job)
        self.assertEqual(len(enriched), 16)
        self.assertTrue(NEW_KEYS <= set(enriched))
        self.assertEqual(enriched["category"], "frontend")
        self.assertEqual(enriched["work_mode"], "remote")
        self.assertEqual(enriched["normalized_job_type"], "full_time")
        # original untouched
        self.assertNotIn("category", job)

    def test_upsert_persists_classification_columns(self):
        job = {
            "source": "upwork", "source_job_id": "~uw1",
            "title": "WordPress Speed Fix", "company": None,
            "location": "Germany", "description": "Make my site fast.",
            "job_type": "Fixed Price", "remote": False, "tags": [],
            "salary": None, "job_url": "https://www.upwork.com/jobs/~uw1",
            "published_at": "2026-09-16T00:00:00+00:00",
            "fetched_at": service.now_iso(),
        }
        with sqlite3.connect(self.db_path) as db:
            service._upsert_jobs(db, [job])
            db.commit()
            row = db.execute(
                "SELECT category, work_mode, normalized_job_type FROM external_jobs"
                " WHERE source='upwork'").fetchone()
        self.assertEqual(row[0], "backend")     # wordpress is in the backend rules
        self.assertIsNone(row[1])               # conservative: no invented mode
        self.assertEqual(row[2], "freelance")   # upwork rule

    def test_migration_backfills_pre_8e4_database(self):
        old_db = os.path.join(self.tmp.name, "old.db")
        with sqlite3.connect(old_db) as db:
            db.execute("""
                CREATE TABLE external_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source TEXT NOT NULL, source_job_id TEXT NOT NULL,
                    title TEXT NOT NULL, company TEXT, location TEXT,
                    description TEXT, job_type TEXT,
                    remote INTEGER NOT NULL DEFAULT 0, tags_json TEXT,
                    salary TEXT, job_url TEXT, published_at TEXT,
                    fetched_at TEXT NOT NULL,
                    UNIQUE(source, source_job_id)
                )
            """)
            db.execute(
                "INSERT INTO external_jobs (source, source_job_id, title,"
                " description, job_type, remote, tags_json, fetched_at)"
                " VALUES ('remoteok','rk-1','Remote React Developer','UI work',"
                "'full_time',1,'[]','2026-09-16T00:00:00+00:00')")
            db.execute(
                "INSERT INTO external_jobs (source, source_job_id, title,"
                " description, job_type, remote, tags_json, fetched_at)"
                " VALUES ('arbeitnow','an-1','Mystery Role','Unspecified work',"
                "'',0,'[]','2026-09-16T00:00:00+00:00')")
            db.commit()

        service.ensure_classification_columns(old_db)

        with sqlite3.connect(old_db) as db:
            cols = {r[1] for r in db.execute("PRAGMA table_info(external_jobs)")}
            self.assertTrue(NEW_KEYS <= cols)
            rows = db.execute(
                "SELECT source, category, work_mode, normalized_job_type"
                " FROM external_jobs ORDER BY id").fetchall()
        self.assertEqual(rows[0], ("remoteok", "frontend", "remote", "full_time"))
        self.assertEqual(rows[1], ("arbeitnow", "other", None, None))
        # idempotent: a second run changes nothing and does not raise
        service.ensure_classification_columns(old_db)
        with sqlite3.connect(old_db) as db:
            n = db.execute("SELECT COUNT(*) FROM external_jobs").fetchone()[0]
        self.assertEqual(n, 2)


# ---------------------------------------------------------------------------
# 5 — get_jobs filter combinations
# ---------------------------------------------------------------------------
def _seed_rows(db_path, rows):
    """Deterministic seed with EXPLICIT filter values (no classifier drift)."""
    import json
    with sqlite3.connect(db_path) as db:
        for r in rows:
            db.execute(
                "INSERT INTO external_jobs (source, source_job_id, title, company,"
                " location, description, job_type, remote, tags_json, salary,"
                " job_url, published_at, fetched_at, category, work_mode,"
                " normalized_job_type)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (r["source"], r["source_job_id"], r["title"], r.get("company"),
                 r.get("location"), r.get("description"), r.get("job_type"),
                 1 if r.get("remote") else 0,
                 json.dumps(r.get("tags", [])), r.get("salary"),
                 r.get("job_url"), r.get("published_at"),
                 r.get("fetched_at") or service.now_iso(),
                 r.get("category"), r.get("work_mode"),
                 r.get("normalized_job_type")),
            )
        db.commit()


BASE = "2026-09-16T00:00:00+00:00"


def _mixed_rows():
    return [
        dict(source="remoteok", source_job_id="rk-1",
             title="React Frontend Engineer", location="Worldwide",
             remote=True, category="frontend", work_mode="remote",
             normalized_job_type="full_time", published_at="2026-09-10T00:00:00+00:00"),
        dict(source="arbeitnow", source_job_id="an-1",
             title="Django Backend Developer", company="AN Co",
             location="Berlin", remote=False, category="backend",
             work_mode=None, normalized_job_type="full_time",
             published_at="2026-09-11T00:00:00+00:00"),
        dict(source="jobicy", source_job_id="jc-1",
             title="Flutter Mobile Developer", company="Jcy",
             location="Poland", remote=True, category="mobile",
             work_mode="remote", normalized_job_type="contract",
             published_at="2026-09-12T00:00:00+00:00"),
        dict(source="adzuna", source_job_id="ad-1",
             title="Digital Marketing Manager", company="Adz",
             location="London", remote=False, category="marketing",
             work_mode=None, normalized_job_type="full_time",
             published_at="2026-09-13T00:00:00+00:00"),
        dict(source="upwork", source_job_id="~uw1",
             title="Shopify Store Fix", company=None, location="Germany",
             remote=False, category="other", work_mode=None,
             normalized_job_type="freelance",
             published_at="2026-09-14T00:00:00+00:00"),
        dict(source="remoteok", source_job_id="rk-2",
             title="Sales Development Rep", company="RK",
             location="Worldwide", remote=False, category="sales",
             work_mode=None, normalized_job_type="other",
             published_at="2026-09-15T00:00:00+00:00"),
    ]


class FilterQueryTests(_DBCase):
    def setUp(self):
        super().setUp()
        _seed_rows(self.db_path, _mixed_rows())

    def test_category_filter(self):
        data = service.get_jobs(self.db_path, category="frontend")
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["jobs"][0]["source"], "remoteok")

    def test_work_mode_filter_excludes_unknown(self):
        data = service.get_jobs(self.db_path, work_mode="remote")
        self.assertEqual(data["total"], 2)  # rk-1 + jc-1; NULL rows never leak in
        self.assertTrue(all(j["work_mode"] == "remote" for j in data["jobs"]))

    def test_unknown_work_mode_jobs_served_without_mode_filter(self):
        data = service.get_jobs(self.db_path, location="Berlin")
        self.assertEqual(data["total"], 1)
        self.assertIsNone(data["jobs"][0]["work_mode"])

    def test_job_type_filter(self):
        data = service.get_jobs(self.db_path, job_type="freelance")
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["jobs"][0]["source"], "upwork")

    def test_and_combination_category_work_mode(self):
        data = service.get_jobs(self.db_path, category="mobile",
                                work_mode="remote")
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["jobs"][0]["source"], "jobicy")
        # a category+work_mode pair that never co-occurs yields zero, not error
        self.assertEqual(service.get_jobs(
            self.db_path, category="backend", work_mode="remote")["total"], 0)

    def test_source_plus_category(self):
        data = service.get_jobs(self.db_path, source="remoteok",
                                category="frontend")
        self.assertEqual(data["total"], 1)
        self.assertEqual(service.get_jobs(
            self.db_path, source="remoteok", category="mobile")["total"], 0)

    def test_location_plus_work_mode(self):
        data = service.get_jobs(self.db_path, location="Berlin",
                                work_mode="remote")
        self.assertEqual(data["total"], 0)
        data = service.get_jobs(self.db_path, location="poland",
                                work_mode="remote")
        self.assertEqual(data["total"], 1)

    def test_full_and_stack(self):
        data = service.get_jobs(self.db_path, q="shopify", location="Germany",
                                category="other", work_mode="any",
                                job_type="freelance", source="upwork")
        self.assertEqual(data["total"], 1)

    def test_unknown_values_are_ignored(self):
        data = service.get_jobs(self.db_path, category="not-a-cat",
                                work_mode="side-eye", job_type="gig")
        self.assertEqual(data["total"], 6)  # nothing filtered, nothing broken

    def test_legacy_remote_flag_still_works(self):
        data = service.get_jobs(self.db_path, remote=True)
        self.assertEqual(data["total"], 2)

    def test_pagination_after_filtering(self):
        extra = []
        for i in range(25):
            extra.append(dict(
                source="arbeitnow", source_job_id=f"pg-{i}",
                title=f"Backend Engineer {i}", location="Berlin",
                remote=False, category="backend", work_mode=None,
                normalized_job_type="full_time",
                published_at=f"2026-09-09T00:{i:02d}:00+00:00"))
        _seed_rows(self.db_path, extra)
        # 25 seeded + an-1 ("Django Backend Developer") = 26 backend rows
        page1 = service.get_jobs(self.db_path, category="backend", page=1)
        page2 = service.get_jobs(self.db_path, category="backend", page=2)
        self.assertEqual(page1["total"], 26)
        self.assertEqual(page1["pages"], 2)
        self.assertEqual(len(page1["jobs"]), 20)
        self.assertTrue(all(j["category"] == "backend" for j in page1["jobs"]))
        self.assertEqual(len(page2["jobs"]), 6)
        self.assertTrue(all(j["category"] == "backend" for j in page2["jobs"]))


# ---------------------------------------------------------------------------
# 6 — /api/jobs with the unified filters (authenticated endpoint)
# ---------------------------------------------------------------------------
class FiltersApiTests(_DBCase):
    def setUp(self):
        super().setUp()
        _seed_rows(self.db_path, _mixed_rows())

    def _client(self):
        client, _ = signup_and_login(self.app_module, name="Filter User")
        return client

    def test_api_combined_and_semantics(self):
        client = self._client()
        data = client.get(
            "/api/jobs?category=mobile&work_mode=remote&job_type=contract"
            "&location=Poland").get_json()
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["jobs"][0]["source"], "jobicy")
        self.assertEqual(data["jobs"][0]["category"], "mobile")

    def test_api_contract_16_keys_per_job(self):
        client = self._client()
        data = client.get("/api/jobs?source=remoteok").get_json()
        expected = {"id",  # internal cache id — part of the shape since 8B.1
                    "source", "source_job_id", "title", "company", "location",
                    "description", "job_type", "remote", "tags", "salary",
                    "job_url", "published_at", "fetched_at",
                    "category", "work_mode", "normalized_job_type"}
        self.assertEqual(set(data["jobs"][0].keys()), expected)

    def test_api_jobguard_published_listing_filters(self):
        from test_employer_jobs import VALID as JOB_VALID, _register_employer
        client = self._client()
        _register_employer(client)
        payload = dict(JOB_VALID, title="UI/UX Design Internship",
                       job_type="Internship", location="Lahore",
                       description=(
                           "We are hiring a design intern to join our product "
                           "team. You will support designers, review wireframes, "
                           "and improve application usability. The role includes "
                           "a structured development plan, paid leave, and access "
                           "to health coverage. Candidates should share a "
                           "portfolio."),)
        created = client.post("/api/employer-jobs", json=payload).get_json()["job"]
        client.post(f"/api/employer-jobs/{created['id']}/screen")
        published = client.post(f"/api/employer-jobs/{created['id']}/publish")
        self.assertEqual(published.status_code, 200)

        hits = client.get("/api/jobs?source=jobguard&job_type=internship").get_json()
        self.assertEqual(hits["total"], 1)
        job = hits["jobs"][0]
        self.assertEqual(job["normalized_job_type"], "internship")
        self.assertEqual(job["category"], "ui_ux")
        # AND semantics: a mismatching second filter excludes the row
        misses = client.get(
            "/api/jobs?source=jobguard&job_type=internship"
            "&category=backend").get_json()
        self.assertEqual(misses["total"], 0)

    def test_six_provider_filter_regression(self):
        client = self._client()
        from test_employer_jobs import VALID as JOB_VALID, _register_employer
        _register_employer(client)
        payload = dict(JOB_VALID, title="Backend Engineer",
                       job_type="Full Time", location="Lahore",
                       description=(
                           "We are hiring a backend engineer to join our product "
                           "team. You will design APIs, review code, collaborate "
                           "with designers, and improve application reliability. "
                           "The role includes a clear development plan, paid "
                           "leave, and access to health coverage. Candidates "
                           "should share a portfolio."),)
        created = client.post("/api/employer-jobs", json=payload).get_json()["job"]
        client.post(f"/api/employer-jobs/{created['id']}/screen")
        self.assertEqual(
            client.post(f"/api/employer-jobs/{created['id']}/publish").status_code,
            200)

        expect = {
            ("remoteok", "frontend"): 1,
            ("arbeitnow", "backend"): 1,
            ("jobicy", "mobile"): 1,
            ("adzuna", "marketing"): 1,
            ("upwork", "other"): 1,
            ("jobguard", "backend"): 1,
        }
        for (src, cat), n in expect.items():
            data = client.get(f"/api/jobs?source={src}&category={cat}").get_json()
            self.assertEqual(data["total"], n, f"{src}+{cat}")
        # every one of the six sources flows through the same filter contract
        merged = client.get("/api/jobs?category=backend").get_json()
        sources = {j["source"] for j in merged["jobs"]}
        self.assertIn("arbeitnow", sources)
        self.assertIn("jobguard", sources)

    def test_api_unknown_params_do_not_break(self):
        client = self._client()
        data = client.get("/api/jobs?category=zzz&work_mode=teleport").get_json()
        self.assertEqual(data["total"], 6)

    def test_api_upwork_freelance_filter(self):
        client = self._client()
        data = client.get("/api/jobs?source=upwork&job_type=freelance").get_json()
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["jobs"][0]["title"], "Shopify Store Fix")


if __name__ == "__main__":
    unittest.main()
