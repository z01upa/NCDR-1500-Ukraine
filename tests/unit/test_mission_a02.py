from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.agent import project_director


class MissionA02Tests(unittest.TestCase):
    def test_a02_reports_saved_oom_review_checkpoint_and_bounded_memory_probe(self) -> None:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as temporary:
            root = Path(temporary)
            state_db = root / "project_state.sqlite"
            osm_dir = root / "work" / "ukraine_national" / "fixture"
            osm_dir.mkdir(parents=True)
            (osm_dir / "ukraine.sqlite").write_bytes(b"published sqlite fixture")
            raw = osm_dir / "ukraine.osm.raw"
            raw.write_bytes(b"<?xml version=\"1.0\"?>\n<osm version=\"0.6\">\n<node id=\"7\" lat=\"47.0\" lon=\"33.0\" />\n</osm>\n")
            source = root / "ukraine-latest.osm.pbf"
            source.write_bytes(b"fixture PBF")
            review_result = {"status": "PASS", "source_task": "AUTO_OSM_NATIONAL_CONVERSION_01",
                "error": "ParseError: out of memory: line 3, column 0",
                "root_cause_class": "MEMORY_MONOLITH", "checkpoint_token": "cp-822ba7a5",
                "model_output_executed": False}
            conversion_budget = {"source_path": "data/osm/ukraine-latest.osm.pbf",
                "source_pbf_sha256": "a" * 64, "extract_sha256": "b" * 64,
                "output_directory": "work/ukraine_national/fixture",
                "max_records_per_slice": 500000, "slice_budget_seconds": 180,
                "timeout_s": 900, "resume_checkpoint_artifact": "checkpoint.json"}
            conn = sqlite3.connect(state_db)
            try:
                conn.execute("CREATE TABLE tasks(id TEXT, status TEXT, result_json TEXT, budget_json TEXT)")
                conn.execute("INSERT INTO tasks VALUES(?,?,?,?)", (
                    "AUTO_OSM_FAILURE_REVIEW_FIXTURE", "DONE", json.dumps(review_result),
                    json.dumps({"osm_failure_review": True})))
                conn.execute("INSERT INTO tasks VALUES(?,?,?,?)", (
                    "AUTO_OSM_NATIONAL_CONVERSION_01", "DONE",
                    json.dumps({"status": "CONTINUE", "checkpoint_token": "cp-822ba7a5"}),
                    json.dumps(conversion_budget)))
                conn.commit()
            finally:
                conn.close()

            def artifact(task_id: str, path: Path, description: str, acceptance: str) -> dict[str, object]:
                return {"path": path.relative_to(root).as_posix(),
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "size_bytes": path.stat().st_size, "description": description,
                    "acceptance": acceptance}

            with mock.patch.object(project_director, "PROJECT_ROOT", root), \
                 mock.patch.object(project_director, "STATE_DB", state_db), \
                 mock.patch.object(project_director, "WORK_ROOT", root / "work"), \
                 mock.patch.object(project_director, "SOURCE_PBF", source), \
                 mock.patch.object(project_director.manager, "_task", return_value={"id": "AUTO_A02_FIXTURE", "budget": {"mission_pack_task": "A02"}}), \
                 mock.patch.object(project_director.manager, "_artifact", side_effect=artifact):
                result = project_director.execute_mission_pack_task("AUTO_A02_FIXTURE")

            self.assertEqual(result["status"], "PASS")
            diagnosis = result["acceptance"]["osm_oom_diagnosis"]
            self.assertEqual(diagnosis["root_cause_class"], "MEMORY_MONOLITH")
            self.assertEqual(diagnosis["failure_line"]["line_number"], 3)
            self.assertEqual(diagnosis["failure_line"]["element_type"], "node")
            self.assertEqual(diagnosis["checkpoint"]["token"], "cp-822ba7a5")
            self.assertIsNone(diagnosis["memory"]["historical_peak_working_set_bytes"])
            self.assertGreater(diagnosis["memory"]["diagnostic_peak_working_set_bytes"], 0)
            self.assertEqual(result["acceptance"]["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
