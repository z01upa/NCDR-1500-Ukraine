from __future__ import annotations

import sqlite3
import sys
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.agent import capability_broker, project_director
from src.agent.failure_triage import classify_failure


class MissionA05Tests(unittest.TestCase):
    def test_historical_errors_are_classified_and_blank_diagnostics_wait_for_evidence(self) -> None:
        cases = {
            "NameError: name 'available_models' is not defined": "CODE_DEFECT",
            "RuntimeError: stale OSM continuation token": "DATA",
            "KeyError: 'IL'": "CODE_DEFECT",
            "ScriptRejected: script field is missing or too large": "TEST_FAILURE",
            "task exceeded 900 seconds; задача перевищила ліміт 900 секунд": "TIMEOUT",
        }
        for error, expected in cases.items():
            with self.subTest(error=error):
                self.assertEqual(classify_failure(error)["class"], expected)
                self.assertTrue(classify_failure(error)["matched_rules"])
        self.assertEqual(classify_failure("")["class"], "WAITING_EXTERNAL")
        self.assertTrue(classify_failure("")["matched_rules"])
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as temporary:
            root = Path(temporary)
            state_db = root / "project_state.sqlite"
            conn = sqlite3.connect(state_db)
            try:
                conn.execute("CREATE TABLE tasks(id TEXT, status TEXT, result_json TEXT)")
                rows = (
                    ("AUTO_A01", "NameError: name 'available_models' is not defined"),
                    ("AUTO_OSM", "RuntimeError: stale OSM continuation token"),
                    ("AUTO_PROBE", "KeyError: 'IL'"),
                    ("AUTO_SCRIPT", "ScriptRejected: script field is missing or too large"),
                    ("AUTO_TIMEOUT", "task exceeded 900 seconds; задача перевищила ліміт 900 секунд"),
                    ("F1_TARGET_COMPATIBILITY", ""),
                )
                for task_id, error in rows:
                    payload = "{}" if not error else json.dumps({"error": error})
                    conn.execute("INSERT INTO tasks VALUES(?,?,?)", (task_id, "BLOCKED", payload))
                conn.commit()
            finally:
                conn.close()
            with mock.patch.object(project_director, "PROJECT_ROOT", root), \
                 mock.patch.object(project_director, "STATE_DB", state_db), \
                 mock.patch.object(project_director.manager, "_task", return_value={
                     "id": "AUTO_A05_FIXTURE", "budget": {"mission_pack_task": "A05"}}), \
                 mock.patch.object(capability_broker, "create_request") as create_request:
                result = project_director.execute_mission_pack_task("AUTO_A05_FIXTURE")
            self.assertEqual(result["status"], "WAITING_EXTERNAL")
            self.assertIn("diagnostic", result["reason"].casefold())
            create_request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
