"""Persistent, bounded task and evidence store for the NCDR workbench."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
import os
from typing import Any
import uuid

from src.agent import project_scope


PROJECT_ROOT = Path(__file__).resolve().parents[2]
STATE_DB = PROJECT_ROOT / "project_state.sqlite"
TASK_DB = PROJECT_ROOT / "TASK_BACKLOG.sqlite"
EVIDENCE_DB = PROJECT_ROOT / "EVIDENCE_LEDGER.sqlite"
EVENT_LOG = PROJECT_ROOT / "logs" / "events.jsonl"


@contextmanager
def _connection(path: Path, timeout: int = 5):
    """Commit or roll back a transaction and always close its SQLite handle."""
    conn = sqlite3.connect(path, timeout=timeout)
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _schema(conn: sqlite3.Connection, kind: str) -> None:
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    if kind == "state":
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS tasks(
              id TEXT PRIMARY KEY, stage TEXT NOT NULL, depends_on_json TEXT NOT NULL,
              hypothesis TEXT NOT NULL, evidence_json TEXT NOT NULL, agent TEXT NOT NULL,
              budget_json TEXT NOT NULL, deliverables_json TEXT NOT NULL,
              objective_tests_json TEXT NOT NULL, verdict TEXT NOT NULL DEFAULT 'PENDING',
              next_action TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'PENDING',
              attempts INTEGER NOT NULL DEFAULT 0, retry_limit INTEGER NOT NULL DEFAULT 1,
              priority INTEGER NOT NULL DEFAULT 100, lease_owner TEXT, lease_until TEXT,
              heartbeat_utc TEXT, result_json TEXT NOT NULL DEFAULT '{}',
              created_utc TEXT NOT NULL, updated_utc TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS artifacts(
              path TEXT PRIMARY KEY, sha256 TEXT, size_bytes INTEGER, description TEXT NOT NULL,
              created_utc TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS evidence(
              id INTEGER PRIMARY KEY AUTOINCREMENT, source_path TEXT NOT NULL, sha256 TEXT NOT NULL,
              size_bytes INTEGER NOT NULL, source_mtime_utc TEXT, classification TEXT,
              claim TEXT NOT NULL DEFAULT '', file_offset TEXT, raw_hex TEXT,
              test_name TEXT, verdict TEXT NOT NULL DEFAULT 'INVENTORIED',
              provenance_json TEXT NOT NULL DEFAULT '{}'
            );
            CREATE INDEX IF NOT EXISTS idx_evidence_sha ON evidence(sha256);
            CREATE TABLE IF NOT EXISTS model_runs(
              id INTEGER PRIMARY KEY AUTOINCREMENT, model TEXT NOT NULL, task_id TEXT,
              status TEXT NOT NULL, wall_ms INTEGER, prompt_tokens INTEGER, output_tokens INTEGER,
              tokens_per_second REAL, ram_before_bytes INTEGER, ram_peak_bytes INTEGER,
              vram_before_mib INTEGER, vram_peak_mib INTEGER, useful_artifacts INTEGER NOT NULL DEFAULT 0,
              result_json TEXT NOT NULL DEFAULT '{}', started_utc TEXT NOT NULL, finished_utc TEXT
            );
            CREATE TABLE IF NOT EXISTS blocked_reasons(
              id INTEGER PRIMARY KEY AUTOINCREMENT, stage TEXT NOT NULL, reason TEXT NOT NULL,
              evidence_json TEXT NOT NULL, required_action TEXT NOT NULL,
              status TEXT NOT NULL DEFAULT 'OPEN', created_utc TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS stage_gates(
              stage TEXT PRIMARY KEY, status TEXT NOT NULL, criteria_json TEXT NOT NULL,
              proof_json TEXT NOT NULL DEFAULT '{}', updated_utc TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS leases(
              task_id TEXT PRIMARY KEY REFERENCES tasks(id), owner TEXT NOT NULL,
              lease_id TEXT NOT NULL UNIQUE, lease_until TEXT NOT NULL, heartbeat_utc TEXT NOT NULL
            );
            """
        )
    elif kind == "tasks":
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS tasks(
              id TEXT PRIMARY KEY, stage TEXT NOT NULL, depends_on_json TEXT NOT NULL,
              hypothesis TEXT NOT NULL, input_evidence_json TEXT NOT NULL, agent TEXT NOT NULL,
              budget_json TEXT NOT NULL, deliverables_json TEXT NOT NULL,
              objective_tests_json TEXT NOT NULL, verdict TEXT NOT NULL DEFAULT 'PENDING',
              next_action TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'PENDING',
              attempts INTEGER NOT NULL DEFAULT 0, retry_limit INTEGER NOT NULL DEFAULT 1,
              updated_utc TEXT NOT NULL
            );
            """
        )
    elif kind == "evidence":
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS artifacts(
              source_path TEXT PRIMARY KEY, sha256 TEXT NOT NULL, size_bytes INTEGER NOT NULL,
              source_mtime_utc TEXT, extension TEXT, signature_first_16 TEXT,
              classification TEXT NOT NULL, source_group TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_artifacts_sha ON artifacts(sha256);
            CREATE TABLE IF NOT EXISTS claims(
              id TEXT PRIMARY KEY, claim TEXT NOT NULL, verdict TEXT NOT NULL,
              source_paths_json TEXT NOT NULL, source_sha256_json TEXT NOT NULL,
              file_offsets_json TEXT NOT NULL, test_name TEXT NOT NULL,
              conclusion TEXT NOT NULL, observed_utc TEXT NOT NULL
            );
            """
        )


