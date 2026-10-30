from __future__ import annotations

from datetime import datetime, timedelta, timezone
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from src.agent import mission_pack


class MissionReplanEvidenceRevisionTests(unittest.TestCase):
    def test_verified_evidence_revision_allows_a_fresh_director_cycle(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[2] / "work") as folder:
            database = Path(folder) / "state.sqlite"
            mission_pack.import_pack(database)
            with closing(sqlite3.connect(database)) as connection:
                connection.execute("UPDATE mission_tasks SET status='DONE' WHERE canonical_id!='D02'")
                connection.execute("UPDATE mission_tasks SET status='PROPOSED',status_reason='',evidence_json='{}',runtime_task_id=NULL WHERE canonical_id='D02'")
                connection.commit()

            first_time = datetime(2026, 10, 26, tzinfo=timezone.utc)
            first_tick = mission_pack.planner_tick(database, now=first_time, force=True)
            self.assertTrue(first_tick["should_plan"])
            first_plan = mission_pack.seed_director_task(first_tick, database)
            self.assertTrue(first_plan["created"])

            mission_pack.mark_status("D02", "READY", evidence={
                "verifier": "capability_patch_test_gate", "verdict": "PASS",
                "capability_request_id": "CAP_VERIFIED_FIXTURE"},
                reason="Reusable source provenance tool passed independent tests.", db_path=database)
            second_tick = mission_pack.planner_tick(database,
                now=first_time + timedelta(seconds=181))
            self.assertTrue(second_tick["should_plan"])
            self.assertNotEqual(first_tick["candidate_fingerprint"], second_tick["candidate_fingerprint"])
            second_plan = mission_pack.seed_director_task(second_tick, database)
            self.assertTrue(second_plan["created"])
            self.assertNotEqual(first_plan["task_id"], second_plan["task_id"])


if __name__ == "__main__":
    unittest.main()
