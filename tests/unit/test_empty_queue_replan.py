from __future__ import annotations

from datetime import datetime, timedelta, timezone
import sys
import tempfile
from pathlib import Path
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.agent import mission_pack


class EmptyQueueReplanTests(unittest.TestCase):
    def test_empty_ready_queue_with_unmet_goals_emits_one_novel_tick(self) -> None:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as temporary:
            db = Path(temporary) / "queue.sqlite"
            mission_pack.import_pack(db)
            now = datetime(2026, 10, 26, tzinfo=timezone.utc)
            plan = mission_pack.planner_tick(db, now=now)
            self.assertTrue(plan["should_plan"])
            self.assertEqual([task["id"] for task in plan["candidates"]], ["A01"])
            mission_pack.seed_director_task(plan, db_path=db)
            duplicate = mission_pack.planner_tick(db, now=now + timedelta(minutes=10))
            self.assertFalse(duplicate["should_plan"])
            self.assertEqual(duplicate["decision"], "UNCHANGED_CANDIDATES")

    def test_new_evidence_reopens_planning_immediately(self) -> None:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as temporary:
            db = Path(temporary) / "queue.sqlite"
            mission_pack.import_pack(db)
            now = datetime(2026, 10, 26, tzinfo=timezone.utc)
            mission_pack.planner_tick(db, now=now)
            mission_pack.mark_status("A01", "DONE",
                evidence={"verifier": "independent_test", "verdict": "PASS"}, db_path=db)
            resumed = mission_pack.planner_tick(db, now=now + timedelta(minutes=1))
            self.assertTrue(resumed["should_plan"])
            self.assertEqual(resumed["decision"], "PLAN")
            self.assertEqual({row["id"] for row in resumed["candidates"]}, {"A02", "A03"})

    def test_legacy_codex_waiters_return_to_local_director_and_ncdx_precedes_osm(self) -> None:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as temporary:
            db = Path(temporary) / "queue.sqlite"
            mission_pack.import_pack(db)
            mission_pack.mark_status("A01", "DONE",
                evidence={"verifier": "unit_test", "verdict": "PASS"}, db_path=db)
            mission_pack.mark_status("A03", "DONE",
                evidence={"verifier": "unit_test", "verdict": "PASS"}, db_path=db)
            mission_pack.mark_status("B01", "WAITING_CODEX",
                evidence={"verifier": "prior_codex_gate", "verdict": "WAITING"}, db_path=db)
            mission_pack.mark_status("D02", "WAITING_CODEX",
                evidence={"verifier": "prior_codex_gate", "verdict": "WAITING"}, db_path=db)
            reopened = mission_pack.reopen_legacy_codex_waiters(db)
            candidates = mission_pack.planner_candidates(db)
        self.assertEqual(set(reopened), {"B01", "D02"})
        product_candidates = [row["id"] for row in candidates if row["id"] in {"B01", "D02"}]
        self.assertEqual(product_candidates, ["B01", "D02"])


if __name__ == "__main__":
    unittest.main()