def _seed_tasks() -> list[dict[str, Any]]:
    return [
        {"id": "F0_SOURCE_INVENTORY", "stage": "F0", "status": "DONE", "verdict": "PASS", "priority": 10,
         "depends_on": [], "hypothesis": "The current NCDR source root contains the discoverable local project and media trees.",
         "evidence": ["inventory/discs_manifest.json"], "agent": "deterministic", "budget": {"attempts": 1, "timeout_s": 120},
         "deliverables": ["inventory/discs_manifest.json", "inventory/discs_manifest.csv"],
         "tests": ["All discovered files have exact relative paths and non-empty SHA-256 values."],
         "next_action": "Compare regional map files and prior research."},
        {"id": "F0_HASH_BASELINE", "stage": "F0", "status": "DONE", "verdict": "PASS", "priority": 11,
         "depends_on": ["F0_SOURCE_INVENTORY"], "hypothesis": "All 5,600 files in the located source tree can be hashed without write access.",
         "evidence": ["inventory/hash_verification.json"], "agent": "deterministic", "budget": {"attempts": 1, "timeout_s": 300},
         "deliverables": ["inventory/hash_verification.json"], "tests": ["files_hashed equals files_expected and errors is empty."],
         "next_action": "Keep source references read-only and proceed to file analysis."},
        {"id": "F0_OLLAMA_SMOKE", "stage": "F0", "status": "DONE", "verdict": "PASS", "priority": 12,
         "depends_on": ["F0_SOURCE_INVENTORY"], "hypothesis": "An installed local model can return a bounded JSON response through Ollama.",
         "evidence": ["qwen3.5:4b API smoke response"], "agent": "ollama:qwen3.5:4b", "budget": {"attempts": 1, "timeout_s": 120, "context": 4096},
         "deliverables": ["reports/model_smoke.json"], "tests": ["API tags succeeded and smoke response parsed as JSON."],
         "next_action": "Run the 15-case serial benchmark across installed local models."},
        {"id": "F0_RUNNER_ENTRYPOINT", "stage": "F0", "status": "PENDING", "verdict": "PENDING", "priority": 13,
         "depends_on": ["F0_SOURCE_INVENTORY"], "hypothesis": "A local launcher can make the transferred ncdqwen package importable from any working directory.",
         "evidence": ["NCDR_QWEN_TRANSFER/ncdqwen/runner.py", "alternate-cwd import failure"], "agent": "deterministic", "budget": {"attempts": 1, "timeout_s": 30},
         "deliverables": ["src/agent/run_ncdqwen.ps1", "tests/integration/test_entrypoint.ps1"],
         "tests": ["--help succeeds from an unrelated working directory; runner source remains unchanged."],
         "next_action": "Create and test the wrapper against a working copy."},
        {"id": "F0_MODEL_BENCHMARK", "stage": "F0", "status": "PENDING", "verdict": "PENDING", "priority": 20,
         "depends_on": ["F0_OLLAMA_SMOKE"], "hypothesis": "A serial benchmark identifies the highest verified NCDR task yield per minute under the 8 GB VRAM budget.",
         "evidence": ["three installed GGUF manifests", "GPU inventory"], "agent": "ollama-worker", "budget": {"attempts": 1, "timeout_s": 1800, "models_serial": True, "num_ctx": 4096},
         "deliverables": ["src/agent/benchmark_tasks.json", "reports/model_benchmark.json"],
         "tests": ["At least 15 NCDR tasks per model, valid JSON, automatic scoring, resource sample, one model resident at a time."],
         "next_action": "Run all installed candidates serially and unload each model."},
        {"id": "F1_TARGET_COMPATIBILITY", "stage": "F1", "status": "BLOCKED", "verdict": "BLOCKED", "priority": 30,
         "depends_on": ["F0_SOURCE_INVENTORY"], "hypothesis": "CD_7185, CD_7186 or CD_7190 may be compatible with a specific NCDR unit.",
         "evidence": ["three CDROM.TOC files", "legacy 9-disc report"], "agent": "Codex-review", "budget": {"attempts": 1, "timeout_s": 0},
         "deliverables": ["reports/COMPATIBILITY_MATRIX.md"], "tests": ["Exact head-unit model and physical acceptance evidence required."],
         "next_action": "Obtain the NCDR faceplate/model label and test only on matching hardware."},
        {"id": "F2_MP0_HEADER_READER", "stage": "F2", "status": "PENDING", "verdict": "PENDING", "priority": 21,
         "depends_on": ["F0_SOURCE_INVENTORY"], "hypothesis": "The regional *Z.MP0 files share a stable, bounded header containing a Siemens marker and a dataset code.",
         "evidence": ["EUZ.MP0", "IZ.MP0", "SCZ.MP0"], "agent": "deterministic", "budget": {"attempts": 1, "timeout_s": 120},
         "deliverables": ["src/readers/ncdx_mp0_header.py", "tests/unit/test_ncdx_mp0_header.py"],
         "tests": ["Header parser and SHA check pass on all three independent disc trees."],
         "next_action": "Run the read-only golden tests, then byte-preserving roundtrip on a working copy."},
        {"id": "F2_REGIONAL_DIFF", "stage": "F2", "status": "PENDING", "verdict": "PENDING", "priority": 22,
         "depends_on": ["F0_SOURCE_INVENTORY"], "hypothesis": "Italia and Scandinavia use matching NCDx file families with region-specific payloads.",
         "evidence": ["CD_7185 file tree", "CD_7186 file tree"], "agent": "deterministic", "budget": {"attempts": 1, "timeout_s": 300},
         "deliverables": ["inventory/region_cross_diff.json", "inventory/format_matrix.md"],
         "tests": ["Compare normalized relative names, sizes, hashes and TOC metadata."],
         "next_action": "Record shared and differing paths with hashes; preserve semantics as unknown."},
        {"id": "F3_WRITER", "stage": "F3", "status": "BLOCKED", "verdict": "BLOCKED", "priority": 40,
         "depends_on": ["F1_TARGET_COMPATIBILITY", "F2_MP0_HEADER_READER"], "hypothesis": "A safe writer is possible only after the actual target format and relevant field structures are proven.",
         "evidence": ["unknown records beyond the fixed MP0 header", "no hardware target"], "agent": "deterministic", "budget": {"attempts": 0, "timeout_s": 0},
         "deliverables": ["src/writers/"], "tests": ["No-op byte roundtrip plus one parsed field modification and independent readback."],
         "next_action": "Resume after F1 passes and the affected MP0 record format is decoded."},
        {"id": "F4_OSM_PIPELINE", "stage": "F4", "status": "BLOCKED", "verdict": "BLOCKED", "priority": 50,
         "depends_on": ["F1_TARGET_COMPATIBILITY", "F3_WRITER"], "hypothesis": "Modern Ukraine OSM data can be transformed only after the target database and writer are known.",
         "evidence": ["no selected writer target"], "agent": "Codex-review", "budget": {"attempts": 0, "timeout_s": 0},
         "deliverables": ["src/osm/"], "tests": ["A small regional fixture roundtrips through the validated target writer."],
         "next_action": "Resume after a proven writer target exists."},
    ]


