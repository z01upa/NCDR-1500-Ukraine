from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.agent import capability_broker


class CapabilityBrokerTests(unittest.TestCase):
    def test_request_is_typed_atomic_and_deduplicated(self) -> None:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as temporary:
            db = Path(temporary) / "capabilities.sqlite"
            args = {"source_task_id": "unit-capability-request", "failure_class": "TOOL_MISSING",
                    "capability": "fixture-only helper", "scope": "Only describe the missing helper.",
                    "reproducer": "ImportError: No module named fixture_helper",
                    "expected_behavior": "A fixed helper returns a deterministic value.",
                    "acceptance_tests": ["The helper's result matches the fixture."],
                    "allowed_paths": ["src/agent/fixture_helper.py"], "test_paths": []}
            first = capability_broker.create_request(**args, db_path=db)
            second = capability_broker.create_request(**args, db_path=db)
            self.assertFalse(first["deduplicated"])
            self.assertTrue(second["deduplicated"])
            self.assertEqual(first["payload"]["type"], "CAPABILITY_REQUEST")
            self.assertTrue(first["payload"]["safety"]["sandbox_required"])
            request_file = PROJECT_ROOT / Path(*Path(first["path"]).parts)
            self.assertTrue(request_file.is_file())
            request_file.unlink(missing_ok=True)

    def test_request_rejects_paths_outside_project_engineering_scope(self) -> None:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as temporary:
            db = Path(temporary) / "capabilities.sqlite"
            with self.assertRaises(ValueError):
                capability_broker.create_request(
                    source_task_id="unsafe", failure_class="TOOL_MISSING", capability="x",
                    scope="x", reproducer="x", expected_behavior="x", acceptance_tests=["x"],
                    allowed_paths=["../../Desktop/crz/NCDR/SW/DB/EUZ.MP0"], db_path=db)

    def test_status_file_and_sqlite_remain_consistent_if_atomic_replace_fails(self) -> None:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as temporary:
            db = Path(temporary) / "capabilities.sqlite"
            args = {"source_task_id": "unit-status-atomicity", "failure_class": "TOOL_MISSING",
                    "capability": "status transaction fixture", "scope": "Atomic status change.",
                    "reproducer": "os.replace failure", "expected_behavior": "File and SQLite agree.",
                    "acceptance_tests": ["Injected rename failure leaves both stores unchanged."]}
            created = capability_broker.create_request(**args, db_path=db)
            path = PROJECT_ROOT / Path(*Path(created["path"]).parts)
            try:
                with patch("src.agent.capability_broker.os.replace", side_effect=OSError("injected rename failure")):
                    with self.assertRaises(OSError):
                        capability_broker.update_status(created["request_id"], "WAITING_CODEX", db_path=db)
                conn = sqlite3.connect(db)
                try:
                    status = conn.execute("SELECT status FROM capability_requests WHERE request_id=?",
                                          (created["request_id"],)).fetchone()[0]
                finally:
                    conn.close()
                self.assertEqual(status, "WAITING_LOCAL")
                self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["status"], "WAITING_LOCAL")
            finally:
                path.unlink(missing_ok=True)

    def test_legacy_requests_migrate_locally_except_rate_limited_requests(self) -> None:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as temporary:
            db = Path(temporary) / "capabilities.sqlite"
            paths = []
            ordinary = capability_broker.create_request(
                source_task_id="legacy-local-migration", failure_class="TOOL_MISSING",
                capability="bounded helper", scope="implement a deterministic helper",
                reproducer="local handler missing", expected_behavior="test passes",
                acceptance_tests=["independent test passes"], allowed_paths=["src/agent/example.py"],
                test_paths=["tests/unit/test_codex_quota.py"], db_path=db)
            limited = capability_broker.create_request(
                source_task_id="legacy-quota-migration", failure_class="TOOL_MISSING",
                capability="bounded helper", scope="implement after quota",
                reproducer="local handler missing", expected_behavior="test passes",
                acceptance_tests=["independent test passes"], allowed_paths=["src/agent/example.py"],
                test_paths=["tests/unit/test_codex_quota.py"], db_path=db)
            for request in (ordinary, limited):
                path = PROJECT_ROOT / Path(*Path(request["path"]).parts)
                paths.append(path)
                self.addCleanup(path.unlink, missing_ok=True)
            capability_broker.update_status(ordinary["request_id"], "WAITING_CODEX",
                detail={"reason": "test failed locally"}, db_path=db)
            capability_broker.update_status(limited["request_id"], "WAITING_CODEX",
                detail={"reason": "Codex usage limit reached"}, db_path=db)
            moved = capability_broker.migrate_legacy_codex_requests_to_local(db)
            conn = sqlite3.connect(db)
            try:
                statuses = dict(conn.execute("SELECT request_id,status FROM capability_requests"))
            finally:
                conn.close()
        self.assertEqual(moved["waiting_local"], [ordinary["request_id"]])
        self.assertEqual(moved["waiting_codex_quota"], [limited["request_id"]])
        self.assertEqual(statuses[ordinary["request_id"]], "WAITING_LOCAL")
        self.assertEqual(statuses[limited["request_id"]], "WAITING_CODEX_QUOTA")


if __name__ == "__main__":
    unittest.main()
