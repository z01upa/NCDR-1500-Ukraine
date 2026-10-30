from __future__ import annotations

from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.agent import project_director


class MissionA01Tests(unittest.TestCase):
    def test_baseline_records_model_inventory_without_global_name_lookup(self) -> None:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as temporary:
            root = Path(temporary)
            state_db = root / "project_state.sqlite"
            for name in ("project_state.sqlite", "TASK_BACKLOG.sqlite", "EVIDENCE_LEDGER.sqlite"):
                conn = sqlite3.connect(root / name)
                try:
                    if name == "project_state.sqlite":
                        conn.execute("CREATE TABLE tasks(id TEXT,status TEXT,result_json TEXT)")
                    else:
                        conn.execute("CREATE TABLE integrity_fixture(value TEXT)")
                finally:
                    conn.close()
            task = {"id": "A01-fixture", "budget": {"mission_pack_task": "A01"}}
            with mock.patch.object(project_director, "PROJECT_ROOT", root), \
                 mock.patch.object(project_director, "STATE_DB", state_db), \
                 mock.patch.object(project_director.manager, "_task", return_value=task), \
                 mock.patch.object(project_director.manager, "_control", return_value={"worker_pid": 123}), \
                 mock.patch.object(project_director.manager, "available_models", return_value=(["qwen-fixture"], None)), \
                 mock.patch.object(project_director.manager, "_artifact", return_value={"path": "baseline.json"}), \
                 mock.patch.object(project_director.manager.shutil, "which", return_value=None), \
                 mock.patch.object(project_director.subprocess, "run",
                                   return_value=mock.Mock(returncode=1, stdout="", stderr="")):
                result = project_director.execute_mission_pack_task(task["id"])
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["acceptance"]["available_local_models"], ["qwen-fixture"])

    def test_baseline_keeps_running_when_scheduled_path_has_no_git(self) -> None:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as temporary:
            root = Path(temporary)
            state_db = root / "project_state.sqlite"
            for name in ("project_state.sqlite", "TASK_BACKLOG.sqlite", "EVIDENCE_LEDGER.sqlite"):
                conn = sqlite3.connect(root / name)
                try:
                    if name == "project_state.sqlite":
                        conn.execute("CREATE TABLE tasks(id TEXT,status TEXT,result_json TEXT)")
                    else:
                        conn.execute("CREATE TABLE integrity_fixture(value TEXT)")
                finally:
                    conn.close()
            task = {"id": "A01-no-git-fixture", "budget": {"mission_pack_task": "A01"}}
            with mock.patch.object(project_director, "PROJECT_ROOT", root), \
                 mock.patch.object(project_director, "STATE_DB", state_db), \
                 mock.patch.object(project_director.manager, "_task", return_value=task), \
                 mock.patch.object(project_director.manager, "_control", return_value={"worker_pid": 123}), \
                 mock.patch.object(project_director.manager, "available_models", return_value=(["qwen-fixture"], None)), \
                 mock.patch.object(project_director.manager, "_artifact", return_value={"path": "baseline.json"}), \
                 mock.patch.object(project_director.manager.shutil, "which", return_value=None), \
                 mock.patch.object(project_director.subprocess, "run",
                                   side_effect=FileNotFoundError(2, "git executable missing")):
                result = project_director.execute_mission_pack_task(task["id"])
            self.assertEqual(result["status"], "PASS")
            self.assertIsNone(result["acceptance"]["git_commit"])
            self.assertFalse(result["acceptance"]["git_probe"]["available"])
            self.assertIn("FileNotFoundError", result["acceptance"]["git_probe"]["error"])


if __name__ == "__main__":
    unittest.main()
