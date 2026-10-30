from __future__ import annotations

import json
import sqlite3
import unittest

from src.agent import project_scope


class ProjectScopeTests(unittest.TestCase):
    def test_startup_migration_archives_excluded_tasks_and_persists_disc_first_scope(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript("""
            CREATE TABLE tasks(
                id TEXT PRIMARY KEY, stage TEXT, status TEXT, verdict TEXT, budget_json TEXT,
                result_json TEXT, lease_owner TEXT, lease_until TEXT, updated_utc TEXT,
                depends_on_json TEXT, next_action TEXT);
            CREATE TABLE leases(task_id TEXT PRIMARY KEY);
            CREATE TABLE stage_gates(stage TEXT PRIMARY KEY,status TEXT,criteria_json TEXT,
                proof_json TEXT,updated_utc TEXT);
            CREATE TABLE autonomy_events(id INTEGER PRIMARY KEY,created_utc TEXT,event TEXT,
                severity TEXT,detail_json TEXT);
            INSERT INTO tasks VALUES
                ('AUTO_TRACK_VIRTUAL_CID','F5','PENDING','PENDING','{"focus":"virtual_cid"}','{}','worker','soon','old','[]','run'),
                ('AUTO_BRANCH_POI_EDITOR','F6','BLOCKED','BLOCKED','{"focus":"poi_editor"}','{"error":"old"}','worker','soon','old','[]','run'),
                ('AUTO_NCDX_PROFILE','F2','PENDING','PENDING','{"focus":"binary_analysis"}','{}',NULL,NULL,'old','[]','run');
            INSERT INTO leases VALUES('AUTO_TRACK_VIRTUAL_CID');
            INSERT INTO stage_gates VALUES
                ('F2','IN_PROGRESS','{"header_reader":3,"semantic_records":6}','{}','old'),
                ('F4','BLOCKED','{"dated_osm_source":2,"road_graph_tests":3}','{}','old'),
                ('F6','PENDING','{"poi_editor_tests":7}','{}','old'),
                ('F7','PENDING','{"simulator":2,"final_image_interpreter":5}','{"criteria_pass":{"simulator":true}}','old');
        """)
        project_scope.sync_scope_in_connection(conn)

        rows = {row["id"]: dict(row) for row in conn.execute("SELECT * FROM tasks")}
        self.assertEqual(rows["AUTO_TRACK_VIRTUAL_CID"]["status"], "CANCELLED")
        self.assertEqual(rows["AUTO_BRANCH_POI_EDITOR"]["status"], "CANCELLED")
        self.assertEqual(rows["AUTO_NCDX_PROFILE"]["status"], "PENDING")
        self.assertEqual(json.loads(rows["AUTO_TRACK_VIRTUAL_CID"]["result_json"])["scope_migration"]["status"],
                         "CANCELLED_OUT_OF_SCOPE")
        self.assertFalse(conn.execute("SELECT 1 FROM leases WHERE task_id='AUTO_TRACK_VIRTUAL_CID'").fetchone())

        gates = {row["stage"]: dict(row) for row in conn.execute("SELECT * FROM stage_gates")}
        self.assertEqual(gates["F6"]["status"], "OUT_OF_SCOPE")
        self.assertEqual(json.loads(gates["F6"]["criteria_json"]), {})
        self.assertEqual(gates["F7"]["status"], "PENDING")
        self.assertEqual(json.loads(gates["F7"]["criteria_json"]), {"final_image_interpreter": 5})
        self.assertEqual(json.loads(gates["F2"]["criteria_json"])["firmware_hex_structures"], 2)
        self.assertEqual(json.loads(gates["F4"]["criteria_json"])["whole_ukraine_osm_database"], 5)
        scope_row = conn.execute("SELECT value_json FROM project_configuration WHERE setting_key='active_scope'").fetchone()
        scope = json.loads(scope_row[0])
        self.assertIn("NCDX_REVERSE_ENGINEERING", [item["id"] for item in scope["active_tracks"]])
        self.assertEqual(scope["readiness_policy"]["physical_compatibility"], "NOT_TESTED")
        self.assertTrue(scope["director_policy"]["schedule_only_active_tracks"])
        self.assertTrue(scope["director_policy"]["never_reactivate_excluded_tracks_from_history"])
        self.assertTrue(scope["reporting_policy"]["exclude_archived_tracks_from_readiness_and_active_reports"])

        project_scope.sync_scope_in_connection(conn)
        self.assertEqual(conn.execute("SELECT status FROM tasks WHERE id='AUTO_NCDX_PROFILE'").fetchone()[0], "PENDING")
        conn.close()

    def test_exclusion_does_not_match_disk_data_poi_processing(self) -> None:
        self.assertTrue(project_scope.task_is_excluded("AUTO_BRANCH_POI_EDITOR"))
        self.assertTrue(project_scope.task_is_excluded("AUTO_VIRTUAL_CID_GUI_ACCEPTANCE"))
        self.assertFalse(project_scope.task_is_excluded(
            "AUTO_OSM_POI_TAG_NORMALIZATION", {"focus": "osm", "purpose": "disk data preparation"}))


if __name__ == "__main__":
    unittest.main()
