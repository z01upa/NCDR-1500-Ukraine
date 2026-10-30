from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.cid.virtual_cid import PoiStore
from src.poi_editor import parse_coordinate


TEST_TEMP_ROOT = PROJECT_ROOT / "work" / "autonomous_manager" / "test_tmp"


class PoiEditorTests(unittest.TestCase):
    def test_coordinates_accept_dot_or_comma_and_enforce_ranges(self) -> None:
        self.assertEqual(parse_coordinate("47,9123", "Широта", -90, 90), 47.9123)
        self.assertEqual(parse_coordinate("33.405", "Довгота", -180, 180), 33.405)
        with self.assertRaisesRegex(ValueError, "числом"):
            parse_coordinate("вулиця", "Широта", -90, 90)
        with self.assertRaisesRegex(ValueError, "допустиме значення"):
            parse_coordinate("181", "Довгота", -180, 180)

    def test_saved_ukrainian_poi_is_available_after_database_reopen(self) -> None:
        TEST_TEMP_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as temp_dir:
            database = Path(temp_dir) / "personal.sqlite"
            saved = PoiStore(database).save("Моя станція", 47.91, 33.40, "АЗС")
            reopened = PoiStore(database)
            restored = reopened.all()
            self.assertEqual(len(restored), 1)
            self.assertEqual(restored[0]["id"], saved["id"])
            self.assertEqual(restored[0]["name_uk"], "Моя станція")
            self.assertEqual(restored[0]["category"], "АЗС")
            self.assertEqual(restored[0]["latitude"], 47.91)
            self.assertEqual(restored[0]["longitude"], 33.40)


if __name__ == "__main__":
    unittest.main()
