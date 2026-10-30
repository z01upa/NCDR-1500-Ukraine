from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))
SPEC = importlib.util.spec_from_file_location(
    "autonomy_soak_monitor", PROJECT_ROOT / "work" / "autonomy_soak_monitor.py")
assert SPEC and SPEC.loader
autonomy_soak_monitor = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(autonomy_soak_monitor)


class AutonomySoakMonitorTests(unittest.TestCase):
    def test_full_payload_cycle_requires_the_next_actual_director_after_verifier(self) -> None:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as temporary:
            root = Path(temporary)
            database = root / "state.sqlite"
            artifact = root / "profiles" / "payload.json"
            artifact.parent.mkdir()
            payload = b'{"bounded":"read-only payload census"}\n'
            artifact.write_bytes(payload)
            digest = hashlib.sha256(payload).hexdigest()
            conn = sqlite3.connect(database)
            conn.executescript("""
                CREATE TABLE autonomy_control(singleton INTEGER PRIMARY KEY, desired_state TEXT,
                    worker_pid INTEGER, session_id TEXT, current_task TEXT, health_json TEXT,
                    last_error TEXT, updated_utc TEXT);
                INSERT INTO autonomy_control VALUES(1,'RUNNING',10,'session-2',NULL,
                    '{"ollama_models":["qwen3.5:9b","qwen3.5:4b"],"codex_cli":null}','',
                    '2026-10-27T15:00:00+00:00');
                CREATE TABLE codex_call_ledger(created_utc TEXT);
                CREATE TABLE tasks(id TEXT PRIMARY KEY,status TEXT,verdict TEXT,created_utc TEXT,
                    updated_utc TEXT,result_json TEXT);
            """)
            director_id = "AUTO_DIRECTOR_NCDX_DATA_TEST"
            target_id = "AUTO_NCDX_DATA_MG1_ZLIB_DECODED_COORDINATE_CANDIDATE_CENSUS_TEST"
            supervisor_id = f"AUTO_SUPERVISOR_{target_id}"
            director_result = {"status": "PASS", "model": "qwen3.5:9b",
                "selected_goal_id": target_id, "next_task_id": target_id}
            target_result = {"status": "PASS", "profile_mode": "ZLIB_DECODED_COORDINATE_CANDIDATE_CENSUS",
                "original_media_write_count": 0,
                "profile_parameters": {"tier": "selected_full_payload_audit", "batch_index": 4},
                "artifact": {"path": "profiles/payload.json", "sha256": digest}}
            supervisor_result = {"status": "PASS", "model": "qwen3.5:4b",
                "target_task": target_id, "followup_created": False,
                "deterministic_verification": {"deterministic_proof": {
                    "fresh_manifest_bound_coordinate_rescan": True,
                    "fresh_selected_full_payload_audit": True,
                    "selected_stream_count_by_region": {"SW": 2, "Italy": 0, "Scandinavia": 0},
                    "original_media_write_count": 0}}}
            rows = [
                (director_id, "DONE", "PASS", "2026-10-27T14:59:00+00:00",
                 "2026-10-27T15:00:00+00:00", json.dumps(director_result)),
                (target_id, "DONE", "PASS", "2026-10-27T15:00:00+00:00",
                 "2026-10-27T15:00:30+00:00", json.dumps(target_result)),
                (supervisor_id, "DONE", "PASS", "2026-10-27T15:00:30+00:00",
                 "2026-10-27T15:01:00+00:00", json.dumps(supervisor_result)),
                ("AUTO_DIRECTOR_NCDX_DATA_NEXT", "PENDING", "PENDING",
                 "2026-10-27T15:01:01+00:00", "2026-10-27T15:01:01+00:00", "{}"),
            ]
            conn.executemany("INSERT INTO tasks VALUES(?,?,?,?,?,?)", rows)
            conn.commit()
            conn.close()
            with mock.patch.object(autonomy_soak_monitor, "ROOT", root), \
                 mock.patch.object(autonomy_soak_monitor, "STATE_DB", database), \
                 mock.patch.object(autonomy_soak_monitor, "_worker_lock_held", return_value=True):
                current = autonomy_soak_monitor.snapshot(
                    datetime(2026, 10, 27, 14, 30, tzinfo=timezone.utc), "session-1")
        self.assertTrue(current["worker"]["worker_lock_held"])
        cycles = current["verified_continuing_full_payload_cycles"]
        self.assertEqual(len(cycles), 1)
        self.assertEqual(cycles[0]["continuation_director_task_id"], "AUTO_DIRECTOR_NCDX_DATA_NEXT")
        self.assertEqual(cycles[0]["continuation_director_status"], "PENDING")


if __name__ == "__main__":
    unittest.main()
