"""Persistent active project scope shared by the Director, scheduler and GUI."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCOPE_PATH = PROJECT_ROOT / "config" / "project_scope.json"


def load_scope() -> dict[str, Any]:
    value = json.loads(SCOPE_PATH.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise RuntimeError("active project scope configuration is missing or has an unsupported schema")
    if not isinstance(value.get("global_goal"), str) or not value["global_goal"].strip():
        raise RuntimeError("active project scope must define a non-empty global goal")
    if not isinstance(value.get("active_tracks"), list) or not value["active_tracks"]:
        raise RuntimeError("active project scope must define at least one active track")
    return value


def global_goal() -> str:
    return str(load_scope()["global_goal"])


def active_track_ids() -> tuple[str, ...]:
    return tuple(str(row["id"]) for row in load_scope()["active_tracks"])


def excluded_track_ids() -> tuple[str, ...]:
    return tuple(str(row["id"]) for row in load_scope()["excluded_tracks"])


def task_is_excluded(task: dict[str, Any] | str, budget_json: str | dict[str, Any] | None = None) -> bool:
    """Recognize only the retired Virtual CID and standalone personal-POI work."""
    if isinstance(task, dict):
        task_id = str(task.get("id", ""))
        budget: Any = task.get("budget", task.get("budget_json", budget_json))
    else:
        task_id = str(task)
        budget = budget_json
    if isinstance(budget, str):
        try:
            budget = json.loads(budget)
        except json.JSONDecodeError:
            budget = {}
    text = (task_id + " " + json.dumps(budget or {}, ensure_ascii=False, sort_keys=True)).casefold()
    markers = ("virtual_cid", "virtual cid", "poi_editor", "poi editor", "personal_poi_editor",
               "kryvyi_rih_poi_editor", "virtual_personal_poi")
    return any(marker in text for marker in markers)


def sync_scope_in_connection(conn: sqlite3.Connection) -> None:
    """Persist the active scope and exclude retired product gates on every startup."""
    conn.row_factory = sqlite3.Row
    scope = load_scope()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute("""CREATE TABLE IF NOT EXISTS project_configuration(
        setting_key TEXT PRIMARY KEY, value_json TEXT NOT NULL, updated_utc TEXT NOT NULL)""")
    scope_json = json.dumps(scope, ensure_ascii=False, sort_keys=True)
    prior_scope = conn.execute("SELECT value_json FROM project_configuration WHERE setting_key='active_scope'").fetchone()
    if not prior_scope or prior_scope[0] != scope_json:
        conn.execute("INSERT OR REPLACE INTO project_configuration(setting_key,value_json,updated_utc) VALUES(?,?,?)",
                     ("active_scope", scope_json, now))
    tables = {str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "tasks" in tables:
        cancelled: list[str] = []
        terminal = {"DONE", "FAILED", "CANCELLED"}
        task_columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(tasks)")}
        selected = [name for name in ("id", "status", "budget_json", "result_json") if name in task_columns]
        for row in list(conn.execute("SELECT " + ",".join(selected) + " FROM tasks")):
            if str(row["status"]).upper() in terminal or not task_is_excluded(str(row["id"]), row["budget_json"] if "budget_json" in task_columns else "{}"):
                continue
            values: list[Any] = []
            assignments = ["status='CANCELLED'"]
            if "verdict" in task_columns:
                assignments.append("verdict='OUT_OF_SCOPE'")
            if "result_json" in task_columns:
                try:
                    result = json.loads(row["result_json"] or "{}")
                except (TypeError, json.JSONDecodeError):
                    result = {}
                result["scope_migration"] = {"revision": scope["scope_revision"],
                    "status": "CANCELLED_OUT_OF_SCOPE", "archive": scope["excluded_tracks"][0].get("archive"),
                    "previous_status": row["status"]}
                assignments.append("result_json=?")
                values.append(json.dumps(result, ensure_ascii=False))
            for column in ("lease_owner", "lease_until", "heartbeat_utc"):
                if column in task_columns:
                    assignments.append(f"{column}=NULL")
            if "updated_utc" in task_columns:
                assignments.append("updated_utc=?")
                values.append(now)
            values.append(row["id"])
            conn.execute("UPDATE tasks SET " + ",".join(assignments) + " WHERE id=?", values)
            if "leases" in tables:
                conn.execute("DELETE FROM leases WHERE task_id=?", (row["id"],))
            cancelled.append(str(row["id"]))
        if cancelled and "autonomy_events" in tables:
            conn.execute("INSERT INTO autonomy_events(created_utc,event,severity,detail_json) VALUES(?,?,?,?)",
                         (now, "excluded_scope_tasks_cancelled", "INFO",
                          json.dumps({"scope_revision": scope["scope_revision"], "task_ids": cancelled,
                                      "archive": scope["excluded_tracks"][0].get("archive")}, ensure_ascii=False)))
    if "stage_gates" not in tables:
        return
    archive_path = str(scope["excluded_tracks"][0].get("archive", "archive/excluded_tracks"))
    for stage, status, criteria in (
        ("F6", "OUT_OF_SCOPE", {}),
        ("F7", "PENDING", {"final_image_interpreter": 5}),
    ):
        row = conn.execute("SELECT status,criteria_json,proof_json FROM stage_gates WHERE stage=?", (stage,)).fetchone()
        if not row:
            continue
        old = {"stage": stage, "status": row[0], "criteria_json": row[1], "proof_json": row[2]}
        archive_key = f"archived_gate_{stage}_{scope['scope_revision']}"
        conn.execute("INSERT OR IGNORE INTO project_configuration(setting_key,value_json,updated_utc) VALUES(?,?,?)",
                     (archive_key, json.dumps(old, ensure_ascii=False), now))
        if stage == "F6":
            proof = {"scope": "OUT_OF_SCOPE", "archive": archive_path,
                     "note": "Historical POI Editor work is preserved and excluded from active readiness."}
        else:
            try:
                prior_proof = json.loads(row[2] or "{}")
            except (TypeError, json.JSONDecodeError):
                prior_proof = {}
            criteria_pass = prior_proof.get("criteria_pass", {}) if isinstance(prior_proof, dict) else {}
            final_image_verified = criteria_pass.get("final_image_interpreter") is True
            status = "COMPLETE" if final_image_verified else "PENDING"
            proof = {"criteria_pass": {"final_image_interpreter": criteria_pass.get("final_image_interpreter") is True},
                     "scope_note": "Virtual CID simulator criterion removed; only physical-disc image interpretation remains active."}
        criteria_json = json.dumps(criteria)
        proof_json = json.dumps(proof, ensure_ascii=False)
        if row[0] == status and row[1] == criteria_json and row[2] == proof_json:
            continue
        conn.execute("UPDATE stage_gates SET status=?,criteria_json=?,proof_json=?,updated_utc=? WHERE stage=?",
                     (status, criteria_json, proof_json, now, stage))

    # Keep the active firmware-format criterion on databases created before
    # the reader was added. It earns points only after the Supervisor writes
    # independently verified evidence into criteria_pass.
    f2 = conn.execute("SELECT criteria_json FROM stage_gates WHERE stage='F2'").fetchone()
    if f2:
        try:
            f2_criteria = json.loads(f2[0] or "{}")
        except (TypeError, json.JSONDecodeError):
            f2_criteria = {}
        if "firmware_hex_structures" not in f2_criteria:
            f2_criteria["firmware_hex_structures"] = 2
            conn.execute("UPDATE stage_gates SET criteria_json=?,updated_utc=? WHERE stage='F2'",
                         (json.dumps(f2_criteria), now))

    # Award national OSM readiness only from a deterministic readback proof
    # written after the independent Supervisor accepts the produced database.
    f4 = conn.execute("SELECT criteria_json FROM stage_gates WHERE stage='F4'").fetchone()
    if f4:
        try:
            f4_criteria = json.loads(f4[0] or "{}")
        except (TypeError, json.JSONDecodeError):
            f4_criteria = {}
        if "whole_ukraine_osm_database" not in f4_criteria:
            f4_criteria["whole_ukraine_osm_database"] = 5
            conn.execute("UPDATE stage_gates SET criteria_json=?,updated_utc=? WHERE stage='F4'",
                         (json.dumps(f4_criteria), now))