def _event(event: str, payload: dict[str, Any]) -> None:
    EVENT_LOG.parent.mkdir(parents=True, exist_ok=True)
    with EVENT_LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"utc": utcnow(), "event": event, **payload}, ensure_ascii=False) + "\n")


def _sync_task_db(task_id: str, status: str, verdict: str, attempts: int) -> None:
    if not TASK_DB.exists():
        return
    with _connection(TASK_DB) as conn:
        project_scope.sync_scope_in_connection(conn)
        conn.execute(
            "UPDATE tasks SET status=?,verdict=?,attempts=?,updated_utc=? WHERE id=?",
            (status, verdict, attempts, utcnow(), task_id),
        )


def initialize(project_root: Path = PROJECT_ROOT) -> dict[str, Any]:
    project_root = project_root.resolve()
    for path in (STATE_DB, TASK_DB, EVIDENCE_DB):
        path.parent.mkdir(parents=True, exist_ok=True)
    with _connection(STATE_DB) as state:
        state.row_factory = sqlite3.Row
        _schema(state, "state")
        now = utcnow()
        for item in _seed_tasks():
            state.execute(
                """INSERT OR IGNORE INTO tasks
                (id,stage,depends_on_json,hypothesis,evidence_json,agent,budget_json,deliverables_json,
                 objective_tests_json,verdict,next_action,status,retry_limit,priority,created_utc,updated_utc)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (item["id"], item["stage"], json.dumps(item["depends_on"]), item["hypothesis"],
                 json.dumps(item["evidence"], ensure_ascii=False), item["agent"], json.dumps(item["budget"]),
                 json.dumps(item["deliverables"], ensure_ascii=False), json.dumps(item["tests"], ensure_ascii=False),
                 item["verdict"], item["next_action"], item["status"], item["budget"].get("attempts", 1),
                 item["priority"], now, now),
            )
        gates = {
            "F0": ("IN_PROGRESS", {"hash_manifest": 2, "previous_results_review": 2, "local_model_check": 2, "portable_entrypoint": 2, "runnable_healthcheck": 2}),
            "F1": ("BLOCKED", {"target_device_identity": 4, "disc_acceptance_evidence": 4, "format_matrix": 2, "image_layout_evidence": 2}),
            "F2": ("IN_PROGRESS", {"header_reader": 3, "independent_disc_golden_tests": 3, "unknowns_documented": 2, "corruption_detection": 2, "semantic_records": 6, "firmware_hex_structures": 2}),
            "F3": ("BLOCKED", {"no_op_roundtrip": 3, "controlled_change": 4, "independent_readback": 5}),
            "F4": ("BLOCKED", {"dated_osm_source": 2, "road_graph_tests": 4, "target_conversion": 6}),
            "F5": ("BLOCKED", {"encoding_support_proof": 3, "ukrainian_names_test": 2}),
            "F6": ("OUT_OF_SCOPE", {}),
            "F7": ("PENDING", {"final_image_interpreter": 5}),
            "F8": ("BLOCKED", {"target_disc_layout": 3, "independent_image_verifier": 3}),
            "F9": ("BLOCKED", {"software_acceptance": 8, "hardware_acceptance": 5}),
        }
        for stage, (status, criteria) in gates.items():
            state.execute(
                "INSERT OR IGNORE INTO stage_gates(stage,status,criteria_json,proof_json,updated_utc) VALUES(?,?,?,?,?)",
                (stage, status, json.dumps(criteria), "{}", now),
            )
        project_scope.sync_scope_in_connection(state)
        manifest = project_root / "inventory" / "discs_manifest.json"
        evidence_rows = json.loads(manifest.read_text(encoding="utf-8-sig")) if manifest.exists() else []
        state.execute("DELETE FROM evidence WHERE claim=''")
        for row in evidence_rows:
            state.execute(
                """INSERT INTO evidence(source_path,sha256,size_bytes,source_mtime_utc,classification,claim,verdict,provenance_json)
                VALUES(?,?,?,?,?,'','INVENTORIED',?)""",
                (row["relative_path"], row["sha256"], row["length_bytes"], row["last_write_utc"], row["classification"],
                 json.dumps({"source_root": str(project_root / "corpus" / "original_readonly"),
                             "original_root": os.environ.get("NCDR_SOURCE_ROOT", str(project_root))})),
            )
        state.commit()
        integrity = state.execute("PRAGMA integrity_check").fetchone()[0]

    with _connection(TASK_DB) as task_conn:
        task_conn.row_factory = sqlite3.Row
        _schema(task_conn, "tasks")
        for item in _seed_tasks():
            task_conn.execute(
                """INSERT OR IGNORE INTO tasks
                (id,stage,depends_on_json,hypothesis,input_evidence_json,agent,budget_json,deliverables_json,
                 objective_tests_json,verdict,next_action,status,retry_limit,updated_utc)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (item["id"], item["stage"], json.dumps(item["depends_on"]), item["hypothesis"],
                 json.dumps(item["evidence"], ensure_ascii=False), item["agent"], json.dumps(item["budget"]),
                 json.dumps(item["deliverables"], ensure_ascii=False), json.dumps(item["tests"], ensure_ascii=False),
                 item["verdict"], item["next_action"], item["status"], item["budget"].get("attempts", 1), utcnow()),
            )
        project_scope.sync_scope_in_connection(task_conn)
        task_conn.commit()

    with _connection(EVIDENCE_DB) as evidence_conn:
        evidence_conn.row_factory = sqlite3.Row
        _schema(evidence_conn, "evidence")
        for row in evidence_rows:
            source_group = row["relative_path"].split("\\", 1)[0]
            evidence_conn.execute(
                """INSERT OR REPLACE INTO artifacts
                (source_path,sha256,size_bytes,source_mtime_utc,extension,signature_first_16,classification,source_group)
                VALUES(?,?,?,?,?,?,?,?)""",
                (row["relative_path"], row["sha256"], row["length_bytes"], row["last_write_utc"],
                 row.get("extension", ""), row.get("signature_first_16", ""), row["classification"], source_group),
            )
        evidence_conn.commit()

    _event("state_initialized", {"evidence_files": len(evidence_rows), "sqlite_integrity": integrity})
    return {"evidence_files": len(evidence_rows), "sqlite_integrity": integrity, "databases": [str(STATE_DB), str(TASK_DB), str(EVIDENCE_DB)]}


