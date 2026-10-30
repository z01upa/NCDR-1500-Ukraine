from __future__ import annotations

import gzip
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from src.osm import build_ukraine


def _write_fixture_extract(_source: Path, destination: Path, _bbox: tuple[float, float, float, float]) -> dict:
    destination.parent.mkdir(parents=True, exist_ok=True)
    nodes = [
        (1, 47.9000, 33.4080), (2, 47.9005, 33.4085), (3, 47.9010, 33.4090),
        (4, 47.9015, 33.4095), (5, 47.9020, 33.4100), (6, 47.9025, 33.4105),
        (7, 47.9030, 33.4110), (8, 47.9035, 33.4115), (9, 47.9040, 33.4120),
        (10, 50.4500, 30.5200), (11, 50.4510, 30.5210),
        (12, 44.4000, 22.1000), (13, 52.4000, 40.2000),
    ]
    xml = ['<?xml version="1.0"?><osm version="0.6">']
    for node_id, lat, lon in nodes:
        xml.append(f'<node id="{node_id}" lat="{lat}" lon="{lon}"/>')
    xml += [
        '<way id="100">' + ''.join(f'<nd ref="{n}"/>' for n in (1, 2, 3, 4, 5)) +
        '<tag k="highway" v="residential"/><tag k="name" v="вулиця Соборності"/></way>',
        '<way id="101">' + ''.join(f'<nd ref="{n}"/>' for n in (5, 6, 7, 8, 9)) +
        '<tag k="highway" v="residential"/><tag k="name" v="вулиця Героїв АТО"/></way>',
        '<way id="102"><nd ref="10"/><nd ref="11"/><tag k="highway" v="primary"/><tag k="name" v="Київ"/></way>',
        '</osm>',
    ]
    with gzip.open(destination, "wb") as stream:
        stream.write(''.join(xml).encode('utf-8'))
    return {"status": "PASS_FIXTURE", "whole_source": True}


class UkraineNationalBuildTests(unittest.TestCase):
    def test_published_recovery_rehashes_source_and_extract_without_reimport(self) -> None:
        with tempfile.TemporaryDirectory(dir=build_ukraine.PROJECT_ROOT / "work") as folder:
            root = Path(folder)
            project = root / "project"
            output = project / "work" / "ukraine"
            output.mkdir(parents=True)
            source = project / "data" / "ukraine-latest.osm.pbf"
            source.parent.mkdir(parents=True)
            source.write_bytes(b"immutable PBF fixture")
            extract = output / "ukraine.osm.gz"
            extract.write_bytes(b"immutable extract fixture")
            database = output / "ukraine.sqlite"
            source_hash = build_ukraine.sha256_file(source)
            extract_hash = build_ukraine.sha256_file(extract)
            with sqlite3.connect(database) as conn:
                conn.executescript("""
                    CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
                    CREATE TABLE build_checkpoint(key TEXT PRIMARY KEY,value TEXT NOT NULL);
                    CREATE TABLE nodes(id TEXT); CREATE TABLE ways(id TEXT);
                    CREATE TABLE way_nodes(id TEXT); CREATE TABLE edges(id TEXT);
                    CREATE TABLE features(id TEXT); CREATE TABLE feature_names(id TEXT);
                    CREATE TABLE relations(id TEXT);
                    CREATE INDEX idx_nodes_lat_lon ON nodes(id);
                    CREATE INDEX idx_edges_from ON edges(id);
                    CREATE INDEX idx_feature_names_normalized ON feature_names(id);
                """)
                conn.executemany("INSERT INTO meta VALUES(?,?)", [
                    ("source_pbf_sha256", source_hash), ("source_sha256", extract_hash),
                    ("node_count", "10"), ("way_count", "3"),
                    ("directed_edge_count", "4"), ("feature_count", "2"),
                    ("unresolved_node_refs", "0"), ("minimum_latitude", "44.4"),
                    ("minimum_longitude", "22.1"), ("maximum_latitude", "52.4"),
                    ("maximum_longitude", "40.2")])
                conn.executemany("INSERT INTO build_checkpoint VALUES(?,?)", [
                    ("source_pbf_sha256", source_hash), ("extract_sha256", extract_hash),
                    ("phase", "FINALIZE")])
            conn.close()
            with patch.object(build_ukraine, "PROJECT_ROOT", project), \
                 patch.object(build_ukraine, "SOURCE_PBF", source), \
                 patch.object(build_ukraine, "OSMStore") as osm_store, \
                 patch.object(build_ukraine, "_street_route_proof", return_value={"node_count": 5}):
                osm_store.return_value.search.return_value = [object()]
                proof = build_ukraine.verify_published_recovery(output,
                    expected_source_sha256=source_hash, expected_extract_sha256=extract_hash)
                self.assertEqual(proof["status"], "PASS")
                self.assertTrue(proof["source_sha256_unchanged"])
                self.assertEqual(proof["extract_sha256"], extract_hash)
                self.assertFalse(proof["independent_full_integrity_check_repeated"])
            self.assertEqual(build_ukraine.sha256_file(source), source_hash)

    def test_build_resume_and_readback_are_provenance_bound(self) -> None:
        with tempfile.TemporaryDirectory(dir=build_ukraine.PROJECT_ROOT / "work") as folder:
            root = Path(folder)
            fake_root = root / "project"
            data_dir = fake_root / "data" / "osm"
            data_dir.mkdir(parents=True)
            source = data_dir / "ukraine-latest.osm.pbf"
            source.write_bytes(b"dated read-only PBF test fixture")
            import hashlib
            source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
            meta_path = data_dir / "source.json"
            meta_path.write_text(json.dumps({"dataset_content_timestamp": "2026-09-08T20:21:01Z",
                "pbf_download": {"sha256": source_hash}}), encoding="utf-8")
            output_root = fake_root / "work" / "ukraine_national"
            with patch.object(build_ukraine, "PROJECT_ROOT", fake_root), \
                 patch.object(build_ukraine, "SOURCE_PBF", source), \
                 patch.object(build_ukraine, "SOURCE_METADATA", meta_path), \
                 patch.object(build_ukraine, "DEFAULT_OUTPUT_ROOT", output_root), \
                 patch.object(build_ukraine, "extract_city", side_effect=_write_fixture_extract):
                result = build_ukraine.build(source, output_root)
                self.assertEqual(result["status"], "PASS_PENDING_INDEPENDENT_SUPERVISOR")
                self.assertEqual(result["source_pbf_sha256"], source_hash)
                self.assertEqual(result["sqlite_integrity_check"], "ok")
                self.assertGreater(result["counts"]["directed_edges"], 0)
                self.assertEqual(result["kryvyi_rih_route"]["node_count"], 5)
                second = build_ukraine.build(source, output_root)
                self.assertEqual(second["status"], "PASS_PENDING_INDEPENDENT_SUPERVISOR")
                self.assertEqual(second["database_sha256"], result["database_sha256"])
                proof = build_ukraine.verify_snapshot(fake_root / result["output_directory"],
                    expected_source_sha256=source_hash)
                self.assertTrue(proof["read_only_readback"])
                self.assertEqual(source.read_bytes(), b"dated read-only PBF test fixture")


if __name__ == "__main__":
    unittest.main()
