from __future__ import annotations

import json
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from src.agent import autonomous_layout


class AutonomousLayoutTests(unittest.TestCase):
    def test_layout_projects_queue_without_copying_authoritative_sqlite(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[2] / "work") as folder:
            root = Path(folder)
            state_db = root / "project_state.sqlite"
            with closing(sqlite3.connect(state_db)) as conn:
                conn.execute("CREATE TABLE tasks(id TEXT,status TEXT)")
                conn.executemany("INSERT INTO tasks VALUES(?,?)", [
                    ("LOCAL-1", "PENDING"), ("CODEX-1", "WAITING_CODEX_QUOTA")])
                conn.commit()
            layout = autonomous_layout.ensure_layout(root)
            projected = autonomous_layout.sync_active_tasks(state_db, project_root=root)
            self.assertEqual(projected, 2)
            pending = json.loads((layout / "TASKS" / "INBOX" / "LOCAL-1.json").read_text(encoding="utf-8"))
            quota = json.loads((layout / "TASKS" / "WAITING_CODEX_QUOTA" / "CODEX-1.json").read_text(encoding="utf-8"))
            self.assertEqual(pending["authoritative_record"], "project_state.sqlite:tasks")
            self.assertEqual(quota["status"], "WAITING_CODEX_QUOTA")
            self.assertFalse((layout / "project_state.sqlite").exists())

    def test_verified_checkpoint_moves_result_to_verified_and_records_hash(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[2] / "work") as folder:
            root = Path(folder)
            result = {"status": "PASS", "artifact_path": "reports/result.json"}
            checkpoint = autonomous_layout.persist_checkpoint(
                "TASK-OK", "DONE", result, state_db=root / "project_state.sqlite",
                verified=True, project_root=root)
            layout = root / "AUTONOMOUS_RESEARCH"
            verified = json.loads((layout / "RESULTS" / "VERIFIED" / "TASK-OK.json").read_text(encoding="utf-8"))
            self.assertEqual(checkpoint["result_sha256"], verified["result_sha256"])
            self.assertTrue(verified["verified_by_independent_reviewer"])
            self.assertFalse((layout / "RESULTS" / "NEW" / "TASK-OK.json").exists())
            latest = json.loads((layout / "STATE" / "latest_checkpoint.json").read_text(encoding="utf-8"))
            self.assertEqual(latest["task_id"], "TASK-OK")
            self.assertEqual(latest["artifact_pointers"], ["reports/result.json"])

    def test_worker_resume_checkpoint_points_to_sqlite_and_latest_completed_task(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[2] / "work") as folder:
            root = Path(folder)
            state_db = root / "project_state.sqlite"
            with closing(sqlite3.connect(state_db)) as conn:
                conn.execute("CREATE TABLE autonomy_control(singleton INTEGER PRIMARY KEY,desired_state TEXT,worker_pid INTEGER,current_task TEXT,updated_utc TEXT)")
                conn.execute("INSERT INTO autonomy_control VALUES(1,'RUNNING',1234,NULL,'2026-10-27T00:00:00Z')")
                conn.execute("CREATE TABLE tasks(id TEXT,status TEXT,updated_utc TEXT)")
                conn.execute("INSERT INTO tasks VALUES('VERIFIED-1','DONE','2026-10-26T23:59:00Z')")
                conn.commit()
            snapshot = autonomous_layout.persist_manager_checkpoint(state_db, "session-1", project_root=root)
            saved = json.loads((root / "AUTONOMOUS_RESEARCH" / "STATE" / "latest_checkpoint.json").read_text(encoding="utf-8"))
            self.assertEqual(snapshot, saved)
            self.assertEqual(saved["control"]["desired_state"], "RUNNING")
            self.assertEqual(saved["latest_completed_task"]["task_id"], "VERIFIED-1")
            self.assertEqual(saved["authoritative_state_db"], str(state_db.resolve()))


if __name__ == "__main__":
    unittest.main()