def add_task(task: dict[str, Any], db_path: Path = STATE_DB) -> bool:
    if db_path.resolve() == STATE_DB.resolve() and project_scope.task_is_excluded(task):
        _event("task_rejected_out_of_scope", {"task_id": str(task.get("id", "")),
            "scope_revision": project_scope.load_scope()["scope_revision"]})
        return False
    with _connection(db_path) as conn:
        _schema(conn, "state")
        now = utcnow()
        cursor = conn.execute(
            """INSERT OR IGNORE INTO tasks
            (id,stage,depends_on_json,hypothesis,evidence_json,agent,budget_json,deliverables_json,
             objective_tests_json,verdict,next_action,status,retry_limit,priority,created_utc,updated_utc)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (task["id"], task["stage"], json.dumps(task.get("depends_on", [])), task["hypothesis"],
             json.dumps(task.get("evidence", []), ensure_ascii=False), task.get("agent", "deterministic"),
             json.dumps(task.get("budget", {})), json.dumps(task.get("deliverables", []), ensure_ascii=False),
             json.dumps(task.get("tests", []), ensure_ascii=False), task.get("verdict", "PENDING"),
             task.get("next_action", ""), task.get("status", "PENDING"), task.get("retry_limit", 1),
             task.get("priority", 100), now, now),
        )
        added = cursor.rowcount == 1
    if added and db_path.resolve() == STATE_DB.resolve() and TASK_DB.exists():
        with _connection(TASK_DB) as task_conn:
            _schema(task_conn, "tasks")
            task_conn.execute(
                """INSERT OR IGNORE INTO tasks
                (id,stage,depends_on_json,hypothesis,input_evidence_json,agent,budget_json,deliverables_json,
                 objective_tests_json,verdict,next_action,status,retry_limit,updated_utc)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (task["id"], task["stage"], json.dumps(task.get("depends_on", [])), task["hypothesis"],
                 json.dumps(task.get("evidence", []), ensure_ascii=False), task.get("agent", "deterministic"),
                 json.dumps(task.get("budget", {})), json.dumps(task.get("deliverables", []), ensure_ascii=False),
                 json.dumps(task.get("tests", []), ensure_ascii=False), task.get("verdict", "PENDING"),
                 task.get("next_action", ""), task.get("status", "PENDING"), task.get("retry_limit", 1), utcnow()),
            )
    return added


