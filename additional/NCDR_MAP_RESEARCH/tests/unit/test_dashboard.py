from __future__ import annotations

import sys
import re
from pathlib import Path
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.agent.build_dashboard import build_html


class DashboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.document = build_html()

    def test_all_ten_requested_tabs_have_panels(self) -> None:
        self.assertEqual(len(re.findall(r'role="tab"(?=[ >])', self.document)), 10)
        self.assertEqual(len(re.findall(r'role="tabpanel"(?=[ >])', self.document)), 10)
        self.assertIn('aria-label="Розділи Dashboard"', self.document)

    def test_disk_is_not_marked_ready_without_hardware_proof(self) -> None:
        self.assertIn("DISK_NOT_READY", self.document)
        self.assertIn("HARDWARE_UNVERIFIED", self.document)
        self.assertIn("джерело не змінене", self.document)

    def test_benchmark_recommendation_is_visible(self) -> None:
        self.assertIn("qwen2.5-coder:7b", self.document)
        self.assertIn("20.8781", self.document)
        self.assertIn("Жоден кандидат не допущений до генерації writer-коду", self.document)


if __name__ == "__main__":
    unittest.main()
