from __future__ import annotations

import gzip
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.osm.engine import OSMStore, import_osm_xml, normalize_name


OSM_FIXTURE = """<?xml version="1.0" encoding="UTF-8"?>
<osm version="0.6" generator="unit-test">
  <bounds minlat="47.9" minlon="33.3" maxlat="48.0" maxlon="33.5"/>
  <node id="1" lat="47.9100" lon="33.4000"/>
  <node id="2" lat="47.9110" lon="33.4010"/>
  <node id="3" lat="47.9120" lon="33.4020"/>
  <node id="4" lat="47.9130" lon="33.4030">
    <tag k="amenity" v="cafe"/>
    <tag k="name:uk" v="Кава і друзі"/>
    <tag k="alt_name" v="Kava; Кав'ярня"/>
  </node>
  <way id="10">
    <nd ref="1"/><nd ref="2"/>
    <tag k="highway" v="residential"/><tag k="oneway" v="yes"/>
    <tag k="name" v="вулиця Центральна"/><tag k="name:uk" v="вулиця Центральна"/>
  </way>
  <way id="11">
    <nd ref="2"/><nd ref="3"/>
    <tag k="highway" v="service"/><tag k="name" v="Провулок Тихий"/>
  </way>
  <way id="12">
    <nd ref="3"/><nd ref="4"/>
    <tag k="highway" v="footway"/>
  </way>
  <way id="20">
    <nd ref="1"/><nd ref="2"/>
    <tag k="building" v="yes"/><tag k="addr:street" v="вулиця Центральна"/>
    <tag k="addr:housenumber" v="12А"/><tag k="addr:city" v="Кривий Ріг"/>
  </way>
  <way id="30">
    <nd ref="3"/><nd ref="999"/>
    <tag k="highway" v="service"/>
  </way>
  <relation id="50">
    <member type="way" ref="10" role="from"/>
    <member type="way" ref="11" role="to"/>
    <member type="node" ref="2" role="via"/>
    <tag k="type" v="restriction"/><tag k="restriction" v="no_left_turn"/>
  </relation>
</osm>
"""

TEST_TEMP_ROOT = PROJECT_ROOT / "work" / "autonomous_manager" / "test_tmp"


class OSMEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        TEST_TEMP_ROOT.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "kryvyi-rih.osm"
        self.source.write_text(OSM_FIXTURE, encoding="utf-8")
        self.database = self.root / "kryvyi-rih.sqlite"

    def test_normalization_keeps_cyrillic_searchable(self) -> None:
        self.assertEqual(normalize_name("  ВУЛИЦЯ—Центральна! "), "вулиця центральна")
        self.assertEqual(normalize_name("КРИВИЙ РІГ"), "кривий ріг")

    def test_import_is_read_only_for_source_and_keeps_provenance(self) -> None:
        before = hashlib.sha256(self.source.read_bytes()).hexdigest()
        summary = import_osm_xml(self.source, self.database)
        after = hashlib.sha256(self.source.read_bytes()).hexdigest()
        self.assertEqual(before, after)
        self.assertEqual(summary.source_sha256, before)
        self.assertEqual((summary.node_count, summary.way_count, summary.relation_count), (4, 5, 1))
        self.assertEqual(summary.unresolved_node_refs, 1)
        self.assertGreater(summary.directed_edge_count, 0)

        store = OSMStore(self.database)
        self.assertEqual(store.metadata["source_sha256"], before)
        results = store.search("КАВА")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].name, "Кава і друзі")
        self.assertEqual(results[0].tags["alt_name"], "Kava; Кав'ярня")
        streets = store.search("центральна")
        self.assertTrue(any(item.element_type == "way" and item.element_id == "10" and item.kind == "street"
                            for item in streets))
        self.assertEqual((store.search("Центральна", limit=1)[0].element_id, store.search("Центральна", limit=1)[0].kind),
                         ("10", "street"))

    def test_address_search_and_map_geometry(self) -> None:
        import_osm_xml(self.source, self.database)
        store = OSMStore(self.database)
        results = store.search("центральна 12а кривий ріг")
        self.assertTrue(results)
        self.assertTrue(any(item.kind in {"address", "poi+address"} and item.tags.get("addr:housenumber") == "12А" for item in results))
        ways = list(store.iter_map_ways(limit=20))
        self.assertTrue(any(item["id"] == "10" and item["tags"]["highway"] == "residential" for item in ways))
        self.assertTrue(any(item["id"] == "20" and len(item["coordinates"]) == 2 for item in ways))
        nearest = store.nearest_node(47.9101, 33.4001)
        self.assertEqual(nearest[0], "1")
        self.assertLess(nearest[1], 20)

    def test_astar_respects_oneway_and_reports_unenforced_turn_restrictions(self) -> None:
        import_osm_xml(self.source, self.database)
        store = OSMStore(self.database)
        route = store.route("1", "3")
        self.assertIsNotNone(route)
        self.assertEqual(route.node_ids, ("1", "2", "3"))
        self.assertEqual(route.way_ids, ("10", "11"))
        self.assertGreater(route.distance_m, 0)
        self.assertTrue(route.limitations)
        self.assertIsNone(store.route("3", "1"))
        self.assertIsNone(store.route("1", "999"))
        with self.assertRaisesRegex(ValueError, "only the experimental"):
            store.route("1", "3", profile="walk")

    def test_nearest_routable_node_skips_a_nearby_poi_node(self) -> None:
        import_osm_xml(self.source, self.database)
        store = OSMStore(self.database)
        result = store.nearest_routable_node(47.913, 33.403, max_distance_m=1000)
        self.assertIsNotNone(result)
        self.assertIn(result[0], {"1", "2", "3"})
        self.assertIsNone(store.nearest_routable_node(0, 0, max_distance_m=1))

    def test_gzip_import_is_supported(self) -> None:
        compressed = self.root / "kryvyi-rih.osm.gz"
        with gzip.open(compressed, "wb") as stream:
            stream.write(OSM_FIXTURE.encode("utf-8"))
        database = self.root / "compressed.sqlite"
        summary = import_osm_xml(compressed, database)
        self.assertEqual(summary.node_count, 4)
        self.assertEqual(len(OSMStore(database).search("кав'ярня")), 1)

    def test_existing_destination_is_never_overwritten(self) -> None:
        self.database.write_bytes(b"keep existing data")
        with self.assertRaises(FileExistsError):
            import_osm_xml(self.source, self.database)
        self.assertEqual(self.database.read_bytes(), b"keep existing data")

    def test_malformed_input_does_not_publish_partial_database(self) -> None:
        bad_source = self.root / "bad.osm"
        bad_source.write_text("<osm><node id='1' lat='bad' lon='0'/></osm>", encoding="utf-8")
        output = self.root / "bad.sqlite"
        with self.assertRaisesRegex(ValueError, "invalid coordinates"):
            import_osm_xml(bad_source, output)
        self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
