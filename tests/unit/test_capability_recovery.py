from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.agent import autonomous_manager, capability_broker, state_store


class CapabilityRecoveryTests(unittest.TestCase):
    def _retry_external_mission(self, *, canonical_id="A05", budget_id="A05",
                                agent="mission-pack-executor", failure_class="CODE_DEFECT",
                                repair_status="VERIFIED", repair_source="AUTO_A05",
                                mission_source="AUTO_A05"):
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as temporary:
            database = Path(temporary) / "state.sqlite"
            source = {
                "id": "AUTO_A05", "stage": "F2", "status": "DONE", "agent": agent,
                "priority": 10, "budget_json": json.dumps({"mission_pack_task": budget_id}),
                "result_json": json.dumps({"canonical_id": canonical_id,
                                           "status": "WAITING_EXTERNAL", "diagnostics": ""}),
                "depends_on_json": json.dumps(["ORIGINAL_DEPENDENCY"]),
                "evidence_json": json.dumps([{"original": "unchanged"}]),
                "deliverables_json": "[]", "objective_tests_json": '["deterministic verifier"]',
                "hypothesis": "Classify existing metadata", "next_action": "Verify A05",
            }
            with closing(sqlite3.connect(database)) as conn:
                columns = ",".join(f"{key} {'INTEGER' if key == 'priority' else 'TEXT'}"
                                   for key in source)
                conn.execute(f"CREATE TABLE tasks({columns})")
                conn.execute(f"INSERT INTO tasks VALUES({','.join('?' for _ in source)})",
                             tuple(source.values()))
                conn.execute("CREATE TABLE capability_requests(request_id TEXT, source_task_id TEXT, status TEXT, failure_class TEXT)")
                conn.execute("INSERT INTO capability_requests VALUES(?,?,?,?)",
                             ("CAP_REPAIR", repair_source, repair_status, failure_class))
                conn.execute("CREATE TABLE mission_tasks(canonical_id TEXT, status TEXT, runtime_task_id TEXT, evidence_json TEXT)")
                conn.execute("INSERT INTO mission_tasks VALUES(?,?,?,?)",
                             (budget_id, "WAITING_EXTERNAL", mission_source, '[{"mission": "original"}]'))
                conn.commit()

            def connect_fixture():
                conn = sqlite3.connect(database)
                conn.row_factory = sqlite3.Row
                return conn

            from src.agent import mission_pack
            with mock.patch.object(autonomous_manager, "_connect", side_effect=connect_fixture), \
                 mock.patch.object(state_store, "add_task", side_effect=[True, False]) as add_task, \
                 mock.patch.object(mission_pack, "mark_status") as mark_status:
                first = autonomous_manager._queue_repaired_source_task("AUTO_A05", "CODEX_REPAIR", "CAP_REPAIR")
                second = autonomous_manager._queue_repaired_source_task("AUTO_A05", "CODEX_REPAIR", "CAP_REPAIR")
            with closing(connect_fixture()) as conn:
                self.assertEqual(dict(conn.execute("SELECT * FROM tasks").fetchone()), source)
                self.assertEqual(dict(conn.execute("SELECT * FROM mission_tasks").fetchone()), {
                    "canonical_id": budget_id, "status": "WAITING_EXTERNAL",
                    "runtime_task_id": mission_source, "evidence_json": '[{"mission": "original"}]'})
            return first, second, add_task, mark_status, source

    def test_verified_a05_classifier_repair_requeues_once_and_preserves_evidence(self):
        first, second, add_task, mark_status, source = self._retry_external_mission()
        self.assertTrue(first["created"])
        self.assertFalse(second["created"])
        retry = add_task.call_args_list[0].args[0]
        self.assertEqual(retry, add_task.call_args_list[1].args[0])
        self.assertNotEqual(retry["id"], source["id"])
        self.assertEqual(first["task_id"], retry["id"])
        self.assertEqual(retry["depends_on"], ["CODEX_REPAIR", "ORIGINAL_DEPENDENCY"])
        self.assertEqual(retry["budget"]["mission_pack_task"], "A05")
        self.assertEqual(retry["tests"], ["deterministic verifier"])
        self.assertEqual(retry["evidence"][:-1], json.loads(source["evidence_json"]))
        self.assertEqual(retry["evidence"][-1]["previous_result"], json.loads(source["result_json"]))
        mark_status.assert_called_once()
        self.assertEqual(mark_status.call_args.args, ("A05", "RUNNING"))
        self.assertEqual(mark_status.call_args.kwargs["runtime_task_id"], retry["id"])
        evidence = mark_status.call_args.kwargs["evidence"]
        self.assertEqual(evidence["verifier"], "capability_patch_test_gate")
        self.assertEqual(evidence["verdict"], "PASS")
        self.assertEqual(evidence["capability_task_id"], "CODEX_REPAIR")
        self.assertEqual(evidence["previous_evidence"], [{"mission": "original"}])

    def test_external_retry_exception_requires_exact_a05_verified_code_repair(self):
        cases = [
            {"canonical_id": value, "budget_id": value} for value in ("A08", "E06", "A01")
        ] + [
            {"canonical_id": "A08"}, {"budget_id": "A08"},
            {"canonical_id": "a05"}, {"budget_id": "a05"},
            {"agent": "deterministic"}, {"failure_class": "TOOL_MISSING"},
            {"repair_status": "WAITING_CODEX"}, {"repair_source": "OTHER_A05"},
            {"mission_source": "OTHER_A05"},
        ]
        for overrides in cases:
            with self.subTest(**overrides):
                first, second, add_task, mark_status, _ = self._retry_external_mission(**overrides)
                self.assertFalse(first["created"])
                self.assertFalse(second["created"])
                add_task.assert_not_called()
                mark_status.assert_not_called()

    def _run_waiting_request(self, updated_utc: str, *, initial_status: str = "WAITING_CODEX",
                             prior_tasks: tuple[tuple[str, str], ...] = ()) -> tuple[list[dict], mock.Mock]:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as temporary:
            database = Path(temporary) / "state.sqlite"
            request_id = "CAP_1234567890ABCDEF"
            base_id = "AUTO_LOCAL_CAPABILITY_1234567890ABCDEF"
            payload = {"allowed_paths": ["src/agent/example.py"],
                       "test_paths": ["tests/unit/test_capability_recovery.py"]}
            with closing(sqlite3.connect(database)) as conn:
                conn.execute("CREATE TABLE capability_requests(request_id TEXT, source_task_id TEXT, status TEXT, payload_json TEXT, created_utc TEXT, updated_utc TEXT)")
                conn.execute("CREATE TABLE tasks(id TEXT PRIMARY KEY, status TEXT NOT NULL, agent TEXT NOT NULL DEFAULT 'unit-test', result_json TEXT NOT NULL DEFAULT '{}', budget_json TEXT NOT NULL DEFAULT '{}')")
                conn.execute("INSERT INTO capability_requests VALUES(?,?,?,?,?,?)",
                    (request_id, "AUTO_SOURCE", initial_status, json.dumps(payload), updated_utc, updated_utc))
                conn.execute("INSERT INTO tasks(id,status,result_json) VALUES(?,?,?)",
                    ("AUTO_SOURCE", "WAITING_LOCAL", json.dumps({"status": "WAITING_LOCAL"})))
                for task_id, status in prior_tasks:
                    conn.execute("INSERT INTO tasks(id,status) VALUES(?,?)", (task_id, status))
                conn.commit()

            def connect_fixture():
                conn = sqlite3.connect(database)
                conn.row_factory = sqlite3.Row
                return conn

            with mock.patch.object(autonomous_manager, "_connect", side_effect=connect_fixture), \
                 mock.patch.object(capability_broker, "ensure_schema"), \
                 mock.patch.object(autonomous_manager, "_event"), \
                 mock.patch.object(state_store, "add_task", return_value=True) as add_task:
                queued = autonomous_manager._queue_waiting_capability_requests(min_retry_age_s=180)
            return queued, add_task

    def test_codex_waiters_never_retry_without_new_evidence(self) -> None:
        old = (datetime.now(timezone.utc) - timedelta(seconds=181)).isoformat()
        for status in ("WAITING_CODEX", "WAITING_CODEX_QUOTA"):
            with self.subTest(status=status):
                queued, add_task = self._run_waiting_request(old, initial_status=status)
                self.assertEqual(queued, [])
                add_task.assert_not_called()

    def test_new_request_is_immediate_and_recent_failure_is_delayed(self) -> None:
        now = datetime.now(timezone.utc).isoformat()
        fresh, fresh_add = self._run_waiting_request(now, initial_status="NEW")
        self.assertEqual(len(fresh), 1)
        self.assertEqual(fresh[0]["attempt"], 1)
        fresh_add.assert_called_once()

        recent, recent_add = self._run_waiting_request(now, initial_status="WAITING_LOCAL",
            prior_tasks=(("AUTO_LOCAL_CAPABILITY_1234567890ABCDEF", "DONE"),))
        self.assertEqual(recent, [])
        recent_add.assert_not_called()

    def test_pending_attempt_prevents_duplicate_and_attempt_cap_is_kept(self) -> None:
        old = (datetime.now(timezone.utc) - timedelta(seconds=300)).isoformat()
        base = "AUTO_LOCAL_CAPABILITY_1234567890ABCDEF"
        queued, add_task = self._run_waiting_request(old,
            prior_tasks=((base, "LEASED"),))
        self.assertEqual(queued, [])
        add_task.assert_not_called()

        exhausted, exhausted_add = self._run_waiting_request(old,
            prior_tasks=((base, "DONE"), (base + "_R02", "DONE"), (base + "_R03", "DONE")))
        self.assertEqual(exhausted, [])
        exhausted_add.assert_not_called()

    def test_eligible_new_requests_are_not_starved_by_the_first_eight_old_requests(self) -> None:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as temporary:
            database = Path(temporary) / "state.sqlite"
            old = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
            with closing(sqlite3.connect(database)) as conn:
                conn.execute("CREATE TABLE capability_requests(request_id TEXT, source_task_id TEXT, status TEXT, payload_json TEXT, created_utc TEXT, updated_utc TEXT)")
                conn.execute("CREATE TABLE tasks(id TEXT PRIMARY KEY, status TEXT NOT NULL, agent TEXT NOT NULL DEFAULT 'unit-test', result_json TEXT NOT NULL DEFAULT '{}', budget_json TEXT NOT NULL DEFAULT '{}')")
                payload = {"allowed_paths": ["src/agent/example.py"],
                           "test_paths": ["tests/unit/test_capability_recovery.py"]}
                for index in range(8):
                    request_id = f"CAP_{index:016X}"
                    conn.execute("INSERT INTO capability_requests VALUES(?,?,?,?,?,?)",
                        (request_id, "AUTO_SOURCE", "WAITING_CODEX", json.dumps(payload), old, old))
                    conn.execute("INSERT INTO tasks(id,status) VALUES(?,?)",
                        (f"AUTO_LOCAL_CAPABILITY_{index:016X}", "DONE"))
                conn.execute("INSERT INTO tasks(id,status,result_json) VALUES(?,?,?)",
                    ("AUTO_SOURCE", "WAITING_LOCAL", json.dumps({"status": "WAITING_LOCAL"})))
                fresh_id = "CAP_FFFFFFFFFFFFFFFF"
                now = datetime.now(timezone.utc).isoformat()
                conn.execute("INSERT INTO capability_requests VALUES(?,?,?,?,?,?)",
                    (fresh_id, "AUTO_FRESH_SOURCE", "NEW", json.dumps(payload), now, now))
                conn.execute("INSERT INTO tasks(id,status,result_json) VALUES(?,?,?)",
                    ("AUTO_FRESH_SOURCE", "WAITING_LOCAL", json.dumps({"status": "WAITING_LOCAL"})))
                conn.commit()

            def connect_fixture():
                conn = sqlite3.connect(database)
                conn.row_factory = sqlite3.Row
                return conn

            with mock.patch.object(autonomous_manager, "_connect", side_effect=connect_fixture), \
                 mock.patch.object(capability_broker, "ensure_schema"), \
                 mock.patch.object(autonomous_manager, "_event"), \
                 mock.patch.object(state_store, "add_task", return_value=True):
                queued = autonomous_manager._queue_waiting_capability_requests(
                    limit=8, min_retry_age_s=180)

        self.assertIn(fresh_id, [item["request_id"] for item in queued])

    def test_pending_requests_do_not_hide_later_eligible_requests(self) -> None:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as temporary:
            database = Path(temporary) / "state.sqlite"
            now = datetime.now(timezone.utc).isoformat()
            with closing(sqlite3.connect(database)) as conn:
                conn.execute("CREATE TABLE capability_requests(request_id TEXT, source_task_id TEXT, status TEXT, payload_json TEXT, created_utc TEXT, updated_utc TEXT)")
                conn.execute("CREATE TABLE tasks(id TEXT PRIMARY KEY, status TEXT NOT NULL, agent TEXT NOT NULL DEFAULT 'unit-test', result_json TEXT NOT NULL DEFAULT '{}', budget_json TEXT NOT NULL DEFAULT '{}')")
                payload = {"allowed_paths": ["src/agent/example.py"],
                           "test_paths": ["tests/unit/test_capability_recovery.py"]}
                for index in range(8):
                    request_id = f"CAP_{index:016X}"
                    conn.execute("INSERT INTO capability_requests VALUES(?,?,?,?,?,?)",
                        (request_id, "AUTO_SOURCE", "NEW", json.dumps(payload), now, now))
                    conn.execute("INSERT INTO tasks(id,status) VALUES(?,?)",
                        (f"AUTO_LOCAL_CAPABILITY_{index:016X}", "LEASED"))
                conn.execute("INSERT INTO tasks(id,status,result_json) VALUES(?,?,?)",
                    ("AUTO_SOURCE", "WAITING_LOCAL", json.dumps({"status": "WAITING_LOCAL"})))
                fresh_id = "CAP_FFFFFFFFFFFFFFFE"
                conn.execute("INSERT INTO capability_requests VALUES(?,?,?,?,?,?)",
                    (fresh_id, "AUTO_FRESH_SOURCE", "NEW", json.dumps(payload), now, now))
                conn.execute("INSERT INTO tasks(id,status,result_json) VALUES(?,?,?)",
                    ("AUTO_FRESH_SOURCE", "WAITING_LOCAL", json.dumps({"status": "WAITING_LOCAL"})))
                conn.commit()

            def connect_fixture():
                conn = sqlite3.connect(database)
                conn.row_factory = sqlite3.Row
                return conn

            with mock.patch.object(autonomous_manager, "_connect", side_effect=connect_fixture), \
                 mock.patch.object(capability_broker, "ensure_schema"), \
                 mock.patch.object(autonomous_manager, "_event"), \
                 mock.patch.object(state_store, "add_task", return_value=True):
                queued = autonomous_manager._queue_waiting_capability_requests(limit=8)

        self.assertIn(fresh_id, [item["request_id"] for item in queued])


if __name__ == "__main__":
    unittest.main()
