from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.cid.virtual_cid import PoiStore

TEST_TEMP_ROOT = PROJECT_ROOT / "work" / "autonomous_manager" / "test_tmp"


class PoiStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        TEST_TEMP_ROOT.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT)
        self.addCleanup(self.temp.cleanup)
        self.database = Path(self.temp.name) / "poi.sqlite"
        self.store = PoiStore(self.database)

    def test_ukrainian_poi_persists_and_searches_alias_after_reopen(self) -> None:
        saved = self.store.save("Моя майстерня", 47.91, 33.40, "Авто", ["гараж", "service"])
        reopened = PoiStore(self.database)
        result = reopened.search("ГАРАЖ")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], saved["id"])
        self.assertEqual(result[0]["name_uk"], "Моя майстерня")

    def test_duplicate_names_and_nearby_pois_are_refused(self) -> None:
        self.store.save("Шиномонтаж", 47.91, 33.40, "Авто")
        with self.assertRaisesRegex(ValueError, "Схоже місце"):
            self.store.save("ШИНОМОНТАЖ", 48.00, 33.40, "Авто")
        with self.assertRaisesRegex(ValueError, "Схоже місце"):
            self.store.save("Інше місце", 47.91001, 33.40001, "Авто")

    def test_json_roundtrip_and_duplicate_skip(self) -> None:
        self.store.save("Бібліотека", 47.92, 33.41, "Культура", ["читальня"])
        export = Path(self.temp.name) / "poi.json"
        self.assertEqual(self.store.export_json(export), 1)
        self.assertEqual(json.loads(export.read_text(encoding="utf-8"))["format"], "ncdr-personal-poi-v1")
        imported, skipped = PoiStore(Path(self.temp.name) / "other.sqlite").import_json(export)
        self.assertEqual((imported, skipped), (1, 0))
        imported2, skipped2 = PoiStore(Path(self.temp.name) / "other.sqlite").import_json(export)
        self.assertEqual((imported2, skipped2), (0, 1))


if __name__ == "__main__":
    unittest.main()
