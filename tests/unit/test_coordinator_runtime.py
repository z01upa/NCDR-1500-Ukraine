from __future__ import annotations

import json
import hashlib
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.agent import autonomous_manager, coordinator_runtime, mission_pack, project_director


class CoordinatorRuntimeTests(unittest.TestCase):
    def test_b01_format_index_has_exact_offsets_hashes_and_independent_readback(self) -> None:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as folder:
            base = Path(folder)
            source_root = base / "source"
            project_root = base / "project"
            project_root.mkdir()
            (project_root / "reports").mkdir()
            (project_root / "reports" / "FORMAT_UNKNOWN.md").write_text(
                "# Unknowns\n- Road record semantics remain unknown.\n", encoding="utf-8")
            dataset_codes = {"EUZ": "EU44420940.82", "IZ": "I44431940.82",
                             "SCZ": "SC44442940.82"}
            toc_versions = {"EUZ": "444.20.940.82", "IZ": "444.31.940.82",
                            "SCZ": "444.42.940.82"}
            for _label, folder_rel, prefix in coordinator_runtime.REGIONS:
                db_dir = source_root / folder_rel
                db_dir.mkdir(parents=True)
                header = bytearray(96)
                header[:13] = b"(*$SIEMENS&^)"
                for offset, value in ((16, b"Copyright 1998"), (32, b"2.0.0"),
                                      (48, dataset_codes[prefix].encode("ascii"))):
                    header[offset:offset + len(value)] = value
                (db_dir / f"{prefix}.MP0").write_bytes(header)
                toc = source_root / folder_rel.parent / "CDROM.TOC"
                toc.parent.mkdir(parents=True, exist_ok=True)
                toc.write_text(f"Version:    {toc_versions[prefix]}\n", encoding="cp1252")

            output = project_root / "evidence" / "format-evidence-index.json"
            built = project_director.build_b01_format_evidence_index(
                source_root=source_root, output_path=output, project_root=project_root)
            proof = mission_pack.verify_b01_format_evidence_index(
                output, source_root=source_root, project_root=project_root)
            index = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(built["fact_count"], 12)
        self.assertEqual(proof["b01_verified_fact_count"], 12)
        self.assertEqual(proof["b01_verified_dataset_count"], 3)
        self.assertEqual(index["claim_boundaries"]["db_0_format_transferred_to_ncdx"], False)
        self.assertTrue(all(len(fact["checks"]) >= 2 for fact in index["facts"]))

    def test_local_first_roles_are_pinned_and_never_use_benchmark_fallbacks(self) -> None:
        installed = {"qwen3.5:4b", "qwen3.5:9b", "qwen2.5-coder:7b"}
        with mock.patch.object(coordinator_runtime, "_model_report",
                               return_value={"recommended_model": "qwen3.5:4b", "models": []}):
            self.assertEqual(coordinator_runtime._choose_model("project-director", installed), "qwen3.5:9b")
            self.assertEqual(coordinator_runtime._choose_model("code", installed), "qwen2.5-coder:7b")
            with self.assertRaisesRegex(RuntimeError, "qwen3.5:9b"):
                coordinator_runtime._choose_model("project-director", {"qwen3.5:4b"})

    def test_dashboard_accepts_legacy_artifact_table_without_task_id_and_filters_archived_paths(self) -> None:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as folder:
            root = Path(folder)
            database = root / "state.sqlite"
            conn = sqlite3.connect(database)
            conn.executescript("""
                CREATE TABLE tasks(id TEXT PRIMARY KEY,stage TEXT,status TEXT,agent TEXT,
                    updated_utc TEXT,budget_json TEXT,next_action TEXT,result_json TEXT,evidence_json TEXT);
                CREATE TABLE artifacts(path TEXT PRIMARY KEY,sha256 TEXT,size_bytes INTEGER,
                    description TEXT,created_utc TEXT);
                CREATE TABLE autonomy_artifacts(task_id TEXT,path TEXT,sha256 TEXT,size_bytes INTEGER,
                    description TEXT,acceptance TEXT,created_utc TEXT,PRIMARY KEY(task_id,path));
                CREATE TABLE evidence(id INTEGER PRIMARY KEY);
                INSERT INTO artifacts VALUES('reports/legacy-result.json','abc',10,'legacy','2026-10-26T00:00:00Z');
                INSERT INTO autonomy_artifacts VALUES('AUTO_NCDX_RESEARCH','reports/ncdx-result.json','def',12,'active','PASS','2026-10-26T01:00:00Z');
                INSERT INTO autonomy_artifacts VALUES('AUTO_VIRTUAL_CID_GUI','reports/virtual_cid_result.json','ghi',20,'archived','PASS','2026-10-26T02:00:00Z');
            """)
            conn.commit()
            conn.close()
            with mock.patch.object(coordinator_runtime, "STATE_DB", database), \
                 mock.patch.object(coordinator_runtime, "PROJECT_ROOT", root), \
                 mock.patch.object(coordinator_runtime, "_host_resources", return_value={}), \
                 mock.patch.object(coordinator_runtime, "_model_report", return_value={"models": []}):
                state = coordinator_runtime.dashboard_state()
        paths = {row["path"] for row in state["artifacts"]}
        self.assertIn("reports/legacy-result.json", paths)
        self.assertIn("reports/ncdx-result.json", paths)
        self.assertNotIn("reports/virtual_cid_result.json", paths)

    def test_independent_review_uses_benchmarked_small_model_before_qwythos(self) -> None:
        benchmark = {"recommended_model": "qwen3.5:4b", "models": [
            {"model": "qwen3.5:4b", "status": "COMPLETE", "passed": 8, "verified_results_per_minute": 24.38},
            {"model": "hf.co/empero-ai/Qwythos-9B-v2-GGUF:Q4_K_M", "status": "COMPLETE", "passed": 8, "verified_results_per_minute": 10.66},
        ]}
        with mock.patch.object(coordinator_runtime, "_model_report", return_value=benchmark):
            selected = coordinator_runtime._choose_model("independent-review", {
                "qwen3.5:4b", "qwen2.5-coder:7b", "hf.co/empero-ai/Qwythos-9B-v2-GGUF:Q4_K_M"})
        self.assertEqual(selected, "qwen3.5:4b")

    def test_ollama_api_timeout_is_persisted_with_model_and_error(self) -> None:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as folder:
            database = Path(folder) / "state.sqlite"
            settings = Path(folder) / "model_text_settings.json"
            conn = sqlite3.connect(database)
            conn.execute("""CREATE TABLE research_runs(
                task_id TEXT, sequence INTEGER, role TEXT, model TEXT, input_json TEXT,
                response_text TEXT, parsed_json TEXT, artifact_paths_json TEXT, tests_json TEXT,
                decision TEXT, elapsed_ms INTEGER, resource_json TEXT, error TEXT, created_utc TEXT,
                UNIQUE(task_id,sequence))""")
            conn.commit()
            conn.close()
            resources = {"disk_free_bytes": 20 * 1024**3, "ram": {"available_bytes": 8 * 1024**3},
                         "gpu": {"memory_free_mib": 7000}}
            with mock.patch.object(coordinator_runtime, "STATE_DB", database), \
                 mock.patch.object(coordinator_runtime, "_start_ollama_if_needed"), \
                 mock.patch.object(coordinator_runtime, "_available_models", return_value={"qwen3.5:4b"}), \
                 mock.patch.object(coordinator_runtime, "_choose_model", return_value="qwen3.5:4b"), \
                 mock.patch.object(coordinator_runtime, "_host_resources", return_value=resources), \
                 mock.patch.object(coordinator_runtime, "_api_json", side_effect=TimeoutError("model deadline")), \
                 mock.patch.object(coordinator_runtime, "_log_event"):
                with self.assertRaisesRegex(RuntimeError, "qwen3.5:4b.*model deadline"):
                    coordinator_runtime._call_model("timeout-task", "independent-review", "bounded test")
            conn = sqlite3.connect(database)
            row = conn.execute("SELECT model,decision,error FROM research_runs WHERE task_id='timeout-task'").fetchone()
            conn.close()
        self.assertEqual(row[0], "qwen3.5:4b")
        self.assertEqual(row[1], "API_ERROR")
        self.assertIn("model deadline", row[2])

    def test_thinking_model_review_disables_separate_reasoning_channel(self) -> None:
        class Sampler:
            def __enter__(self):
                return self
            def __exit__(self, *_args):
                return None
            def summary(self):
                return {"sample_count": 1}

        resources = {"disk_free_bytes": 20 * 1024**3,
                     "ram": {"available_bytes": 8 * 1024**3},
                     "gpu": {"memory_free_mib": 7000}}
        api = mock.Mock(return_value={"message": {"content": '{"assessment":"valid"}'}})
        with mock.patch.object(coordinator_runtime, "_start_ollama_if_needed"), \
             mock.patch.object(coordinator_runtime, "_available_models", return_value={"qwen3.5:4b"}), \
             mock.patch.object(coordinator_runtime, "_choose_model", return_value="qwen3.5:4b"), \
             mock.patch.object(coordinator_runtime, "_host_resources", return_value=resources), \
             mock.patch.object(coordinator_runtime, "ResourceSampler", Sampler), \
             mock.patch.object(coordinator_runtime, "_api_json", api), \
             mock.patch.object(coordinator_runtime, "_record_llm_run"), \
             mock.patch.object(coordinator_runtime, "_log_event"):
            model, raw, parsed = coordinator_runtime._call_model("review", "independent-review", "review evidence")
        self.assertEqual(model, "qwen3.5:4b")
        self.assertEqual(parsed["assessment"], "valid")
        self.assertFalse(api.call_args.args[1]["think"])

    def test_goal_scheduler_skips_missing_regional_suffixes(self) -> None:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as folder:
            database = Path(folder) / "state.sqlite"
            conn = sqlite3.connect(database)
            conn.executescript("""
                CREATE TABLE research_experiments(target_suffix TEXT);
                CREATE TABLE tasks(id TEXT, status TEXT, evidence_json TEXT, result_json TEXT);
                CREATE TABLE research_target_claims(target_suffix TEXT PRIMARY KEY, task_id TEXT, reason TEXT, created_utc TEXT);
            """)
            conn.executemany("INSERT INTO research_experiments VALUES(?)",
                             [(suffix,) for suffix in ("PDX", "FEA", "RL", "RT")])
            conn.executemany("INSERT INTO tasks VALUES(?,?,?,?)", [
                ("missing-il", "BLOCKED", json.dumps({"required_suffix": "IL"}), json.dumps({"error": "KeyError: IL"})),
                ("missing-iof", "BLOCKED", json.dumps({"required_suffix": "IOF"}), json.dumps({"error": "KeyError: IOF"})),
            ])
            conn.commit()
            conn.close()
            with mock.patch.object(coordinator_runtime, "STATE_DB", database), \
                 mock.patch.object(coordinator_runtime, "ensure_runtime_schema"), \
                 mock.patch.object(coordinator_runtime, "available_target_suffixes",
                                   return_value=("PDX", "FEA", "RL", "RT", "MP0")), \
                 mock.patch.object(coordinator_runtime, "_read_target", return_value=[]), \
                 mock.patch.object(coordinator_runtime, "_source_fingerprint", return_value="mp0-fingerprint"), \
                 mock.patch.object(coordinator_runtime, "_create_task", return_value=True) as create, \
                 mock.patch.object(coordinator_runtime, "_log_event"):
                result = coordinator_runtime.seed_independent_goal_task()
        self.assertTrue(result["created"])
        self.assertEqual(result["suffix"], "MP0")
        self.assertEqual(create.call_args.args[0], f"AUTO_SCHEDULED_PROBE_MP0_{'mp0-fingerprint'[:12]}")

    def test_goal_scheduler_advances_to_new_index_family_after_prefix_cap(self) -> None:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as folder:
            database = Path(folder) / "state.sqlite"
            conn = sqlite3.connect(database)
            conn.executescript("""
                CREATE TABLE research_experiments(target_suffix TEXT);
                CREATE TABLE tasks(id TEXT, status TEXT, evidence_json TEXT, result_json TEXT);
                CREATE TABLE research_target_claims(target_suffix TEXT PRIMARY KEY, task_id TEXT, reason TEXT, created_utc TEXT);
            """)
            conn.executemany("INSERT INTO research_experiments VALUES(?)",
                             [(suffix,) for suffix in ("PDX", "FEA", "RL", "RT", "IL", "IOF")])
            conn.commit()
            conn.close()
            with mock.patch.object(coordinator_runtime, "STATE_DB", database), \
                 mock.patch.object(coordinator_runtime, "ensure_runtime_schema"), \
                 mock.patch.object(coordinator_runtime, "available_target_suffixes",
                                   return_value=("PDX", "FEA", "RL", "RT", "IL", "IOF", "MG1", "MG2", "MG3", "MP0")), \
                 mock.patch.object(coordinator_runtime, "_read_target", return_value=[]), \
                 mock.patch.object(coordinator_runtime, "_source_fingerprint", return_value="mg1-fingerprint"), \
                 mock.patch.object(coordinator_runtime, "_create_task", return_value=True) as create, \
                 mock.patch.object(coordinator_runtime, "_log_event"):
                result = coordinator_runtime.seed_independent_goal_task()
            self.assertTrue(result["created"])
            self.assertEqual(result["suffix"], "MG1")
            self.assertEqual(create.call_args.args[0], f"AUTO_SCHEDULED_PROBE_MG1_{'mg1-fingerprint'[:12]}")

    def test_extended_manifest_stems_continue_after_the_ten_saved_targets(self) -> None:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as folder:
            database = Path(folder) / "state.sqlite"
            conn = sqlite3.connect(database)
            conn.executescript("""
                CREATE TABLE research_experiments(target_suffix TEXT);
                CREATE TABLE tasks(id TEXT, status TEXT, evidence_json TEXT, result_json TEXT);
                CREATE TABLE research_target_claims(target_suffix TEXT PRIMARY KEY, task_id TEXT, reason TEXT, created_utc TEXT);
            """)
            conn.executemany("INSERT INTO research_experiments VALUES(?)", [
                (suffix,) for suffix in ("PDX", "FEA", "RL", "RT", "IL", "IOF", "MG1", "MG2", "MG3", "MP0")
            ])
            conn.commit()
            conn.close()
            all_targets = ("PDX", "FEA", "RL", "RT", "IL", "IOF", "MG1", "MG2", "MG3", "MP0",
                           "ABC", "RD", "STT", "AFF", "ASC", "CL", "CNY", "CT", "CTY", "PTI", "PTP", "TYP", "CFG")
            with mock.patch.object(coordinator_runtime, "STATE_DB", database), \
                 mock.patch.object(coordinator_runtime, "ensure_runtime_schema"), \
                 mock.patch.object(coordinator_runtime, "available_target_suffixes", return_value=all_targets), \
                 mock.patch.object(coordinator_runtime, "_read_target", return_value=[]), \
                 mock.patch.object(coordinator_runtime, "_source_fingerprint", return_value="abc-fingerprint"), \
                 mock.patch.object(coordinator_runtime, "_create_task", return_value=True) as create, \
                 mock.patch.object(coordinator_runtime, "_log_event"):
                result = coordinator_runtime.seed_independent_goal_task()
            self.assertTrue(result["created"])
            self.assertEqual(result["suffix"], "ABC")
            self.assertEqual(create.call_args.args[0], "AUTO_SCHEDULED_PROBE_ABC_abc-fingerpr")

    def test_remaining_manifest_stems_are_found_read_only_across_regions(self) -> None:
        prefixes = (
            (Path("SW") / "DB", "EUZ", "EU"),
            (Path("OPEL NCDx Italia 2010-2011") / "DB", "IZ", "I"),
            (Path("OPEL NCDx Scandinavia 2010-2011") / "DB", "SCZ", "SC"),
        )
        overrides = {"ABC": ("EU", "I", "SC"), "RD": ("EU", "I", "SC"),
                     "STT": ("EU", "I", "SC"), "CFG": ("ZONE", "ZONE", "ZONE")}
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as folder:
            source_root = Path(folder)
            for _index, (suffix, stems) in enumerate(overrides.items()):
                for (relative, _default, _region_stem), stem in zip(prefixes, stems):
                    path = source_root / relative / f"{stem}.{suffix}"
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(bytes([_index + 1]) * 64)
            with mock.patch.object(coordinator_runtime, "SOURCE_ROOT", source_root), \
                 mock.patch.object(coordinator_runtime, "ALLOWED_SUFFIXES", set(overrides)):
                self.assertEqual(coordinator_runtime.available_target_suffixes(), tuple(overrides))
                rows = coordinator_runtime._read_target("ABC")
                self.assertEqual([row["region"] for row in rows], ["SW", "Italy", "Scandinavia"])
                self.assertTrue(all(row["bytes"] == 64 for row in rows))

    def test_target_suffix_claim_is_atomic_and_not_reused(self) -> None:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as folder:
            database = Path(folder) / "state.sqlite"
            with mock.patch.object(coordinator_runtime, "STATE_DB", database):
                self.assertTrue(coordinator_runtime._claim_target_suffix("MP0", "task-a", "test"))
                self.assertFalse(coordinator_runtime._claim_target_suffix("MP0", "task-b", "concurrent test"))
                self.assertTrue(coordinator_runtime._claim_target_suffix("MP0", "task-a", "idempotent retry"))
            conn = sqlite3.connect(database)
            try:
                self.assertEqual(conn.execute("SELECT target_suffix,task_id FROM research_target_claims").fetchone(),
                                 ("MP0", "task-a"))
            finally:
                conn.close()

    def test_fixed_runner_can_finish_one_previously_claimed_probe_at_the_cap(self) -> None:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as folder:
            database = Path(folder) / "state.sqlite"
            conn = sqlite3.connect(database)
            conn.executescript("""
                CREATE TABLE research_experiments(
                  fingerprint TEXT, probe_type TEXT, target_suffix TEXT, hypothesis TEXT, depth INTEGER,
                  parent_task TEXT, status TEXT, source_fingerprint TEXT, created_utc TEXT);
                CREATE TABLE research_target_claims(target_suffix TEXT PRIMARY KEY, task_id TEXT, reason TEXT, created_utc TEXT);
            """)
            conn.executemany("INSERT INTO research_experiments VALUES(?,?,?,?,?,?,?,?,?)",
                [(f"fp-{i}", "cross_region_prefix", f"X{i}", "old", 0, "old-task", "VERIFIED", "src", "now")
                 for i in range(coordinator_runtime.MAX_DYNAMIC_HYPOTHESES)])
            task_id = "AUTO_SCHEDULED_PROBE_MG1_reserved"
            conn.execute("INSERT INTO research_target_claims VALUES(?,?,?,?)",
                         ("MG1", task_id, "fixed diagnostic retry", "now"))
            conn.commit(); conn.close()
            records = [
                {"region": "SW", "bytes": 64, "sha256": "a", "prefix_bytes": [1] * 64},
                {"region": "Italy", "bytes": 64, "sha256": "b", "prefix_bytes": [1] * 64},
                {"region": "Scandinavia", "bytes": 64, "sha256": "c", "prefix_bytes": [1] * 64},
            ]
            with mock.patch.object(coordinator_runtime, "STATE_DB", database), \
                 mock.patch.object(coordinator_runtime, "_read_target", return_value=records), \
                 mock.patch.object(coordinator_runtime, "_source_fingerprint", return_value="mg1-source"), \
                 mock.patch.object(coordinator_runtime, "_create_task", return_value=True) as create, \
                 mock.patch.object(coordinator_runtime, "_log_event"):
                added, fingerprint = coordinator_runtime._register_probe(
                    task_id, "MG1", "same reserved hypothesis", "common_prefix = 1", 0,
                    "one-time diagnostic repair after explicit UTF-8 fix")
        self.assertTrue(added)
        self.assertTrue(fingerprint)
        self.assertEqual(create.call_args.args[0], f"AUTO_VERIFY_{fingerprint}")

    def test_followup_prompt_excludes_verified_target_and_tests_next_suffix(self) -> None:
        prompt, data = coordinator_runtime._prompt_for_proposal(
            "unit-followup", excluded_suffixes=["PDX"],
            prior_verified_result={"target_suffix": "PDX", "common_prefix_bytes": 8},
        )
        self.assertEqual(len(data["prefixes"]), 3)
        self.assertIn("FEA", prompt)
        self.assertIn("Не повторюй", prompt)
        self.assertIn("common_prefix_bytes", prompt)
        self.assertIn("НЕ є словником data", prompt)
        self.assertIn("data['prefixes'][0]", prompt)

    def test_followup_prompt_requires_explicit_hypothesis_and_script(self) -> None:
        prompt, _ = coordinator_runtime._prompt_for_proposal(
            "unit-followup-repair", excluded_suffixes=["PDX"], required_suffix="FEA",
            prior_verified_result={"target_suffix": "PDX", "common_prefix_bytes": 8},
            prior_diagnostic="previous model used explanation instead of hypothesis",
        )
        self.assertIn("непорожніми рядковими полями hypothesis", prompt)
        self.assertIn("target_suffix має бути рівно FEA", prompt)
        self.assertIn("explanation instead of hypothesis", prompt)

    def test_completed_review_seeds_next_unused_suffix_with_finite_cap(self) -> None:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as folder:
            database = Path(folder) / "state.sqlite"
            conn = sqlite3.connect(database)
            conn.executescript("""
                CREATE TABLE research_experiments(fingerprint TEXT, target_suffix TEXT);
                CREATE TABLE tasks(id TEXT, status TEXT, result_json TEXT);
            """)
            conn.executemany("INSERT INTO research_experiments VALUES(?,?)",
                             [("pdx", "PDX"), ("fea", "FEA")])
            conn.execute("INSERT INTO tasks VALUES(?,?,?)", (
                "verified-fea", "DONE", json.dumps({"target_suffix": "FEA", "fingerprint": "fea"})))
            conn.commit()
            conn.close()
            review_task = {"id": "review-fea", "depends_on_json": '["verified-fea"]'}
            review_result = {"next_target": "NONE", "parent_result": {"fingerprint": "fea"}}
            with mock.patch.object(coordinator_runtime, "STATE_DB", database), \
                 mock.patch.object(coordinator_runtime, "MAX_DYNAMIC_HYPOTHESES", 6), \
                 mock.patch.object(coordinator_runtime, "_create_task", return_value=True) as create, \
                 mock.patch.object(coordinator_runtime, "_log_event"):
                created = coordinator_runtime._queue_followup_proposal(review_task, review_result)
        self.assertTrue(created)
        args = create.call_args.args
        self.assertEqual(args[0], "AUTO_RESEARCH_FOLLOWUP_fea")
        self.assertEqual(args[4]["required_suffix"], "RL")
        self.assertEqual(args[4]["exclude_suffixes"], ["FEA", "PDX"])

    def test_followup_hypothesis_count_stops_at_configured_cap(self) -> None:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as folder:
            database = Path(folder) / "state.sqlite"
            conn = sqlite3.connect(database)
            conn.executescript("""
                CREATE TABLE research_experiments(fingerprint TEXT, target_suffix TEXT);
                CREATE TABLE tasks(id TEXT, status TEXT, result_json TEXT);
            """)
            conn.executemany("INSERT INTO research_experiments VALUES(?,?)",
                             [(str(i), suffix) for i, suffix in enumerate(("PDX", "FEA", "RL"))])
            conn.execute("INSERT INTO tasks VALUES(?,?,?)", (
                "verified", "DONE", json.dumps({"target_suffix": "RL", "fingerprint": "rl"})))
            conn.commit()
            conn.close()
            with mock.patch.object(coordinator_runtime, "STATE_DB", database), \
                 mock.patch.object(coordinator_runtime, "MAX_DYNAMIC_HYPOTHESES", 3), \
                 mock.patch.object(coordinator_runtime, "_create_task") as create, \
                 mock.patch.object(coordinator_runtime, "_log_event"):
                created = coordinator_runtime._queue_followup_proposal(
                    {"id": "review", "depends_on_json": '["verified"]'},
                    {"next_target": "NONE", "parent_result": {"fingerprint": "rl"}})
        self.assertFalse(created)
        create.assert_not_called()

    def test_recovery_retests_persisted_qwen_output_and_queues_verification(self) -> None:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as folder:
            root = Path(folder)
            database = root / "state.sqlite"
            conn = sqlite3.connect(database)
            conn.executescript("""
                CREATE TABLE tasks(
                  id TEXT PRIMARY KEY, agent TEXT, evidence_json TEXT, status TEXT,
                  updated_utc TEXT, verdict TEXT, next_action TEXT, result_json TEXT,
                  lease_owner TEXT, lease_until TEXT
                );
                CREATE TABLE research_runs(
                  task_id TEXT, sequence INTEGER, role TEXT, decision TEXT, error TEXT,
                  model TEXT, response_text TEXT, parsed_json TEXT
                );
                CREATE TABLE artifacts(
                  path TEXT PRIMARY KEY, sha256 TEXT, size_bytes INTEGER,
                  description TEXT, created_utc TEXT
                );
            """)
            evidence = {"mode": "followup", "required_suffix": "FEA", "depth": 1,
                        "exclude_suffixes": ["PDX"]}
            parsed = {"target_suffix": "FEA", "explanation": "Compare the FEA prefixes.",
                      "script": "common_prefix = 8"}
            conn.execute("INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?,?,?)", (
                "recover-me", "ollama-research-code", json.dumps(evidence), "BLOCKED",
                "2026-10-25T00:00:00Z", "BLOCKED", "", "{}", None, None))
            conn.execute("INSERT INTO research_runs VALUES(?,?,?,?,?,?,?,?)", (
                "recover-me", 1, "code", "SCRIPT_VERIFIED", None, "qwen2.5-coder:7b",
                json.dumps(parsed), json.dumps(parsed)))
            conn.commit()
            conn.close()
            records = [{"region": label, "bytes": 64, "sha256": label,
                        "prefix_hex": "00" * 64, "prefix_bytes": [0] * 64}
                       for label in ("SW", "Italy", "Scandinavia")]
            with mock.patch.object(coordinator_runtime, "STATE_DB", database), \
                 mock.patch.object(coordinator_runtime, "PROJECT_ROOT", root), \
                 mock.patch.object(coordinator_runtime, "_read_target", return_value=records), \
                 mock.patch.object(coordinator_runtime, "_common_prefix_length", return_value=8), \
                 mock.patch.object(coordinator_runtime, "run_research_script",
                                   return_value={"result": {"common_prefix": 8}, "stdout": "8\\n"}), \
                 mock.patch.object(coordinator_runtime, "_register_probe", return_value=(True, "abc123")) as register, \
                 mock.patch.object(coordinator_runtime, "_update_llm_validation"), \
                 mock.patch.object(coordinator_runtime, "_log_event"):
                recovered = coordinator_runtime._recover_verified_model_outputs()
            conn = sqlite3.connect(database)
            status, result_json = conn.execute(
                "SELECT status,result_json FROM tasks WHERE id='recover-me'").fetchone()
            artifact = conn.execute("SELECT sha256 FROM artifacts WHERE path LIKE '%model_generated_script.py'").fetchone()
            conn.close()
        self.assertEqual(recovered, 1)
        self.assertEqual(status, "DONE")
        self.assertEqual(json.loads(result_json)["verification_task"], "AUTO_VERIFY_abc123")
        self.assertEqual(json.loads(result_json)["hypothesis"], "Compare the FEA prefixes.")
        self.assertTrue(artifact[0])
        register.assert_called_once()

    def test_interrupted_review_recovery_discards_duplicate_target(self) -> None:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as folder:
            database = Path(folder) / "state.sqlite"
            conn = sqlite3.connect(database)
            conn.executescript("""
                CREATE TABLE tasks(
                  id TEXT PRIMARY KEY, agent TEXT, evidence_json TEXT, status TEXT,
                  updated_utc TEXT, verdict TEXT, next_action TEXT, result_json TEXT,
                  lease_owner TEXT, lease_until TEXT, depends_on_json TEXT, attempts INTEGER
                );
                CREATE TABLE research_runs(
                  task_id TEXT, sequence INTEGER, role TEXT, decision TEXT, error TEXT,
                  model TEXT, response_text TEXT, parsed_json TEXT
                );
                CREATE TABLE research_experiments(target_suffix TEXT);
            """)
            parent_result = {"target_suffix": "FEA", "fingerprint": "verified-fea",
                             "claim_status": "BYTE_COMPARISON_VERIFIED_SEMANTICS_UNKNOWN"}
            conn.execute("INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (
                "verified-fea-task", "binary-probe", "{}", "DONE", "2026-10-25T00:00:00Z",
                "PASS", "", json.dumps(parent_result), None, None, "[]", 1))
            evidence = {"mode": "review", "depth": 1}
            timeout_result = {"error": "TimeoutError: task timed out after persisted model response"}
            conn.execute("INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (
                "interrupted-review", "ollama-independent-review", json.dumps(evidence), "BLOCKED",
                "2026-10-25T00:00:01Z", "BLOCKED", "", json.dumps(timeout_result), None, None,
                json.dumps(["verified-fea-task"]), 0))
            parsed = {"assessment": "FEA verified", "next_target": "PDX",
                      "next_hypothesis": "repeat", "falsifier": "", "reason": "next"}
            conn.execute("INSERT INTO research_runs VALUES(?,?,?,?,?,?,?,?)", (
                "interrupted-review", 1, "independent-review", "RESPONSE_RECEIVED", None,
                "hf.co/empero-ai/Qwythos-9B-v2-GGUF:Q4_K_M", json.dumps(parsed), json.dumps(parsed)))
            conn.executemany("INSERT INTO research_experiments VALUES(?)", [("PDX",), ("FEA",)])
            conn.commit()
            conn.close()
            with mock.patch.object(coordinator_runtime, "STATE_DB", database), \
                 mock.patch.object(coordinator_runtime, "_write_json", return_value="review.json"), \
                 mock.patch.object(coordinator_runtime, "_update_llm_validation") as update, \
                 mock.patch.object(coordinator_runtime, "_after_success") as followup, \
                 mock.patch.object(coordinator_runtime, "_log_event"), \
                 mock.patch.object(coordinator_runtime.state_store, "_sync_task_db") as sync:
                recovered = coordinator_runtime._recover_persisted_reviews()
            conn = sqlite3.connect(database)
            status, verdict, result_json, next_action = conn.execute(
                "SELECT status,verdict,result_json,next_action FROM tasks WHERE id='interrupted-review'").fetchone()
            conn.close()
        result = json.loads(result_json)
        self.assertEqual(recovered, 1)
        self.assertEqual((status, verdict), ("DONE", "PASS"))
        self.assertEqual(result["next_target"], "NONE")
        self.assertEqual(result["review_validation"][0]["rejected_duplicate"], "PDX")
        self.assertIn("duplicate suffix rejected", next_action)
        update.assert_called_once()
        followup.assert_called_once()
        sync.assert_called_once_with("interrupted-review", "DONE", "PASS", 0)

    def test_sandbox_validation_update_preserves_model_cost_and_provenance(self) -> None:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as folder:
            database = Path(folder) / "state.sqlite"
            settings = Path(folder) / "model_text_settings.json"
            conn = sqlite3.connect(database)
            conn.execute("""CREATE TABLE research_runs(
                task_id TEXT,sequence INTEGER,role TEXT,model TEXT,input_json TEXT,response_text TEXT,
                parsed_json TEXT,artifact_paths_json TEXT,tests_json TEXT,decision TEXT,elapsed_ms INTEGER,
                resource_json TEXT,error TEXT,created_utc TEXT,UNIQUE(task_id,sequence))""")
            conn.close()
            with mock.patch.object(coordinator_runtime, "STATE_DB", database), \
                 mock.patch.object(coordinator_runtime, "MODEL_TEXT_SETTINGS", settings):
                coordinator_runtime._record_llm_run("job", 1, "code", "qwen2.5-coder:7b", "prompt",
                    '{"script":"pass"}', {"script": "pass"}, [], [], "RESPONSE_RECEIVED", 1234,
                    {"ram": {"before": 10}, "vram": {"peak": 20}})
                coordinator_runtime._update_llm_validation("job", 1, "code",
                    [{"name": "sandbox", "status": "PASS"}], "SCRIPT_VERIFIED")
            conn = sqlite3.connect(database)
            row = conn.execute("SELECT input_json,parsed_json,elapsed_ms,resource_json,tests_json,decision,error FROM research_runs").fetchone()
            conn.close()
        saved_input = json.loads(row[0])
        self.assertEqual(saved_input["prompt_sha256"], hashlib.sha256(b"prompt").hexdigest())
        self.assertFalse(saved_input["text_persisted"])
        self.assertEqual(json.loads(row[1]), {})
        self.assertEqual(row[2], 1234)
        self.assertEqual(json.loads(row[3])["vram"]["peak"], 20)
        self.assertEqual(json.loads(row[4])[0]["status"], "PASS")
        self.assertEqual((row[5], row[6]), ("SCRIPT_VERIFIED", None))

    def test_model_text_storage_requires_opt_in_and_redacts_secrets(self) -> None:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as folder:
            database = Path(folder) / "state.sqlite"
            settings = Path(folder) / "model_text_settings.json"
            conn = sqlite3.connect(database)
            conn.execute("""CREATE TABLE research_runs(
                task_id TEXT,sequence INTEGER,role TEXT,model TEXT,input_json TEXT,response_text TEXT,
                parsed_json TEXT,artifact_paths_json TEXT,tests_json TEXT,decision TEXT,elapsed_ms INTEGER,
                resource_json TEXT,error TEXT,created_utc TEXT,UNIQUE(task_id,sequence))""")
            conn.close()
            settings.write_text('{"store_model_text":true}', encoding="utf-8")
            with mock.patch.object(coordinator_runtime, "STATE_DB", database), \
                 mock.patch.object(coordinator_runtime, "MODEL_TEXT_SETTINGS", settings):
                coordinator_runtime._record_llm_run("job", 1, "review", "qwen3.5:4b",
                    'api_key="prompt-secret"', '{"answer":"ok","password":"response-secret"}',
                    {"answer": "ok", "api_key": "parsed-secret"}, [], [], "RESPONSE_RECEIVED", 22, {})
            conn = sqlite3.connect(database)
            row = conn.execute("SELECT input_json,response_text,parsed_json,resource_json FROM research_runs").fetchone()
            conn.close()
        self.assertTrue(json.loads(row[0])["text_persisted"])
        self.assertNotIn("prompt-secret", row[0])
        self.assertNotIn("response-secret", row[1])
        self.assertEqual(json.loads(row[2])["api_key"], "[REDACTED]")
        self.assertTrue(json.loads(row[3])["model_text_persisted"])

    def test_model_telemetry_reports_real_empty_schema_without_fabricating_runs(self) -> None:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as folder:
            database = Path(folder) / "state.sqlite"
            conn = sqlite3.connect(database)
            conn.execute("""CREATE TABLE research_runs(
                id INTEGER PRIMARY KEY,task_id TEXT,sequence INTEGER,role TEXT,model TEXT,input_json TEXT,
                response_text TEXT,parsed_json TEXT,artifact_paths_json TEXT,tests_json TEXT,decision TEXT,
                elapsed_ms INTEGER,resource_json TEXT,error TEXT,created_utc TEXT)""")
            conn.row_factory = sqlite3.Row
            telemetry = coordinator_runtime._model_telemetry(conn)
            conn.close()
        self.assertTrue(telemetry["available"])
        self.assertEqual(telemetry["source_table"], "research_runs")
        self.assertEqual(telemetry["recent_runs"], [])
        self.assertEqual(telemetry["periods"]["all"]["requests"], 0)
        self.assertIsNone(telemetry["periods"]["all"]["input_tokens"])

    def test_existing_windows_worker_delegates_adaptive_experiment_agents(self) -> None:
        from src.agent import coordinator_runtime as runtime
        task = {"id": "AUTO_UNIT_BINARY", "agent": "binary-probe", "budget": {"timeout_s": 30}}
        with mock.patch.object(autonomous_manager, "_task", return_value=task), \
             mock.patch.object(runtime, "_execute", return_value={"status": "verified"}) as execute, \
             mock.patch.object(runtime, "_after_success") as followup:
            result = autonomous_manager.execute_task(task["id"])
        self.assertEqual(result, {"status": "verified"})
        execute.assert_called_once_with(task)
        followup.assert_called_once_with(task, result)


if __name__ == "__main__":
    unittest.main()
