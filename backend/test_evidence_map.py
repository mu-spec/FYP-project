"""Milestone 2 tests for deterministic evidence metadata.

Run from backend/:
    python -m unittest test_evidence_map -v

These tests exercise the existing red-flag conditions and verify that evidence
is additive: the hybrid probability formula still uses only the original flag
weights, while snippets/categories/severity/explanations are display metadata.
"""

import json
import os
import sqlite3
import sys
import tempfile
import unittest

from nlp_pipeline import detect_red_flags, extract_signals, rule_score

SCAM_TEXT = (
    "Earn $9,000 EVERY WEEK working from home! No experience needed. "
    "Immediate hiring! Just pay a $99 registration fee via Easypaisa. "
    "Email hiring.manager2024@gmail.com NOW. Act fast!"
)

LEGIT_TEXT = (
    "We are hiring a backend engineer to join our product team. You will design "
    "APIs, review code, collaborate with designers, and improve application "
    "reliability. The role includes a clear development plan, paid leave, and "
    "access to health coverage. Candidates should share a portfolio and describe "
    "relevant projects."
)


class EvidenceRuleTests(unittest.TestCase):
    def test_multiple_flags_include_raw_text_evidence(self):
        signals = extract_signals(SCAM_TEXT)
        flags = detect_red_flags(SCAM_TEXT, signals)

        self.assertGreaterEqual(len(flags), 4)
        self.assertIn("UPFRONT PAYMENT", {flag["category"] for flag in flags})
        self.assertIn("High", {flag["severity"] for flag in flags})

        for flag in flags:
            self.assertIn(flag["severity"], {"High", "Medium", "Low"})
            self.assertTrue(flag["explanation"])
            self.assertTrue(flag["evidence"])
            for snippet in flag["evidence"]:
                self.assertIn(snippet.lower(), SCAM_TEXT.lower())

    def test_evidence_does_not_change_original_rule_score(self):
        flags = detect_red_flags(SCAM_TEXT, extract_signals(SCAM_TEXT))
        expected = min(0.99, sum(flag["weight"] for flag in flags))
        self.assertEqual(rule_score(flags), expected)

    def test_legitimate_text_has_no_major_indicators(self):
        flags = detect_red_flags(LEGIT_TEXT, extract_signals(LEGIT_TEXT))
        self.assertEqual(flags, [])


class EvidenceApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import app

        cls.app_module = app
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.original_db_path = app.DB_PATH
        app.DB_PATH = os.path.join(cls.temp_dir.name, "evidence-test.db")
        app.init_db()
        cls.client = app.app.test_client()

    @classmethod
    def tearDownClass(cls):
        cls.app_module.DB_PATH = cls.original_db_path
        cls.temp_dir.cleanup()

    def _post(self, text, title):
        return self.client.post(
            "/api/predict",
            data=json.dumps({"job_text": text, "title": title}),
            content_type="application/json",
        )

    def test_scam_api_returns_evidence_without_probability_change(self):
        response = self._post(SCAM_TEXT, "evidence scam")
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        flags = body["red_flags"]
        expected_scam = round(
            1 - (1 - body["engine"]["xgboost_scam_prob"])
            * (1 - body["engine"]["rule_scam_score"]),
            4,
        )
        self.assertEqual(body["probabilities"]["scam"], expected_scam)
        self.assertTrue(all(flag.get("evidence") for flag in flags))
        self.assertTrue(all(flag.get("category") for flag in flags))

    def test_legitimate_api_returns_empty_evidence_map(self):
        response = self._post(LEGIT_TEXT, "evidence legitimate")
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body["red_flags"], [])
        self.assertIn("probabilities", body)

    def test_invalid_input_is_rejected_before_evidence_or_history(self):
        before = self.client.get("/api/history").get_json()
        response = self._post("hello", "invalid evidence")
        self.assertEqual(response.status_code, 400)
        self.assertTrue(response.get_json()["invalid_input"])
        after = self.client.get("/api/history").get_json()
        self.assertEqual(len(after), len(before))

    def test_new_history_row_round_trips_evidence(self):
        response = self._post(SCAM_TEXT, "stored evidence")
        self.assertEqual(response.status_code, 200)
        expected = response.get_json()["red_flags"]
        history = self.client.get("/api/history").get_json()
        row = next(item for item in history if item["job_title"] == "stored evidence")
        self.assertEqual(row["evidence"], expected)

    def test_old_history_rows_remain_readable(self):
        with sqlite3.connect(self.app_module.DB_PATH) as db:
            db.execute(
                "INSERT INTO predictions "
                "(job_title, prediction, confidence, created_at) VALUES (?,?,?,?)",
                ("old record", "Legitimate", 0.9, "2025-01-01T00:00:00+00:00"),
            )
            db.commit()
        history = self.client.get("/api/history").get_json()
        row = next(item for item in history if item["job_title"] == "old record")
        self.assertEqual(row["evidence"], [])


if __name__ == "__main__":
    unittest.main()
