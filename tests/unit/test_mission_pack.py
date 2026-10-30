from __future__ import annotations

from datetime import datetime, timedelta, timezone
from contextlib import closing
import json
import sqlite3
import sys
import tempfile
from pathlib import Path
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.agent import mission_pack, state_store


class MissionPackTests(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work")
        self.addCleanup(temp.cleanup)
        self.db = Path(temp.name) / "mission.sqlite"

    def test_imports_all_canonical_tasks_idempotently(self) -> None:
        first = mission_pack.import_pack(self.db)
        second = mission_pack.import_pack(self.db)
        self.assertEqual(first["task_count"], 46)
        self.assertEqual(first["inserted"], 46)
        self.assertEqual(second["inserted"], 0)
        conn = sqlite3.connect(self.db)
        try:
            self.assertEqual(conn.execute("SELECT count(*) FROM mission_tasks").fetchone()[0], 46)
        finally:
            conn.close()

    def test_dependency_gates_and_planner_novelty(self) -> None:
        mission_pack.import_pack(self.db)
        # A persisted planning tick is only considered complete when its
        # durable Director task was also committed.  Seed that task here so
        # this test covers cooldown/novelty rather than crash recovery.
        with closing(sqlite3.connect(self.db)) as conn:
            state_store._schema(conn, "state")
            conn.commit()
        self.assertEqual([row["id"] for row in mission_pack.planner_candidates(self.db)], ["A01"])
        now = datetime(2026, 10, 26, tzinfo=timezone.utc)
        first = mission_pack.planner_tick(self.db, now=now)
        self.assertTrue(mission_pack.seed_director_task(first, self.db)["created"])
        repeated = mission_pack.planner_tick(self.db, now=now + timedelta(minutes=1))
        self.assertTrue(first["should_plan"])
        self.assertFalse(repeated["should_plan"])
        mission_pack.mark_status("A01", "DONE", evidence={"verifier": "unit_test", "verdict": "PASS"},
                                 db_path=self.db)
        too_soon = mission_pack.planner_tick(self.db, now=now + timedelta(minutes=2))
        self.assertTrue(too_soon["should_plan"])
        self.assertTrue(mission_pack.seed_director_task(too_soon, self.db)["created"])
        # The novel A02/A03 candidate set was persisted immediately. Later
        # ticks must not issue the same Director plan again.
        after_cooldown = mission_pack.planner_tick(self.db, now=now + timedelta(minutes=4))
        self.assertFalse(after_cooldown["should_plan"])
        candidates = {row["id"] for row in mission_pack.planner_candidates(self.db)}
        self.assertEqual(candidates, {"A02", "A03"})

    def test_unseeded_planner_tick_is_recoverable_without_waiting_for_cooldown(self) -> None:
        from src.agent import state_store
        mission_pack.import_pack(self.db)
        with closing(sqlite3.connect(self.db)) as conn:
            state_store._schema(conn, "state")
            conn.commit()
        now = datetime(2026, 10, 28, 15, 0, tzinfo=timezone.utc)
        interrupted = mission_pack.planner_tick(self.db, now=now, force=True)
        resumed = mission_pack.planner_tick(self.db, now=now + timedelta(seconds=1))
        self.assertTrue(interrupted["should_plan"])
        self.assertTrue(resumed["should_plan"])
        self.assertTrue(resumed["diagnosis"] is not None)
        self.assertEqual(interrupted["candidate_fingerprint"], resumed["candidate_fingerprint"])
        seeded = mission_pack.seed_director_task(resumed, self.db)
        self.assertTrue(seeded["created"])
        after_seed = mission_pack.planner_tick(self.db, now=now + timedelta(seconds=2))
        self.assertFalse(after_seed["should_plan"])

    def test_runtime_wait_reconciles_running_mission_without_claiming_done(self) -> None:
        mission_pack.import_pack(self.db)
        with closing(sqlite3.connect(self.db)) as conn:
            conn.execute("""CREATE TABLE tasks(
                id TEXT PRIMARY KEY,status TEXT,agent TEXT,budget_json TEXT,
                result_json TEXT,updated_utc TEXT)""")
            conn.execute("UPDATE mission_tasks SET status='RUNNING',runtime_task_id=? WHERE canonical_id='B01'",
                         ("B01-RUNTIME",))
            conn.execute("INSERT INTO tasks VALUES(?,?,?,?,?,?)", (
                "B01-RUNTIME", "WAITING_LOCAL", "mission-pack-executor",
                json.dumps({"mission_pack_task": "B01"}),
                json.dumps({"status": "WAITING_LOCAL", "reason": "worker capability missing"}),
                "2026-10-26T10:00:00+00:00"))
            conn.commit()
        changes = mission_pack.reconcile_runtime_missions(self.db)
        self.assertEqual(changes[0]["to"], "WAITING_LOCAL")
        with closing(sqlite3.connect(self.db)) as conn:
            status, evidence = conn.execute(
                "SELECT status,evidence_json FROM mission_tasks WHERE canonical_id='B01'").fetchone()
        self.assertEqual(status, "WAITING_LOCAL")
        self.assertEqual(json.loads(evidence)["completion_inferred"], False)

    def test_added_local_handler_atomically_supersedes_exact_legacy_wait(self) -> None:
        mission_pack.import_pack(self.db)
        with closing(sqlite3.connect(self.db)) as conn:
            state_store._schema(conn, "state")
            conn.execute("""INSERT INTO tasks(
                id,stage,depends_on_json,hypothesis,evidence_json,agent,budget_json,
                deliverables_json,objective_tests_json,verdict,next_action,status,result_json,
                attempts,retry_limit,priority,created_utc,updated_utc)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                ("B01-RUNTIME", "R3", "[]", "catalog NCDx facts", "[]",
                 "mission-pack-executor", json.dumps({"mission_pack_task": "B01"}),
                 "[]", "[]", "WAITING_LOCAL", "No deterministic handler exists yet; capability request persisted.",
                 "WAITING_LOCAL", json.dumps({"status": "WAITING_LOCAL",
                    "reason": "No deterministic handler exists yet; capability request persisted."}),
                 1, 1, 3, "2026-10-28T00:00:00Z", "2026-10-28T00:00:00Z"))
            conn.commit()
        mission_pack.mark_status("B01", "WAITING_LOCAL",
            evidence={"verifier": "unit_fixture", "verdict": "PASS"},
            reason="old handler wait", runtime_task_id="B01-RUNTIME", db_path=self.db)
        result = mission_pack.reopen_waiting_local_mission_after_handler_added("B01",
            expected_runtime_task_id="B01-RUNTIME",
            evidence={"verifier": "deterministic_handler_registry", "verdict": "PASS"},
            db_path=self.db)
        with closing(sqlite3.connect(self.db)) as conn:
            task_status = conn.execute("SELECT status FROM tasks WHERE id='B01-RUNTIME'").fetchone()[0]
            mission_status, runtime_id = conn.execute(
                "SELECT status,runtime_task_id FROM mission_tasks WHERE canonical_id='B01'").fetchone()
        self.assertTrue(result["reopened"])
        self.assertEqual(task_status, "SUPERSEDED")
        self.assertEqual((mission_status, runtime_id), ("READY", None))

    def test_local_handler_migration_can_retire_exact_waiting_codex_no_handler(self) -> None:
        mission_pack.import_pack(self.db)
        with closing(sqlite3.connect(self.db)) as conn:
            state_store._schema(conn, "state")
            conn.execute("UPDATE mission_tasks SET status='WAITING_CODEX',runtime_task_id=? WHERE canonical_id='B02'",
                         ("B02-RUNTIME",))
            conn.execute("""INSERT INTO tasks(
                id,stage,depends_on_json,hypothesis,evidence_json,agent,budget_json,
                deliverables_json,objective_tests_json,verdict,next_action,status,result_json,
                attempts,retry_limit,priority,created_utc,updated_utc)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                ("B02-RUNTIME", "R3", "[]", "regional NCDx diff", "[]",
                 "mission-pack-executor", json.dumps({"mission_pack_task": "B02"}),
                 "[]", "[]", "WAITING_LOCAL", "Codex CLI is unavailable.",
                 "WAITING_LOCAL", json.dumps({"status": "WAITING_LOCAL",
                    "reason": "No deterministic handler exists yet; capability request persisted."}),
                 1, 1, 3, "2026-10-28T00:00:00Z", "2026-10-28T00:00:00Z"))
            conn.commit()
        result = mission_pack.reopen_waiting_local_mission_after_handler_added("B02",
            expected_runtime_task_id="B02-RUNTIME",
            evidence={"verifier": "deterministic_handler_registry", "verdict": "PASS"},
            db_path=self.db)
        with closing(sqlite3.connect(self.db)) as conn:
            task_status = conn.execute("SELECT status FROM tasks WHERE id='B02-RUNTIME'").fetchone()[0]
            mission_status, runtime_id = conn.execute(
                "SELECT status,runtime_task_id FROM mission_tasks WHERE canonical_id='B02'").fetchone()
        self.assertTrue(result["reopened"])
        self.assertEqual(task_status, "SUPERSEDED")
        self.assertEqual((mission_status, runtime_id), ("READY", None))

    def test_quota_and_external_waiters_are_never_reopened_by_local_handler_migration(self) -> None:
        mission_pack.import_pack(self.db)
        with closing(sqlite3.connect(self.db)) as conn:
            state_store._schema(conn, "state")
            conn.execute("UPDATE mission_tasks SET status='WAITING_CODEX_QUOTA',runtime_task_id=? WHERE canonical_id='B02'",
                         ("B02-RUNTIME",))
            conn.execute("""INSERT INTO tasks(
                id,stage,depends_on_json,hypothesis,evidence_json,agent,budget_json,
                deliverables_json,objective_tests_json,verdict,next_action,status,result_json,
                attempts,retry_limit,priority,created_utc,updated_utc)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                ("B02-RUNTIME", "R3", "[]", "regional NCDx diff", "[]",
                 "mission-pack-executor", json.dumps({"mission_pack_task": "B02"}),
                 "[]", "[]", "WAITING_LOCAL", "quota", "WAITING_LOCAL",
                 json.dumps({"status": "WAITING_LOCAL",
                    "reason": "No deterministic handler exists yet; capability request persisted."}),
                 1, 1, 3, "2026-10-28T00:00:00Z", "2026-10-28T00:00:00Z"))
            conn.commit()
        result = mission_pack.reopen_waiting_local_mission_after_handler_added("B02",
            expected_runtime_task_id="B02-RUNTIME",
            evidence={"verifier": "deterministic_handler_registry", "verdict": "PASS"},
            db_path=self.db)
        self.assertFalse(result["reopened"])
        with closing(sqlite3.connect(self.db)) as conn:
            self.assertEqual(conn.execute("SELECT status FROM mission_tasks WHERE canonical_id='B02'").fetchone()[0],
                             "WAITING_CODEX_QUOTA")

    def test_only_exact_b06_no_handler_quota_wait_can_be_resolved_by_tested_local_handler(self) -> None:
        mission_pack.import_pack(self.db)
        previous = {"previous_evidence": {"reason": "No deterministic handler exists yet; capability request persisted."},
                    "reason": "Daily Codex budget exhausted (1/1).", "result_status": "WAITING_CODEX_QUOTA"}
        with closing(sqlite3.connect(self.db)) as conn:
            state_store._schema(conn, "state")
            conn.execute("UPDATE mission_tasks SET status='WAITING_CODEX_QUOTA',runtime_task_id=?,"
                         "status_reason=?,evidence_json=? WHERE canonical_id='B06'",
                         ("B06-RUNTIME", "Daily Codex budget exhausted (1/1).",
                          json.dumps(previous, ensure_ascii=False)))
            conn.execute("""INSERT INTO tasks(
                id,stage,depends_on_json,hypothesis,evidence_json,agent,budget_json,
                deliverables_json,objective_tests_json,verdict,next_action,status,result_json,
                attempts,retry_limit,priority,created_utc,updated_utc)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                ("B06-RUNTIME", "R3", "[]", "structure catalog", "[]",
                 "mission-pack-executor", json.dumps({"mission_pack_task": "B06"}),
                 "[]", "[]", "WAITING_LOCAL", "missing handler", "WAITING_LOCAL",
                 json.dumps({"status": "WAITING_LOCAL",
                    "reason": "No deterministic handler exists yet; capability request persisted."}),
                 1, 1, 3, "2026-10-28T00:00:00Z", "2026-10-28T00:00:00Z"))
            conn.commit()
        evidence = {"verifier": "deterministic_handler_registry", "verdict": "PASS",
                    "local_tests_passed": True, "codex_attempted": False}
        refused = mission_pack.reopen_waiting_local_mission_after_handler_added("B06",
            expected_runtime_task_id="B06-RUNTIME", evidence={
                "verifier": "deterministic_handler_registry", "verdict": "PASS"},
            db_path=self.db, resolve_quota_after_local_handler=True)
        self.assertFalse(refused["reopened"])
        reopened = mission_pack.reopen_waiting_local_mission_after_handler_added("B06",
            expected_runtime_task_id="B06-RUNTIME", evidence=evidence,
            db_path=self.db, resolve_quota_after_local_handler=True)
        with closing(sqlite3.connect(self.db)) as conn:
            task_status = conn.execute("SELECT status FROM tasks WHERE id='B06-RUNTIME'").fetchone()[0]
            mission_status, mission_task = conn.execute(
                "SELECT status,runtime_task_id FROM mission_tasks WHERE canonical_id='B06'").fetchone()
        self.assertTrue(reopened["reopened"])
        self.assertEqual(task_status, "SUPERSEDED")
        self.assertEqual((mission_status, mission_task), ("READY", None))

    def test_exact_b03_no_handler_quota_wait_reopens_after_local_verifier_tests(self) -> None:
        mission_pack.import_pack(self.db)
        runtime_id = "AUTO_MISSION_EXEC_B03_32A60754"
        previous = {"previous_evidence": {"reason": "No deterministic handler exists yet; capability request persisted."},
                    "reason": "Daily Codex budget exhausted (1/1).", "result_status": "WAITING_CODEX_QUOTA"}
        with closing(sqlite3.connect(self.db)) as conn:
            state_store._schema(conn, "state")
            conn.execute("UPDATE mission_tasks SET status='WAITING_CODEX_QUOTA',runtime_task_id=?,"
                         "status_reason=?,evidence_json=? WHERE canonical_id='B03'",
                         (runtime_id, "Daily Codex budget exhausted (1/1).", json.dumps(previous)))
            conn.execute("""INSERT INTO tasks(
                id,stage,depends_on_json,hypothesis,evidence_json,agent,budget_json,
                deliverables_json,objective_tests_json,verdict,next_action,status,result_json,
                attempts,retry_limit,priority,created_utc,updated_utc)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (runtime_id, "FIRMWARE", "[]", "inventory binary formats", "[]",
                 "mission-pack-executor", json.dumps({"mission_pack_task": "B03"}),
                 "[]", "[]", "WAITING_LOCAL", "missing local handler", "WAITING_LOCAL",
                 json.dumps({"status": "WAITING_LOCAL",
                    "reason": "No deterministic handler exists yet; capability request persisted."}),
                 1, 1, 3, "2026-10-28T00:00:00Z", "2026-10-28T00:00:00Z"))
            conn.commit()
        rejected = mission_pack.reopen_waiting_local_mission_after_handler_added("B03",
            expected_runtime_task_id=runtime_id,
            evidence={"verifier": "deterministic_handler_registry", "verdict": "PASS",
                      "local_tests_passed": False, "codex_attempted": False},
            db_path=self.db, resolve_quota_after_local_handler=True)
        self.assertFalse(rejected["reopened"])
        reopened = mission_pack.reopen_waiting_local_mission_after_handler_added("B03",
            expected_runtime_task_id=runtime_id,
            evidence={"verifier": "deterministic_handler_registry", "verdict": "PASS",
                      "local_tests_passed": True, "codex_attempted": False},
            db_path=self.db, resolve_quota_after_local_handler=True)
        with closing(sqlite3.connect(self.db)) as conn:
            task_status = conn.execute("SELECT status FROM tasks WHERE id=?", (runtime_id,)).fetchone()[0]
            mission_status, mission_runtime = conn.execute(
                "SELECT status,runtime_task_id FROM mission_tasks WHERE canonical_id='B03'").fetchone()
        self.assertTrue(reopened["reopened"])
        self.assertEqual(task_status, "SUPERSEDED")
        self.assertEqual((mission_status, mission_runtime), ("READY", None))

    def test_exact_e03_no_handler_quota_wait_reopens_to_local_evidence_task(self) -> None:
        mission_pack.import_pack(self.db)
        runtime_id = "AUTO_MISSION_EXEC_E03_5152EB9C"
        previous = {"previous_evidence": {"reason": "No deterministic handler exists yet; a typed local-first capability request was persisted."},
                    "reason": "Daily Codex budget exhausted (1/1).", "result_status": "WAITING_CODEX_QUOTA"}
        with closing(sqlite3.connect(self.db)) as conn:
            state_store._schema(conn, "state")
            conn.execute("UPDATE mission_tasks SET status='WAITING_CODEX_QUOTA',runtime_task_id=?,"
                         "status_reason=?,evidence_json=? WHERE canonical_id='E03'",
                         (runtime_id, "Daily Codex budget exhausted (1/1).", json.dumps(previous)))
            conn.execute("""INSERT INTO tasks(
                id,stage,depends_on_json,hypothesis,evidence_json,agent,budget_json,
                deliverables_json,objective_tests_json,verdict,next_action,status,result_json,
                attempts,retry_limit,priority,created_utc,updated_utc)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (runtime_id, "DISC", "[]", "inventory available optical-sector evidence", "[]",
                 "mission-pack-executor", json.dumps({"mission_pack_task": "E03"}),
                 "[]", "[]", "WAITING_LOCAL", "missing local handler", "WAITING_LOCAL",
                 json.dumps({"status": "WAITING_LOCAL",
                    "reason": "No deterministic handler exists yet; a typed local-first capability request was persisted."}),
                 1, 1, 3, "2026-10-28T00:00:00Z", "2026-10-28T00:00:00Z"))
            conn.commit()
        reopened = mission_pack.reopen_waiting_local_mission_after_handler_added("E03",
            expected_runtime_task_id=runtime_id,
            evidence={"verifier": "deterministic_handler_registry", "verdict": "PASS",
                      "local_tests_passed": True, "codex_attempted": False},
            db_path=self.db, resolve_quota_after_local_handler=True)
        with closing(sqlite3.connect(self.db)) as conn:
            task_status = conn.execute("SELECT status FROM tasks WHERE id=?", (runtime_id,)).fetchone()[0]
            mission_status, mission_runtime = conn.execute(
                "SELECT status,runtime_task_id FROM mission_tasks WHERE canonical_id='E03'").fetchone()
        self.assertTrue(reopened["reopened"])
        self.assertEqual(task_status, "SUPERSEDED")
        self.assertEqual((mission_status, mission_runtime), ("READY", None))

    def test_exact_b06_verifier_rule_failure_is_atomically_superseded_after_readback(self) -> None:
        mission_pack.import_pack(self.db)
        runtime_id = "AUTO_MISSION_EXEC_B06_55DFE153"
        with closing(sqlite3.connect(self.db)) as conn:
            state_store._schema(conn, "state")
            conn.execute("UPDATE mission_tasks SET status='BLOCKED',runtime_task_id=?,status_reason=?,evidence_json=? "
                         "WHERE canonical_id='B06'", (runtime_id,
                         "B06 RD/SW scope or source path is wrong", json.dumps({"verdict": "BLOCKED"})))
            conn.execute("""INSERT INTO tasks(
                id,stage,depends_on_json,hypothesis,evidence_json,agent,budget_json,
                deliverables_json,objective_tests_json,verdict,next_action,status,result_json,
                attempts,retry_limit,priority,created_utc,updated_utc)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (runtime_id, "R3", "[]", "structure catalog", "[]", "mission-pack-executor",
                 json.dumps({"mission_pack_task": "B06"}), "[]", "[]", "BLOCKED", "verify",
                 "BLOCKED", json.dumps({"error": "RuntimeError: B06 RD/SW scope or source path is wrong"}),
                 1, 1, 3, "2026-10-28T00:00:00Z", "2026-10-28T00:00:00Z"))
            conn.commit()
        evidence = {"verifier": "deterministic_handler_registry", "verdict": "PASS",
                    "independent_verifier": "mission_pack.verify_b06_structure_catalog",
                    "local_catalog_readback": "PASS", "verification": {"result": "PASS"},
                    "codex_attempted": False}
        recovered = mission_pack.recover_exact_b06_after_verifier_rule_fix(
            expected_runtime_task_id=runtime_id, evidence=evidence, db_path=self.db)
        self.assertTrue(recovered["recovered"])
        with closing(sqlite3.connect(self.db)) as conn:
            task_status = conn.execute("SELECT status FROM tasks WHERE id=?", (runtime_id,)).fetchone()[0]
            mission_status, mission_runtime = conn.execute(
                "SELECT status,runtime_task_id FROM mission_tasks WHERE canonical_id='B06'").fetchone()
        self.assertEqual(task_status, "SUPERSEDED")
        self.assertEqual((mission_status, mission_runtime), ("READY", None))

    def test_exact_b07_no_handler_quota_wait_reopens_only_with_local_test_proof(self) -> None:
        mission_pack.import_pack(self.db)
        runtime_id = "AUTO_MISSION_EXEC_B07_8A72CF7D"
        prior = {"previous_evidence": {"reason": "No deterministic handler exists yet; capability request persisted."},
                 "reason": "Daily Codex budget exhausted (1/1).", "result_status": "WAITING_CODEX_QUOTA"}
        with closing(sqlite3.connect(self.db)) as conn:
            state_store._schema(conn, "state")
            conn.execute("UPDATE mission_tasks SET status='WAITING_CODEX_QUOTA',runtime_task_id=?,status_reason=?,evidence_json=? "
                         "WHERE canonical_id='B07'", (runtime_id, prior["reason"], json.dumps(prior)))
            conn.execute("""INSERT INTO tasks(
                id,stage,depends_on_json,hypothesis,evidence_json,agent,budget_json,
                deliverables_json,objective_tests_json,verdict,next_action,status,result_json,
                attempts,retry_limit,priority,created_utc,updated_utc)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (runtime_id, "R3", "[]", "index integrity", "[]", "mission-pack-executor",
                 json.dumps({"mission_pack_task": "B07"}), "[]", "[]", "WAITING_LOCAL", "local handler",
                 "WAITING_LOCAL", json.dumps({"status": "WAITING_LOCAL",
                    "reason": "No deterministic handler exists yet; capability request persisted."}),
                 1, 1, 3, "2026-10-28T00:00:00Z", "2026-10-28T00:00:00Z"))
            conn.commit()
        missing_proof = mission_pack.reopen_waiting_local_mission_after_handler_added(
            "B07", expected_runtime_task_id=runtime_id,
            evidence={"verifier": "deterministic_handler_registry", "verdict": "PASS",
                      "local_tests_passed": False, "codex_attempted": False},
            db_path=self.db, resolve_quota_after_local_handler=True)
        self.assertFalse(missing_proof["reopened"])
        reopened = mission_pack.reopen_waiting_local_mission_after_handler_added(
            "B07", expected_runtime_task_id=runtime_id,
            evidence={"verifier": "deterministic_handler_registry", "verdict": "PASS",
                      "independent_verifier": "mission_pack.verify_b07_index_integrity_report",
                      "local_tests_passed": True, "codex_attempted": False},
            db_path=self.db, resolve_quota_after_local_handler=True)
        self.assertTrue(reopened["reopened"])
        with closing(sqlite3.connect(self.db)) as conn:
            status = conn.execute("SELECT status FROM tasks WHERE id=?", (runtime_id,)).fetchone()[0]
            mission_status, mission_runtime = conn.execute(
                "SELECT status,runtime_task_id FROM mission_tasks WHERE canonical_id='B07'").fetchone()
        self.assertEqual(status, "SUPERSEDED")
        self.assertEqual((mission_status, mission_runtime), ("READY", None))

    def test_exact_b07_wrong_family_failure_requires_fresh_raw_readback(self) -> None:
        mission_pack.import_pack(self.db)
        runtime_id = "AUTO_MISSION_EXEC_B07_AE0845D4"
        with closing(sqlite3.connect(self.db)) as conn:
            state_store._schema(conn, "state")
            conn.execute("UPDATE mission_tasks SET status='BLOCKED',runtime_task_id=?,status_reason=?,evidence_json=? "
                         "WHERE canonical_id='B07'", (runtime_id,
                         "container does not begin with the observed zip marker", json.dumps({"verdict": "BLOCKED"})))
            conn.execute("""INSERT INTO tasks(
                id,stage,depends_on_json,hypothesis,evidence_json,agent,budget_json,
                deliverables_json,objective_tests_json,verdict,next_action,status,result_json,
                attempts,retry_limit,priority,created_utc,updated_utc)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (runtime_id, "R3", "[]", "index integrity", "[]", "mission-pack-executor",
                 json.dumps({"mission_pack_task": "B07"}), "[]", "[]", "BLOCKED", "verify",
                 "BLOCKED", json.dumps({"error": "NcdxContainerError: container does not begin with the observed zip marker"}),
                 1, 1, 3, "2026-10-28T00:00:00Z", "2026-10-28T00:00:00Z"))
            conn.commit()
        with self.assertRaises(ValueError):
            mission_pack.recover_exact_b07_after_manifest_source_selection_fix(
                expected_runtime_task_id=runtime_id,
                evidence={"verifier": "deterministic_handler_registry", "verdict": "PASS",
                          "independent_verifier": "project_director.verify_b07_manifest_source_selection",
                          "fresh_source_readback": "FAIL", "codex_attempted": False}, db_path=self.db)
        recovered = mission_pack.recover_exact_b07_after_manifest_source_selection_fix(
            expected_runtime_task_id=runtime_id,
            evidence={"verifier": "deterministic_handler_registry", "verdict": "PASS",
                      "independent_verifier": "project_director.verify_b07_manifest_source_selection",
                      "fresh_source_readback": "PASS", "codex_attempted": False}, db_path=self.db)
        self.assertTrue(recovered["recovered"])
        with closing(sqlite3.connect(self.db)) as conn:
            status = conn.execute("SELECT status FROM tasks WHERE id=?", (runtime_id,)).fetchone()[0]
            mission_status, mission_runtime = conn.execute(
                "SELECT status,runtime_task_id FROM mission_tasks WHERE canonical_id='B07'").fetchone()
        self.assertEqual(status, "SUPERSEDED")
        self.assertEqual((mission_status, mission_runtime), ("READY", None))

    def test_empty_mission_candidate_set_reports_dependencies_not_no_unmet_goals(self) -> None:
        mission_pack.import_pack(self.db)
        mission_pack.mark_status("A01", "WAITING_EXTERNAL",
            evidence={"verifier": "unit_gate", "verdict": "WAITING"},
            reason="input required", db_path=self.db)
        tick = mission_pack.planner_tick(self.db,
            now=datetime(2026, 10, 26, tzinfo=timezone.utc))
        self.assertFalse(tick["should_plan"])
        self.assertEqual(tick["decision"], "WAITING_DEPENDENCIES")
        self.assertGreater(tick["diagnosis"]["unfinished_count"], 0)
        self.assertGreater(tick["diagnosis"]["dependency_blocked_count"], 0)

    def test_waiting_quota_state_preserves_previous_mission_evidence(self) -> None:
        mission_pack.import_pack(self.db)
        previous = {"verifier": "checkpoint_fixture", "verdict": "PASS",
                    "checkpoint": {"token": "tile-07", "completed_shards": 6}}
        mission_pack.mark_status("D03", "WAITING_LOCAL", evidence=previous,
                                 reason="local capability pending", runtime_task_id="D03-RUNTIME",
                                 db_path=self.db)
        verified = mission_pack.verify_runtime_result("D03", {
            "status": "WAITING_CODEX_QUOTA", "request_id": "CAP_D03_FIXTURE",
            "reason": "daily quota exhausted", "quota": {"allowed": False}}, db_path=self.db)
        self.assertEqual(verified["status"], "WAITING_CODEX_QUOTA")
        with closing(sqlite3.connect(self.db)) as conn:
            status, evidence_json, reason = conn.execute(
                "SELECT status,evidence_json,status_reason FROM mission_tasks WHERE canonical_id='D03'").fetchone()
        evidence = json.loads(evidence_json)
        self.assertEqual(status, "WAITING_CODEX_QUOTA")
        self.assertEqual(reason, "daily quota exhausted")
        self.assertEqual(evidence["previous_evidence"], previous)
        self.assertEqual(evidence["request_id"], "CAP_D03_FIXTURE")
        self.assertEqual(evidence["quota"], {"allowed": False})

    def test_precompletion_mission_verification_can_be_non_mutating(self) -> None:
        mission_pack.import_pack(self.db)
        mission_pack.mark_status("B02", "RUNNING", evidence={"verifier": "fixture", "verdict": "PASS"},
                                 runtime_task_id="B02-RUNTIME", db_path=self.db)
        before = mission_pack.planner_diagnosis(self.db)
        result = mission_pack.verify_runtime_result("B02", {
            "status": "WAITING_LOCAL", "runtime_task_id": "B02-RUNTIME",
            "reason": "bounded local executor is unavailable"}, db_path=self.db, persist=False)
        with closing(sqlite3.connect(self.db)) as conn:
            status, reason = conn.execute(
                "SELECT status,status_reason FROM mission_tasks WHERE canonical_id='B02'").fetchone()
        self.assertEqual(result["status"], "WAITING_LOCAL")
        self.assertEqual(status, "RUNNING")
        self.assertEqual(reason, "")
        self.assertEqual(before["unfinished_count"], 46)

    def test_model_cannot_mark_mission_task_done(self) -> None:
        mission_pack.import_pack(self.db)
        with self.assertRaisesRegex(ValueError, "deterministic or independent verifier"):
            mission_pack.mark_status("A01", "DONE", evidence={"verifier": "model", "verdict": "PASS"},
                                     db_path=self.db)

    def test_static_scopes_cover_real_code_deliverables_and_exclude_forbidden_tracks(self) -> None:
        backlog = mission_pack.json.loads(mission_pack.BACKLOG_PATH.read_text(encoding="utf-8"))
        self.assertEqual(set(mission_pack.MISSION_CAPABILITY_SCOPES),
                         {task["id"] for task in backlog["tasks"]})
        required_sources = {
            "A08": {"windows/install_manager.ps1"},
            "B08": {"src/readers/geometry_decoder.py"},
            "B09": {"src/readers/road_graph.py"},
            "B10": {"src/readers/text_poi.py"},
            "B11": {"src/readers/reference_reader.py", "src/readers/independent_reader.py"},
            "C03": {"src/writers/index_builder.py"},
            "D01": {"src/osm/streaming_pipeline.py"},
            "Q03": {"src/agent/novelty_check.py"},
        }
        for canonical_id, required in required_sources.items():
            with self.subTest(canonical_id=canonical_id):
                scope = mission_pack.capability_scope(canonical_id)
                self.assertEqual(scope["status"], "WAITING_LOCAL")
                self.assertTrue(required.issubset(set(scope["allowed_paths"])))
        for canonical_id in mission_pack.MISSION_CAPABILITY_SCOPES:
            with self.subTest(canonical_id=canonical_id):
                scope = mission_pack.capability_scope(canonical_id)
                if canonical_id == "E06":
                    self.assertEqual(scope["status"], "WAITING_EXTERNAL")
                    continue
                self.assertTrue(scope["allowed_paths"])
                self.assertTrue(scope["test_paths"])
                for test_path in scope["test_paths"]:
                    self.assertTrue((PROJECT_ROOT / test_path).is_file(), test_path)
                for source_path in scope["allowed_paths"]:
                    self.assertFalse(any(char in source_path for char in "*?[]"), source_path)
                    target = (PROJECT_ROOT / source_path).resolve()
                    self.assertTrue(target.is_relative_to(PROJECT_ROOT.resolve()), source_path)
                    if source_path == "windows/install_manager.ps1":
                        self.assertEqual(source_path, target.relative_to(PROJECT_ROOT.resolve()).as_posix())
                    else:
                        self.assertTrue(target.is_file() or target.parent.is_dir(), source_path)
        forbidden = ("virtual_cid", "src/cid/", "poi_editor", "poi-editor")
        for canonical_id, (allowed, tests) in mission_pack.MISSION_CAPABILITY_SCOPES.items():
            for path in [*allowed, *tests]:
                self.assertFalse(any(token in path.casefold() for token in forbidden),
                                 f"{canonical_id}: {path}")


if __name__ == "__main__":
    unittest.main()
