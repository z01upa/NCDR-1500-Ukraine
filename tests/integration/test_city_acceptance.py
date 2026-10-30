"""Acceptance checks against the saved Kryvyi Rih OSM extract."""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.cid.virtual_cid import PoiStore
from src.osm.engine import OSMStore, normalize_name


class KryvyiRihAcceptanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.map_db = PROJECT_ROOT / "data" / "osm" / "kryvyi_rih.sqlite"
        cls.source_json = PROJECT_ROOT / "data" / "osm" / "source.json"
        if not cls.map_db.is_file() or not cls.source_json.is_file():
            raise unittest.SkipTest("build the dated local OSM extract before running this integration test")
        cls.store = OSMStore(cls.map_db)
        cls.source = json.loads(cls.source_json.read_text(encoding="utf-8"))

    def test_city_street_search_and_connected_real_road_route(self) -> None:
        connection = sqlite3.connect(self.map_db)
        try:
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        finally:
            connection.close()

        sobornosti = [row for row in self.store.search("Соборності", limit=300)
                      if row.kind == "street" and normalize_name(row.name) == normalize_name("вулиця Соборності")]
        heroiv = [row for row in self.store.search("Героїв АТО", limit=300)
                  if row.kind == "street" and normalize_name(row.name) == normalize_name("вулиця Героїв АТО")
                  and 47.89 <= (row.latitude or 0) <= 47.92 and 33.39 <= (row.longitude or 0) <= 33.44]
        self.assertTrue(sobornosti, "a real Ukrainian street name should be searchable")
        self.assertTrue(heroiv, "a second nearby street should be searchable")
        start_point = min(sobornosti, key=lambda row: abs((row.latitude or 0)-47.9)+abs((row.longitude or 0)-33.408))
        end_point = min(heroiv, key=lambda row: abs((row.latitude or 0)-47.906)+abs((row.longitude or 0)-33.407))
        start = self.store.nearest_routable_node(start_point.latitude, start_point.longitude, max_distance_m=5000)
        end = self.store.nearest_routable_node(end_point.latitude, end_point.longitude, max_distance_m=5000)
        self.assertIsNotNone(start)
        self.assertIsNotNone(end)
        route = self.store.route(start[0], end[0])
        self.assertIsNotNone(route, "the imported Kryvyi Rih road graph should connect these streets")
        self.assertGreater(route.distance_m, 0)
        self.assertLess(route.distance_m, 10_000)
        self.assertGreater(len(route.node_ids), 2)

    def test_personal_location_survives_database_reopen(self) -> None:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as folder:
            path = Path(folder) / "personal_poi.sqlite"
            first = PoiStore(path)
            first.save("Моя тестова локація", 47.8994, 33.4091, "Власне місце", ["мій тест"])
            reopened = PoiStore(path)
            found = reopened.search("мій тест")
            self.assertEqual(len(found), 1)
            self.assertEqual(found[0]["name_uk"], "Моя тестова локація")
            self.assertEqual(found[0]["category"], "Власне місце")

    def test_current_osm_snapshot_has_provenance_search_and_connected_route(self) -> None:
        data_dir = PROJECT_ROOT / "data" / "osm"
        pointer_path = data_dir / "current.json"
        if not pointer_path.is_file():
            self.skipTest("no explicitly selected current OSM snapshot")
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
        map_db = data_dir / pointer["database_file"]
        source_manifest = data_dir / pointer["source_manifest"]
        self.assertTrue(map_db.is_file())
        self.assertTrue(source_manifest.is_file())
        manifest = json.loads(source_manifest.read_text(encoding="utf-8"))
        self.assertEqual(manifest["source_sha256"], pointer["source_sha256"])
        self.assertTrue(manifest["retrieved_utc"])

        connection = sqlite3.connect(map_db)
        try:
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        finally:
            connection.close()

        store = OSMStore(map_db)
        sobornosti = [row for row in store.search("Соборності", limit=300)
                      if row.kind == "street" and normalize_name(row.name) == normalize_name("вулиця Соборності")]
        heroiv = [row for row in store.search("Героїв АТО", limit=300)
                  if row.kind == "street" and normalize_name(row.name) == normalize_name("вулиця Героїв АТО")
                  and 47.89 <= (row.latitude or 0) <= 47.92 and 33.39 <= (row.longitude or 0) <= 33.44]
        self.assertTrue(sobornosti)
        self.assertTrue(heroiv)
        start_point = min(sobornosti, key=lambda row: abs((row.latitude or 0)-47.9)+abs((row.longitude or 0)-33.408))
        end_point = min(heroiv, key=lambda row: abs((row.latitude or 0)-47.906)+abs((row.longitude or 0)-33.407))
        start = store.nearest_routable_node(start_point.latitude, start_point.longitude, max_distance_m=5000)
        end = store.nearest_routable_node(end_point.latitude, end_point.longitude, max_distance_m=5000)
        self.assertIsNotNone(start)
        self.assertIsNotNone(end)
        route = store.route(start[0], end[0])
        self.assertIsNotNone(route)
        self.assertGreater(route.distance_m, 0)
        self.assertLess(route.distance_m, 10_000)


if __name__ == "__main__":
    unittest.main()
