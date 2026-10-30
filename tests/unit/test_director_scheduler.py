from __future__ import annotations

from datetime import datetime, timedelta, timezone
import shutil
import uuid
from pathlib import Path
import unittest
from contextlib import closing
from unittest import mock

from src.agent import director_scheduler
from src.agent.autonomous_manager import PROJECT_ROOT


class DirectorSchedulerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = PROJECT_ROOT / "work" / ("unit_director_scheduler_" + uuid.uuid4().hex)
        self.temp.mkdir(parents=True)
        self.db = self.temp / "director.sqlite"
        director_scheduler.ensure_schema(self.db)

    def tearDown(self) -> None:
        shutil.rmtree(self.temp)

    def test_defaults_and_interval_persist(self) -> None:
        state = director_scheduler.snapshot(db_path=self.db)
        self.assertTrue(state["config"]["enabled"])
        self.assertEqual(state["config"]["interval_seconds"], 1800)
        changed = director_scheduler.configure(False, 7200, db_path=self.db)
        self.assertFalse(changed["config"]["enabled"])
        self.assertEqual(changed["config"]["interval_seconds"], 7200)
        self.assertIsNone(changed["config"]["next_run_utc"])

    def test_manual_requests_are_deduplicated_until_claimed(self) -> None:
        first = director_scheduler.request_manual(db_path=self.db)
        second = director_scheduler.request_manual(db_path=self.db)
        self.assertEqual(first, second)
        state = director_scheduler.snapshot(db_path=self.db)
        self.assertEqual(state["config"]["pending_request_id"], first)

    def test_sqlite_lease_prevents_concurrent_director_cycles(self) -> None:
        due_time = datetime.now(timezone.utc) + timedelta(minutes=31)
        claim = director_scheduler._reserve_cycle("worker-one", db_path=self.db, now=due_time)
        self.assertIsNotNone(claim)
        self.assertIsNone(director_scheduler._reserve_cycle("worker-two", db_path=self.db, now=due_time))

    def test_missing_qwen_is_logged_without_creating_a_task(self) -> None:
        request_id = director_scheduler.request_manual(db_path=self.db)
        with mock.patch("src.agent.coordinator_runtime._available_models", return_value=[]):
            result = director_scheduler.process_due("acceptance-worker", db_path=self.db)
        self.assertTrue(result["processed"])
        self.assertEqual(result["decision"], "BLOCKED_EXTERNAL")
        snapshot = director_scheduler.snapshot(db_path=self.db)
        self.assertEqual(snapshot["decisions"][0]["request_id"], request_id)
        self.assertEqual(snapshot["decisions"][0]["decision"], "BLOCKED_EXTERNAL")

    def _create_minimal_task_table(self) -> None:
        import sqlite3
        with closing(sqlite3.connect(self.db)) as conn:
            conn.execute("""CREATE TABLE tasks(
                id TEXT PRIMARY KEY,stage TEXT,status TEXT,verdict TEXT,agent TEXT,
                hypothesis TEXT,result_json TEXT,updated_utc TEXT,depends_on_json TEXT,
                priority INTEGER,next_action TEXT,created_utc TEXT)""")
            conn.commit()

    def test_empty_queue_runs_one_bounded_qwen_no_action_decision(self) -> None:
        self._create_minimal_task_table()
        director_scheduler.request_manual(db_path=self.db)
        parsed = {"decision": "NO_NEW_EVIDENCE", "task_id": None,
                  "reason": "Жоден зареєстрований обробник не має нового підтвердженого входу.",
                  "missing_proofs": ["новий маніфестний вхід"]}
        with mock.patch("src.agent.coordinator_runtime._available_models", return_value=["qwen3.5:9b"]), \
             mock.patch("src.agent.coordinator_runtime._call_model",
                        return_value=("qwen3.5:9b", "{}", parsed)) as call_model, \
             mock.patch("src.agent.project_director._director_context", return_value={"queue_counts": {}}), \
             mock.patch("src.agent.autonomous_manager.schedule_next_goal_task",
                        return_value={"created": False, "reason": "немає кандидата"}):
            result = director_scheduler.process_due("unit-worker", db_path=self.db)
        self.assertEqual(result["decision"], "NO_NEW_EVIDENCE")
        call_model.assert_called_once()
        snapshot = director_scheduler.snapshot(db_path=self.db)
        self.assertEqual(snapshot["decisions"][0]["decision"], "NO_NEW_EVIDENCE")
        self.assertIn("новий маніфестний вхід", snapshot["decisions"][0]["reason"])

    def test_registered_candidate_requires_exact_qwen_acceptance(self) -> None:
        self._create_minimal_task_table()
        director_scheduler.request_manual(db_path=self.db)
        candidate_id = "AUTO_NCDX_REGISTERED_TEST"
        parsed = {"decision": "CONTINUE", "task_id": candidate_id,
                  "reason": "Збігаються виконавець та критерії.", "missing_proofs": []}
        fake_task = {"id": candidate_id, "stage": "F2", "agent": "ncdx-component-survey",
            "hypothesis": "Перевірка manifest-bound NCDx компонента", "evidence_json": "[]",
            "objective_tests_json": '["hash source","independent verifier"]', "depends_on": []}
        with mock.patch("src.agent.coordinator_runtime._available_models", return_value=["qwen3.5:9b"]), \
             mock.patch("src.agent.coordinator_runtime._call_model",
                        return_value=("qwen3.5:9b", "{}", parsed)), \
             mock.patch("src.agent.project_director._director_context", return_value={"queue_counts": {}}), \
             mock.patch("src.agent.autonomous_manager.schedule_next_goal_task",
                        return_value={"created": True, "task_id": candidate_id, "reason": "candidate"}), \
             mock.patch("src.agent.autonomous_manager._task", return_value=fake_task):
            result = director_scheduler.process_due("unit-worker", db_path=self.db)
        self.assertEqual(result["decision"], "CREATED")
        self.assertEqual(result["task_id"], candidate_id)


if __name__ == "__main__":
    unittest.main()