def claim_next(owner: str, lease_seconds: int = 300, db_path: Path = STATE_DB) -> dict[str, Any] | None:
    now = datetime.now(timezone.utc)
    now_text = now.isoformat()
    with _connection(db_path, timeout=30) as conn:
        conn.row_factory = sqlite3.Row
        _schema(conn, "state")
        # Schema setup contains PRAGMAs and executescript migrations.  Make
        # that initialization boundary explicit before taking the write lock;
        # otherwise an inherited transaction can make BEGIN IMMEDIATE fail
        # and terminate the long-running worker before it claims any task.
        conn.commit()
        conn.execute("BEGIN IMMEDIATE")
        if db_path.resolve() == STATE_DB.resolve():
            project_scope.sync_scope_in_connection(conn)
        expired = conn.execute("SELECT id FROM tasks WHERE status='LEASED' AND lease_until < ?", (now_text,)).fetchall()
        for row in expired:
            conn.execute("UPDATE tasks SET status='PENDING',lease_owner=NULL,lease_until=NULL,updated_utc=? WHERE id=?", (now_text, row["id"]))
            conn.execute("DELETE FROM leases WHERE task_id=?", (row["id"],))
        tasks = conn.execute("SELECT * FROM tasks WHERE status='PENDING' ORDER BY priority,created_utc").fetchall()
        for task in tasks:
            if project_scope.task_is_excluded(task["id"], task["budget_json"]):
                continue
            deps = json.loads(task["depends_on_json"])
            if any((conn.execute("SELECT status FROM tasks WHERE id=?", (dep,)).fetchone() or [None])[0] != "DONE" for dep in deps):
                continue
            lease_id = str(uuid.uuid4())
            until = (now + timedelta(seconds=lease_seconds)).isoformat()
            conn.execute("UPDATE tasks SET status='LEASED',attempts=attempts+1,lease_owner=?,lease_until=?,heartbeat_utc=?,updated_utc=? WHERE id=?",
                         (owner, until, now_text, now_text, task["id"]))
            conn.execute("INSERT OR REPLACE INTO leases(task_id,owner,lease_id,lease_until,heartbeat_utc) VALUES(?,?,?,?,?)",
                         (task["id"], owner, lease_id, until, now_text))
            conn.commit()
            result = dict(task)
            result.update({"status": "LEASED", "attempts": task["attempts"] + 1, "lease_owner": owner, "lease_id": lease_id, "lease_until": until})
            if db_path.resolve() == STATE_DB.resolve():
                _sync_task_db(task["id"], "LEASED", task["verdict"], task["attempts"] + 1)
            _event("task_claimed", {"task_id": task["id"], "owner": owner, "lease_id": lease_id})
            return result
        conn.commit()
    return None


