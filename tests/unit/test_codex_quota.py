from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.agent import codex_quota


class CodexQuotaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work")
        self.addCleanup(self.temporary.cleanup)
        self.db = Path(self.temporary.name) / "quota.sqlite"
        self.now = datetime(2026, 10, 26, 12, tzinfo=timezone.utc)

    def test_noneligible_codex_call_is_denied_without_using_budget(self) -> None:
        with patch.dict("os.environ", {"NCDR_CODEX_DAILY_BUDGET": "1"}):
            denied = codex_quota.reserve_call("demo-task", evidence={}, db_path=self.db, now=self.now)
            allowed = codex_quota.reserve_call("local-failure-task",
                evidence={"test": "failed in isolated local attempt"}, local_failure_recorded=True,
                db_path=self.db, now=self.now)
        self.assertEqual(denied["status"], "NOT_ELIGIBLE")
        self.assertTrue(allowed["allowed"])
        self.assertEqual(allowed["used_today"], 1)

    def test_daily_and_per_request_limits_are_atomic(self) -> None:
        with patch.dict("os.environ", {"NCDR_CODEX_DAILY_BUDGET": "1"}):
            first = codex_quota.reserve_call("request-1", evidence={"local_failure": True},
                local_failure_recorded=True, db_path=self.db, now=self.now)
            repeat = codex_quota.reserve_call("request-1", evidence={"local_failure": True},
                local_failure_recorded=True, db_path=self.db, now=self.now)
            other = codex_quota.reserve_call("request-2", evidence={"critical": True},
                critical_architecture=True, db_path=self.db, now=self.now)
        self.assertTrue(first["allowed"])
        self.assertEqual(repeat["status"], "WAITING_CODEX_QUOTA")
        self.assertEqual(other["status"], "WAITING_CODEX_QUOTA")

    def test_rate_limit_parks_future_requests_until_next_utc_day(self) -> None:
        with patch.dict("os.environ", {"NCDR_CODEX_DAILY_BUDGET": "3"}), \
             patch("src.agent.codex_quota._now", side_effect=[self.now, self.now, self.now]):
            reserved = codex_quota.reserve_call("request-1", evidence={"local_failure": True},
                local_failure_recorded=True, db_path=self.db, now=self.now)
            self.assertTrue(reserved["allowed"])
            codex_quota.finish_call("request-1", "RATE_LIMITED",
                detail={"reason": "usage limit reached"}, db_path=self.db)
            later = codex_quota.reserve_call("request-2", evidence={"local_failure": True},
                local_failure_recorded=True, db_path=self.db,
                now=datetime(2026, 10, 26, 23, 59, tzinfo=timezone.utc))
        self.assertEqual(later["status"], "WAITING_CODEX_QUOTA")
        self.assertTrue(codex_quota.rate_limit_detected("You have hit your usage limit"))
        state = codex_quota.snapshot(self.db, now=self.now)
        self.assertEqual(state["recent_calls"][0]["status"], "RATE_LIMITED")
        self.assertTrue(state["blocked_until_utc"].startswith("2026-10-27"))


if __name__ == "__main__":
    unittest.main()
