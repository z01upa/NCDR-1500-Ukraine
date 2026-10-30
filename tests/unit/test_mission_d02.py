from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from src.agent import project_director


class D02SourceManifestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[2] / "work")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        data = self.root / "data" / "osm"
        data.mkdir(parents=True)
        self.source = data / "ukraine-latest.osm.pbf"
        self.source_bytes = b"deterministic offline PBF fixture\x00\x01"
        self.source.write_bytes(self.source_bytes)
        self.source_hash = hashlib.sha256(self.source_bytes).hexdigest()
        self.metadata = data / "source.json"
        self.output = self.root / "osm" / "source-manifest.json"

    def _write_metadata(self, *, content_time: str | None, retrieved: str | None) -> None:
        record = {
            "source_url": "https://download.geofabrik.de/europe/ukraine-latest.osm.pbf",
            "dataset_content_timestamp": content_time,
            "pbf_download": {
                "url": "https://download.geofabrik.de/europe/ukraine-latest.osm.pbf",
                "retrieved_utc": retrieved,
                "sha256": self.source_hash,
                "bytes": len(self.source_bytes),
            },
        }
        self.metadata.write_text(json.dumps(record), encoding="utf-8")

    def _patched_project(self):
        return patch.multiple(project_director,
            PROJECT_ROOT=self.root, SOURCE_PBF=self.source)

    def test_manifest_binds_saved_provenance_hash_and_size_without_network(self) -> None:
        self._write_metadata(content_time="2026-09-08T20:21:01Z (reported upstream content timestamp)",
                             retrieved="2026-09-09T12:00:00Z")
        source_before = (self.source.read_bytes(), self.source.stat().st_size,
                         self.source.stat().st_mtime_ns)
        with self._patched_project(), \
             patch("urllib.request.urlopen", side_effect=AssertionError("network access")), \
             patch("urllib.request.urlretrieve", side_effect=AssertionError("network access")):
            result = project_director.write_d02_source_manifest()
            manifest = json.loads(self.output.read_text(encoding="utf-8"))
            verified = project_director.verify_d02_source_manifest()
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(verified["status"], "PASS")
        self.assertEqual(manifest["source_pbf_sha256"], self.source_hash)
        self.assertEqual(manifest["source_pbf_bytes"], len(self.source_bytes))
        self.assertEqual(manifest["dataset_content_timestamp"], "2026-09-08T20:21:01Z")
        self.assertEqual(manifest["retrieved_utc"], "2026-09-09T12:00:00Z")
        self.assertEqual(manifest["license"], "Open Database License (ODbL)")
        self.assertEqual(manifest["attribution"], "© OpenStreetMap contributors")
        self.assertEqual(source_before,
                         (self.source.read_bytes(), self.source.stat().st_size,
                          self.source.stat().st_mtime_ns))

    def test_unknown_timestamps_are_not_inferred_from_file_dates(self) -> None:
        self._write_metadata(content_time=None, retrieved=None)
        with self._patched_project():
            project_director.write_d02_source_manifest()
        manifest = json.loads(self.output.read_text(encoding="utf-8"))
        self.assertEqual(manifest["dataset_content_timestamp"], "NOT_RECORDED")
        self.assertEqual(manifest["retrieved_utc"], "NOT_RECORDED")

    def test_malformed_manifest_fails_and_source_remains_unchanged(self) -> None:
        self._write_metadata(content_time=None, retrieved=None)
        self.output.parent.mkdir(parents=True)
        self.output.write_text("{}\n", encoding="utf-8")
        before = hashlib.sha256(self.source.read_bytes()).hexdigest()
        with self._patched_project():
            with self.assertRaisesRegex(ValueError, "schema mismatch"):
                project_director.verify_d02_source_manifest()
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(), before)
        self.assertEqual(self.source.read_bytes(), self.source_bytes)

    def test_mission_runner_registers_manifest_under_the_safe_report_root(self) -> None:
        self._write_metadata(content_time=None, retrieved=None)
        report_path = self.root / "reports" / "mission_pack" / "runtime" / "D02_source_manifest.json"
        database = self.root / "state.sqlite"
        connection = sqlite3.connect(database)
        connection.execute("""CREATE TABLE autonomy_artifacts(
            task_id TEXT, path TEXT, sha256 TEXT, size_bytes INTEGER,
            description TEXT, acceptance TEXT, created_utc TEXT,
            PRIMARY KEY(task_id,path))""")
        connection.commit()

        def connect_fixture():
            return connection

        try:
            with self._patched_project(), \
                 patch.object(project_director.manager, "PROJECT_ROOT", self.root), \
                 patch.object(project_director.manager, "MANAGER_WORK", self.root / "work"), \
                 patch.object(project_director.manager, "_connect", side_effect=connect_fixture):
                result = project_director.execute_osm_source_provenance(
                    "D02-fixture", source_path=self.source, metadata_path=self.metadata,
                    output_path=report_path)
            row = connection.execute(
                "SELECT path,sha256,size_bytes FROM autonomy_artifacts WHERE task_id=?",
                ("D02-fixture",)).fetchone()
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["manifest_path"], "reports/mission_pack/runtime/D02_source_manifest.json")
            self.assertEqual(row[0], "reports\\mission_pack\\runtime\\D02_source_manifest.json")
            self.assertEqual(row[1], result["manifest_sha256"])
            self.assertEqual(row[2], report_path.stat().st_size)
        finally:
            connection.close()


if __name__ == "__main__":
    unittest.main()
