from __future__ import annotations

import sys
from pathlib import Path
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.agent.failure_triage import classify_failure


class FailureTriageTests(unittest.TestCase):
    def test_priority_failure_classes_are_distinguished(self) -> None:
        cases = {
            "ParseError: out of memory at XML line 35": "OOM",
            "task timed out after 900 seconds": "TIMEOUT",
            "invalid data: unexpected EOF": "DATA",
            "No module named osmium": "TOOL_MISSING",
            "AssertionError: acceptance test failed": "TEST_FAILURE",
            "physical compatibility requires vehicle acceptance": "EXTERNAL_DEPENDENCY",
            "Codex usage limit exceeded (429)": "CODEX_RATE_LIMIT",
        }
        for error, expected in cases.items():
            with self.subTest(error=error):
                self.assertEqual(classify_failure(error)["class"], expected)

    def test_retry_requires_new_evidence(self) -> None:
        result = classify_failure("TimeoutError: no durable progress")
        self.assertTrue(result["retry_requires_new_evidence"])
        self.assertIn("checkpoint", result["recommended_action"])


if __name__ == "__main__":
    unittest.main()