def heartbeat(task_id: str, lease_id: str, lease_seconds: int = 300, db_path: Path = STATE_DB) -> bool:
    now = datetime.now(timezone.utc)
    until = (now + timedelta(seconds=lease_seconds)).isoformat()
    with _connection(db_path) as conn:
        cur = conn.execute("UPDATE leases SET heartbeat_utc=?,lease_until=? WHERE task_id=? AND lease_id=?", (now.isoformat(), until, task_id, lease_id))
        if cur.rowcount:
            conn.execute("UPDATE tasks SET heartbeat_utc=?,lease_until=?,updated_utc=? WHERE id=? AND status='LEASED'", (now.isoformat(), until, now.isoformat(), task_id))
        conn.commit()
        return cur.rowcount == 1


def complete_task(task_id: str, lease_id: str, result: dict[str, Any], db_path: Path = STATE_DB) -> None:
    parked_statuses = {"WAITING_CODEX_QUOTA", "WAITING_CODEX", "WAITING_LOCAL", "WAITING_EXTERNAL"}
    result_status = str(result.get("status", "")).upper()
    status = result_status if result_status in parked_statuses else "DONE"
    verdict = status if status != "DONE" else "PASS"
    with _connection(db_path) as conn:
        _schema(conn, "state")
        cur = conn.execute("UPDATE tasks SET status=?,verdict=?,result_json=?,lease_owner=NULL,lease_until=NULL,heartbeat_utc=NULL,updated_utc=? WHERE id=? AND status='LEASED' AND id IN (SELECT task_id FROM leases WHERE lease_id=?)",
                           (status, verdict, json.dumps(result, ensure_ascii=False), utcnow(), task_id, lease_id))
        if cur.rowcount != 1:
            raise RuntimeError("lease is missing or no longer owned by this worker")
        conn.execute("DELETE FROM leases WHERE task_id=?", (task_id,))
        attempts = conn.execute("SELECT attempts FROM tasks WHERE id=?", (task_id,)).fetchone()[0]
        conn.commit()
    if db_path.resolve() == STATE_DB.resolve():
        _sync_task_db(task_id, status, verdict, attempts)
    event = "task_parked" if status != "DONE" else "task_completed"
    _event(event, {"task_id": task_id, "status": status, "verdict": verdict, "result": result})


def reconcile_waiting_result_states(db_path: Path = STATE_DB) -> list[str]:
    """Repair legacy DONE rows whose saved result actually represents a parked wait state."""
    parked_statuses = {"WAITING_CODEX_QUOTA", "WAITING_CODEX", "WAITING_LOCAL", "WAITING_EXTERNAL"}
    reconciled: list[tuple[str, str, int]] = []
    with _connection(db_path) as conn:
        conn.row_factory = sqlite3.Row
        _schema(conn, "state")
        rows = conn.execute("SELECT id,result_json,attempts FROM tasks WHERE status='DONE'").fetchall()
        for row in rows:
            try:
                result = json.loads(row["result_json"] or "{}")
            except (TypeError, json.JSONDecodeError):
                continue
            if not isinstance(result, dict):
                continue
            status = str(result.get("status", "")).upper()
            if status not in parked_statuses:
                continue
            updated = conn.execute("UPDATE tasks SET status=?,verdict=?,lease_owner=NULL,lease_until=NULL,heartbeat_utc=NULL,updated_utc=? WHERE id=? AND status='DONE'",
                (status, status, utcnow(), row["id"]))
            if updated.rowcount:
                conn.execute("DELETE FROM leases WHERE task_id=?", (row["id"],))
                reconciled.append((str(row["id"]), status, int(row["attempts"])))
    if not reconciled:
        return []
    if db_path.resolve() == STATE_DB.resolve():
        for task_id, status, attempts in reconciled:
            _sync_task_db(task_id, status, status, attempts)
    for task_id, status, _ in reconciled:
        _event("task_wait_state_reconciled", {"task_id": task_id, "status": status,
            "reason": "saved task result was waiting; stale DONE state was corrected"})
    return [task_id for task_id, _, _ in reconciled]


