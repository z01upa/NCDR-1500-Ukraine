from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.agent.state_store import _schema, add_task, claim_next, complete_task, fail_task, requeue_task


class StateStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory(dir=PROJECT_ROOT)
        self.addCleanup(temp.cleanup)
        self.db = Path(temp.name) / "state.sqlite"
        conn = sqlite3.connect(self.db)
        try:
            _schema(conn, "state")
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def task(task_id: str, deps: list[str] | None = None, retry_limit: int = 1) -> dict:
        return {
            "id": task_id,
            "stage": "F0",
            "depends_on": deps or [],
            "hypothesis": "bounded test",
            "evidence": [],
            "agent": "unit-test",
            "budget": {"attempts": retry_limit, "timeout_s": 1},
            "deliverables": [],
            "tests": [],
            "next_action": "stop after the bounded attempt",
            "retry_limit": retry_limit,
            "priority": 1,
        }

    def test_dependencies_gate_task_claim(self) -> None:
        add_task(self.task("parent"), self.db)
        add_task(self.task("child", ["parent"]), self.db)
        first = claim_next("agent-a", db_path=self.db)
        self.assertEqual(first["id"], "parent")
        self.assertIsNone(claim_next("agent-b", db_path=self.db))
        complete_task("parent", first["lease_id"], {"ok": True}, self.db)
        second = claim_next("agent-b", db_path=self.db)
        self.assertEqual(second["id"], "child")

    def test_retry_limit_blocks_after_one_failed_attempt(self) -> None:
        add_task(self.task("single", retry_limit=1), self.db)
        claimed = claim_next("agent", db_path=self.db)
        self.assertEqual(fail_task("single", claimed["lease_id"], "bounded failure", self.db), "BLOCKED")
        self.assertIsNone(claim_next("agent", db_path=self.db))
        conn = sqlite3.connect(self.db)
        try:
            row = conn.execute("SELECT status,attempts FROM tasks WHERE id='single'").fetchone()
        finally:
            conn.close()
        self.assertEqual(row, ("BLOCKED", 1))

    def test_duplicate_task_id_is_idempotent(self) -> None:
        self.assertTrue(add_task(self.task("once"), self.db))
        self.assertFalse(add_task(self.task("once"), self.db))
        conn = sqlite3.connect(self.db)
        try:
            self.assertEqual(conn.execute("SELECT count(*) FROM tasks WHERE id='once'").fetchone()[0], 1)
        finally:
            conn.close()

    def test_lease_owner_is_required_to_complete(self) -> None:
        add_task(self.task("leased"), self.db)
        claimed = claim_next("agent", db_path=self.db)
        with self.assertRaises(RuntimeError):
            complete_task("leased", "wrong-lease", {"ok": True}, self.db)
        complete_task("leased", claimed["lease_id"], {"ok": True}, self.db)

    def test_requeue_resets_a_terminal_task_with_a_reason(self) -> None:
        add_task(self.task("again"), self.db)
        claimed = claim_next("agent", db_path=self.db)
        self.assertEqual(fail_task("again", claimed["lease_id"], "initial failure", self.db), "BLOCKED")
        requeue_task("again", "new parser evidence added", self.db)
        next_claim = claim_next("agent", db_path=self.db)
        self.assertEqual(next_claim["id"], "again")
        self.assertEqual(next_claim["attempts"], 1)


if __name__ == "__main__":
    unittest.main()
