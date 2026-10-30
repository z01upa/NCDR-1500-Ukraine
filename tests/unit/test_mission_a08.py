from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.agent import project_director


class MissionA08Tests(unittest.TestCase):
    def test_manager_window_match_does_not_count_an_explorer_zip_title(self) -> None:
        self.assertTrue(project_director._is_manager_window_title("NCDR Autonomous Research Manager"))
        self.assertFalse(project_director._is_manager_window_title("NCDR_AUTONOMOUS_MISSION_PACK_V2.zip — Провідник"))
        self.assertFalse(project_director._is_manager_window_title("NCDR_Autonomous_Research_Manager.zip — провідник"))

    def test_logon_task_watchdog_worker_and_closed_gui_are_independently_verified(self) -> None:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as temporary:
            root = Path(temporary)
            task_xml = root / "NCDR Autonomous Research Manager.xml"
            shortcut = root / "NCDR Autonomous Research Worker.lnk"
            watchdog_log = root / "worker_watchdog.jsonl"
            state_db = root / "project_state.sqlite"
            task_xml.write_text('''<?xml version="1.0"?>
<Task xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <Triggers><LogonTrigger><Enabled>true</Enabled></LogonTrigger></Triggers>
  <Settings><Enabled>true</Enabled><ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <RestartOnFailure><Interval>PT1M</Interval><Count>5</Count></RestartOnFailure></Settings>
  <Actions><Exec><Command>pythonw.exe</Command>
    <Arguments>-B "C:/NCDR/windows/worker_watchdog.py"</Arguments></Exec></Actions>
</Task>''', encoding="utf-8")
            shortcut.write_bytes(b"verified-startup-shortcut-fixture")
            watchdog_log.write_text("\n".join([
                json.dumps({"utc": "2026-10-26T14:36:35+00:00", "event": "watchdog_started", "watchdog_pid": 2800}),
                json.dumps({"utc": "2026-10-26T14:36:35+00:00", "event": "worker_started", "watchdog_pid": 2800, "worker_pid": 20604}),
            ]) + "\n", encoding="utf-8")
            with closing(sqlite3.connect(state_db)) as conn:
                conn.execute("CREATE TABLE autonomy_control(singleton INTEGER PRIMARY KEY, desired_state TEXT, worker_pid INTEGER)")
                conn.execute("INSERT INTO autonomy_control VALUES(1, 'RUNNING', 20604)")
                conn.commit()

            with mock.patch.object(project_director, "_autostart_pid_is_running", return_value=True), \
                 mock.patch.object(project_director, "_visible_manager_windows", return_value=[]):
                result = project_director.verify_autostart_acceptance(
                    task_xml_path=task_xml, startup_shortcut_path=shortcut,
                    watchdog_log_path=watchdog_log, state_db_path=state_db)

            self.assertEqual(result["status"], "PASS")
            self.assertTrue(result["task_scheduler_enabled"])
            self.assertEqual(result["trigger"], "LogonTrigger")
            self.assertTrue(result["startup_watchdog_shortcut_exists"])
            self.assertEqual(result["worker_pid"], 20604)
            self.assertTrue(result["worker_process_running"])
            self.assertEqual(result["visible_manager_window_count"], 0)
            self.assertEqual(result["watchdog_pid"], 2800)

    def test_default_watchdog_log_path_matches_installed_worker_log(self) -> None:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as temporary:
            root = Path(temporary)
            task_xml = root / "task.xml"
            shortcut = root / "worker.lnk"
            state_db = root / "project_state.sqlite"
            watchdog_log = root / "work" / "autonomous_manager" / "logs" / "worker_watchdog.jsonl"
            watchdog_log.parent.mkdir(parents=True)
            task_xml.write_text('''<Task xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
<Triggers><LogonTrigger><Enabled>true</Enabled></LogonTrigger></Triggers>
<Settings><Enabled>true</Enabled><ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
<RestartOnFailure><Interval>PT1M</Interval><Count>5</Count></RestartOnFailure></Settings>
<Actions><Exec><Command>pythonw.exe</Command><Arguments>-B "C:/NCDR/windows/worker_watchdog.py"</Arguments></Exec></Actions>
</Task>''', encoding="utf-8")
            shortcut.write_bytes(b"startup-shortcut")
            watchdog_log.write_text("\n".join([
                json.dumps({"event": "watchdog_started", "watchdog_pid": 2800}),
                json.dumps({"event": "worker_started", "watchdog_pid": 2800, "worker_pid": 20604}),
            ]) + "\n", encoding="utf-8")
            with closing(sqlite3.connect(state_db)) as conn:
                conn.execute("CREATE TABLE autonomy_control(singleton INTEGER PRIMARY KEY, desired_state TEXT, worker_pid INTEGER)")
                conn.execute("INSERT INTO autonomy_control VALUES(1, 'RUNNING', 20604)")
                conn.commit()

            with mock.patch.object(project_director, "PROJECT_ROOT", root), \
                 mock.patch.object(project_director, "_autostart_pid_is_running", return_value=True), \
                 mock.patch.object(project_director, "_visible_manager_windows", return_value=[]):
                result = project_director.verify_autostart_acceptance(
                    task_xml_path=task_xml, startup_shortcut_path=shortcut,
                    state_db_path=state_db)

            self.assertEqual(result["status"], "PASS")
            self.assertTrue(result["checks"]["watchdog_start_log"])

    def test_default_scheduler_file_and_log_paths_match_windows_install(self) -> None:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as temporary:
            root = Path(temporary)
            task_xml = root / "System32" / "Tasks" / "NCDR Autonomous Research Manager"
            task_xml.parent.mkdir(parents=True)
            shortcut = root / "worker.lnk"
            state_db = root / "project_state.sqlite"
            watchdog_log = root / "work" / "autonomous_manager" / "logs" / "worker_watchdog.jsonl"
            watchdog_log.parent.mkdir(parents=True)
            task_xml.write_text('''<Task xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
<Triggers><LogonTrigger><Enabled>true</Enabled></LogonTrigger></Triggers>
<Settings><Enabled>true</Enabled><ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
<RestartOnFailure><Interval>PT1M</Interval><Count>5</Count></RestartOnFailure></Settings>
<Actions><Exec><Command>pythonw.exe</Command><Arguments>-B "C:/NCDR/windows/worker_watchdog.py"</Arguments></Exec></Actions>
</Task>''', encoding="utf-8")
            shortcut.write_bytes(b"startup-shortcut")
            watchdog_log.write_text("\n".join([
                json.dumps({"event": "watchdog_started", "watchdog_pid": 2800}),
                json.dumps({"event": "worker_started", "watchdog_pid": 2800, "worker_pid": 20604}),
            ]) + "\n", encoding="utf-8")
            with closing(sqlite3.connect(state_db)) as conn:
                conn.execute("CREATE TABLE autonomy_control(singleton INTEGER PRIMARY KEY, desired_state TEXT, worker_pid INTEGER)")
                conn.execute("INSERT INTO autonomy_control VALUES(1, 'RUNNING', 20604)")
                conn.commit()

            with mock.patch.object(project_director, "PROJECT_ROOT", root), \
                 mock.patch.dict(os.environ, {"SystemRoot": str(root)}), \
                 mock.patch.object(project_director, "_autostart_pid_is_running", return_value=True), \
                 mock.patch.object(project_director, "_visible_manager_windows", return_value=[]):
                result = project_director.verify_autostart_acceptance(
                    startup_shortcut_path=shortcut, state_db_path=state_db)

            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["trigger"], "LogonTrigger")
            self.assertTrue(result["task_scheduler_enabled"])
            self.assertTrue(result["checks"]["watchdog_start_log"])

    def test_missing_worker_stays_waiting_external_and_does_not_claim_acceptance(self) -> None:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as temporary:
            root = Path(temporary)
            task_xml = root / "task.xml"
            shortcut = root / "worker.lnk"
            watchdog_log = root / "worker_watchdog.jsonl"
            state_db = root / "state.sqlite"
            task_xml.write_text('''<Task xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
<Triggers><LogonTrigger><Enabled>true</Enabled></LogonTrigger></Triggers>
<Settings><Enabled>true</Enabled><ExecutionTimeLimit>PT0S</ExecutionTimeLimit></Settings>
<Actions><Exec><Command>pythonw.exe</Command><Arguments>-B "C:/NCDR/windows/worker_watchdog.py"</Arguments></Exec></Actions>
</Task>''', encoding="utf-8")
            shortcut.write_bytes(b"shortcut")
            watchdog_log.write_text(json.dumps({"event": "worker_started", "watchdog_pid": 2800, "worker_pid": 20604}) + "\n", encoding="utf-8")
            with closing(sqlite3.connect(state_db)) as conn:
                conn.execute("CREATE TABLE autonomy_control(singleton INTEGER PRIMARY KEY, desired_state TEXT, worker_pid INTEGER)")
                conn.execute("INSERT INTO autonomy_control VALUES(1, 'RUNNING', 20604)")
                conn.commit()
            with mock.patch.object(project_director, "_autostart_pid_is_running", return_value=False), \
                 mock.patch.object(project_director, "_visible_manager_windows", return_value=[]):
                result = project_director.verify_autostart_acceptance(
                    task_xml_path=task_xml, startup_shortcut_path=shortcut,
                    watchdog_log_path=watchdog_log, state_db_path=state_db)
            self.assertEqual(result["status"], "WAITING_EXTERNAL")
            self.assertFalse(result["worker_process_running"])


if __name__ == "__main__":
    unittest.main()