def fail_task(task_id: str, lease_id: str, reason: str, db_path: Path = STATE_DB,
              failure_diagnostic: dict[str, Any] | None = None) -> str:
    with _connection(db_path) as conn:
        conn.row_factory = sqlite3.Row
        _schema(conn, "state")
        row = conn.execute("SELECT attempts,retry_limit FROM tasks WHERE id=? AND status='LEASED'", (task_id,)).fetchone()
        if not row or not conn.execute("SELECT 1 FROM leases WHERE task_id=? AND lease_id=?", (task_id, lease_id)).fetchone():
            raise RuntimeError("lease is missing or no longer owned by this worker")
        status = "PENDING" if row["attempts"] < row["retry_limit"] else "BLOCKED"
        verdict = "RETRY" if status == "PENDING" else "BLOCKED"
        saved_result = {"error": reason}
        if failure_diagnostic:
            saved_result["failure_diagnostic"] = failure_diagnostic
        conn.execute("UPDATE tasks SET status=?,verdict=?,result_json=?,lease_owner=NULL,lease_until=NULL,updated_utc=? WHERE id=?",
                     (status, verdict, json.dumps(saved_result, ensure_ascii=False), utcnow(), task_id))
        conn.execute("DELETE FROM leases WHERE task_id=?", (task_id,))
        conn.commit()
        attempts = row["attempts"]
    if db_path.resolve() == STATE_DB.resolve():
        _sync_task_db(task_id, status, verdict, attempts)
    _event("task_failed", {"task_id": task_id, "status": status, "reason": reason,
                            "failure_diagnostic": failure_diagnostic or {}})
    return status


def requeue_task(task_id: str, reason: str, db_path: Path = STATE_DB) -> None:
    if not reason.strip():
        raise ValueError("a reason is required to requeue a task")
    with _connection(db_path) as conn:
        row = conn.execute("SELECT status,attempts FROM tasks WHERE id=?", (task_id,)).fetchone()
        if not row:
            raise KeyError(f"unknown task: {task_id}")
        if row[0] not in {"DONE", "BLOCKED"}:
            raise RuntimeError(f"task must be DONE or BLOCKED before requeueing; current status is {row[0]}")
        prior_status, prior_attempts = row
        conn.execute(
            "UPDATE tasks SET status='PENDING',verdict='REQUEUED',attempts=0,result_json='{}',lease_owner=NULL,lease_until=NULL,updated_utc=? WHERE id=?",
            (utcnow(), task_id),
        )
        conn.execute("DELETE FROM leases WHERE task_id=?", (task_id,))
    if db_path.resolve() == STATE_DB.resolve():
        _sync_task_db(task_id, "PENDING", "REQUEUED", 0)
    _event("task_requeued", {"task_id": task_id, "reason": reason, "prior_status": prior_status, "prior_attempts": prior_attempts})


def supersede_task(task_id: str, reason: str, *, evidence: dict[str, Any] | None = None,
                   db_path: Path = STATE_DB) -> bool:
    """Atomically retire an unleased task whose immutable premise is obsolete.

    Only PENDING and BLOCKED work can be superseded.  LEASED work is owned by a
    worker and must finish its deterministic stale-input check before any state
    transition can retire it.  The authoritative project-state transition,
    lease removal, and saved supersession evidence share one SQLite write
    transaction; the legacy task-backlog mirror is updated after commit.
    """
    if not reason.strip():
        raise ValueError("a supersession reason is required")
    attempts = 0
    prior_status = ""
    saved_result: dict[str, Any] = {}
    with _connection(db_path, timeout=30) as conn:
        conn.row_factory = sqlite3.Row
        _schema(conn, "state")
        conn.commit()
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT status,verdict,attempts,result_json FROM tasks WHERE id=?", (task_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown task: {task_id}")
        prior_status = str(row["status"])
        attempts = int(row["attempts"])
        if prior_status == "SUPERSEDED":
            return False
        if prior_status not in {"PENDING", "BLOCKED"}:
            return False
        try:
            decoded = json.loads(row["result_json"] or "{}")
            saved_result = decoded if isinstance(decoded, dict) else {"previous_result": decoded}
        except (TypeError, json.JSONDecodeError):
            saved_result = {"previous_result_raw": str(row["result_json"])[:2000]}
        saved_result["superseded"] = {"reason": reason[:1000],
            "evidence": evidence or {}, "previous_status": prior_status,
            "transitioned_utc": utcnow()}
        updated = conn.execute(
            "UPDATE tasks SET status='SUPERSEDED',verdict='SUPERSEDED',result_json=?,"
            "lease_owner=NULL,lease_until=NULL,heartbeat_utc=NULL,updated_utc=? "
            "WHERE id=? AND status=?",
            (json.dumps(saved_result, ensure_ascii=False, sort_keys=True), utcnow(), task_id, prior_status),
        )
        if updated.rowcount != 1:
            return False
        conn.execute("DELETE FROM leases WHERE task_id=?", (task_id,))
    if db_path.resolve() == STATE_DB.resolve():
        _sync_task_db(task_id, "SUPERSEDED", "SUPERSEDED", attempts)
    _event("task_superseded", {"task_id": task_id, "reason": reason,
        "previous_status": prior_status, "evidence": evidence or {}})
    return True


