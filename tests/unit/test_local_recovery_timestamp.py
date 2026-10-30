"""Regression for the fixed-code OSM published-checkpoint requeue (no large files)."""
from __future__ import annotations

import json
from contextlib import closing
import sqlite3
import tempfile
from pathlib import Path
import unittest
from unittest import mock

from src.agent import autonomous_manager, state_store


class PublishedRecoveryRegression(unittest.TestCase):
    TASK = "AUTO_OSM_NATIONAL_PUBLISHED_RECOVERY_01"
    ERROR = "RuntimeError: {'error': \"NameError: name '_source_content_timestamp' is not defined\"}"

    def test_only_exact_fixed_osm_error_can_be_requeued(self):
        reason = autonomous_manager._known_recovery_reason(self.TASK, self.ERROR)
        self.assertIsNotNone(reason)
        self.assertIn("manager-osm-timestamp-v2", reason)
        self.assertIsNone(autonomous_manager._known_recovery_reason(
            "F1_TARGET_COMPATIBILITY", self.ERROR))
        self.assertIsNone(autonomous_manager._known_recovery_reason(
            self.TASK, "RuntimeError: PBF SHA-256 differs from manifest"))

    def test_missing_import_must_not_unblock_job(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            osm = root / "src" / "osm" / "build_ukraine.py"
            director = root / "src" / "agent" / "project_director.py"
            osm.parent.mkdir(parents=True)
            director.parent.mkdir(parents=True)
            osm.write_text("def _source_content_timestamp(): return 'unknown'\n")
            director.write_text("def execute_osm_national_conversion(task_id): return task_id\n")
            with mock.patch.object(autonomous_manager, "PROJECT_ROOT", root):
                self.assertIsNone(autonomous_manager._known_recovery_reason(self.TASK, self.ERROR))

    def test_once_only_marker_blocks_repeat(self):
        with tempfile.TemporaryDirectory() as folder:
            db = Path(folder) / "checkpoint.sqlite"
            with closing(sqlite3.connect(db)) as conn, conn:
                conn.executescript("""
                    CREATE TABLE tasks(id TEXT PRIMARY KEY,status TEXT,result_json TEXT,priority INTEGER);
                    CREATE TABLE autonomy_events(id INTEGER PRIMARY KEY AUTOINCREMENT,event TEXT,task_id TEXT,detail_json TEXT);
                """)
                conn.execute("INSERT INTO tasks VALUES(?,?,?,?)",
                    (self.TASK, "BLOCKED", json.dumps({"error": self.ERROR}), 1))
            with mock.patch.object(state_store, "requeue_task") as requeue:
                found = autonomous_manager.recover_known_code_blockers(db)
                self.assertEqual(found, [self.TASK])
                requeue.assert_called_once()
            # Persisted once-only evidence is respected on subsequent polls.
            with closing(sqlite3.connect(db)) as conn, conn:
                conn.execute("INSERT INTO autonomy_events(event,task_id,detail_json) VALUES(?,?,?)",
                    ("known_blocker_recovered", self.TASK,
                     json.dumps({"reason": "manager-osm-timestamp-v2: previously retried"})))
            with mock.patch.object(state_store, "requeue_task") as requeue:
                self.assertEqual(autonomous_manager.recover_known_code_blockers(db), [])
                requeue.assert_not_called()


if __name__ == "__main__":
    unittest.main()
