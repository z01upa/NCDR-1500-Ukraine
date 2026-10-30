from __future__ import annotations

import json
import hashlib
from contextlib import closing
from pathlib import Path
import sys
import tempfile
import sqlite3
import unittest
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.agent import autonomous_manager, coordinator_runtime, project_director


def _connect_temp(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


class AutonomousManagerGuardTests(unittest.TestCase):
    def test_geoblock_candidate_uses_worker_child_dispatch_allowlist(self):
        task_id = "AUTO_NCDX_GEOBLOCK_0123456789ABCDEF"
        task = {"id": task_id, "agent": "ncdx-geoblock-research", "budget": {"timeout_s": 600}}
        with mock.patch.object(autonomous_manager, "_task", return_value=task), \
             mock.patch.object(project_director, "dispatch", return_value={"status": "PASS"}) as dispatch:
            result = autonomous_manager.execute_task(task_id)
        self.assertEqual(result, {"status": "PASS"})
        dispatch.assert_called_once_with(task_id, "ncdx-geoblock-research")

    def test_geoblock_missing_dispatch_handler_gets_exact_one_time_recovery(self):
        reason = autonomous_manager._known_recovery_reason(
            "AUTO_NCDX_GEOBLOCK_0123456789ABCDEF",
            "RuntimeError: No allowlisted autonomous handler for geoblock task")
        self.assertIn("ncdx-geoblock-dispatch-v1", reason)

    def test_supervisor_proof_envelope_binds_the_exact_target_identity(self):
        task_id = "AUTO_NCDX_GEOBLOCK_0123456789ABCDEF"
        proof = {"artifact_sha256": "a" * 64, "road_geometry_decoded": False}
        with mock.patch.object(project_director, "_verified_target", return_value=proof):
            verified = project_director._supervisor_verified_target(task_id)
        self.assertEqual(verified, {"task_id": task_id, **proof})

    def test_geoblock_supervisor_shape_failure_gets_exact_one_time_recovery(self):
        reason = autonomous_manager._known_recovery_reason(
            "AUTO_SUPERVISOR_AUTO_NCDX_GEOBLOCK_0123456789ABCDEF",
            "RuntimeError: KeyError: 'task_id'")
        self.assertIn("ncdx-geoblock-supervisor-proof-v1", reason)

    def test_local_component_director_is_routed_to_allowlisted_handler(self) -> None:
        expected = {"status": "PASS", "task_id": "AUTO_DIRECTOR_SW_COMPONENT_SCAN_TEST"}
        with mock.patch.object(autonomous_manager, "_task", return_value={
                "id": expected["task_id"], "agent": "ollama-component-survey-director",
                "budget": {"timeout_s": 90}}), \
             mock.patch.object(project_director, "dispatch", return_value=expected) as dispatch:
            result = autonomous_manager.execute_task(expected["task_id"])
        self.assertEqual(result, expected)
        dispatch.assert_called_once_with(expected["task_id"], "ollama-component-survey-director")

    def test_roadlink_portability_agent_is_allowlisted_and_known_failure_is_repaired_once(self) -> None:
        expected = {"status": "PASS", "task_id": "AUTO_NCDX_ROADLINK_PORTABILITY_V1_FIXTURE"}
        with mock.patch.object(autonomous_manager, "_task", return_value={
                "id": expected["task_id"], "agent": "ncdx-roadlink-portability", "budget": {}}), \
             mock.patch.object(project_director, "dispatch", return_value=expected) as dispatch:
            result = autonomous_manager.execute_task(expected["task_id"])
        self.assertEqual(result, expected)
        dispatch.assert_called_once_with(expected["task_id"], "ncdx-roadlink-portability")
        reason = autonomous_manager._known_recovery_reason(
            expected["task_id"], "RuntimeError: No allowlisted autonomous handler")
        self.assertTrue(reason and reason.startswith("roadlink-portability-dispatch-v1:"))
        self.assertIsNone(autonomous_manager._known_recovery_reason(
            "AUTO_OTHER_TASK", "RuntimeError: No allowlisted autonomous handler"))

    def test_worker_runtime_fingerprint_changes_when_planner_source_changes(self) -> None:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as folder:
            root = Path(folder)
            names = ("src/agent/autonomous_manager.py", "src/agent/director_scheduler.py",
                     "src/agent/project_director.py",
                     "src/agent/coordinator_runtime.py", "src/agent/state_store.py",
                     "src/agent/mission_pack.py", "src/readers/ncdx_binary_headers.py",
                     "src/readers/ncdx_roadlink_portability.py",
                     "src/readers/ncdx_geography_portability.py",
                     "src/readers/ncdx_city_coordinate_crosscheck.py",
                     "src/readers/ncdx_roadlink_name_consistency.py",
                     "src/readers/ncdx_pe_imports.py",
                     "src/readers/ncdx_pe_imports_verifier.py",
                     "src/readers/ncdx_embedded_pe.py",
                     "src/readers/ncdx_embedded_pe_verifier.py")
            for name in names:
                path = root.joinpath(*Path(name).parts)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("# initial\n", encoding="utf-8")
            with mock.patch.object(autonomous_manager, "PROJECT_ROOT", root):
                initial = autonomous_manager._worker_runtime_fingerprint()
                changed_file = root / "src" / "readers" / "ncdx_roadlink_portability.py"
                changed_file.write_text("# updated planner\n", encoding="utf-8")
                updated = autonomous_manager._worker_runtime_fingerprint()
        self.assertNotEqual(initial, updated)
        self.assertEqual([item[0] for item in initial], list(names))

    def test_codex_direct_handler_is_gated_before_cli_lookup_for_demo_task(self) -> None:
        from src.agent import codex_quota
        with mock.patch.object(autonomous_manager, "_task", side_effect=KeyError("demo")), \
             mock.patch.object(codex_quota, "reserve_call", return_value={
                 "allowed": False, "status": "NOT_ELIGIBLE", "reason": "local failure required"}), \
             mock.patch.object(autonomous_manager.shutil, "which") as which:
            with self.assertRaises(codex_quota.CodexQuotaDeferred):
                autonomous_manager._codex_json("demo", cwd=PROJECT_ROOT, sandbox="read-only", task_id="AUTO_CODEX_DEMO")
        which.assert_not_called()

    def test_capability_request_queues_local_repair_only_with_existing_test_scope(self) -> None:
        from src.agent import state_store
        request = {"request_id": "CAP_1234567890ABCDEF", "status": "NEW",
                   "payload": {"request_id": "CAP_1234567890ABCDEF",
                               "allowed_paths": ["src/agent/example.py"],
                               "test_paths": ["tests/unit/test_example.py"]}}
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as temporary:
            database = Path(temporary) / "state.sqlite"
            with closing(sqlite3.connect(database)) as conn:
                conn.execute("CREATE TABLE tasks(id TEXT PRIMARY KEY,status TEXT NOT NULL)")
                conn.commit()
            with mock.patch.object(autonomous_manager, "_connect", side_effect=lambda: _connect_temp(database)), \
                 mock.patch.object(state_store, "add_task", return_value=True) as add_task:
                queued = autonomous_manager._queue_capability_request(request, source_task_id="AUTO_SOURCE")
        self.assertTrue(queued["created"])
        spec = add_task.call_args.args[0]
        self.assertEqual(spec["agent"], "local-code-repair")
        self.assertEqual(spec["budget"]["capability_request_id"], request["request_id"])

    def test_unscoped_capability_request_stays_persisted_without_running_codex(self) -> None:
        from src.agent import state_store
        request = {"request_id": "CAP_1234567890ABCDEF", "status": "NEW",
                   "payload": {"request_id": "CAP_1234567890ABCDEF",
                               "allowed_paths": [], "test_paths": []}}
        with mock.patch.object(state_store, "add_task") as add_task:
            queued = autonomous_manager._queue_capability_request(request, source_task_id="AUTO_SOURCE")
        self.assertFalse(queued["created"])
        add_task.assert_not_called()

    def test_waiting_codex_request_is_never_automatically_requeued(self) -> None:
        from src.agent import state_store
        request = {"request_id": "CAP_1234567890ABCDEF", "status": "WAITING_CODEX",
                   "payload": {"request_id": "CAP_1234567890ABCDEF",
                               "allowed_paths": ["src/agent/example.py"],
                               "test_paths": ["tests/unit/test_example.py"]}}
        with mock.patch.object(state_store, "add_task") as add_task:
            queued = autonomous_manager._queue_capability_request(request, source_task_id="AUTO_SOURCE")
        self.assertFalse(queued["created"])
        add_task.assert_not_called()

    def test_capability_resume_skips_completed_sources_and_keeps_current_local_repair(self) -> None:
        from src.agent import capability_broker
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as folder:
            database = Path(folder) / "state.sqlite"
            with closing(sqlite3.connect(database)) as conn:
                conn.executescript("""
                  CREATE TABLE capability_requests(request_id TEXT,source_task_id TEXT,status TEXT,
                    payload_json TEXT,updated_utc TEXT,created_utc TEXT);
                  CREATE TABLE tasks(id TEXT,status TEXT,agent TEXT,result_json TEXT,budget_json TEXT);
                  CREATE TABLE mission_tasks(canonical_id TEXT,status TEXT,runtime_task_id TEXT);
                """)
                stale_payload = json.dumps({"status": "WAITING_LOCAL", "allowed_paths": ["src/a.py"],
                                            "test_paths": ["tests/unit/test_a.py"]})
                current_payload = json.dumps({"status": "WAITING_LOCAL", "allowed_paths": ["src/b.py"],
                                              "test_paths": ["tests/unit/test_b.py"]})
                conn.execute("INSERT INTO capability_requests VALUES(?,?,?,?,?,?)",
                    ("CAP_STALE", "TASK_DONE", "NEW", stale_payload, "", ""))
                conn.execute("INSERT INTO capability_requests VALUES(?,?,?,?,?,?)",
                    ("CAP_CURRENT", "TASK_CURRENT", "NEW", current_payload, "", ""))
                conn.execute("INSERT INTO tasks VALUES(?,?,?,?,?)",
                    ("TASK_DONE", "DONE", "mission-pack-executor", stale_payload,
                     json.dumps({"mission_pack_task": "A09"})))
                conn.execute("INSERT INTO tasks VALUES(?,?,?,?,?)",
                    ("TASK_CURRENT", "BLOCKED", "mission-pack-executor", current_payload,
                     json.dumps({"mission_pack_task": "B01"})))
                conn.execute("INSERT INTO mission_tasks VALUES(?,?,?)", ("A09", "DONE", "TASK_DONE"))
                conn.execute("INSERT INTO mission_tasks VALUES(?,?,?)", ("B01", "PROPOSED", "TASK_CURRENT"))
                conn.commit()
            queued_ids: list[str] = []

            def queue(request: dict, *, source_task_id: str) -> dict:
                queued_ids.append(str(request["request_id"]))
                return {"created": True, "request_id": request["request_id"]}

            with mock.patch.object(autonomous_manager, "_connect",
                                   side_effect=lambda *_args, **_kwargs: _connect_temp(database)), \
                 mock.patch.object(capability_broker, "ensure_schema"), \
                 mock.patch.object(autonomous_manager, "_event"), \
                 mock.patch.object(autonomous_manager, "_queue_capability_request", side_effect=queue):
                result = autonomous_manager._queue_waiting_capability_requests(min_retry_age_s=0)
        self.assertEqual(queued_ids, ["CAP_CURRENT"])
        self.assertEqual([item["request_id"] for item in result], ["CAP_CURRENT"])

    def test_empty_queue_schedules_independent_mp0_writer_readback(self) -> None:
        idle = {"status": "NO_TASKS", "eligible_task_ids": [], "leased_count": 0,
                "message": "no eligible tasks"}
        readback = {"created": True, "task_id": "AUTO_MP0_INDEPENDENT_READBACK_01",
                    "reason": "new independent writer check"}
        with mock.patch.object(autonomous_manager, "queue_diagnosis", return_value=idle), \
             mock.patch("src.agent.mission_pack.reconcile_runtime_missions", return_value=[]), \
             mock.patch("src.agent.mission_pack.planner_diagnosis", return_value={"decision": "WAITING_DEPENDENCIES", "message": "fixture"}), \
             mock.patch.object(project_director, "seed_next_deterministic_supervisor_replay", return_value={"created": False}), \
             mock.patch.object(project_director, "seed_next_national_osm_task", return_value={"created": False}) as national, \
             mock.patch.object(autonomous_manager, "seed_experimental_writer_roundtrip_task",
                               return_value={"created": False}), \
             mock.patch.object(project_director, "seed_next_plan_task", return_value={"created": False}), \
             mock.patch.object(project_director, "seed_next_component_survey_director_task", return_value={"created": False}), \
             mock.patch.object(project_director, "seed_next_component_survey_task", return_value={"created": False}), \
             mock.patch.object(project_director, "seed_next_mp0_independent_readback_task",
                               return_value=readback) as seed_readback, \
             mock.patch.object(project_director, "seed_next_firmware_hex_task") as later_firmware:
            result = autonomous_manager.schedule_next_goal_task()
        self.assertEqual(result["task_id"], readback["task_id"])
        seed_readback.assert_called_once_with()
        national.assert_not_called()
        later_firmware.assert_not_called()

    def test_empty_queue_seeds_local_director_from_unseen_binary_inputs(self) -> None:
        idle = {"status": "NO_TASKS", "eligible_task_ids": [], "leased_count": 0,
                "message": "no eligible tasks"}
        planned = {"created": True, "task_id": "AUTO_DIRECTOR_SW_COMPONENT_SCAN_TEST",
                   "reason": "unexamined manifest-backed SW inputs"}
        with mock.patch.object(autonomous_manager, "queue_diagnosis", return_value=idle), \
             mock.patch("src.agent.mission_pack.reconcile_runtime_missions", return_value=[]), \
             mock.patch("src.agent.mission_pack.planner_diagnosis", return_value={"decision": "WAITING_DEPENDENCIES", "message": "fixture"}), \
             mock.patch.object(project_director, "seed_next_deterministic_supervisor_replay", return_value={"created": False}), \
             mock.patch.object(project_director, "reconcile_national_osm_continuations",
                               return_value={"complete": False}), \
             mock.patch.object(project_director, "seed_next_mp0_independent_readback_task",
                               return_value={"created": False}), \
             mock.patch.object(project_director, "seed_next_component_survey_director_task",
                               return_value=planned) as seed_director:
            result = autonomous_manager.schedule_next_goal_task()
        self.assertEqual(result["task_id"], planned["task_id"])
        seed_director.assert_called_once_with()

    def test_starting_a_task_clears_stale_idle_reason(self) -> None:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as folder:
            database = Path(folder) / "state.sqlite"
            with closing(sqlite3.connect(database)) as conn:
                conn.execute("CREATE TABLE autonomy_control(singleton INTEGER PRIMARY KEY, worker_pid INTEGER, session_id TEXT, current_task TEXT, health_json TEXT, last_error TEXT, updated_utc TEXT)")
                conn.execute("INSERT INTO autonomy_control VALUES(1,NULL,NULL,NULL,'{}','No PENDING tasks; 7 BLOCKED','')")
                conn.commit()
            with mock.patch.object(autonomous_manager, "_connect", side_effect=lambda *_args, **_kwargs: _connect_temp(database)):
                autonomous_manager._set_worker("session", 1234, task_id="AUTO_NEXT_TASK")
            with closing(sqlite3.connect(database)) as conn:
                last_error, current_task = conn.execute("SELECT last_error,current_task FROM autonomy_control WHERE singleton=1").fetchone()
            self.assertEqual(current_task, "AUTO_NEXT_TASK")
            self.assertEqual(last_error, "")

    def test_empty_queue_seeds_local_director_for_unfinished_ncdx_data(self) -> None:
        idle = {"status": "NO_TASKS", "eligible_task_ids": [], "leased_count": 0,
                "message": "no eligible tasks; hardware remains blocked"}
        planned = {"created": True, "task_id": "AUTO_DIRECTOR_NCDX_DATA_TEST",
                   "reason": "unexamined map data"}
        with mock.patch.object(autonomous_manager, "queue_diagnosis", return_value=idle), \
             mock.patch("src.agent.mission_pack.reconcile_runtime_missions", return_value=[]), \
             mock.patch("src.agent.mission_pack.planner_diagnosis", return_value={"decision": "WAITING_DEPENDENCIES", "message": "fixture"}), \
             mock.patch.object(project_director, "seed_next_deterministic_supervisor_replay", return_value={"created": False}), \
             mock.patch.object(project_director, "seed_next_national_osm_task", return_value={"created": False}), \
             mock.patch.object(autonomous_manager, "seed_experimental_writer_roundtrip_task",
                               return_value={"created": False, "reason": "already tested"}), \
             mock.patch.object(project_director, "seed_next_plan_task",
                               return_value={"created": False, "reason": "fixed plans complete"}), \
             mock.patch.object(project_director, "seed_next_component_survey_director_task", return_value={"created": False}), \
             mock.patch.object(project_director, "seed_next_component_survey_task",
                               return_value={"created": False, "reason": "SW survey complete"}), \
             mock.patch.object(project_director, "seed_next_mp0_independent_readback_task",
                               return_value={"created": False, "reason": "readback already tested"}), \
             mock.patch.object(project_director, "seed_next_firmware_hex_task",
                               return_value={"created": False, "reason": "firmware HEX already verified"}), \
             mock.patch.object(project_director, "seed_next_data_family_director_task",
                               return_value=planned) as seed_data, \
             mock.patch.object(coordinator_runtime, "seed_independent_goal_task") as old_f2:
            result = autonomous_manager.schedule_next_goal_task()
        self.assertTrue(result["created"])
        self.assertEqual(result["task_id"], planned["task_id"])
        seed_data.assert_called_once_with()
        old_f2.assert_not_called()

    def test_empty_queue_advances_to_verified_firmware_format_research(self) -> None:
        idle = {"status": "NO_TASKS", "eligible_task_ids": [], "leased_count": 0,
                "message": "no eligible tasks; hardware remains blocked"}
        firmware = {"created": True, "task_id": "AUTO_FIRMWARE_INTEL_HEX_TEST",
                    "reason": "four manifest-backed firmware inputs"}
        with mock.patch.object(autonomous_manager, "queue_diagnosis", return_value=idle), \
             mock.patch("src.agent.mission_pack.reconcile_runtime_missions", return_value=[]), \
             mock.patch("src.agent.mission_pack.planner_diagnosis", return_value={"decision": "WAITING_DEPENDENCIES", "message": "fixture"}), \
             mock.patch.object(project_director, "seed_next_national_osm_task", return_value={"created": False}) as national, \
             mock.patch.object(autonomous_manager, "seed_experimental_writer_roundtrip_task",
                               return_value={"created": False}), \
             mock.patch.object(project_director, "seed_next_plan_task", return_value={"created": False}), \
             mock.patch.object(project_director, "seed_next_component_survey_director_task", return_value={"created": False}), \
             mock.patch.object(project_director, "seed_next_component_survey_task", return_value={"created": False}), \
             mock.patch.object(project_director, "seed_next_mp0_independent_readback_task", return_value={"created": False}), \
             mock.patch.object(project_director, "seed_next_firmware_hex_task", return_value=firmware) as seed_hex, \
             mock.patch.object(project_director, "seed_next_deterministic_supervisor_replay",
                               return_value={"created": False}), \
             mock.patch.object(project_director, "seed_next_data_family_director_task") as later_data, \
             mock.patch.object(coordinator_runtime, "seed_independent_goal_task") as old_f2:
            result = autonomous_manager.schedule_next_goal_task()
        self.assertEqual(result["task_id"], firmware["task_id"])
        seed_hex.assert_called_once_with()
        national.assert_not_called()
        later_data.assert_not_called()
        old_f2.assert_not_called()

    def test_writer_goal_is_scheduled_from_the_read_only_source_root_once(self) -> None:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as folder:
            root = Path(folder)
            database = root / "state.sqlite"
            regions = (("SW", Path("SW") / "DB", "EUZ"),
                       ("Italy", Path("Italy") / "DB", "IZ"),
                       ("Scandinavia", Path("Scandinavia") / "DB", "SCZ"))
            for label, relative, prefix in regions:
                source = root / relative / f"{prefix}.MP0"
                source.parent.mkdir(parents=True, exist_ok=True)
                source.write_bytes((label + " confirmed header fixture\n").encode("ascii") * 8)
            with mock.patch.object(autonomous_manager, "STATE_DB", database), \
                 mock.patch.object(coordinator_runtime, "SOURCE_ROOT", root), \
                 mock.patch.object(coordinator_runtime, "REGIONS", regions), \
                 mock.patch.object(autonomous_manager, "ensure_schema"), \
                 mock.patch.object(autonomous_manager, "_event"), \
                 mock.patch.object(autonomous_manager, "_connect", side_effect=lambda *_args, **_kwargs:
                                   _connect_temp(database)):
                from src.agent import state_store
                state_store.add_task({"id": "F2_MP0_HEADER_READER", "stage": "F2", "depends_on": [],
                                      "hypothesis": "verified header", "evidence": [],
                                      "agent": "deterministic", "budget": {}, "deliverables": [],
                                      "tests": [], "next_action": "continue"}, db_path=database)
                with closing(sqlite3.connect(database)) as conn:
                    conn.execute("UPDATE tasks SET status='DONE' WHERE id='F2_MP0_HEADER_READER'")
                    conn.commit()
                scheduled = autonomous_manager.seed_experimental_writer_roundtrip_task()
                self.assertTrue(scheduled["created"], scheduled)
                self.assertEqual([source["relative_path"] for source in scheduled["sources"]],
                                 ["SW/DB/EUZ.MP0", "Italy/DB/IZ.MP0", "Scandinavia/DB/SCZ.MP0"])
                self.assertFalse(autonomous_manager.seed_experimental_writer_roundtrip_task()["created"])
                for _label, relative, prefix in regions:
                    source = root / relative / f"{prefix}.MP0"
                    self.assertTrue(source.is_file())

    def test_copy_only_writer_roundtrips_three_allowlisted_sources_and_changes_one_field(self) -> None:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as folder:
            root = Path(folder)
            regions = (("SW", Path("SW") / "DB", "EUZ"),
                       ("Italy", Path("Italy") / "DB", "IZ"),
                       ("Scandinavia", Path("Scandinavia") / "DB", "SCZ"))
            codes = ("EU44420940.82", "I44442940.83", "SC44442940.84")
            sources = []
            for (label, relative, prefix), code in zip(regions, codes):
                source = root / relative / f"{prefix}.MP0"
                source.parent.mkdir(parents=True, exist_ok=True)
                header = bytearray(b"?" * 64)
                header[:13] = b"(*$SIEMENS&^)"
                header[16:32] = b"Copyright 1998\0\0"
                header[32:48] = b"2.0.0\0" + b"\0" * 10
                encoded = code.encode("ascii")
                header[48:64] = encoded + b"\0" * (16 - len(encoded))
                source.write_bytes(bytes(header) + bytes(range(64)))
                sources.append({"region": label, "relative_path": str(source.relative_to(root)).replace("\\", "/"),
                                "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                                "size_bytes": source.stat().st_size})
            task = {"id": autonomous_manager.EXPERIMENTAL_WRITER_TASK_ID,
                    "evidence_json": json.dumps([{"mode": "copy_only_mp0_roundtrip", "sources": sources}])}
            report_path = root / "reports" / "autonomous_writer_roundtrip.json"
            with mock.patch.object(autonomous_manager, "PROJECT_ROOT", root), \
                 mock.patch.object(autonomous_manager, "MANAGER_WORK", root / "work"), \
                 mock.patch.object(autonomous_manager, "REPORT_PATH", report_path), \
                 mock.patch.object(autonomous_manager, "_task", return_value=task), \
                 mock.patch.object(autonomous_manager, "_protected_source_hashes", return_value={}), \
                 mock.patch.object(autonomous_manager, "_artifact", side_effect=lambda _tid, path, _desc, acceptance:
                                   {"path": str(path.relative_to(root)), "acceptance": acceptance}), \
                 mock.patch.object(autonomous_manager, "_event"), \
                 mock.patch.object(coordinator_runtime, "REGIONS", regions), \
                 mock.patch.object(coordinator_runtime, "SOURCE_ROOT", root):
                result = autonomous_manager._experimental_writer_roundtrip(
                    autonomous_manager.EXPERIMENTAL_WRITER_TASK_ID)
            self.assertEqual(result["status"], "PASS_COPY_ONLY")
            self.assertEqual(len(result["regional_roundtrips"]), 3)
            self.assertEqual(result["source_write_count"], 0)
            self.assertTrue(result["controlled_header_change"]["controlled_change_pass"])
            for row in result["regional_roundtrips"]:
                self.assertEqual(row["no_op"]["source_sha256_before"], row["no_op"]["working_copy_sha256"])
                self.assertEqual(row["source_header"]["sha256"], row["copy_header"]["sha256"])
                self.assertEqual(row["source_header"]["header_hex"], row["copy_header"]["header_hex"])

    def test_worker_child_environment_is_utf8(self) -> None:
        env = autonomous_manager.python_utf8_environment()
        self.assertEqual(env["PYTHONUTF8"], "1")
        self.assertEqual(env["PYTHONIOENCODING"], "utf-8:backslashreplace")
        self.assertEqual(env["PYTHONDONTWRITEBYTECODE"], "1")

    def test_child_capture_accepts_result_larger_than_windows_pipe_buffer(self) -> None:
        class ExitedChild:
            pid = 12345
            returncode = 0
            def poll(self):
                return 0

        expected = {"payload": "x" * 8192}
        def fake_popen(_command, **kwargs):
            kwargs["stdout"].write((json.dumps(expected) + "\n").encode("utf-8"))
            return ExitedChild()

        with mock.patch.object(autonomous_manager.subprocess, "Popen", side_effect=fake_popen):
            result = autonomous_manager._capture_child("large-result", "session", 10)
        self.assertEqual(result, expected)

    def test_queue_diagnosis_names_blocked_dependency_and_error(self) -> None:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as folder:
            database = Path(folder) / "queue.sqlite"
            conn = sqlite3.connect(database)
            conn.execute("""CREATE TABLE tasks(
                id TEXT, status TEXT, depends_on_json TEXT, result_json TEXT,
                priority INTEGER, created_utc TEXT, next_action TEXT DEFAULT '')""")
            conn.execute("INSERT INTO tasks(id,status,depends_on_json,result_json,priority,created_utc) VALUES(?,?,?,?,?,?)", (
                "review", "BLOCKED", "[]", json.dumps({"error": "TimeoutError: model deadline"}), 2, "1"))
            conn.execute("INSERT INTO tasks(id,status,depends_on_json,result_json,priority,created_utc) VALUES(?,?,?,?,?,?)", (
                "followup", "PENDING", json.dumps(["review"]), "{}", 3, "2"))
            conn.commit()
            conn.close()
            diagnosis = autonomous_manager.queue_diagnosis(database)
        self.assertEqual(diagnosis["status"], "WAITING_DEPENDENCY")
        self.assertIn("followup", diagnosis["message"])
        self.assertIn("review [BLOCKED]", diagnosis["message"])
        self.assertIn("TimeoutError", diagnosis["message"])

    def test_only_known_fixed_diagnostics_are_recoverable(self) -> None:
        reason = autonomous_manager._known_recovery_reason(
            "AUTO_BRANCH_OSM", "UnicodeEncodeError: 'charmap' codec can't encode characters")
        self.assertIn(autonomous_manager.KNOWN_RECOVERY_VERSION, reason)
        bootstrap_reason = autonomous_manager._known_recovery_reason(
            "AUTO_RESEARCH_BOOTSTRAP", "ScriptRejected: syntax rejected: AugAssign")
        self.assertIn(autonomous_manager.KNOWN_RECOVERY_VERSION, bootstrap_reason)
        git_reason = autonomous_manager._known_recovery_reason(
            "AUTO_MISSION_EXEC_A01_E93FBACD",
            'RuntimeError: {"error": "FileNotFoundError: [WinError 2] git executable missing"}')
        self.assertIn("optional Git/version probes in A01", git_reason)
        d02_reason = autonomous_manager._known_recovery_reason(
            "AUTO_MISSION_EXEC_D02_04B54E91",
            'RuntimeError: {"error": "ValueError: artifact path escaped the manager work area: '
            'C:\\\\NCDR\\\\osm\\\\source-manifest.json"}')
        self.assertIn("D02 runner now publishes its verified manifest", d02_reason)
        b01_reason = autonomous_manager._known_recovery_reason(
            "AUTO_MISSION_EXEC_B01_88597DAE",
            'RuntimeError: {"error": "ValueError: artifact path escaped the manager work area: '
            'C:\\NCDR\\evidence\\format-evidence-index.json"}')
        self.assertIn("b01-format-index-artifact-v1", b01_reason)
        ollama_reason = autonomous_manager._known_recovery_reason(
            "AUTO_OSM_FAILURE_REVIEW_B749A7021693",
            'RuntimeError: {"error": "TimeoutError: Ollama API did not become available within 45 seconds"}')
        self.assertIn("without an automatic retry loop", ollama_reason)
        self.assertIsNone(autonomous_manager._known_recovery_reason(
            "F1_TARGET_COMPATIBILITY", "hardware target identity unavailable"))
        self.assertIsNone(autonomous_manager._known_recovery_reason(
            "AUTO_RESEARCH_FOLLOWUP_0cd28fa7886a", "script field is missing or too large"))
        review_reason = autonomous_manager._known_recovery_reason(
            "AUTO_REVIEW_11070784d881defd9c",
            "ValueError: local model returned invalid structured JSON: Expecting value: line 1 column 1 (char 0)")
        self.assertIn(autonomous_manager.KNOWN_RECOVERY_VERSION, review_reason)
        utf8_reason = autonomous_manager._known_recovery_reason(
            "AUTO_SCHEDULED_PROBE_MG1_deadbeef0000",
            "UnicodeEncodeError: 'charmap' codec can't encode characters in position 59-67")
        self.assertIn("isolated Python stdout now explicitly reconfigures UTF-8", utf8_reason)
        firmware_reason = autonomous_manager._known_recovery_reason(
            "AUTO_FIRMWARE_INTEL_HEX_READ_704b4872a2c6",
            "RuntimeError: No allowlisted autonomous handler for 'AUTO_FIRMWARE_INTEL_HEX_READ_704b4872a2c6'")
        self.assertIn("firmware-intel-hex-reader was added", firmware_reason)

    def test_zlib_census_contract_recovery_is_narrow_and_requires_a_saved_pass_target(self) -> None:
        target_id = "AUTO_NCDX_DATA_RL_STANDALONE_ZLIB_STREAM_CENSUS_fixture"
        target_reason = autonomous_manager._known_recovery_reason(
            target_id, "RuntimeError: task process returned no result JSON: truncated stream inventory")
        self.assertIn("ncdx-zlib-result-contract-v2", target_reason)
        self.assertIsNone(autonomous_manager._known_recovery_reason(
            target_id, "RuntimeError: source hash mismatch"))
        self.assertIsNone(autonomous_manager._known_recovery_reason(
            "AUTO_NCDX_DATA_RL_CONTAINER_ROUNDTRIP_fixture",
            "RuntimeError: task process returned no result JSON: oversized output"))

        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as temporary:
            database = Path(temporary) / "state.sqlite"
            with closing(sqlite3.connect(database)) as conn:
                conn.execute("CREATE TABLE tasks(id TEXT PRIMARY KEY,status TEXT,result_json TEXT)")
                saved_result = {"status": "PASS", "verified": {
                    "semantic_format": "UNKNOWN; bounded zlib stream candidates only"}}
                conn.execute("INSERT INTO tasks VALUES(?,?,?)",
                             (target_id, "DONE", json.dumps(saved_result)))
                conn.commit()
            supervisor_id = f"AUTO_SUPERVISOR_{target_id}"
            diagnostic = f"RuntimeError: Supervisor refused incomplete read-only proof for {target_id}"
            with mock.patch.object(autonomous_manager, "STATE_DB", database):
                supervisor_reason = autonomous_manager._known_recovery_reason(supervisor_id, diagnostic)
                self.assertIn("ncdx-zlib-result-contract-v2", supervisor_reason)
                with closing(sqlite3.connect(database)) as conn:
                    conn.execute("UPDATE tasks SET status='BLOCKED' WHERE id=?", (target_id,))
                    conn.commit()
                self.assertIsNone(autonomous_manager._known_recovery_reason(supervisor_id, diagnostic))

                legacy_result = {"status": "PASS", "observations": [
                    {"streams": [{} for _ in range(65)]} for _ in range(3)]}
                with closing(sqlite3.connect(database)) as conn:
                    conn.execute("UPDATE tasks SET status='DONE',result_json=? WHERE id=?",
                                 (json.dumps(legacy_result), target_id))
                    conn.commit()
                legacy_diagnostic = f"RuntimeError: fresh Supervisor standalone-zlib census differed for {target_id}"
                legacy_reason = autonomous_manager._known_recovery_reason(supervisor_id, legacy_diagnostic)
                self.assertIn("ncdx-zlib-legacy-result-v1", legacy_reason)

                with closing(sqlite3.connect(database)) as conn:
                    conn.execute("""CREATE TABLE autonomy_events(
                        task_id TEXT,event TEXT,detail_json TEXT)""")
                    conn.execute("CREATE TABLE leases(task_id TEXT)")
                    conn.execute("""CREATE TABLE recovery_tasks(
                        id TEXT PRIMARY KEY,status TEXT,attempts INTEGER,verdict TEXT,result_json TEXT,
                        lease_owner TEXT,lease_until TEXT,updated_utc TEXT,priority INTEGER)""")
                    conn.execute("DROP TABLE tasks")
                    conn.execute("ALTER TABLE recovery_tasks RENAME TO tasks")
                    conn.execute("INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?,?)", (
                        target_id, "DONE", 1, "PASS", json.dumps(legacy_result), None, None, "now", 16))
                    conn.execute("INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?,?)", (
                        supervisor_id, "BLOCKED", 1, "BLOCKED", json.dumps({"error": legacy_diagnostic}),
                        None, None, "now", 11))
                    conn.commit()
                with mock.patch.object(autonomous_manager, "STATE_DB", database), \
                     mock.patch.object(autonomous_manager, "_event"):
                    recovered = autonomous_manager.recover_known_code_blockers(db_path=database)
                self.assertEqual(set(recovered), {target_id, supervisor_id})
                with closing(sqlite3.connect(database)) as conn:
                    statuses = dict(conn.execute("SELECT id,status FROM tasks"))
                self.assertEqual(statuses, {target_id: "PENDING", supervisor_id: "PENDING"})

    def test_sandbox_allowlist_accepts_only_the_expected_pure_repair(self) -> None:
        self.assertTrue(autonomous_manager._pure_normalizer(
            "def normalize_region_code(value):\n    return value.strip().upper()\n"))

    def test_sandbox_rejects_imports_side_effects_and_extra_functions(self) -> None:
        invalid = (
            "import os\ndef normalize_region_code(value):\n    return value.strip().upper()\n",
            "def normalize_region_code(value):\n    open('original.img', 'wb').write(b'x')\n",
            "def normalize_region_code(value):\n    return value.strip()\n\ndef extra():\n    return None\n",
            "@property\ndef normalize_region_code(value):\n    return value.strip().upper()\n",
        )
        for candidate in invalid:
            with self.subTest(candidate=candidate):
                self.assertFalse(autonomous_manager._pure_normalizer(candidate))

    def test_track_acceptance_is_fixed_to_an_internal_allowlist(self) -> None:
        self.assertEqual(set(autonomous_manager.TRACKS), {"binary_analysis", "osm", "writer_boundary"})
        self.assertNotIn("virtual_cid", autonomous_manager.TRACKS)
        self.assertNotIn("poi_editor", autonomous_manager.TRACKS)
        for focus in autonomous_manager.TRACKS:
            with self.subTest(focus=focus):
                self.assertTrue(autonomous_manager._track_acceptance(focus))
        with self.assertRaises(ValueError):
            autonomous_manager._track_acceptance("run arbitrary code")

    def test_initial_seed_does_not_recreate_archived_product_tracks(self) -> None:
        from src.agent import state_store
        with mock.patch.object(autonomous_manager, "_selected_model", return_value="qwen3.5:4b"), \
             mock.patch.object(state_store, "add_task", return_value=True):
            task_ids = autonomous_manager.seed_initial_tasks()
        self.assertFalse(any("VIRTUAL_CID" in task_id or "POI_EDITOR" in task_id for task_id in task_ids))
        self.assertIn("AUTO_BRANCH_OSM", task_ids)
        self.assertIn("AUTO_BRANCH_BINARY_ANALYSIS", task_ids)
        self.assertIn("AUTO_BRANCH_WRITER_BOUNDARY", task_ids)

    def test_artifact_registration_rejects_paths_outside_owned_outputs(self) -> None:
        outside = PROJECT_ROOT.parent / "not-an-autonomous-artifact.txt"
        with self.assertRaises(ValueError):
            autonomous_manager._artifact("test", outside, "probe", "PASS")

    def test_worker_releases_lock_when_checkpoint_recovery_fails(self) -> None:
        from src.agent import coordinator_runtime
        lock = object()
        with mock.patch.object(autonomous_manager, "ensure_schema"), \
             mock.patch.object(autonomous_manager, "seed_initial_tasks"), \
             mock.patch.object(autonomous_manager, "_control", return_value={"desired_state": "RUNNING"}), \
             mock.patch.object(autonomous_manager, "_acquire_worker_lock", return_value=lock), \
             mock.patch.object(autonomous_manager, "_recover_orphaned_leases", return_value=0), \
             mock.patch.object(coordinator_runtime, "_recover_verified_model_outputs", side_effect=RuntimeError("recovery failure")), \
             mock.patch.object(autonomous_manager, "_set_worker") as set_worker, \
             mock.patch.object(autonomous_manager, "_release_worker_lock") as release_lock, \
             mock.patch.object(autonomous_manager, "_event"):
            with self.assertRaisesRegex(RuntimeError, "recovery failure"):
                autonomous_manager.run_worker(max_tasks=1)
        release_lock.assert_called_once_with(lock)
        set_worker.assert_called_once_with(None, None, task_id=None)


if __name__ == "__main__":
    unittest.main()
