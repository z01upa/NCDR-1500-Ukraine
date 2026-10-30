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

from src.agent.state_store import (_schema, add_task, claim_next, complete_task, fail_task,
    requeue_task, reconcile_waiting_result_states, supersede_task)


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

    def test_scope_sync_runs_inside_claim_transaction(self) -> None:
        """Main-state scope migration must not open a nested SQLite transaction."""
        add_task(self.task("scope-sync-claim"), self.db)
        # Exercise the main-database branch using an isolated temporary database.
        with patch("src.agent.state_store.STATE_DB", self.db):
            claimed = claim_next("scope-test", db_path=self.db)
        self.assertIsNotNone(claimed)
        self.assertEqual(claimed["id"], "scope-sync-claim")

    def test_claim_commits_schema_migration_before_begin_immediate(self) -> None:
        add_task(self.task("schema-transaction-claim"), self.db)
        original_schema = _schema

        def schema_leaving_a_migration_transaction_open(conn, kind):
            original_schema(conn, kind)
            conn.execute("UPDATE tasks SET updated_utc=updated_utc WHERE id='schema-transaction-claim'")

        with patch("src.agent.state_store._schema", side_effect=schema_leaving_a_migration_transaction_open):
            claimed = claim_next("schema-transaction-test", db_path=self.db)
        self.assertIsNotNone(claimed)
        self.assertEqual(claimed["id"], "schema-transaction-claim")

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

    def test_quota_wait_is_parked_and_does_not_release_dependents(self) -> None:
        add_task(self.task("quota-parent"), self.db)
        add_task(self.task("quota-child", ["quota-parent"]), self.db)
        claimed = claim_next("agent", db_path=self.db)
        self.assertEqual(claimed["id"], "quota-parent")
        complete_task("quota-parent", claimed["lease_id"],
                      {"status": "WAITING_CODEX_QUOTA", "reason": "daily budget exhausted"}, self.db)
        conn = sqlite3.connect(self.db)
        try:
            row = conn.execute("SELECT status,verdict FROM tasks WHERE id='quota-parent'").fetchone()
        finally:
            conn.close()
        self.assertEqual(row, ("WAITING_CODEX_QUOTA", "WAITING_CODEX_QUOTA"))
        self.assertIsNone(claim_next("agent", db_path=self.db))

    def test_startup_reconciles_legacy_done_waiting_result(self) -> None:
        add_task(self.task("legacy-quota"), self.db)
        conn = sqlite3.connect(self.db)
        try:
            conn.execute("UPDATE tasks SET status='DONE',verdict='PASS',result_json=? WHERE id='legacy-quota'",
                         ('{"status":"WAITING_CODEX_QUOTA","reason":"budget exhausted"}',))
            conn.commit()
        finally:
            conn.close()
        self.assertEqual(reconcile_waiting_result_states(self.db), ["legacy-quota"])
        self.assertEqual(reconcile_waiting_result_states(self.db), [])
        conn = sqlite3.connect(self.db)
        try:
            row = conn.execute("SELECT status,verdict,result_json FROM tasks WHERE id='legacy-quota'").fetchone()
        finally:
            conn.close()
        self.assertEqual(row[0:2], ("WAITING_CODEX_QUOTA", "WAITING_CODEX_QUOTA"))
        self.assertIn("budget exhausted", row[2])

    def test_requeue_resets_a_terminal_task_with_a_reason(self) -> None:
        add_task(self.task("again"), self.db)
        claimed = claim_next("agent", db_path=self.db)
        self.assertEqual(fail_task("again", claimed["lease_id"], "initial failure", self.db), "BLOCKED")
        requeue_task("again", "new parser evidence added", self.db)
        next_claim = claim_next("agent", db_path=self.db)
        self.assertEqual(next_claim["id"], "again")
        self.assertEqual(next_claim["attempts"], 1)

    def test_supersede_is_atomic_idempotent_and_preserves_failure_evidence(self) -> None:
        add_task(self.task("stale-checkpoint"), self.db)
        conn = sqlite3.connect(self.db)
        try:
            conn.execute("UPDATE tasks SET status='BLOCKED',verdict='BLOCKED',result_json=? WHERE id=?",
                         ('{"error":"old checkpoint"}', "stale-checkpoint"))
            conn.commit()
        finally:
            conn.close()
        self.assertTrue(supersede_task("stale-checkpoint", "published checkpoint advanced",
            evidence={"expected": "old", "current": "new"}, db_path=self.db))
        self.assertFalse(supersede_task("stale-checkpoint", "duplicate reconciliation",
            evidence={"current": "new"}, db_path=self.db))
        self.assertIsNone(claim_next("agent", db_path=self.db))
        conn = sqlite3.connect(self.db)
        try:
            status, verdict, result = conn.execute(
                "SELECT status,verdict,result_json FROM tasks WHERE id='stale-checkpoint'").fetchone()
        finally:
            conn.close()
        self.assertEqual((status, verdict), ("SUPERSEDED", "SUPERSEDED"))
        self.assertEqual(json.loads(result)["error"], "old checkpoint")
        self.assertEqual(json.loads(result)["superseded"]["evidence"],
                         {"expected": "old", "current": "new"})

    def test_supersede_does_not_interrupt_a_leased_task(self) -> None:
        add_task(self.task("leased-checkpoint"), self.db)
        claimed = claim_next("active-worker", db_path=self.db)
        self.assertFalse(supersede_task("leased-checkpoint", "checkpoint moved", db_path=self.db))
        conn = sqlite3.connect(self.db)
        try:
            status = conn.execute("SELECT status FROM tasks WHERE id='leased-checkpoint'").fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(status, "LEASED")


if __name__ == "__main__":
    unittest.main()
