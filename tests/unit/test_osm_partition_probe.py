from __future__ import annotations

from pathlib import Path
from contextlib import closing
import sqlite3
import sys
import tempfile
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.osm.partition_probe import run_partition_probe


class OSMPartitionProbeTests(unittest.TestCase):
    def _database(self, folder: Path) -> Path:
        path = folder / "osm.sqlite"
        with closing(sqlite3.connect(path)) as conn:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.executescript("""
                CREATE TABLE nodes(id TEXT PRIMARY KEY, latitude REAL NOT NULL,
                    longitude REAL NOT NULL, tags_json TEXT NOT NULL DEFAULT '{}');
                CREATE INDEX idx_nodes_lat_lon ON nodes(latitude, longitude);
                CREATE TABLE way_nodes(way_id TEXT NOT NULL, node_index INTEGER NOT NULL,
                    node_id TEXT NOT NULL, PRIMARY KEY(way_id, node_index));
                CREATE INDEX idx_way_nodes_node ON way_nodes(node_id);
                CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                INSERT INTO meta VALUES('source_sha256', 'a-source-hash');
                INSERT INTO meta VALUES('node_count', '5');
                INSERT INTO nodes(id, latitude, longitude) VALUES
                    ('1', .1, .1), ('2', .1, .6), ('3', .6, .6),
                    ('4', .6, .1), ('5', 2, 2);
                INSERT INTO way_nodes VALUES
                    ('a',0,'1'), ('a',1,'2'),
                    ('b',0,'2'), ('b',1,'3'),
                    ('c',0,'4');
            """)
        return path

    def test_regional_measurement_matches_independent_streaming_pass(self) -> None:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as temporary:
            database = self._database(Path(temporary))
            before = database.stat()
            result = run_partition_probe(database, bbox=(0, 0, 1, 1), rows=2,
                columns=2, max_nodes=10, timeout_s=30)
            after = database.stat()

        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["node_count"], 4)
        self.assertEqual(result["way_count"], 3)
        self.assertEqual(result["way_node_memberships"], 5)
        self.assertEqual(result["cross_tile_way_count"], 2)
        self.assertEqual(result["ways_by_tile_span"], {"1": 1, "2": 2})
        self.assertEqual(result["ways_by_tile_span"],
            result["independent_streaming_verification"]["ways_by_tile_span"])
        self.assertEqual((before.st_size, before.st_mtime_ns), (after.st_size, after.st_mtime_ns))
        self.assertTrue(any("idx_nodes_lat_lon" in line for line in result["query_plan"]))
        self.assertEqual(result["sqlite_limits"]["page_cache_bytes"], 64 * 1024 * 1024)

    def test_node_bound_rejects_oversized_region_before_membership_scan(self) -> None:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as temporary:
            database = self._database(Path(temporary))
            with self.assertRaisesRegex(ValueError, "above the 2 node bound"):
                run_partition_probe(database, bbox=(0, 0, 1, 1), rows=2,
                    columns=2, max_nodes=2, timeout_s=30)

    def test_rejects_invalid_grid_and_geographic_window(self) -> None:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as temporary:
            database = self._database(Path(temporary))
            with self.assertRaisesRegex(ValueError, "grid dimensions"):
                run_partition_probe(database, bbox=(0, 0, 1, 1), rows=17,
                    columns=2, max_nodes=10, timeout_s=30)
            with self.assertRaisesRegex(ValueError, "ordered geographic"):
                run_partition_probe(database, bbox=(1, 0, 0, 1), rows=2,
                    columns=2, max_nodes=10, timeout_s=30)


if __name__ == "__main__":
    unittest.main()