def status_summary(db_path: Path = STATE_DB) -> dict[str, Any]:
    with _connection(db_path) as conn:
        conn.row_factory = sqlite3.Row
        task_rows = [dict(row) for row in conn.execute("SELECT status,id,budget_json FROM tasks")]
        active_rows = [row for row in task_rows if not project_scope.task_is_excluded(row)]
        task_counts: dict[str, int] = {}
        for row in active_rows:
            task_counts[row["status"]] = task_counts.get(row["status"], 0) + 1
        gates = [dict(row) for row in conn.execute("SELECT stage,status,criteria_json,proof_json,updated_utc FROM stage_gates ORDER BY stage")]
        evidence_count = conn.execute("SELECT count(*) FROM evidence").fetchone()[0]
        model_count = conn.execute("SELECT count(*) FROM model_runs").fetchone()[0]
    return {"updated_utc": utcnow(), "task_counts": task_counts, "stage_gates": gates,
            "evidence_count": evidence_count, "model_run_count": model_count}


def update_stage_gate(stage: str, status: str, proof: dict[str, Any], db_path: Path = STATE_DB) -> None:
    if status not in {"PENDING", "IN_PROGRESS", "BLOCKED", "COMPLETE"}:
        raise ValueError(f"invalid stage gate status: {status}")
    with _connection(db_path) as conn:
        cur = conn.execute(
            "UPDATE stage_gates SET status=?,proof_json=?,updated_utc=? WHERE stage=?",
            (status, json.dumps(proof, ensure_ascii=False), utcnow(), stage),
        )
        if cur.rowcount != 1:
            raise KeyError(f"unknown stage gate: {stage}")
    _event("stage_gate_updated", {"stage": stage, "status": status, "proof": proof})


def record_model_runs(report: dict[str, Any], db_path: Path = STATE_DB) -> None:
    """Persist one measured resource/result row per benchmark candidate."""
    finished = report.get("created_utc", utcnow())
    with _connection(db_path) as conn:
        conn.execute("DELETE FROM model_runs WHERE task_id='F0_MODEL_BENCHMARK'")
        for row in report.get("models", []):
            baseline = row.get("baseline_resources", {})
            ram = baseline.get("ram", {})
            gpu = baseline.get("gpu", {}) or {}
            conn.execute(
                """INSERT INTO model_runs
                (model,task_id,status,wall_ms,ram_before_bytes,ram_peak_bytes,vram_before_mib,
                 vram_peak_mib,useful_artifacts,result_json,started_utc,finished_utc)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (row.get("model", "unknown"), "F0_MODEL_BENCHMARK", row.get("status", "UNKNOWN"),
                 int(float(row.get("duration_seconds", 0)) * 1000), ram.get("used_bytes"),
                 row.get("peak_host_ram_used_bytes"), gpu.get("memory_used_mib"),
                 row.get("peak_vram_used_mib"), int(row.get("useful_artifacts", row.get("passed", 0))),
                 json.dumps(row, ensure_ascii=False), finished, finished),
            )
    _event("model_runs_recorded", {"models": len(report.get("models", [])), "report_status": report.get("status")})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="NCDR SQLite project state utility")
    parser.add_argument("command", choices=("init", "status", "claim", "requeue"))
    parser.add_argument("--owner", default="local-worker")
    parser.add_argument("--task-id")
    parser.add_argument("--reason", default="")
    args = parser.parse_args(argv)
    if args.command == "init":
        print(json.dumps(initialize(), ensure_ascii=False, indent=2))
    elif args.command == "status":
        print(json.dumps(status_summary(), ensure_ascii=False, indent=2))
    elif args.command == "claim":
        print(json.dumps(claim_next(args.owner), ensure_ascii=False, indent=2))
    else:
        if not args.task_id or not args.reason.strip():
            parser.error("requeue requires --task-id and a non-empty --reason")
        requeue_task(args.task_id, args.reason)
        print(json.dumps({"task_id": args.task_id, "status": "PENDING", "reason": args.reason}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
