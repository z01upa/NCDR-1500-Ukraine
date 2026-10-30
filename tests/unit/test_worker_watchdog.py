from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from windows import worker_watchdog


class WorkerWatchdogTests(unittest.TestCase):
    def test_stop_waits_for_active_worker_instead_of_abandoning_its_lease(self) -> None:
        class Child:
            pid = 4321
            returncode = None
            waits = 0
            def poll(self):
                return self.returncode
            def wait(self, timeout):
                self.waits += 1
                if self.waits == 1:
                    raise subprocess.TimeoutExpired("worker", timeout)
                self.returncode = 0
                return 0

        child = Child()
        self.assertEqual(worker_watchdog._wait_for_worker_exit(child), (False, None))
        self.assertEqual(worker_watchdog._wait_for_worker_exit(child), (True, 0))

    def test_worker_environment_removes_codex_cli_and_forces_utf8(self) -> None:
        codex_bin = str(Path.home() / "Codex" / "bin" / "build")
        python_bin = r"C:\Python313"
        with mock.patch.dict(os.environ, {"PATH": os.pathsep.join((codex_bin, python_bin))}, clear=False):
            env = worker_watchdog._worker_environment()
        self.assertEqual(env["PATH"], python_bin)
        self.assertEqual(env["PYTHONUTF8"], "1")
        self.assertEqual(env["PYTHONIOENCODING"], "utf-8:backslashreplace")
        self.assertEqual(env["PYTHONDONTWRITEBYTECODE"], "1")

    def test_direct_task_scheduler_script_bootstraps_project_import_path(self) -> None:
        source = (PROJECT_ROOT / "windows" / "worker_watchdog.py").read_text(encoding="utf-8")
        self.assertIn("sys.path.insert(0, str(PROJECT_ROOT))", source)
        self.assertLess(source.index("sys.path.insert(0, str(PROJECT_ROOT))"),
                        source.index("def _resume_on_logon"))

    def test_watchdog_reads_saved_run_state_and_logs_restart_evidence(self) -> None:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as temporary:
            root = Path(temporary)
            state_db = root / "state.sqlite"
            conn = sqlite3.connect(state_db)
            try:
                conn.execute("CREATE TABLE autonomy_control(singleton INTEGER PRIMARY KEY, desired_state TEXT)")
                conn.execute("INSERT INTO autonomy_control VALUES(1,'RUNNING')")
                conn.commit()
            finally:
                conn.close()
            log_path = root / "watchdog.jsonl"
            with mock.patch.object(worker_watchdog, "STATE_DB", state_db), \
                 mock.patch.object(worker_watchdog, "LOG_PATH", log_path):
                self.assertEqual(worker_watchdog._desired_state(), "RUNNING")
                worker_watchdog._log_event("worker_started", worker_pid=2468)
            event = json.loads(log_path.read_text(encoding="utf-8"))
            self.assertEqual(event["event"], "worker_started")
            self.assertEqual(event["worker_pid"], 2468)

    def test_logon_resumes_a_stopped_checkpoint_but_keeps_explicit_pause(self) -> None:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as temporary:
            state_db = Path(temporary) / "state.sqlite"
            conn = sqlite3.connect(state_db)
            try:
                conn.execute("CREATE TABLE autonomy_control(singleton INTEGER PRIMARY KEY, desired_state TEXT)")
                conn.execute("INSERT INTO autonomy_control VALUES(1,'STOPPED')")
                conn.commit()
            finally:
                conn.close()
            from src.agent import autonomous_manager
            def persist_control(state: str) -> None:
                conn = sqlite3.connect(state_db)
                try:
                    conn.execute("UPDATE autonomy_control SET desired_state=? WHERE singleton=1", (state,))
                    conn.commit()
                finally:
                    conn.close()
            with mock.patch.object(worker_watchdog, "STATE_DB", state_db), \
                 mock.patch.object(worker_watchdog, "_worker_lock_held", return_value=False), \
                 mock.patch.object(autonomous_manager, "set_control", side_effect=persist_control) as set_control, \
                 mock.patch.object(worker_watchdog, "LOG_PATH", Path(temporary) / "watchdog.jsonl"):
                self.assertEqual(worker_watchdog._resume_on_logon(), "RUNNING")
                self.assertEqual(worker_watchdog._desired_state(), "RUNNING")
                set_control.assert_called_once_with("RUNNING")
                event = json.loads((Path(temporary) / "watchdog.jsonl").read_text(encoding="utf-8"))
                self.assertEqual(event["event"], "logon_resume")
                autonomous_manager.set_control("PAUSED")
                self.assertEqual(worker_watchdog._resume_on_logon(), "PAUSED")
                self.assertEqual(worker_watchdog._desired_state(), "PAUSED")


if __name__ == "__main__":
    unittest.main()
