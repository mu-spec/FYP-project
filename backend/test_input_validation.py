"""
Automated tests for the Job-Post Input Validation layer.

Run from the backend/ directory:

    python -m unittest test_input_validation -v

Two suites:

  1. ValidationRulesTests   - unit tests on validate_job_text() (no model).
  2. ApiBehaviourTests      - Flask test-client checks proving that invalid
                              input is rejected with invalid_input=true, that
                              predict_one() (the ML pipeline) is NEVER called
                              for rejected input, and that nothing is stored
                              in prediction history for rejected input.

These tests do NOT retrain, fit, or modify the model / vectorizer / artifacts.
"""

import json
import unittest
from unittest import mock

from input_validation import REJECT_MESSAGE, validate_job_text

# ---------------------------------------------------------------------------
# The required acceptance / rejection cases from the task.
# ---------------------------------------------------------------------------
MUST_REJECT = [
    "",
    "     ",
    "hello",
    "123456789",
    "asdfghjklqwertyuiopzxcvbnm",
    "ekhfeifhojibbejfbijebijdfkoenfoenfenfklenfkoefkoenfoiefoiehielfekofoe",
    "I went to the market today and bought some food.",
    "Football is my favorite sport and I watch it every weekend.",
]

MUST_ACCEPT = [
    "Need Flutter developer to fix Firebase notification issues in our existing "
    "Android application. Project duration is approximately 2-3 days. Please "
    "include previous Flutter experience.",
    "Looking for a React developer to build a responsive website from our Figma "
    "designs. Experience with React, JavaScript and REST APIs required.",
]

LINKEDIN_LIKE = (
    "Acme Software is hiring a Senior Full-Stack Engineer to join our product "
    "team. You will build scalable web applications with React and Node.js. "
    "Requirements: 5+ years experience, strong REST API design and a passion for "
    "clean code. We offer a competitive salary, health insurance, stock options "
    "and full remote work."
)

SCAM_LIKE = (
    "Earn $9,000 EVERY WEEK working from home! No experience needed, no degree. "
    "Immediate hiring, positions filling fast! Just pay a one-time $99 "
    "registration fee via Easypaisa or JazzCash to secure your slot. Email "
    "hiring.manager2024@gmail.com or WhatsApp us NOW. Act fast, limited time!"
)

SHORT_UPWORK_LIKE = (
    "Need a React developer to build a simple landing page within a week. Budget "
    "is open, please share your portfolio."
)


class ValidationRulesTests(unittest.TestCase):
    def test_rejects_empty_and_whitespace(self):
        for t in ("", "   ", "\n\t  "):
            self.assertFalse(validate_job_text(t)[0], repr(t))

    def test_rejects_short_or_meaningless(self):
        for t in ("hello", "test", "abc", "12345", "123456789"):
            self.assertFalse(validate_job_text(t)[0], repr(t))

    def test_rejects_gibberish_strings(self):
        for t in ("asdfghjklqwertyuiopzxcvbnm",
                  "ekhfeifhojibbejfbijebijdfkoenfoenfenfklenfkoefkoenfoiefoiehielfekofoe"):
            self.assertFalse(validate_job_text(t)[0], repr(t[:40]))

    def test_rejects_coherent_non_job_prose(self):
        for t in MUST_REJECT[6:]:
            self.assertFalse(validate_job_text(t)[0], repr(t))

    def test_accepts_short_upwork_style_posts(self):
        for t in MUST_ACCEPT:
            self.assertTrue(validate_job_text(t)[0], repr(t[:50]))

    def test_accepts_full_linkedin_like_posting(self):
        self.assertTrue(validate_job_text(LINKEDIN_LIKE)[0])

    def test_accepts_realistic_scam_posting(self):
        # A scam ad is still a job-shaped text -> must reach the classifier.
        self.assertTrue(validate_job_text(SCAM_LIKE)[0])

    def test_accepts_short_legit_upwork_post(self):
        self.assertTrue(validate_job_text(SHORT_UPWORK_LIKE)[0])

    def test_reject_reason_codes_are_meaningful(self):
        self.assertEqual(validate_job_text("")[1], "empty_or_whitespace")
        self.assertEqual(validate_job_text("hello")[1], "too_short")
        self.assertEqual(validate_job_text("123456789")[1], "no_alphabetic_words")
        self.assertIn(validate_job_text(
            "I went to the market today and bought some food.")[1],
            {"not_job_like", "too_short"})

    def test_no_non_job_prose_accidentally_accepted(self):
        more_negatives = [
            "Cricket is my favourite sport and I watch matches every weekend.",
            "I ate lunch then went to the gym with my friends yesterday.",
            "The weather today is very pleasant and sunny in the city.",
            "aaaa bbbb cccc dddd eeee ffff gggg hhhh",
            "qwerty asdfgh zxcvbn poiuy lkjhg mnbvc",
        ]
        for t in more_negatives:
            self.assertFalse(validate_job_text(t)[0], repr(t))


class ApiBehaviourTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import app
        cls.app_module = app
        cls.client = app.app.test_client()

    def _post(self, text):
        return self.client.post(
            "/api/predict",
            data=json.dumps({"job_text": text, "title": "test"}),
            content_type="application/json",
        )

    def test_invalid_input_returns_400_and_flag(self):
        for t in MUST_REJECT:
            with self.subTest(text=t[:30]):
                r = self._post(t)
                self.assertEqual(r.status_code, 400)
                body = r.get_json()
                self.assertTrue(body["invalid_input"])
                self.assertEqual(body["error"], REJECT_MESSAGE)

    @mock.patch("app.predict_one")
    def test_ml_pipeline_never_called_for_invalid(self, predict_mock):
        predict_mock.return_value = {"ignored": True}
        for t in MUST_REJECT:
            with self.subTest(text=t[:30]):
                self._post(t)
        # The full ML prediction function must not have executed at all.
        predict_mock.assert_not_called()

    @mock.patch("app.predict_one")
    def test_ml_pipeline_called_for_valid(self, predict_mock):
        predict_mock.return_value = {
            "job_title": "x", "prediction": "Legitimate", "confidence": 0.9,
            "probabilities": {"scam": 0.1, "legitimate": 0.9},
            "engine": {}, "red_flags": [], "signals": {}, "latency_ms": 1.0,
        }
        for t in MUST_ACCEPT:
            with self.subTest(text=t[:40]):
                r = self._post(t)
                self.assertEqual(r.status_code, 200)
        self.assertEqual(predict_mock.call_count, len(MUST_ACCEPT))

    def test_invalid_input_not_stored_in_history(self):
        before = self.client.get("/api/history").get_json()
        before_ids = [row["id"] for row in before]

        r = self._post("hello")
        self.assertEqual(r.status_code, 400)

        after = self.client.get("/api/history").get_json()
        after_ids = [row["id"] for row in after]
        # No new prediction row was added for a rejected input.
        self.assertEqual(before_ids, after_ids)

    def test_valid_input_is_stored_in_history(self):
        before = len(self.client.get("/api/history").get_json())
        r = self._post(SHORT_UPWORK_LIKE)
        self.assertEqual(r.status_code, 200)
        after = len(self.client.get("/api/history").get_json())
        self.assertEqual(after, before + 1)


if __name__ == "__main__":
    unittest.main()
