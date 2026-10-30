from __future__ import annotations

import sys
import re
from pathlib import Path
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.agent.build_dashboard import build_html, load_benchmark


class DashboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.document = build_html()

    def test_active_disc_scope_tabs_have_panels_without_retired_products(self) -> None:
        self.assertEqual(len(re.findall(r'role="tab"(?=[ >])', self.document)), 8)
        self.assertEqual(len(re.findall(r'role="tabpanel"(?=[ >])', self.document)), 8)
        self.assertIn('aria-label="Розділи Dashboard"', self.document)

    def test_disk_is_not_marked_ready_without_hardware_proof(self) -> None:
        self.assertIn("DISK_NOT_READY", self.document)
        self.assertIn("PHYSICAL_COMPATIBILITY_NOT_TESTED", self.document)
        self.assertIn("джерело не змінене", self.document)

    def test_benchmark_recommendation_is_visible(self) -> None:
        self.assertIn(load_benchmark().get("recommended_model", ""), self.document)
        self.assertIn("Жоден кандидат не допущений до генерації writer-коду", self.document)

    def test_disc_readiness_uses_active_scope_and_archives_retired_products(self) -> None:
        self.assertIn("NCDR Ukraine · підготовка фізичного диска", self.document)
        self.assertIn("AUTO_VERIFY_e53bd95866f9da2fc4", self.document)
        self.assertIn("OSM-пошук, дорожній граф і POI", self.document)
        self.assertIn("Кількість задач", self.document)
        self.assertNotIn("Віртуальний CID", self.document)
        self.assertNotIn("Редактор POI", self.document)
        self.assertNotIn("READY_FOR_SIMULATION", self.document)
        self.assertIn("PHYSICAL_COMPATIBILITY_NOT_TESTED", self.document)


if __name__ == "__main__":
    unittest.main()
