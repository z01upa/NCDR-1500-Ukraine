from __future__ import annotations

from datetime import datetime, timezone, timedelta
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest import mock

from src.agent import autonomous_gui_compact as gui
from src.agent import autonomous_manager as manager
from src.agent import resource_probe


class CompactGuiStatusTests(unittest.TestCase):
    def test_ai_indicator_uses_request_telemetry_and_staleness(self) -> None:
        now = datetime.now(timezone.utc)
        base = {"ollama_models": ["qwen3.5:9b"], "ollama_status_known": True, "events": []}
        self.assertEqual(gui.derive_ai_status({"ollama_status_known": False})["level"], "gray")
        self.assertEqual(gui.derive_ai_status(base)["level"], "yellow")
        active = dict(base, events=[{"id": 1, "event": "ollama_request_started",
            "created_utc": now.isoformat(), "detail_json": {"model": "qwen3.5:9b", "role": "project-director",
                "started_utc": now.isoformat()}}])
        self.assertEqual(gui.derive_ai_status(active, now_utc=now)["level"], "green")
        stale = dict(base, events=[{"id": 1, "event": "ollama_request_started",
            "created_utc": (now - timedelta(minutes=10)).isoformat(),
            "detail_json": {"started_utc": (now - timedelta(minutes=10)).isoformat()}}])
        self.assertEqual(gui.derive_ai_status(stale, now_utc=now)["level"], "gray")
        failed = dict(base, events=[{"id": 2, "event": "ollama_request_failed",
            "created_utc": now.isoformat(), "detail_json": {"error": "timeout"}}])
        self.assertEqual(gui.derive_ai_status(failed, now_utc=now)["level"], "red")
        old_failure = dict(base, events=[{"id": 3, "event": "ollama_request_failed",
            "created_utc": (now - timedelta(minutes=10)).isoformat(),
            "detail_json": {"error": "timeout"}}])
        self.assertEqual(gui.derive_ai_status(old_failure, now_utc=now)["level"], "yellow")
        self.assertEqual(gui.derive_ai_status(dict(base, ollama_error="offline"))["level"], "red")

    def test_research_indicator_requires_a_live_lease(self) -> None:
        state = {"control": {"desired_state": "RUNNING", "current_task": "task-a"},
                 "tasks": [{"id": "task-a", "status": "DONE"}],
                 "worker_lock_held": True,
                 "queue_diagnosis": {"status": "NO_TASKS", "pending_count": 0}}
        self.assertEqual(gui.derive_research_status(state)["level"], "yellow")
        state["tasks"] = [{"id": "task-a", "status": "LEASED"}]
        self.assertEqual(gui.derive_research_status(state)["level"], "green")
        state["control"]["current_task"] = None
        self.assertEqual(gui.derive_research_status(state)["level"], "red")
        state["queue_diagnosis"] = {"status": "READY", "pending_count": 1,
                                    "eligible_task_ids": ["task-next"]}
        self.assertEqual(gui.derive_research_status(state)["level"], "yellow")

    def test_gui_dashboard_snapshot_uses_query_only_database_access(self) -> None:
        with tempfile.TemporaryDirectory(dir=manager.PROJECT_ROOT / "work") as folder:
            database = Path(folder) / "readonly.sqlite"
            conn = sqlite3.connect(database)
            conn.executescript("""
                CREATE TABLE autonomy_control(singleton INTEGER,desired_state TEXT,worker_pid INTEGER,current_task TEXT);
                INSERT INTO autonomy_control VALUES(1,'RUNNING',77,NULL);
                CREATE TABLE tasks(id TEXT,stage TEXT,status TEXT,agent TEXT,hypothesis TEXT,verdict TEXT,
                    attempts INTEGER,retry_limit INTEGER,priority INTEGER,updated_utc TEXT,result_json TEXT,
                    budget_json TEXT,depends_on_json TEXT,next_action TEXT,heartbeat_utc TEXT);
                INSERT INTO tasks VALUES('AUTO_UNIT_GUI','F2','PENDING','deterministic','real hypothesis',
                    'PENDING',0,1,5,'2026-10-28T00:00:00+00:00','{}','{}','[]','run','');
                CREATE TABLE autonomy_events(id INTEGER,created_utc TEXT,event TEXT,severity TEXT,task_id TEXT,
                    session_id TEXT,detail_json TEXT);
                CREATE TABLE autonomy_artifacts(task_id TEXT,path TEXT,sha256 TEXT,size_bytes INTEGER,
                    description TEXT,acceptance TEXT,created_utc TEXT);
                CREATE TABLE stage_gates(stage TEXT,status TEXT,criteria_json TEXT,proof_json TEXT,updated_utc TEXT);
                CREATE TABLE evidence(id INTEGER);
                CREATE TABLE model_runs(id INTEGER);
            """)
            conn.commit()
            conn.close()
            with mock.patch.object(manager, "STATE_DB", database), \
                 mock.patch.object(manager, "_national_osm_dashboard_progress", return_value={"phase": "IDLE", "percent": 0}), \
                 mock.patch.object(resource_probe, "resource_snapshot", return_value={"ram": {}, "gpu": None}):
                state = gui._read_only_dashboard_snapshot(include_model_telemetry=False)
            self.assertEqual(state["project"]["task_counts"]["PENDING"], 1)
            self.assertEqual(state["queue_diagnosis"]["eligible_task_ids"], ["AUTO_UNIT_GUI"])
            readonly = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)
            try:
                with self.assertRaises(sqlite3.OperationalError):
                    readonly.execute("INSERT INTO tasks(id,stage,status) VALUES('x','F2','PENDING')")
            finally:
                readonly.close()


if __name__ == "__main__":
    unittest.main()
