from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

from src.agent import codex_quota, weekly_review


class WeeklyReviewTests(unittest.TestCase):
    def _fixture(self, root: Path) -> Path:
        database = root / "project_state.sqlite"
        with closing(sqlite3.connect(database)) as conn:
            conn.execute("CREATE TABLE tasks(id TEXT,status TEXT,result_json TEXT,updated_utc TEXT)")
            conn.executemany("INSERT INTO tasks VALUES(?,?,?,?)", [
                ("DONE-1", "DONE", '{"status":"PASS"}', "2026-10-27T10:00:00Z"),
                ("BLOCKED-1", "BLOCKED", '{"error":"fixed local issue"}', "2026-10-27T10:01:00Z")])
            conn.commit()
        return database

    def test_quota_wait_is_persisted_and_does_not_invoke_exec_or_retry(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[2] / "work") as folder:
            root = Path(folder)
            database = self._fixture(root)
            now = datetime(2026, 10, 27, 12, tzinfo=timezone.utc)
            login = SimpleNamespace(returncode=0, stdout="Logged in using ChatGPT", stderr="")
            with mock.patch.object(weekly_review, "subprocess") as subprocess_mock, \
                 mock.patch.object(weekly_review.codex_quota, "reserve_call",
                    return_value={"allowed": False, "status": "WAITING_CODEX_QUOTA",
                                  "reason": "Daily Codex budget exhausted (1/1)."}) as reserve:
                subprocess_mock.run.return_value = login
                first = weekly_review.run_weekly_review(project_root=root, state_db=database,
                    now=now, executable="codex.exe")
                second = weekly_review.run_weekly_review(project_root=root, state_db=database,
                    now=now, executable="codex.exe")
            self.assertEqual(first["status"], "WAITING_CODEX_QUOTA")
            self.assertEqual(second, first)
            reserve.assert_called_once()
            self.assertEqual(subprocess_mock.run.call_count, 1)
            self.assertNotIn("exec", subprocess_mock.run.call_args.args[0])
            task_id = weekly_review._week_key(now)
            task = json.loads((root / "AUTONOMOUS_RESEARCH" / "TASKS" / "WAITING_CODEX_QUOTA" / f"{task_id}.json").read_text(encoding="utf-8"))
            self.assertEqual(task["status"], "WAITING_CODEX_QUOTA")

    def test_rate_limit_is_parked_for_the_week_without_cyclic_cli_calls(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[2] / "work") as folder:
            root = Path(folder)
            database = self._fixture(root)
            now = datetime(2026, 10, 27, 12, tzinfo=timezone.utc)
            login = SimpleNamespace(returncode=0, stdout="Logged in using ChatGPT", stderr="")
            rate_limited = SimpleNamespace(returncode=1, stdout="", stderr="rate limit reached")
            with mock.patch.object(weekly_review, "subprocess") as subprocess_mock:
                subprocess_mock.run.side_effect = [login, rate_limited]
                first = weekly_review.run_weekly_review(project_root=root, state_db=database,
                    now=now, executable="codex.exe")
                second = weekly_review.run_weekly_review(project_root=root, state_db=database,
                    now=now, executable="codex.exe")
            self.assertEqual(first["status"], "WAITING_CODEX_QUOTA")
            self.assertEqual(second, first)
            self.assertEqual(subprocess_mock.run.call_count, 2)
            quota = codex_quota.snapshot(database, now=now)
            self.assertEqual(quota["recent_calls"][0]["status"], "RATE_LIMITED")
            task_id = weekly_review._week_key(now)
            saved = json.loads((root / "AUTONOMOUS_RESEARCH" / "ENGINEERING" / "CODEX_WEEKLY_OUTBOX" / f"{task_id}.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["status"], "WAITING_CODEX_QUOTA")

    def test_read_only_review_waits_for_local_director_validation(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[2] / "work") as folder:
            root = Path(folder)
            database = self._fixture(root)
            now = datetime(2026, 10, 27, 12, tzinfo=timezone.utc)
            review = {"summary": "Review only.", "findings": [],
                "recommended_actions": [{"title": "Inspect current parser evidence",
                    "rationale": "A saved source-bound result is ready.",
                    "acceptance_test": "Fresh read-only verification reproduces the saved hash."}],
                "codex_required_actions": [], "hardware_evidence_needed": []}
            event = {"type": "item.completed", "item": {"type": "agent_message", "text": json.dumps(review)}}
            login = SimpleNamespace(returncode=0, stdout="Logged in using ChatGPT", stderr="")
            response = SimpleNamespace(returncode=0, stdout=json.dumps(event) + "\n", stderr="")
            with mock.patch.object(weekly_review, "subprocess") as subprocess_mock, \
                 mock.patch.object(weekly_review.codex_quota, "reserve_call",
                                   return_value={"allowed": True, "status": "RESERVED"}), \
                 mock.patch.object(weekly_review.codex_quota, "finish_call") as finish:
                subprocess_mock.run.side_effect = [login, response]
                result = weekly_review.run_weekly_review(project_root=root, state_db=database,
                    now=now, executable="codex.exe")
            self.assertEqual(result["status"], "REVIEW_PENDING_LOCAL_DIRECTOR_VALIDATION")
            self.assertFalse(result["auto_execution"])
            self.assertEqual(subprocess_mock.run.call_count, 2)
            command = subprocess_mock.run.call_args.args[0]
            self.assertIn("read-only", command)
            self.assertEqual(finish.call_args.args[:2], (weekly_review._week_key(now), "SUCCEEDED"))


if __name__ == "__main__":
    unittest.main()
