"""Idempotent persistence and novelty gates for Mission Pack V2.

The JSON package is an immutable specification snapshot. Runtime task state and
evidence links live in the existing project SQLite database; importing the
package never inserts 46 duplicate executable tasks into the legacy queue.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PACK_ROOT = PROJECT_ROOT / "docs" / "mission_pack_v2"
BACKLOG_PATH = PACK_ROOT / "plans" / "task_backlog.json"
GATES_PATH = PACK_ROOT / "plans" / "goal_gates.json"
DEFAULT_DB = PROJECT_ROOT / "project_state.sqlite"
STATUSES = {"PROPOSED", "READY", "RUNNING", "DONE", "WAITING_LOCAL",
            "WAITING_CODEX", "WAITING_CODEX_QUOTA", "WAITING_EXTERNAL", "BLOCKED",
            "SUPERSEDED"}



# Reviewed engineering scopes. Never infer write authority from the mission documents.
# Report-only tasks intentionally expose only their fixed handler/verifier code.
MISSION_CAPABILITY_SCOPES = {
    "A01": (["src/agent/project_director.py"], ["tests/unit/test_mission_a01.py"]),
    "A02": (["src/agent/project_director.py"], ["tests/unit/test_mission_a02.py"]),
    "A03": (["src/agent/project_director.py"], ["tests/unit/test_mission_pack.py"]),
    "A04": (["src/agent/mission_pack.py","src/agent/autonomous_manager.py"], ["tests/unit/test_empty_queue_replan.py","tests/unit/test_mission_pack.py"]),
    "A05": (["src/agent/project_director.py","src/agent/failure_triage.py"], ["tests/unit/test_mission_a05.py"]),
    "A06": (["src/agent/capability_broker.py","src/agent/autonomous_manager.py"], ["tests/unit/test_capability_broker.py","tests/unit/test_capability_recovery.py"]),
    "A07": (["src/agent/state_store.py"], ["tests/unit/test_state_store.py"]),
    "A08": (["windows/install_manager.ps1","src/agent/project_director.py"], ["tests/unit/test_mission_a08.py"]),
    "A09": (["src/agent/file_bridge.py"], ["tests/unit/test_file_bridge.py"]),
    "A10": (["src/agent/model_router.py","src/agent/autonomous_manager.py"], ["tests/unit/test_model_router.py"]),
    "A11": (["src/agent/build_dashboard.py","src/agent/autonomous_manager.py"], ["tests/unit/test_dashboard.py"]),
    "A12": (["src/agent/autonomous_manager.py","src/agent/project_director.py"], ["tests/unit/test_autonomous_manager.py","tests/unit/test_capability_recovery.py"]),
    "B01": (["src/agent/project_director.py","src/agent/coordinator_runtime.py"], ["tests/unit/test_inventory_analysis.py","tests/unit/test_coordinator_runtime.py"]),
    "B02": (["src/agent/project_director.py","src/agent/coordinator_runtime.py"], ["tests/unit/test_inventory_analysis.py"]),
    "B03": (["src/agent/project_director.py","src/agent/mission_pack.py","src/agent/b03_inventory_verifier.py"], ["tests/unit/test_mission_b03.py","tests/unit/test_ncdx_binary_headers.py"]),
    "B04": (["src/agent/project_director.py"], ["tests/unit/test_project_director.py"]),
    "B05": (["src/agent/project_director.py"], ["tests/unit/test_project_director.py"]),
    "B06": (["src/agent/project_director.py","src/agent/coordinator_runtime.py"], ["tests/unit/test_inventory_analysis.py"]),
    "B07": (["src/agent/project_director.py"], ["tests/unit/test_mp0_independent.py","tests/unit/test_ncdx_mp0_header.py"]),
    "B08": (["src/readers/geometry_decoder.py","src/agent/project_director.py"], ["tests/unit/test_project_director.py"]),
    "B09": (["src/readers/road_graph.py","src/agent/project_director.py"], ["tests/unit/test_project_director.py"]),
    "B10": (["src/readers/text_poi.py","src/agent/project_director.py"], ["tests/unit/test_project_director.py"]),
    "B11": (["src/readers/reference_reader.py","src/readers/independent_reader.py","src/agent/project_director.py"], ["tests/unit/test_mp0_independent.py","tests/unit/test_ncdx_mp0_header.py"]),
    "B12": (["src/agent/project_director.py"], ["tests/unit/test_coordinator_runtime.py"]),
    "C01": (["src/agent/project_director.py","src/writers/research_writer.py","src/readers/mp0_independent.py"], ["tests/unit/test_research_writer.py","tests/unit/test_mp0_independent.py"]),
    "C02": (["src/agent/project_director.py","src/writers/research_writer.py"], ["tests/unit/test_research_writer.py"]),
    "C03": (["src/writers/index_builder.py","src/agent/project_director.py","src/writers/research_writer.py"], ["tests/unit/test_research_writer.py"]),
    "C04": (["src/agent/project_director.py","src/writers/research_writer.py"], ["tests/unit/test_research_writer.py"]),
    "D01": (["src/osm/streaming_pipeline.py","src/agent/project_director.py","src/osm/extract_pbf.py","src/osm/resumable_national.py","src/osm/build_ukraine.py"], ["tests/unit/test_extract_pbf_whole_source.py","tests/unit/test_resumable_national.py","tests/unit/test_build_ukraine.py"]),
    "D02": (["src/agent/project_director.py"], ["tests/unit/test_mission_d02.py"]),
    "D03": (["src/agent/project_director.py","src/osm/build_ukraine.py"], ["tests/unit/test_build_ukraine.py"]),
    "D04": (["src/agent/project_director.py","src/osm/resumable_national.py"], ["tests/unit/test_resumable_national.py"]),
    "D05": (["src/agent/project_director.py","src/osm/engine.py"], ["tests/unit/test_osm_engine.py"]),
    "D06": (["src/agent/project_director.py","src/osm/build_kryvyi_rih.py"], ["tests/unit/test_build_kryvyi_rih.py"]),
    "D07": (["src/agent/project_director.py","src/osm/resumable_national.py","src/osm/build_ukraine.py"], ["tests/unit/test_resumable_national.py","tests/unit/test_build_ukraine.py"]),
    "D08": (["src/agent/project_director.py","src/osm/engine.py"], ["tests/unit/test_osm_engine.py"]),
    "E01": (["src/agent/project_director.py","src/adapters/ncdx_adapter.py"], ["tests/unit/test_research_writer.py"]),
    "E02": (["src/agent/project_director.py","src/adapters/ncdx_adapter.py"], ["tests/unit/test_research_writer.py"]),
    "E03": (["src/agent/project_director.py","src/agent/e03_optical_layout.py","src/agent/e03_optical_layout_verifier.py","src/agent/mission_pack.py"], ["tests/unit/test_mission_e03.py"]),
    "E04": (["src/agent/project_director.py"], ["tests/unit/test_research_writer.py"]),
    "E05": (["src/agent/project_director.py"], ["tests/unit/test_project_director.py"]),
    "E06": ([], []),
    "Q01": (["src/agent/build_dashboard.py","src/agent/readiness.py"], ["tests/unit/test_dashboard.py"]),
    "Q02": (["src/agent/project_director.py"], ["tests/unit/test_project_director.py"]),
    "Q03": (["src/agent/novelty_check.py","src/agent/mission_pack.py","src/agent/project_director.py"], ["tests/unit/test_mission_pack.py","tests/unit/test_project_director.py"]),
    "Q04": (["src/agent/project_director.py"], ["tests/unit/test_failure_triage.py","tests/unit/test_model_router.py","tests/unit/test_capability_broker.py"]),
}
EXTERNAL_MISSION_IDS = frozenset({"E06"})


def capability_scope(canonical_id: str) -> dict[str, Any]:
    """Return fresh exact scopes; unknown IDs fail closed and tests remain read-only."""
    allowed, tests = MISSION_CAPABILITY_SCOPES[canonical_id]
    if canonical_id in EXTERNAL_MISSION_IDS:
        return {"status": "WAITING_EXTERNAL", "allowed_paths": [], "test_paths": []}
    root = PROJECT_ROOT.resolve()
    source_root = root / "src"
    for relative in [*allowed, *tests]:
        path = Path(relative)
        resolved = (root / path).resolve()
        if (not relative or any(char in relative for char in "*?[]\\:") or path.is_absolute()
                or ".." in path.parts or path.as_posix() != relative
                or not resolved.is_relative_to(root)):
            raise ValueError(f"Invalid static mission capability path: {relative}")
        if relative in tests:
            valid = path.parts[0] == "tests" and resolved.is_file() and resolved.is_relative_to(root / "tests")
        elif path.parts[0] == "src":
            valid = (resolved.is_relative_to(source_root)
                     and (resolved.is_file() or (not resolved.exists() and path.suffix == ".py"
                          and resolved.parent.is_dir()
                          and resolved.parent.is_relative_to(source_root))))
        else:
            candidate = root / path
            # Older broker sandboxes omitted windows/. Validate the one fixed
            # installer against their owning project, never an arbitrary ancestor
            # or a new Windows script. This does not grant writes to that project.
            installer = candidate
            if (not candidate.exists() and root.parent.name == "capability_worktrees"
                    and root.parent.parent.name == "autonomous_manager"
                    and root.parent.parent.parent.name == "work"):
                installer = root.parents[3] / path
            installer_root = installer.parent.resolve()
            valid = (relative == "windows/install_manager.ps1"
                     and not installer.is_symlink()
                     and installer.is_file()
                     and installer.resolve().parent == installer_root
                     and installer_root == installer.parent.parent.resolve() / "windows"
                     and resolved.is_relative_to(root / "windows"))
        if not valid:
            raise ValueError(f"Invalid static mission capability path: {relative}")
    if not allowed or not tests or set(allowed) & set(tests):
        raise ValueError(f"Missing independent scope for {canonical_id}")
    return {"status": "WAITING_LOCAL", "allowed_paths": list(allowed), "test_paths": list(tests)}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _utc_text(value: datetime | None = None) -> str:
    return (value or _utcnow()).isoformat()


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


@contextmanager
def _connection(db_path: Path):
    conn = _connect(db_path)
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def ensure_schema(db_path: Path = DEFAULT_DB) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with _connection(db_path) as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS mission_tasks(
          canonical_id TEXT PRIMARY KEY, phase TEXT NOT NULL, priority INTEGER NOT NULL,
          objective TEXT NOT NULL, dependencies_json TEXT NOT NULL,
          expected_artifacts_json TEXT NOT NULL, acceptance_json TEXT NOT NULL,
          executor_preference TEXT NOT NULL, spec_sha256 TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'PROPOSED', runtime_task_id TEXT,
          evidence_json TEXT NOT NULL DEFAULT '{}', status_reason TEXT NOT NULL DEFAULT '',
          created_utc TEXT NOT NULL, updated_utc TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS mission_planner_ticks(
          id INTEGER PRIMARY KEY AUTOINCREMENT, candidate_fingerprint TEXT NOT NULL UNIQUE,
          created_utc TEXT NOT NULL, selected_id TEXT, decision TEXT NOT NULL,
          detail_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE TABLE IF NOT EXISTS mission_pack_metadata(
          key TEXT PRIMARY KEY,value TEXT NOT NULL,updated_utc TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_mission_tasks_status_priority
          ON mission_tasks(status,priority,canonical_id);
        """)


def import_pack(db_path: Path = DEFAULT_DB) -> dict[str, Any]:
    """Import all 46 canonical specs without resetting runtime statuses."""
    ensure_schema(db_path)
    backlog = json.loads(BACKLOG_PATH.read_text(encoding="utf-8"))
    gates = json.loads(GATES_PATH.read_text(encoding="utf-8"))
    tasks = backlog.get("tasks")
    if not isinstance(tasks, list) or len(tasks) != int(backlog.get("task_count", -1)):
        raise ValueError("Mission Pack backlog count does not match its declared task_count")
    ids = [str(task.get("id", "")) for task in tasks]
    if len(set(ids)) != len(ids) or any(not task_id for task_id in ids):
        raise ValueError("Mission Pack contains missing or duplicate canonical task IDs")
    id_set = set(ids)
    if id_set != set(MISSION_CAPABILITY_SCOPES):
        raise ValueError("Mission Pack IDs differ from the reviewed static capability registry")
    for task in tasks:
        if any(dependency not in id_set for dependency in task.get("dependencies", [])):
            raise ValueError(f"Mission Pack task {task['id']} references an unknown dependency")

    now = _utc_text()
    inserted = 0
    updated_specs = 0
    with _connection(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        for task in tasks:
            canonical_id = str(task["id"])
            payload = json.dumps(task, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            spec_sha = hashlib.sha256(payload.encode("utf-8")).hexdigest()
            cursor = conn.execute("""INSERT OR IGNORE INTO mission_tasks(
              canonical_id,phase,priority,objective,dependencies_json,expected_artifacts_json,
              acceptance_json,executor_preference,spec_sha256,status,created_utc,updated_utc)
              VALUES(?,?,?,?,?,?,?,?,?,'PROPOSED',?,?)""",
              (canonical_id, task.get("phase", ""), int(task.get("priority", 100)),
               str(task.get("objective", "")),
               json.dumps(task.get("dependencies", []), ensure_ascii=False),
               json.dumps(task.get("expected_artifacts", []), ensure_ascii=False),
               json.dumps(task.get("acceptance_criteria", []), ensure_ascii=False),
               str(task.get("executor_preference", "tool")), spec_sha, now, now))
            inserted += max(0, cursor.rowcount)
            if cursor.rowcount == 0:
                existing = conn.execute("SELECT spec_sha256 FROM mission_tasks WHERE canonical_id=?",
                                        (canonical_id,)).fetchone()
                if existing and existing[0] != spec_sha:
                    # A new package revision updates its specification only;
                    # verified runtime state and evidence are preserved.
                    conn.execute("""UPDATE mission_tasks SET phase=?,priority=?,objective=?,
                      dependencies_json=?,expected_artifacts_json=?,acceptance_json=?,
                      executor_preference=?,spec_sha256=?,updated_utc=? WHERE canonical_id=?""",
                      (task.get("phase", ""), int(task.get("priority", 100)),
                       str(task.get("objective", "")),
                       json.dumps(task.get("dependencies", []), ensure_ascii=False),
                       json.dumps(task.get("expected_artifacts", []), ensure_ascii=False),
                       json.dumps(task.get("acceptance_criteria", []), ensure_ascii=False),
                       str(task.get("executor_preference", "tool")), spec_sha, now, canonical_id))
                    updated_specs += 1
        conn.execute("INSERT OR REPLACE INTO mission_pack_metadata(key,value,updated_utc) VALUES('mission_pack_v2',?,?)",
                     (json.dumps({"version": backlog.get("package_version"),
                                  "source": str(BACKLOG_PATH.relative_to(PROJECT_ROOT)),
                                  "goal_gate_count": len(gates.get("gates", []))}, ensure_ascii=False), now))
        conn.commit()
        total = int(conn.execute("SELECT count(*) FROM mission_tasks").fetchone()[0])
    return {"task_count": total, "inserted": inserted, "updated_specs": updated_specs,
            "package_version": str(backlog.get("package_version", "")),
            "goal_gate_count": len(gates.get("gates", []))}


def task_spec(canonical_id: str) -> dict[str, Any]:
    backlog = json.loads(BACKLOG_PATH.read_text(encoding="utf-8"))
    task = next((row for row in backlog["tasks"] if row.get("id") == canonical_id), None)
    if task is None:
        raise KeyError(f"unknown canonical Mission Pack ID: {canonical_id}")
    return task


def verify_runtime_result(canonical_id: str, result: dict[str, Any], *,
                          db_path: Path = DEFAULT_DB,
                          persist: bool = True) -> dict[str, Any]:
    """Independently validate a mission execution artifact and persist its state."""
    if result.get("status") in {"WAITING_LOCAL", "WAITING_CODEX", "WAITING_CODEX_QUOTA", "WAITING_EXTERNAL"}:
        with _connection(db_path) as conn:
            current = conn.execute("SELECT evidence_json FROM mission_tasks WHERE canonical_id=?",
                                   (canonical_id,)).fetchone()
        previous: Any = {}
        if current:
            try:
                previous = json.loads(current["evidence_json"] or "{}")
            except json.JSONDecodeError:
                previous = {"prior_evidence_text": str(current["evidence_json"] or "")[:1000]}
        if not isinstance(previous, dict):
            previous = {"prior_evidence": previous}
        evidence = {"verifier": "deterministic_mission_state_verifier", "verdict": "PASS",
                    "result_status": result["status"], "reason": str(result.get("reason", ""))[:1000],
                    "previous_evidence": previous}
        if canonical_id == "E03" and result.get("status") == "WAITING_EXTERNAL":
            artifact = result.get("artifact")
            relative = str(artifact.get("path", "")).replace("\\", "/") if isinstance(artifact, dict) else ""
            if relative != "evidence/optical-layout-proof.json" or not artifact.get("sha256"):
                raise RuntimeError("E03 WAITING_EXTERNAL result lacks its exact optical evidence artifact")
            artifact_path = (PROJECT_ROOT / relative).resolve(strict=True)
            if (not artifact_path.is_relative_to(PROJECT_ROOT.resolve())
                    or hashlib.sha256(artifact_path.read_bytes()).hexdigest() != artifact["sha256"]):
                raise RuntimeError("E03 optical evidence artifact escaped the project or changed")
            from src.agent.e03_optical_layout_verifier import verify_e03_optical_layout_evidence
            evidence["artifact"] = artifact
            evidence["independent_verification"] = verify_e03_optical_layout_evidence(artifact_path)
            evidence["acceptance"] = result.get("acceptance", {})
        for key in ("request_id", "quota", "local_failure", "artifact", "acceptance"):
            if key in result:
                evidence[key] = result[key]
        if persist:
            mark_status(canonical_id, result["status"], evidence=evidence,
                        reason=evidence["reason"], runtime_task_id=result.get("runtime_task_id"), db_path=db_path)
        return {"status": result["status"], "canonical_id": canonical_id, "evidence": evidence}
    if result.get("status") != "PASS":
        raise RuntimeError(f"Mission Pack result did not pass: {canonical_id}")
    artifact = result.get("artifact")
    if not isinstance(artifact, dict) or not artifact.get("path") or not artifact.get("sha256"):
        raise RuntimeError(f"Mission Pack result lacks a registered artifact: {canonical_id}")
    path = (PROJECT_ROOT / str(artifact["path"])).resolve(strict=True)
    if not path.is_relative_to(PROJECT_ROOT.resolve()) or not path.is_file():
        raise RuntimeError(f"Mission Pack artifact is outside the current project: {path}")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != artifact["sha256"]:
        raise RuntimeError(f"Mission Pack artifact hash changed after execution: {path}")
    saved = json.loads(path.read_text(encoding="utf-8"))
    if saved.get("canonical_id") != canonical_id or saved.get("status") != "PASS":
        raise RuntimeError(f"Mission Pack artifact does not match the claimed canonical task: {path}")
    specialized: dict[str, Any] = {}
    if canonical_id == "B01":
        acceptance = saved.get("acceptance", {})
        index_artifact = acceptance.get("index_artifact", {}) if isinstance(acceptance, dict) else {}
        if not isinstance(index_artifact, dict) or not index_artifact.get("path") or not index_artifact.get("sha256"):
            raise RuntimeError("B01 result lacks the separately registered format evidence index")
        index_path = (PROJECT_ROOT / str(index_artifact["path"])).resolve(strict=True)
        if not index_path.is_relative_to(PROJECT_ROOT.resolve()) or not index_path.is_file():
            raise RuntimeError("B01 format index escaped the project directory")
        if hashlib.sha256(index_path.read_bytes()).hexdigest() != index_artifact["sha256"]:
            raise RuntimeError("B01 format index hash changed after execution")
        specialized = verify_b01_format_evidence_index(index_path)
    elif canonical_id == "B02":
        acceptance = saved.get("acceptance", {})
        diff_artifact = acceptance.get("diff_artifact", {}) if isinstance(acceptance, dict) else {}
        diff_relative = str(diff_artifact.get("path", "")).replace("\\", "/") if isinstance(diff_artifact, dict) else ""
        if (not isinstance(diff_artifact, dict)
                or diff_relative != "evidence/region-diff-records.json"
                or not diff_artifact.get("sha256")):
            raise RuntimeError("B02 result lacks the separately registered region-diff evidence")
        diff_path = (PROJECT_ROOT / str(diff_artifact["path"])).resolve(strict=True)
        if (not diff_path.is_relative_to(PROJECT_ROOT.resolve())
                or hashlib.sha256(diff_path.read_bytes()).hexdigest() != diff_artifact["sha256"]):
            raise RuntimeError("B02 region-diff artifact escaped the project or changed after execution")
        specialized = verify_b02_region_diff_records(diff_path, db_path=db_path)
    elif canonical_id == "B03":
        acceptance = saved.get("acceptance", {})
        inventory_artifact = acceptance.get("binary_inventory_artifact", {}) if isinstance(acceptance, dict) else {}
        inventory_relative = str(inventory_artifact.get("path", "")).replace("\\", "/") if isinstance(inventory_artifact, dict) else ""
        if (not isinstance(inventory_artifact, dict)
                or inventory_relative != "firmware/binary-format-inventory.json"
                or not inventory_artifact.get("sha256")):
            raise RuntimeError("B03 result lacks its registered binary-format inventory")
        inventory_file = (PROJECT_ROOT / inventory_relative).resolve(strict=True)
        if (not inventory_file.is_relative_to(PROJECT_ROOT.resolve())
                or hashlib.sha256(inventory_file.read_bytes()).hexdigest() != inventory_artifact["sha256"]):
            raise RuntimeError("B03 binary-format inventory escaped the project or changed after execution")
        from src.agent.b03_inventory_verifier import verify_b03_binary_format_inventory
        specialized = verify_b03_binary_format_inventory(inventory_file)
    elif canonical_id == "B06":
        acceptance = saved.get("acceptance", {})
        catalog_artifact = acceptance.get("catalog_artifact", {}) if isinstance(acceptance, dict) else {}
        catalog_relative = str(catalog_artifact.get("path", "")).replace("\\", "/") if isinstance(catalog_artifact, dict) else ""
        if (not isinstance(catalog_artifact, dict)
                or catalog_relative != "evidence/ncdx-structure-catalog.json"
                or not catalog_artifact.get("sha256")):
            raise RuntimeError("B06 result lacks its separately registered NCDx structure catalog")
        catalog_file = (PROJECT_ROOT / catalog_relative).resolve(strict=True)
        if (not catalog_file.is_relative_to(PROJECT_ROOT.resolve())
                or hashlib.sha256(catalog_file.read_bytes()).hexdigest() != catalog_artifact["sha256"]):
            raise RuntimeError("B06 structure catalog escaped the project or changed after execution")
        specialized = verify_b06_structure_catalog(catalog_file, db_path=db_path)
    elif canonical_id == "B07":
        acceptance = saved.get("acceptance", {})
        index_artifact = acceptance.get("index_integrity_artifact", {}) if isinstance(acceptance, dict) else {}
        index_relative = str(index_artifact.get("path", "")).replace("\\", "/") if isinstance(index_artifact, dict) else ""
        if (not isinstance(index_artifact, dict)
                or index_relative != "evidence/ncdx-index-integrity.json"
                or not index_artifact.get("sha256")):
            raise RuntimeError("B07 result lacks its separately registered index-integrity artifact")
        index_file = (PROJECT_ROOT / index_relative).resolve(strict=True)
        if (not index_file.is_relative_to(PROJECT_ROOT.resolve())
                or hashlib.sha256(index_file.read_bytes()).hexdigest() != index_artifact["sha256"]):
            raise RuntimeError("B07 index-integrity report escaped the project or changed after execution")
        specialized = verify_b07_index_integrity_report(index_file, db_path=db_path)
    evidence = {"verifier": "independent_artifact_hash_and_schema_check", "verdict": "PASS",
                "artifact_path": str(path.relative_to(PROJECT_ROOT)), "artifact_sha256": digest,
                "acceptance": saved.get("acceptance", {}), **specialized}
    if persist:
        mark_status(canonical_id, "DONE", evidence=evidence,
                    runtime_task_id=result.get("runtime_task_id"), db_path=db_path)
    return {"status": "DONE", "canonical_id": canonical_id, "evidence": evidence}


def verify_b01_format_evidence_index(index_path: Path, *, source_root: Path | None = None,
                                    project_root: Path | None = None) -> dict[str, Any]:
    """Independently re-read every indexed MP0 field and its TOC cross-reference."""
    from src.agent import coordinator_runtime
    from src.readers.ncdx_mp0_header import read_mp0_header

    path = Path(index_path).resolve(strict=True)
    index = json.loads(path.read_text(encoding="utf-8"))
    if index.get("canonical_id") != "B01" or index.get("status") != "PASS":
        raise RuntimeError("B01 format index schema is not PASS")
    root = Path(source_root or coordinator_runtime.SOURCE_ROOT).resolve(strict=True)
    project = Path(project_root or PROJECT_ROOT).resolve(strict=True)
    source_for = {label: (folder, prefix) for label, folder, prefix in coordinator_runtime.REGIONS}
    field_specs = {"marker": (0x00, 13), "copyright": (0x10, 16),
                   "internal_format_version": (0x20, 16), "dataset_code": (0x30, 16)}
    prefix_for = {"EUZ": "EU", "IZ": "I", "SCZ": "SC"}
    facts = index.get("facts")
    if not isinstance(facts, list) or len(facts) != len(source_for) * len(field_specs):
        raise RuntimeError("B01 must include exactly four bounded header facts for each of three datasets")
    source_hashes: dict[str, str] = {}
    parsed_sources: dict[str, Any] = {}
    verified_fields = 0
    for fact in facts:
        label = str(fact.get("dataset", ""))
        if label not in source_for:
            raise RuntimeError("B01 fact references an unknown regional dataset")
        folder, prefix = source_for[label]
        field = str(fact.get("field", ""))
        if field not in field_specs:
            raise RuntimeError("B01 fact references an unsupported header field")
        offset, width = field_specs[field]
        expected_path = (folder / f"{prefix}.MP0").as_posix()
        if (fact.get("source_path") != expected_path or int(fact.get("offset", -1)) != offset
                or int(fact.get("length", -1)) != width):
            raise RuntimeError("B01 fact has an unexpected path, byte offset, or field width")
        source = (root / expected_path).resolve(strict=True)
        if not source.is_relative_to(root):
            raise RuntimeError("B01 source path escaped the read-only NCDR root")
        if expected_path not in source_hashes:
            digest_builder = hashlib.sha256()
            with source.open("rb") as handle:
                while chunk := handle.read(1024 * 1024):
                    digest_builder.update(chunk)
            source_hashes[expected_path] = digest_builder.hexdigest()
            parsed_sources[expected_path] = read_mp0_header(source)
        digest = source_hashes[expected_path]
        if digest != fact.get("source_sha256"):
            raise RuntimeError(f"B01 source SHA-256 mismatch for {expected_path}")
        raw = source.open("rb")
        try:
            raw.seek(offset)
            current = raw.read(width)
        finally:
            raw.close()
        if len(current) != width or current.hex() != fact.get("raw_hex"):
            raise RuntimeError(f"B01 raw bytes differ at offset {offset:#x} in {expected_path}")
        value_bytes = current if field == "marker" else current.split(b"\0", 1)[0]
        observed = value_bytes.decode("ascii", errors="strict")
        if observed != fact.get("observed"):
            raise RuntimeError(f"B01 field value differs at offset {offset:#x} in {expected_path}")
        checks = fact.get("checks", [])
        check_methods = {str(item.get("method", "")) for item in checks if isinstance(item, dict)}
        if not {"ncdx_mp0_header.read_mp0_header", "independent_raw_offset_slice"}.issubset(check_methods):
            raise RuntimeError("B01 fact does not declare both required independent checks")
        parsed = parsed_sources[expected_path]
        parsed_value = {"marker": parsed.magic, "copyright": parsed.copyright,
                        "internal_format_version": parsed.internal_format_version,
                        "dataset_code": parsed.dataset_code}[field]
        if parsed.sha256 != digest or parsed_value != observed:
            raise RuntimeError(f"B01 independent parser disagrees for {expected_path}:{offset:#x}")
        if field == "dataset_code":
            toc_path = (root / folder.parent / "CDROM.TOC").resolve(strict=True)
            if not toc_path.is_relative_to(root):
                raise RuntimeError("B01 TOC path escaped the read-only NCDR root")
            toc_text = toc_path.read_text(encoding="cp1252", errors="replace")
            match = re.search(r"(?im)^\s*Version:\s*([0-9.]+)\s*$", toc_text)
            if not match or observed.removeprefix(prefix_for[prefix]).replace(".", "") != match.group(1).replace(".", ""):
                raise RuntimeError(f"B01 dataset code does not match independent TOC version: {label}")
            if hashlib.sha256(toc_path.read_bytes()).hexdigest() != next(
                    str(check.get("toc_sha256", "")) for check in checks
                    if isinstance(check, dict) and check.get("method") == "CDROM.TOC.Version cross-reference"):
                raise RuntimeError(f"B01 TOC hash differs for {label}")
        verified_fields += 1

    claim_boundaries = index.get("claim_boundaries", {})
    if (not claim_boundaries.get("facts_have_two_independent_checks")
            or claim_boundaries.get("db_0_format_transferred_to_ncdx") is not False
            or claim_boundaries.get("original_media_write_count") != 0):
        raise RuntimeError("B01 claim boundary is missing, unsafe, or transfers DB_0 assumptions")
    unknown = index.get("unknown_register", {})
    unknown_path = (project / str(unknown.get("path", ""))).resolve(strict=True)
    if not unknown_path.is_relative_to(project):
        raise RuntimeError("B01 unknowns register escaped the project")
    if hashlib.sha256(unknown_path.read_bytes()).hexdigest() != unknown.get("sha256"):
        raise RuntimeError("B01 unknowns register hash changed")
    return {"b01_independent_source_verification": "PASS",
            "b01_verified_fact_count": verified_fields,
            "b01_verified_dataset_count": len(source_hashes),
            "b01_unknown_register_hash_verified": True,
            "b01_db0_transfer": False,
            "b01_original_media_write_count": 0}


def verify_b02_region_diff_records(diff_path: Path, *, source_root: Path | None = None,
                                  project_root: Path | None = None,
                                  db_path: Path = DEFAULT_DB,
                                  require_prior_evidence: bool = True) -> dict[str, Any]:
    """Independently rehash and recompute B02's bounded three-region byte diff."""
    import struct
    from src.agent import coordinator_runtime
    from src.readers.ncdx_container import iter_decoded_blocks, read_index

    artifact_path = Path(diff_path).resolve(strict=True)
    project = Path(project_root or PROJECT_ROOT).resolve(strict=True)
    root = Path(source_root or coordinator_runtime.SOURCE_ROOT).resolve(strict=True)
    if not artifact_path.is_relative_to(project):
        raise RuntimeError("B02 region-diff evidence escaped the current project")
    saved = json.loads(artifact_path.read_text(encoding="utf-8"))
    expected_suffixes = ("MP0", "MG1", "MG2", "MG3", "CTY", "CNY", "RL", "IOF", "IL")
    expected_regions = {label: (folder, prefix)
                        for label, folder, prefix in coordinator_runtime.REGIONS}
    if (saved.get("canonical_id") != "B02" or saved.get("status") != "PASS"
            or saved.get("suffixes") != list(expected_suffixes)
            or saved.get("regions") != list(expected_regions)):
        raise RuntimeError("B02 artifact does not contain the fixed three-region, nine-family experiment")
    sample_bytes = int(saved.get("sample_prefix_bytes", 0))
    block_bytes = int(saved.get("aligned_block_bytes", 0))
    if not 256 <= block_bytes <= 65536 or block_bytes & (block_bytes - 1):
        raise RuntimeError("B02 diff block size is outside the bounded power-of-two policy")
    if not block_bytes <= sample_bytes <= 4 * 1024 * 1024:
        raise RuntimeError("B02 diff sample prefix is outside the 1..4 MiB policy")
    families = saved.get("families")
    if not isinstance(families, list) or [row.get("suffix") for row in families] != list(expected_suffixes):
        raise RuntimeError("B02 family records are missing, duplicated, or reordered")

    expected_type_ids = {"CTY": 3, "CNY": 12, "RL": 21, "IOF": 21, "IL": 20}
    expected_strides = {"CTY": 178, "CNY": 174, "RL": 61, "IOF": 6}
    source_checks = 0
    recomputed_blocks = 0
    verified_three_way_equal_blocks = 0
    for family in families:
        suffix = str(family["suffix"])
        source_rows = family.get("sources")
        if not isinstance(source_rows, dict) or set(source_rows) != set(expected_regions):
            raise RuntimeError(f"B02 {suffix} source matrix is incomplete")
        samples: dict[str, bytes] = {}
        hashes: dict[str, str] = {}
        counts: dict[str, int | None] = {}
        for label, (folder, prefix) in expected_regions.items():
            row = source_rows[label]
            relative_path = (folder / f"{prefix}.{suffix}").as_posix()
            if row.get("relative_path") != relative_path:
                raise RuntimeError(f"B02 {suffix}/{label} source is not the manifest-bound input")
            source = (root / relative_path).resolve(strict=True)
            if not source.is_relative_to(root) or not source.is_file():
                raise RuntimeError(f"B02 source escaped the read-only root: {relative_path}")
            before = source.stat()
            digest = hashlib.sha256()
            prefix_sample = bytearray()
            size = 0
            with source.open("rb") as handle:
                while chunk := handle.read(1024 * 1024):
                    digest.update(chunk)
                    if len(prefix_sample) < sample_bytes:
                        prefix_sample.extend(chunk[:sample_bytes - len(prefix_sample)])
                    size += len(chunk)
            after_hash = source.stat()
            sha = digest.hexdigest()
            if (before.st_size != size or after_hash.st_size != size
                    or before.st_mtime_ns != after_hash.st_mtime_ns
                    or row.get("source_size_bytes") != size
                    or row.get("source_sha256") != sha
                    or row.get("source_mtime_ns_during_read") != before.st_mtime_ns
                    or row.get("source_unchanged_during_read") is not True):
                raise RuntimeError(f"B02 full-source identity/read-stability verification failed: {relative_path}")
            sample = bytes(prefix_sample)
            samples[label] = sample
            hashes[label] = sha

            with source.open("rb") as handle:
                physical_prefix = handle.read(110)
            header = row.get("header", {})
            if physical_prefix.startswith(b"zip\x01"):
                with source.open("rb") as handle:
                    index = read_index(handle)
                    block_iter = iter_decoded_blocks(handle, index)
                    first_offset, logical = next(block_iter)
                if first_offset != 0 or len(logical) < 94:
                    raise RuntimeError(f"B02 first logical block is malformed: {relative_path}")
                type_id = struct.unpack_from("<H", logical, 84)[0]
                count = struct.unpack_from("<I", logical, 86)[0]
                body = index.logical_size_bytes - 94
                stride = body // count if count and body >= 0 and body % count == 0 else None
                actual_header = {"encoding": "zip_01_block_container", "logical_type_id": type_id,
                    "declared_record_count": count, "logical_size_bytes": index.logical_size_bytes,
                    "derived_record_stride_bytes": stride}
                if (header.get("encoding") != actual_header["encoding"]
                        or header.get("logical_type_id") != type_id
                        or header.get("declared_record_count") != count
                        or header.get("logical_size_bytes") != index.logical_size_bytes
                        or header.get("derived_record_stride_bytes") != stride
                        or type_id != expected_type_ids.get(suffix)
                        or (suffix in expected_strides and stride != expected_strides[suffix])):
                    raise RuntimeError(f"B02 independently decoded header differs: {relative_path}")
            else:
                if len(physical_prefix) < 94:
                    raise RuntimeError(f"B02 raw header is truncated: {relative_path}")
                type_id = struct.unpack_from("<H", physical_prefix, 84)[0]
                count = struct.unpack_from("<I", physical_prefix, 86)[0]
                if (header.get("encoding") != "raw_siemens_map_header"
                        or header.get("logical_type_id") != type_id
                        or header.get("declared_record_count") != count):
                    raise RuntimeError(f"B02 raw header differs on independent readback: {relative_path}")
            counts[label] = count
            source_checks += 1

        if family.get("all_full_file_hashes_distinct") != (len(set(hashes.values())) == len(hashes)):
            raise RuntimeError(f"B02 full-file distinctness claim is wrong for {suffix}")
        if family.get("declared_record_counts") != counts:
            raise RuntimeError(f"B02 record-count summary differs for {suffix}")
        diff = family.get("aligned_byte_diff", {})
        pair_counts: dict[str, int] = {}
        labels = sorted(samples)
        common_all = 0
        extent = min(map(len, samples.values()))
        pair_counts = {f"{left}:{right}": 0 for index, left in enumerate(labels)
                       for right in labels[index + 1:]}
        for index in range(0, extent - block_bytes + 1, block_bytes):
            blocks = {name: samples[name][index:index + block_bytes] for name in labels}
            if len(set(blocks.values())) == 1:
                common_all += 1
            for left_i, left in enumerate(labels):
                for right in labels[left_i + 1:]:
                    key = f"{left}:{right}"
                    pair_counts[key] = pair_counts.get(key, 0) + (blocks[left] == blocks[right])
            recomputed_blocks += 1
        if (diff.get("aligned_prefix_bytes") != extent
                or diff.get("block_bytes") != block_bytes
                or diff.get("common_block_count_across_all_regions") != common_all
                or diff.get("pairwise_equal_block_counts") != pair_counts):
            raise RuntimeError(f"B02 aligned-byte comparison failed independent recomputation: {suffix}")
        verified_three_way_equal_blocks += common_all

    prior = saved.get("prior_evidence", {}).get("accepted_artifacts", [])
    if require_prior_evidence:
        required = {"AUTO_NCDX_ROADLINK_PORTABILITY_V1_35CFAF6ED2C9EAF8",
                    "AUTO_NCDX_GEOGRAPHY_PORTABILITY_V1_35B1A7A107C8243C"}
        refs = {str(item.get("task_id")): item for item in prior if isinstance(item, dict)}
        if not required.issubset(refs):
            raise RuntimeError("B02 is missing its accepted roadlink and geography cross-reference evidence")
        for task_id in required:
            ref = refs[task_id]
            with _connection(db_path) as conn:
                task_row = conn.execute("SELECT status,verdict,result_json FROM tasks WHERE id=?",
                                        (task_id,)).fetchone()
            if not task_row or task_row["status"] != "DONE" or task_row["verdict"] != "PASS":
                raise RuntimeError(f"B02 prior evidence task is not independently accepted: {task_id}")
            result = json.loads(task_row["result_json"] or "{}")
            artifact = result.get("artifact", {})
            if artifact.get("path") != ref.get("path") or artifact.get("sha256") != ref.get("sha256"):
                raise RuntimeError(f"B02 prior evidence link differs from saved task result: {task_id}")
            evidence_file = (project / str(ref.get("path", ""))).resolve(strict=True)
            if (not evidence_file.is_relative_to(project)
                    or hashlib.sha256(evidence_file.read_bytes()).hexdigest() != ref.get("sha256")):
                raise RuntimeError(f"B02 prior evidence artifact hash does not verify: {task_id}")

    bounds = saved.get("claim_boundaries", {})
    if (bounds.get("original_media_write_count") != 0
            or bounds.get("road_geometry_proven") is not False
            or bounds.get("routing_proven") is not False
            or bounds.get("physical_disc_compatibility_proven") is not False):
        raise RuntimeError("B02 claim boundaries are missing or overstate the result")
    return {"b02_independent_source_verification": "PASS",
            "b02_verified_source_count": source_checks,
            "b02_recomputed_aligned_blocks": recomputed_blocks,
            "b02_three_way_equal_blocks": verified_three_way_equal_blocks,
            "b02_prior_cross_reference_artifacts": len(prior),
            "b02_original_media_write_count": 0,
            "b02_road_geometry_proven": False,
            "b02_routing_proven": False}


def verify_b06_structure_catalog(catalog_path: Path, *, source_root: Path | None = None,
                                 project_root: Path | None = None,
                                 db_path: Path = DEFAULT_DB) -> dict[str, Any]:
    """Recheck catalog links, source families, bounded profiles, and unknowns."""
    from src.agent import coordinator_runtime

    path = Path(catalog_path).resolve(strict=True)
    project = Path(project_root or PROJECT_ROOT).resolve(strict=True)
    root = Path(source_root or coordinator_runtime.SOURCE_ROOT).resolve(strict=True)
    if not path.is_relative_to(project):
        raise RuntimeError("B06 catalog escaped the project")
    saved = json.loads(path.read_text(encoding="utf-8"))
    required_families = ("MP0", "FEA", "RD", "RL", "RT", "MG1", "MG2", "MG3", "CTY", "IL", "IOF")
    families = saved.get("families", [])
    if (saved.get("canonical_id") != "B06" or saved.get("status") != "PASS"
            or [row.get("suffix") for row in families] != list(required_families)):
        raise RuntimeError("B06 catalog is missing required NCDx families")
    if len(saved.get("unknown_register", {}).get("items", [])) < 1:
        raise RuntimeError("B06 catalog must retain unresolved format questions")

    references = saved.get("evidence_references", [])
    required_tasks = {"AUTO_NCDX_ROADLINK_PORTABILITY_V1_35CFAF6ED2C9EAF8",
        "AUTO_NCDX_GEOGRAPHY_PORTABILITY_V1_35B1A7A107C8243C",
        "AUTO_NCDX_DATA_FEA_BLOCK_ALIGNMENT_00ddf81e",
        "AUTO_NCDX_DATA_RD_BLOCK_ALIGNMENT_ca740496",
        "AUTO_NCDX_DATA_RT_BLOCK_ALIGNMENT_32a58e38"}
    refs = {str(row.get("task_id")): row for row in references if isinstance(row, dict)}
    b02_refs = [row for row in references if isinstance(row, dict)
                and str(row.get("task_id", "")).startswith("AUTO_MISSION_EXEC_B02_")]
    if not required_tasks.issubset(refs) or len(b02_refs) != 1:
        raise RuntimeError("B06 catalog is missing its B02, geography, roadlink, or profile sources")
    b02_ref = b02_refs[0]
    for task_id, ref in refs.items():
        with _connection(db_path) as conn:
            task = conn.execute("SELECT status,verdict,result_json FROM tasks WHERE id=?", (task_id,)).fetchone()
        if not task or task["status"] != "DONE" or task["verdict"] != "PASS":
            raise RuntimeError(f"B06 supporting task is no longer independently accepted: {task_id}")
        result = json.loads(task["result_json"] or "{}")
        artifact = result.get("artifact", {})
        if (str(artifact.get("path", "")).replace("\\", "/") != ref.get("path")
                or artifact.get("sha256") != ref.get("sha256")):
            raise RuntimeError(f"B06 direct task artifact reference changed: {task_id}")
        task_artifact = (project / str(ref.get("path", ""))).resolve(strict=True)
        support_path = (project / str(ref.get("evidence_path", ""))).resolve(strict=True)
        if (not task_artifact.is_relative_to(project) or not support_path.is_relative_to(project)
                or hashlib.sha256(task_artifact.read_bytes()).hexdigest() != ref.get("sha256")
                or hashlib.sha256(support_path.read_bytes()).hexdigest() != ref.get("evidence_sha256")):
            raise RuntimeError(f"B06 supporting evidence hash changed: {task_id}")

        if task_id == b02_ref["task_id"]:
            diff_path = support_path
            b02_proof = verify_b02_region_diff_records(diff_path, source_root=root,
                                                       project_root=project, db_path=db_path)
            if b02_proof.get("b02_independent_source_verification") != "PASS":
                raise RuntimeError("B06 B02 base evidence failed independent source replay")

    profile_task_ids = {"FEA": "AUTO_NCDX_DATA_FEA_BLOCK_ALIGNMENT_00ddf81e",
                        "RD": "AUTO_NCDX_DATA_RD_BLOCK_ALIGNMENT_ca740496",
                        "RT": "AUTO_NCDX_DATA_RT_BLOCK_ALIGNMENT_32a58e38"}
    profiled_source_count = 0
    for suffix in ("FEA", "RD", "RT"):
        family = next(row for row in families if row["suffix"] == suffix)
        if family.get("classification") != "manifest_bound_block_alignment_profile_only":
            raise RuntimeError(f"B06 overstates the {suffix} profile-only evidence")
        rows = family.get("regions", {})
        task_id = profile_task_ids[suffix]
        profile_path = (project / str(refs[task_id]["path"])).resolve(strict=True)
        profile_result = json.loads(profile_path.read_text(encoding="utf-8"))
        profile_observations = {str(item.get("region")): item
                                for item in profile_result.get("observations", [])}
        if set(rows) != set(profile_observations) or len(profile_observations) != 3:
            raise RuntimeError(f"B06 {suffix} does not include all three regions")
        for label, original in profile_observations.items():
            row = rows[label]
            relative = str(original.get("relative_path", "")).replace("\\", "/")
            parsed = Path(*relative.split("/"))
            if (row.get("relative_path") != relative
                    or row.get("meaning") != "bounded profile only; no record semantics assigned"
                    or row.get("profile_mode") != "BLOCK_ALIGNMENT"
                    or row.get("source_sha256") != original.get("inventory_sha256")
                    or row.get("sample_sha256") != original.get("sample_sha256")
                    or row.get("sample_bytes") != original.get("sample_bytes_total")):
                raise RuntimeError(f"B06 {suffix}/{label} scope or source path is wrong")
            source = (root / parsed).resolve(strict=True)
            before = source.stat()
            digest = hashlib.sha256()
            size = 0
            with source.open("rb") as handle:
                while chunk := handle.read(1024 * 1024):
                    digest.update(chunk)
                    size += len(chunk)
            after = source.stat()
            if (parsed.is_absolute() or ".." in parsed.parts
                    or not relative.casefold().startswith(("sw/", "opel "))
                    or not source.is_relative_to(root) or size != row.get("source_size_bytes")
                    or digest.hexdigest() != row.get("source_sha256")
                    or before.st_mtime_ns != after.st_mtime_ns):
                raise RuntimeError(f"B06 {suffix} source identity failed independent readback: {relative}")
            profiled_source_count += 1

    catalog_ref = saved.get("partial_mp0_header_index", {})
    b01_index = (project / str(catalog_ref.get("path", ""))).resolve(strict=True)
    if (catalog_ref.get("coverage_note") != "fixed MP0 header and TOC facts only; not the complete structure catalog"
            or hashlib.sha256(b01_index.read_bytes()).hexdigest() != catalog_ref.get("sha256")):
        raise RuntimeError("B06 must correctly label and hash the partial B01 header index")
    b01_proof = verify_b01_format_evidence_index(b01_index, source_root=root, project_root=project)
    if b01_proof.get("b01_verified_fact_count") != 12:
        raise RuntimeError("B06 partial B01 header reference did not independently verify")
    unknown = saved.get("unknown_register", {})
    unknown_path = (project / str(unknown.get("path", ""))).resolve(strict=True)
    if (not unknown_path.is_relative_to(project)
            or hashlib.sha256(unknown_path.read_bytes()).hexdigest() != unknown.get("sha256")):
        raise RuntimeError("B06 unresolved-format register hash/path failed")

    components = saved.get("related_components", {})
    ledger = (project / str(components.get("manifest_database_path", ""))).resolve(strict=True)
    ledger_digest = hashlib.sha256()
    if ledger.is_file():
        with ledger.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                ledger_digest.update(chunk)
    if (not ledger.is_relative_to(project) or not ledger.is_file()
            or ledger_digest.hexdigest() != components.get("manifest_database_sha256")
            or len(components.get("candidates", [])) != components.get("manifest_bound_candidate_count")):
        raise RuntimeError("B06 related-component manifest checksum/count failed")
    component_source_count = 0
    for row in components.get("candidates", []):
        relative = str(row.get("relative_path", ""))
        from pathlib import PurePosixPath
        parsed = PurePosixPath(relative)
        source = (root / Path(*parsed.parts)).resolve(strict=True)
        if (parsed.is_absolute() or ".." in parsed.parts or not relative.casefold().startswith("sw/")
                or not source.is_relative_to(root) or source.stat().st_size != row.get("size_bytes")):
            raise RuntimeError(f"B06 component candidate path/size failed: {relative}")
        digest = hashlib.sha256()
        with source.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
        if digest.hexdigest() != row.get("source_sha256"):
            raise RuntimeError(f"B06 component candidate SHA failed: {relative}")
        component_source_count += 1

    boundaries = saved.get("claim_boundaries", {})
    if (boundaries.get("original_media_write_count") != 0
            or boundaries.get("record_semantics_proven_for_all_families") is not False
            or boundaries.get("road_geometry_proven") is not False
            or boundaries.get("routing_proven") is not False
            or boundaries.get("db_0_assumptions_transferred") is not False):
        raise RuntimeError("B06 catalog is missing strict claim boundaries")
    return {"b06_independent_catalog_verification": "PASS",
        "b06_verified_family_count": len(families),
        "b06_verified_profile_source_count": profiled_source_count,
        "b06_verified_component_source_count": component_source_count,
        "b06_verified_evidence_reference_count": len(references),
        "b06_unknown_count": len(unknown.get("items", [])),
        "b06_original_media_write_count": 0,
        "b06_road_geometry_proven": False,
        "b06_routing_proven": False}


def verify_b07_index_integrity_report(report_path: Path, *, source_root: Path | None = None,
        project_root: Path | None = None, db_path: Path = DEFAULT_DB) -> dict[str, Any]:
    """Reparse B07 source indexes independently from the production reader."""
    import io
    import math
    import struct
    import zlib
    from pathlib import PurePosixPath
    from src.agent import coordinator_runtime

    project = Path(project_root or PROJECT_ROOT).resolve(strict=True)
    root = Path(source_root or coordinator_runtime.SOURCE_ROOT).resolve(strict=True)
    report_file = Path(report_path).resolve(strict=True)
    if not report_file.is_relative_to(project):
        raise RuntimeError("B07 integrity report escaped the project")
    saved = json.loads(report_file.read_text(encoding="utf-8"))
    if (saved.get("canonical_id") != "B07" or saved.get("status") != "PASS"
            or saved.get("experiment") != "ncdx_index_integrity_v1"):
        raise RuntimeError("B07 report has an unexpected schema or experiment identity")

    source_catalog = saved.get("source_catalog", {})
    task_id = str(source_catalog.get("task_id", ""))
    with _connection(db_path) as conn:
        b06 = conn.execute("SELECT status,runtime_task_id FROM mission_tasks WHERE canonical_id='B06'").fetchone()
        task = conn.execute("SELECT status,verdict,result_json FROM tasks WHERE id=?", (task_id,)).fetchone()
    if (not b06 or b06["status"] != "DONE" or b06["runtime_task_id"] != task_id
            or not task or task["status"] != "DONE" or task["verdict"] != "PASS"):
        raise RuntimeError("B07 source catalog is no longer an accepted B06 result")
    task_result = json.loads(task["result_json"] or "{}")
    b06_artifact = task_result.get("acceptance", {}).get("catalog_artifact", {})
    catalog_relative = str(b06_artifact.get("path", "")).replace("\\", "/")
    if (catalog_relative != source_catalog.get("path")
            or b06_artifact.get("sha256") != source_catalog.get("sha256")):
        raise RuntimeError("B07 report points to a different B06 source catalog")
    catalog_file = (project / catalog_relative).resolve(strict=True)
    if (not catalog_file.is_relative_to(project)
            or hashlib.sha256(catalog_file.read_bytes()).hexdigest() != source_catalog.get("sha256")):
        raise RuntimeError("B07 source catalog path or checksum failed independent readback")
    catalog = json.loads(catalog_file.read_text(encoding="utf-8"))
    families = {str(row.get("suffix")): row for row in catalog.get("families", [])}
    expected_regions = {label: (folder, prefix) for label, folder, prefix in coordinator_runtime.REGIONS}
    expected: dict[tuple[str, str], dict[str, Any]] = {}
    for suffix in ("CTY", "IL"):
        family = families.get(suffix, {})
        for region in expected_regions:
            entry = family.get("regions", {}).get(region)
            if isinstance(entry, dict):
                expected[(region, suffix)] = entry
    observations = saved.get("observations", [])
    keys = [(str(row.get("region", "")), str(row.get("suffix", "")))
            for row in observations if isinstance(row, dict)]
    if (len(observations) != 6 or len(set(keys)) != 6
            or set(keys) != set(expected) or set(expected) != {
                (region, suffix) for region in expected_regions for suffix in ("CTY", "IL")}):
        raise RuntimeError("B07 must cover exactly CTY and IL across all three accepted regions")

    def parse_raw(stream: Any, *, decode: bool) -> dict[str, Any]:
        stream.seek(0, 2)
        physical = stream.tell()
        stream.seek(0)
        header = stream.read(16)
        if len(header) != 16 or header[:4] != b"zip\x01":
            raise ValueError("bad fixed container marker/header")
        block_size, logical_size, opaque = struct.unpack_from("<III", header, 4)
        if not 0 < block_size <= 65536 or not 0 < logical_size <= 256 * 1024 * 1024:
            raise ValueError("unsafe declared block/logical size")
        count = math.ceil(logical_size / block_size)
        table_end = 16 + 4 * (count + 1)
        if count > 1_000_000 or table_end > physical:
            raise ValueError("offset table exceeds physical bounds")
        raw_table = stream.read(4 * (count + 1))
        if len(raw_table) != 4 * (count + 1):
            raise ValueError("truncated offset table")
        offsets = struct.unpack(f"<{count + 1}I", raw_table)
        if offsets[0] != table_end or offsets[-1] != physical:
            raise ValueError("absolute offset references do not exactly span payload")
        previous = offsets[0]
        for offset in offsets[1:]:
            if offset <= previous or offset - previous > 1_048_576:
                raise ValueError("absolute offset is non-monotonic or compressed span is too large")
            previous = offset
        result = {"physical_size_bytes": physical, "block_size_bytes": block_size,
            "logical_size_bytes": logical_size, "opaque_header_u32_le": opaque,
            "block_count": count, "offset_count": len(offsets),
            "offsets_sha256": hashlib.sha256(raw_table).hexdigest(),
            "offsets_head": list(offsets[:4]), "offsets_tail": list(offsets[-4:])}
        if not decode:
            return result
        logical_offset = 0
        decoded_digest = hashlib.sha256()
        lengths: list[int] = []
        for start, end in zip(offsets, offsets[1:]):
            expected_length = min(block_size, logical_size - logical_offset)
            stream.seek(start)
            compressed = stream.read(end - start)
            inflater = zlib.decompressobj()
            decoded = inflater.decompress(compressed, expected_length + 1)
            if (not inflater.eof or inflater.unused_data or inflater.unconsumed_tail
                    or len(decoded) != expected_length):
                raise ValueError("compressed block violates independently calculated logical length")
            decoded_digest.update(decoded)
            lengths.append(len(decoded))
            logical_offset += len(decoded)
        if logical_offset != logical_size:
            raise ValueError("decoded block lengths do not equal declared logical size")
        result.update({"decoded_size_bytes": logical_offset,
            "decoded_sha256": decoded_digest.hexdigest(),
            "first_decoded_block_bytes": lengths[0], "last_decoded_block_bytes": lengths[-1]})
        return result

    verified = 0
    for row in observations:
        region, suffix = str(row["region"]), str(row["suffix"])
        catalog_entry = expected[(region, suffix)]
        relative = str(row.get("relative_path", "")).replace("\\", "/")
        folder, prefix = expected_regions[region]
        if (relative != (folder / f"{prefix}.{suffix}").as_posix()
                or relative != str(catalog_entry.get("relative_path", "")).replace("\\", "/")
                or row.get("source_sha256") != catalog_entry.get("source_sha256")
                or row.get("source_size_bytes") != catalog_entry.get("source_size_bytes")):
            raise RuntimeError("B07 source is not the exact catalog-bound regional input")
        parsed = PurePosixPath(relative)
        source = (root / Path(*parsed.parts)).resolve(strict=True)
        if parsed.is_absolute() or ".." in parsed.parts or not source.is_relative_to(root):
            raise RuntimeError("B07 source escaped the read-only root")
        before = source.stat()
        with source.open("rb") as handle:
            file_digest = hashlib.sha256()
            while chunk := handle.read(1024 * 1024):
                file_digest.update(chunk)
            handle.seek(0)
            actual = parse_raw(handle, decode=True)
        after = source.stat()
        if (file_digest.hexdigest() != row.get("source_sha256")
                or file_digest.hexdigest() != catalog_entry.get("source_sha256")
                or before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns
                or before.st_size != row.get("source_size_bytes")
                or any(actual.get(key) != row.get(key) for key in actual)):
            raise RuntimeError(f"B07 independent raw parser disagrees for {relative}")
        verified += 1

    controls = saved.get("invalid_reference_negative_controls", [])
    expected_controls = {"first_offset_before_table_end", "zero_length_block_reference",
                         "last_offset_before_eof"}
    if (len(controls) != 3 or {str(row.get("case")) for row in controls} != expected_controls
            or any(row.get("rejected") is not True for row in controls)):
        raise RuntimeError("B07 production reader did not reject the fixed malformed-reference controls")
    block = b"N" * 64
    compressed = zlib.compress(block)
    table_end = 24
    physical = table_end + len(compressed)
    base = bytearray(struct.pack("<4sIII", b"zip\x01", 64, 64, 0xA5A5A5A5))
    base.extend(struct.pack("<II", table_end, physical))
    base.extend(compressed)
    mutations = [("first_offset_before_table_end", 16, table_end - 1),
                 ("zero_length_block_reference", 20, table_end),
                 ("last_offset_before_eof", 20, physical - 1)]
    rejected: set[str] = set()
    for name, offset, value in mutations:
        changed = bytearray(base)
        struct.pack_into("<I", changed, offset, value)
        try:
            parse_raw(io.BytesIO(changed), decode=False)
        except ValueError:
            rejected.add(name)
    if rejected != expected_controls:
        raise RuntimeError("independent verifier accepted a malformed absolute-offset control")

    interpretation = saved.get("interpretation", {})
    if (saved.get("source_count") != 6 or saved.get("independent_suffix_count") != 2
            or saved.get("valid_source_absolute_offset_error_count") != 0
            or saved.get("invalid_reference_negative_control_rejection_count") != 3
            or interpretation.get("road_geometry_proven") is not False
            or interpretation.get("routing_proven") is not False
            or interpretation.get("original_media_write_count") != 0
            or interpretation.get("reference_scope") !=
                "absolute compressed-block offsets only; semantic record references remain UNKNOWN"):
        raise RuntimeError("B07 report is incomplete or overstates container-index evidence")
    return {"b07_independent_raw_index_verification": "PASS",
        "b07_verified_source_count": verified, "b07_verified_suffixes": ["CTY", "IL"],
        "b07_invalid_reference_controls_rejected": len(rejected),
        "b07_valid_source_absolute_offset_error_count": 0,
        "b07_original_media_write_count": 0,
        "b07_road_geometry_proven": False, "b07_routing_proven": False}


def reopen_waiting_local_mission_after_handler_added(canonical_id: str, *,
        expected_runtime_task_id: str, evidence: dict[str, Any],
        db_path: Path = DEFAULT_DB,
        resolve_quota_after_local_handler: bool = False) -> dict[str, Any]:
    """Atomically retire one obsolete local-handler wait and reopen its goal.

    This is deliberately narrow: it only accepts the supplied exact parked
    Mission Pack executor whose saved failure says no deterministic handler
    existed. A quota waiter is reopened only when the caller explicitly proves
    that the exact missing handler and its independent tests now exist locally.
    """
    if not isinstance(evidence, dict) or evidence.get("verifier") != "deterministic_handler_registry" or evidence.get("verdict") != "PASS":
        raise ValueError("reopening a mission requires evidence of a deterministic local handler")
    ensure_schema(db_path)
    now = _utc_text()
    prior: dict[str, Any] = {}
    attempts = 0
    with _connection(db_path) as conn:
        conn.commit()
        conn.execute("BEGIN IMMEDIATE")
        mission = conn.execute("SELECT status,runtime_task_id,evidence_json,status_reason FROM mission_tasks WHERE canonical_id=?",
                               (canonical_id,)).fetchone()
        allowed_mission_statuses = {"WAITING_LOCAL", "WAITING_CODEX"}
        if resolve_quota_after_local_handler and canonical_id in {"B03", "E03", "B06", "B07"}:
            allowed_mission_statuses.add("WAITING_CODEX_QUOTA")
        if (not mission or mission["status"] not in allowed_mission_statuses
                or mission["runtime_task_id"] != expected_runtime_task_id):
            conn.rollback()
            return {"reopened": False, "reason": "mission no longer matches the exact legacy local wait"}
        runtime = conn.execute("SELECT status,agent,budget_json,result_json,attempts FROM tasks WHERE id=?",
                               (expected_runtime_task_id,)).fetchone()
        if not runtime or runtime["status"] != "WAITING_LOCAL" or runtime["agent"] != "mission-pack-executor":
            conn.rollback()
            return {"reopened": False, "reason": "runtime task is not the parked unleased mission executor"}
        budget = json.loads(runtime["budget_json"] or "{}")
        result = json.loads(runtime["result_json"] or "{}")
        if budget.get("mission_pack_task") != canonical_id or "No deterministic handler exists" not in str(result.get("reason", "")):
            conn.rollback()
            return {"reopened": False, "reason": "saved runtime result does not prove the known missing-handler defect"}
        try:
            prior = json.loads(mission["evidence_json"] or "{}")
        except json.JSONDecodeError:
            prior = {"previous_evidence_text": str(mission["evidence_json"] or "")[:1000]}
        quota_resolution = mission["status"] == "WAITING_CODEX_QUOTA"
        if quota_resolution:
            serialized_prior = json.dumps(prior, ensure_ascii=False)
            if (not resolve_quota_after_local_handler or canonical_id not in {"B03", "E03", "B06", "B07"}
                    or not str(mission["status_reason"]).startswith("Daily Codex budget exhausted")
                    or "No deterministic handler exists" not in serialized_prior
                    or evidence.get("local_tests_passed") is not True
                    or evidence.get("codex_attempted") is not False):
                conn.rollback()
                return {"reopened": False,
                    "reason": "quota wait is not the exact no-handler failure or lacks local test/no-Codex evidence"}
        attempts = int(runtime["attempts"])
        previous_mission_status = str(mission["status"])
        result["superseded"] = {"reason": "A deterministic local handler was added and independently tested; the previous no-handler execution is obsolete.",
            "evidence": evidence, "previous_status": str(runtime["status"]),
            "previous_mission_status": previous_mission_status,
            "quota_wait_resolved_by_handler": quota_resolution, "transitioned_utc": now}
        updated = conn.execute("UPDATE tasks SET status='SUPERSEDED',verdict='SUPERSEDED',result_json=?,"
            "lease_owner=NULL,lease_until=NULL,heartbeat_utc=NULL,updated_utc=? WHERE id=? AND status='WAITING_LOCAL'",
            (json.dumps(result, ensure_ascii=False, sort_keys=True), now, expected_runtime_task_id))
        if updated.rowcount != 1:
            conn.rollback()
            return {"reopened": False, "reason": "runtime state changed during reconciliation"}
        conn.execute("DELETE FROM leases WHERE task_id=?", (expected_runtime_task_id,))
        mission_update = conn.execute("UPDATE mission_tasks SET status='READY',runtime_task_id=NULL,evidence_json=?,"
            "status_reason=?,updated_utc=? WHERE canonical_id=? AND status=? AND runtime_task_id=?",
            (json.dumps({"verifier": "deterministic_handler_registry", "verdict": "PASS",
                         "previous_evidence": prior, "superseded_runtime_task_id": expected_runtime_task_id,
                         "handler_evidence": evidence}, ensure_ascii=False, sort_keys=True),
             "The deterministic local handler is available; the previous no-handler wait is preserved as historical state.",
             now, canonical_id, previous_mission_status, expected_runtime_task_id))
        if mission_update.rowcount != 1:
            conn.rollback()
            return {"reopened": False, "reason": "mission changed during the atomic handler migration"}
    if db_path.resolve() == DEFAULT_DB.resolve():
        from src.agent import state_store
        state_store._sync_task_db(expected_runtime_task_id, "SUPERSEDED", "SUPERSEDED", attempts)
    return {"reopened": True, "canonical_id": canonical_id,
            "superseded_runtime_task_id": expected_runtime_task_id,
            "status": "READY", "codex_attempted": False}


def recover_exact_b03_after_artifact_allowlist_fix(*, expected_runtime_task_id: str,
        evidence: dict[str, Any], db_path: Path = DEFAULT_DB) -> dict[str, Any]:
    """Resume B03 after its real scan produced a valid artifact that registration rejected."""
    required_id = "AUTO_MISSION_EXEC_B03_557FA191"
    if (expected_runtime_task_id != required_id or not isinstance(evidence, dict)
            or evidence.get("verifier") != "deterministic_handler_registry"
            or evidence.get("verdict") != "PASS"
            or evidence.get("local_tests_passed") is not True
            or evidence.get("codex_attempted") is not False):
        return {"recovered": False, "reason": "B03 recovery requires the exact failed runtime and local no-Codex test evidence"}
    ensure_schema(db_path)
    with _connection(db_path) as conn:
        mission_preflight = conn.execute(
            "SELECT status,runtime_task_id FROM mission_tasks WHERE canonical_id='B03'").fetchone()
        runtime_preflight = conn.execute(
            "SELECT status FROM tasks WHERE id=?", (required_id,)).fetchone()
    if (not mission_preflight or mission_preflight["status"] != "BLOCKED"
            or mission_preflight["runtime_task_id"] != required_id
            or not runtime_preflight or runtime_preflight["status"] != "BLOCKED"):
        return {"recovered": False, "reason": "B03 mission/runtime no longer matches the exact blocked attempt"}
    inventory_path = PROJECT_ROOT / "firmware" / "binary-format-inventory.json"
    from src.agent.b03_inventory_verifier import verify_b03_binary_format_inventory
    proof = verify_b03_binary_format_inventory(inventory_path)
    artifact_hash = hashlib.sha256(inventory_path.read_bytes()).hexdigest()
    now = _utc_text()
    attempts = 0
    with _connection(db_path) as conn:
        conn.row_factory = sqlite3.Row
        conn.commit()
        conn.execute("BEGIN IMMEDIATE")
        mission = conn.execute("SELECT status,runtime_task_id,evidence_json,status_reason FROM mission_tasks "
                               "WHERE canonical_id='B03'").fetchone()
        runtime = conn.execute("SELECT status,agent,budget_json,result_json,attempts FROM tasks WHERE id=?",
                               (required_id,)).fetchone()
        if (not mission or mission["status"] != "BLOCKED"
                or mission["runtime_task_id"] != required_id or not runtime
                or runtime["status"] != "BLOCKED" or runtime["agent"] != "mission-pack-executor"):
            conn.rollback()
            return {"recovered": False, "reason": "B03 mission/runtime no longer matches the exact blocked attempt"}
        budget = json.loads(runtime["budget_json"] or "{}")
        result = json.loads(runtime["result_json"] or "{}")
        error_text = str(result.get("error", ""))
        expected_error_path = str(inventory_path.resolve())
        if (budget.get("mission_pack_task") != "B03"
                or "artifact path escaped the manager work area" not in error_text
                or expected_error_path.replace("\\", "\\\\") not in error_text):
            conn.rollback()
            return {"recovered": False, "reason": "saved B03 failure is not the exact artifact-registration allowlist error"}
        try:
            previous_evidence = json.loads(mission["evidence_json"] or "{}")
        except json.JSONDecodeError:
            previous_evidence = {"previous_evidence_text": str(mission["evidence_json"] or "")[:1000]}
        attempts = int(runtime["attempts"])
        result["recovered_artifact"] = {"path": "firmware/binary-format-inventory.json",
            "sha256": artifact_hash, "verification": proof, "registration_retry_required": True,
            "recovered_utc": now}
        result["superseded"] = {"reason": "Exact B03 run was blocked only when registering its existing artifact; source-bound independent readback passed.",
            "previous_status": "BLOCKED", "evidence": evidence, "transitioned_utc": now}
        changed_task = conn.execute(
            "UPDATE tasks SET status='SUPERSEDED',verdict='SUPERSEDED',result_json=?,"
            "lease_owner=NULL,lease_until=NULL,heartbeat_utc=NULL,updated_utc=? "
            "WHERE id=? AND status='BLOCKED'",
            (json.dumps(result, ensure_ascii=False, sort_keys=True), now, required_id))
        if changed_task.rowcount != 1:
            conn.rollback()
            return {"recovered": False, "reason": "B03 runtime state changed during atomic recovery"}
        conn.execute("DELETE FROM leases WHERE task_id=?", (required_id,))
        changed_mission = conn.execute(
            "UPDATE mission_tasks SET status='READY',runtime_task_id=NULL,evidence_json=?,"
            "status_reason=?,updated_utc=? WHERE canonical_id='B03' AND status='BLOCKED' AND runtime_task_id=?",
            (json.dumps({"verifier": "exact_b03_artifact_allowlist_recovery", "verdict": "PASS",
                         "previous_evidence": previous_evidence, "superseded_runtime_task_id": required_id,
                         "artifact_sha256": artifact_hash, "independent_verification": proof,
                         "handler_evidence": evidence}, ensure_ascii=False, sort_keys=True),
             "B03 artifact was source-verified; requeue only to register the existing artifact under the corrected exact allowlist.",
             now, required_id))
        if changed_mission.rowcount != 1:
            conn.rollback()
            return {"recovered": False, "reason": "B03 mission changed during atomic recovery"}
    if db_path.resolve() == DEFAULT_DB.resolve():
        from src.agent import state_store
        state_store._sync_task_db(required_id, "SUPERSEDED", "SUPERSEDED", attempts)
    return {"recovered": True, "canonical_id": "B03",
        "superseded_runtime_task_id": required_id, "status": "READY",
        "artifact_sha256": artifact_hash, "verification": proof, "codex_attempted": False}


def recover_exact_b06_after_verifier_rule_fix(*, expected_runtime_task_id: str,
        evidence: dict[str, Any], db_path: Path = DEFAULT_DB) -> dict[str, Any]:
    """Retire the one B06 failure caused by the superseded suffix-path verifier rule."""
    required_id = "AUTO_MISSION_EXEC_B06_55DFE153"
    required_diagnostic = "B06 RD/SW scope or source path is wrong"
    if (expected_runtime_task_id != required_id
            or not isinstance(evidence, dict)
            or evidence.get("verifier") != "deterministic_handler_registry"
            or evidence.get("verdict") != "PASS"
            or evidence.get("independent_verifier") != "mission_pack.verify_b06_structure_catalog"
            or evidence.get("local_catalog_readback") != "PASS"
            or evidence.get("codex_attempted") is not False):
        raise ValueError("B06 verifier recovery requires its exact runtime failure and fresh local verification proof")
    ensure_schema(db_path)
    now = _utc_text()
    with _connection(db_path) as conn:
        conn.commit()
        conn.execute("BEGIN IMMEDIATE")
        mission = conn.execute("SELECT status,runtime_task_id,evidence_json FROM mission_tasks WHERE canonical_id='B06'").fetchone()
        runtime = conn.execute("SELECT status,agent,budget_json,result_json,attempts FROM tasks WHERE id=?",
                               (required_id,)).fetchone()
        if (not mission or mission["status"] != "BLOCKED"
                or mission["runtime_task_id"] != required_id
                or not runtime or runtime["status"] != "BLOCKED"
                or runtime["agent"] != "mission-pack-executor"):
            conn.rollback()
            return {"recovered": False, "reason": "B06 mission/runtime no longer matches the exact verifier failure"}
        budget = json.loads(runtime["budget_json"] or "{}")
        result = json.loads(runtime["result_json"] or "{}")
        if (budget.get("mission_pack_task") != "B06"
                or required_diagnostic not in str(result.get("error", ""))):
            conn.rollback()
            return {"recovered": False, "reason": "saved B06 failure does not match the corrected path rule"}
        try:
            previous = json.loads(mission["evidence_json"] or "{}")
        except json.JSONDecodeError:
            previous = {"previous_evidence_text": str(mission["evidence_json"] or "")[:1000]}
        attempts = int(runtime["attempts"])
        result["superseded"] = {"reason": "The independent B06 verifier now follows manifest-bound source paths for each suffix; a fresh readback passed before retry.",
            "diagnostic": required_diagnostic, "evidence": evidence, "transitioned_utc": now}
        changed = conn.execute("UPDATE tasks SET status='SUPERSEDED',verdict='SUPERSEDED',result_json=?,"
            "lease_owner=NULL,lease_until=NULL,heartbeat_utc=NULL,updated_utc=? WHERE id=? AND status='BLOCKED'",
            (json.dumps(result, ensure_ascii=False, sort_keys=True), now, required_id))
        if changed.rowcount != 1:
            conn.rollback()
            return {"recovered": False, "reason": "B06 runtime state changed during recovery"}
        conn.execute("DELETE FROM leases WHERE task_id=?", (required_id,))
        changed_mission = conn.execute("UPDATE mission_tasks SET status='READY',runtime_task_id=NULL,"
            "evidence_json=?,status_reason=?,updated_utc=? WHERE canonical_id='B06' AND status='BLOCKED' AND runtime_task_id=?",
            (json.dumps({"verifier": "deterministic_handler_registry", "verdict": "PASS",
                         "previous_evidence": previous, "superseded_runtime_task_id": required_id,
                         "handler_evidence": evidence}, ensure_ascii=False, sort_keys=True),
             "The B06 manifest-bound source-path verifier was corrected and independently replayed; the prior attempt is superseded.",
             now, required_id))
        if changed_mission.rowcount != 1:
            conn.rollback()
            return {"recovered": False, "reason": "B06 mission state changed during recovery"}
    if db_path.resolve() == DEFAULT_DB.resolve():
        from src.agent import state_store
        state_store._sync_task_db(required_id, "SUPERSEDED", "SUPERSEDED", attempts)
    return {"recovered": True, "canonical_id": "B06", "status": "READY",
            "superseded_runtime_task_id": required_id, "codex_attempted": False}


def recover_exact_b07_after_manifest_source_selection_fix(*, expected_runtime_task_id: str,
        evidence: dict[str, Any], db_path: Path = DEFAULT_DB) -> dict[str, Any]:
    """Supersede the one B07 attempt that incorrectly treated raw MG3 as a container."""
    required_id = "AUTO_MISSION_EXEC_B07_AE0845D4"
    diagnostic = "container does not begin with the observed zip"
    if (expected_runtime_task_id != required_id or not isinstance(evidence, dict)
            or evidence.get("verifier") != "deterministic_handler_registry"
            or evidence.get("verdict") != "PASS"
            or evidence.get("independent_verifier") != "project_director.verify_b07_manifest_source_selection"
            or evidence.get("fresh_source_readback") != "PASS"
            or evidence.get("codex_attempted") is not False):
        raise ValueError("B07 recovery requires fresh independently verified manifest-bound container evidence")
    ensure_schema(db_path)
    now = _utc_text()
    with _connection(db_path) as conn:
        conn.commit()
        conn.execute("BEGIN IMMEDIATE")
        mission = conn.execute("SELECT status,runtime_task_id,evidence_json FROM mission_tasks WHERE canonical_id='B07'").fetchone()
        runtime = conn.execute("SELECT status,agent,budget_json,result_json,attempts FROM tasks WHERE id=?",
                               (required_id,)).fetchone()
        if (not mission or mission["status"] != "BLOCKED" or mission["runtime_task_id"] != required_id
                or not runtime or runtime["status"] != "BLOCKED"
                or runtime["agent"] != "mission-pack-executor"):
            conn.rollback()
            return {"recovered": False, "reason": "B07 mission/runtime no longer matches the exact failed source selection"}
        budget = json.loads(runtime["budget_json"] or "{}")
        result = json.loads(runtime["result_json"] or "{}")
        if (budget.get("mission_pack_task") != "B07" or diagnostic not in str(result.get("error", ""))):
            conn.rollback()
            return {"recovered": False, "reason": "saved B07 diagnostic differs from the corrected source-family selection"}
        try:
            previous = json.loads(mission["evidence_json"] or "{}")
        except json.JSONDecodeError:
            previous = {"previous_evidence_text": str(mission["evidence_json"] or "")[:1000]}
        attempts = int(runtime["attempts"])
        result["superseded"] = {"reason": "B07 now selects two B06-confirmed zip\x01 families; MG3 raw files are excluded.",
            "diagnostic": diagnostic, "evidence": evidence, "transitioned_utc": now}
        changed = conn.execute("UPDATE tasks SET status='SUPERSEDED',verdict='SUPERSEDED',result_json=?,"
            "lease_owner=NULL,lease_until=NULL,heartbeat_utc=NULL,updated_utc=? WHERE id=? AND status='BLOCKED'",
            (json.dumps(result, ensure_ascii=False, sort_keys=True), now, required_id))
        if changed.rowcount != 1:
            conn.rollback()
            return {"recovered": False, "reason": "B07 runtime changed during atomic source-selection recovery"}
        conn.execute("DELETE FROM leases WHERE task_id=?", (required_id,))
        changed_mission = conn.execute("UPDATE mission_tasks SET status='READY',runtime_task_id=NULL,"
            "evidence_json=?,status_reason=?,updated_utc=? WHERE canonical_id='B07' AND status='BLOCKED' AND runtime_task_id=?",
            (json.dumps({"verifier": "deterministic_handler_registry", "verdict": "PASS",
                         "previous_evidence": previous, "superseded_runtime_task_id": required_id,
                         "handler_evidence": evidence}, ensure_ascii=False, sort_keys=True),
             "The B07 source selector now follows the accepted container marker; prior invalid-source attempt is superseded.",
             now, required_id))
        if changed_mission.rowcount != 1:
            conn.rollback()
            return {"recovered": False, "reason": "B07 mission changed during atomic source-selection recovery"}
    if db_path.resolve() == DEFAULT_DB.resolve():
        from src.agent import state_store
        state_store._sync_task_db(required_id, "SUPERSEDED", "SUPERSEDED", attempts)
    return {"recovered": True, "canonical_id": "B07", "status": "READY",
            "superseded_runtime_task_id": required_id, "codex_attempted": False}


def planner_candidates(db_path: Path = DEFAULT_DB, *, limit: int = 8) -> list[dict[str, Any]]:
    """Return dependency-ready, nonterminal canonical proposals for a compact Director prompt."""
    with _connection(db_path) as conn:
        rows = [dict(row) for row in conn.execute(
            "SELECT * FROM mission_tasks ORDER BY priority,canonical_id")]
    status_by_id = {str(row["canonical_id"]): str(row["status"]) for row in rows}
    topic_rank = {"A": 0, "B": 1, "C": 2, "D": 3, "E": 4, "Q": 5}
    rows.sort(key=lambda row: (topic_rank.get(str(row["canonical_id"])[0:1], 9),
                               int(row["priority"]), str(row["canonical_id"])))
    ready: list[dict[str, Any]] = []
    for row in rows:
        if row["status"] not in {"PROPOSED", "READY"}:
            continue
        dependencies = json.loads(row["dependencies_json"] or "[]")
        if any(status_by_id.get(dep) != "DONE" for dep in dependencies):
            continue
        try:
            evidence_revision = json.loads(row["evidence_json"] or "{}")
        except json.JSONDecodeError:
            evidence_revision = {"invalid_evidence_sha256": hashlib.sha256(
                str(row["evidence_json"] or "").encode("utf-8")).hexdigest()}
        revision_payload = {"status": row["status"],
            "status_reason": row["status_reason"], "evidence": evidence_revision}
        revision = hashlib.sha256(json.dumps(revision_payload, sort_keys=True, ensure_ascii=False,
            separators=(",", ":")).encode("utf-8")).hexdigest()[:16]
        ready.append({"id": row["canonical_id"], "phase": row["phase"],
                      "priority": row["priority"], "objective": row["objective"],
                      "acceptance_criteria": json.loads(row["acceptance_json"]),
                      "executor_preference": row["executor_preference"],
                      "evidence_revision": revision})
        if len(ready) >= max(1, limit):
            break
    return ready


def reconcile_runtime_missions(db_path: Path = DEFAULT_DB) -> list[dict[str, Any]]:
    """Atomically repair RUNNING mission rows whose runtime task is already parked.

    Runtime completion is deliberately not inferred here: DONE still requires the
    existing independent artifact verifier.  This reconciliation only removes a
    false RUNNING state and preserves the runtime result as diagnostic evidence.
    """
    ensure_schema(db_path)
    changes: list[dict[str, Any]] = []
    terminal_mapping = {
        "MISSING": "WAITING_LOCAL",
        "WAITING_LOCAL": "WAITING_LOCAL",
        "WAITING_CODEX": "WAITING_CODEX",
        "WAITING_CODEX_QUOTA": "WAITING_CODEX_QUOTA",
        "WAITING_EXTERNAL": "WAITING_EXTERNAL",
        "BLOCKED": "BLOCKED",
        "SUPERSEDED": "SUPERSEDED",
        "CANCELLED": "BLOCKED",
    }
    with _connection(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        has_tasks = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='tasks'").fetchone()
        if not has_tasks:
            return changes
        rows = conn.execute("""SELECT m.canonical_id,m.runtime_task_id,m.status_reason,m.evidence_json,
                                    t.status AS runtime_status,t.agent,t.budget_json,t.result_json,
                                    t.updated_utc AS runtime_updated_utc
                             FROM mission_tasks AS m
                             LEFT JOIN tasks AS t ON t.id=m.runtime_task_id
                             WHERE m.status='RUNNING' AND m.runtime_task_id IS NOT NULL
                             ORDER BY m.canonical_id""").fetchall()
        for row in rows:
            runtime_status = str(row["runtime_status"] or "MISSING")
            if runtime_status not in terminal_mapping:
                continue
            try:
                budget = json.loads(row["budget_json"] or "{}") if row["budget_json"] else {}
            except json.JSONDecodeError:
                budget = {}
            # A stale or accidentally cross-linked runtime ID must never change
            # the state of a different mission.
            if row["runtime_status"] is not None and (
                    row["agent"] != "mission-pack-executor"
                    or budget.get("mission_pack_task") != row["canonical_id"]):
                continue
            try:
                prior_evidence = json.loads(row["evidence_json"] or "{}")
            except json.JSONDecodeError:
                prior_evidence = {"prior_evidence_text": str(row["evidence_json"] or "")[:1000]}
            if not isinstance(prior_evidence, dict):
                prior_evidence = {"prior_evidence": prior_evidence}
            try:
                result = json.loads(row["result_json"] or "{}") if row["result_json"] else {}
            except json.JSONDecodeError:
                result = {"invalid_result_json_sha256": hashlib.sha256(
                    str(row["result_json"] or "").encode("utf-8")).hexdigest()}
            if not isinstance(result, dict):
                result = {"runtime_result": result}
            new_status = terminal_mapping[runtime_status]
            reason = (str(result.get("reason") or result.get("error") or "")[:800]
                      if runtime_status != "MISSING" else
                      "Runtime task row is missing; mission cannot remain RUNNING.")
            evidence = {
                **prior_evidence,
                "verifier": "atomic_runtime_mission_reconciler",
                "verdict": "STATE_RECONCILED",
                "prior_mission_status": "RUNNING",
                "runtime_task_id": row["runtime_task_id"],
                "runtime_status": runtime_status,
                "runtime_updated_utc": row["runtime_updated_utc"],
                "runtime_result": result,
                "completion_inferred": False,
            }
            cursor = conn.execute("""UPDATE mission_tasks
                SET status=?,status_reason=?,evidence_json=?,updated_utc=?
                WHERE canonical_id=? AND status='RUNNING' AND runtime_task_id=?""",
                (new_status, reason, json.dumps(evidence, ensure_ascii=False, sort_keys=True),
                 _utc_text(), row["canonical_id"], row["runtime_task_id"]))
            if cursor.rowcount == 1:
                changes.append({"canonical_id": row["canonical_id"],
                                "runtime_task_id": row["runtime_task_id"],
                                "from": "RUNNING", "to": new_status,
                                "runtime_status": runtime_status, "reason": reason})
    return changes


def planner_diagnosis(db_path: Path = DEFAULT_DB) -> dict[str, Any]:
    """Describe why unfinished canonical goals do not currently produce a task."""
    with _connection(db_path) as conn:
        rows = [dict(row) for row in conn.execute(
            "SELECT canonical_id,status,dependencies_json,runtime_task_id,status_reason "
            "FROM mission_tasks ORDER BY priority,canonical_id")]
    status_by_id = {str(row["canonical_id"]): str(row["status"]) for row in rows}
    unfinished = [row for row in rows if row["status"] not in {"DONE", "SUPERSEDED"}]
    blocked: list[dict[str, Any]] = []
    for row in unfinished:
        if row["status"] not in {"PROPOSED", "READY"}:
            continue
        try:
            dependencies = json.loads(row["dependencies_json"] or "[]")
        except json.JSONDecodeError:
            dependencies = ["<invalid-dependency-json>"]
        unresolved = [{"id": dependency, "status": status_by_id.get(dependency, "MISSING")}
                      for dependency in dependencies if status_by_id.get(dependency) != "DONE"]
        if unresolved:
            blocked.append({"canonical_id": row["canonical_id"],
                            "dependencies": unresolved})
    waiting_counts: dict[str, int] = {}
    for row in unfinished:
        status = str(row["status"])
        if status.startswith("WAITING_") or status in {"BLOCKED", "RUNNING"}:
            waiting_counts[status] = waiting_counts.get(status, 0) + 1
    if not unfinished:
        decision = "NO_UNMET_TASKS"
        message = "Усі канонічні цілі завершені або явно замінені."
    elif blocked:
        decision = "WAITING_DEPENDENCIES"
        first = blocked[0]
        dep = first["dependencies"][0]
        message = (f"Немає готових місій: {first['canonical_id']} очікує "
                   f"{dep['id']} [{dep['status']}]; незалежні напрями плануються окремо.")
    else:
        decision = "WAITING_EXECUTOR_OR_EVIDENCE"
        message = "Незавершені цілі є, але зараз немає місії з виконуваною залежністю."
    return {"decision": decision, "message": message,
            "unfinished_count": len(unfinished), "dependency_blocked_count": len(blocked),
            "dependency_blocked": blocked[:20], "waiting_counts": waiting_counts}


def reopen_legacy_codex_waiters(db_path: Path = DEFAULT_DB) -> list[str]:
    """Return old Codex-gated mission rows to the local Director without losing evidence."""
    moment = _utc_text(_utcnow())
    with _connection(db_path) as conn:
        rows = conn.execute("SELECT canonical_id,evidence_json FROM mission_tasks WHERE status='WAITING_CODEX'").fetchall()
        for row in rows:
            try:
                evidence = json.loads(row["evidence_json"] or "{}")
            except json.JSONDecodeError:
                evidence = {"prior_evidence_text": str(row["evidence_json"] or "")[:1000]}
            if not isinstance(evidence, dict):
                evidence = {"prior_evidence": evidence}
            history = list(evidence.get("local_first_history", []))
            history.append({"event": "reopened_for_local_first", "prior_status": "WAITING_CODEX",
                            "created_utc": moment})
            evidence["local_first_history"] = history[-10:]
            conn.execute("UPDATE mission_tasks SET status='PROPOSED',status_reason=?,evidence_json=?,updated_utc=? WHERE canonical_id=?",
                ("Returned to local Director; Codex is an escalation after a verified local failure.",
                 json.dumps(evidence, ensure_ascii=False), moment, row["canonical_id"]))
    return [str(row["canonical_id"]) for row in rows]


def planner_tick(db_path: Path = DEFAULT_DB, *, now: datetime | None = None,
                 cooldown_seconds: int = 180, force: bool = False) -> dict[str, Any]:
    """Persist a rate-limited planning opportunity with a no-repeat fingerprint."""
    reconcile_runtime_missions(db_path)
    candidates = planner_candidates(db_path)
    diagnosis = planner_diagnosis(db_path)
    fingerprint = hashlib.sha256(json.dumps(candidates, sort_keys=True, ensure_ascii=False,
                                             separators=(",", ":")).encode("utf-8")).hexdigest()
    moment = now or _utcnow()
    with _connection(db_path) as conn:
        prior = conn.execute("SELECT created_utc FROM mission_planner_ticks ORDER BY id DESC LIMIT 1").fetchone()
        seen = conn.execute("SELECT 1 FROM mission_planner_ticks WHERE candidate_fingerprint=?",
                            (fingerprint,)).fetchone() is not None
        director_task_id = "AUTO_MISSION_DIRECTOR_" + fingerprint[:16].upper()
        try:
            director_task_exists = conn.execute("SELECT 1 FROM tasks WHERE id=?",
                                                (director_task_id,)).fetchone() is not None
        except sqlite3.OperationalError:
            # Some isolated planner stores contain only Mission Pack tables.
            # A tick without its durable runtime task must remain recoverable.
            director_task_exists = False
        wait_remaining = 0
        if prior and not force:
            elapsed = moment - datetime.fromisoformat(str(prior[0]))
            wait_remaining = max(0, cooldown_seconds - int(elapsed.total_seconds()))
        orphaned_tick = seen and not director_task_exists
        # A cooldown on the *previous* fingerprint must not delay a genuinely
        # new candidate set after a useful result. The fingerprint is the
        # novelty/idempotency gate; cooldown only remains diagnostic metadata.
        # Replaying an orphaned tick is also immediate so a crash between the
        # tick and durable Director task cannot strand the queue.
        should_plan = bool(candidates) and (not seen or orphaned_tick)
        decision = ("PLAN" if should_plan else
                    diagnosis["decision"] if not candidates else "UNCHANGED_CANDIDATES")
        detail = {"candidate_count": len(candidates), "cooldown_remaining_seconds": wait_remaining,
                  "force": force, "orphaned_tick_recovered": orphaned_tick,
                  "director_task_exists": director_task_exists,
                  "candidates": candidates, "diagnosis": diagnosis}
        if should_plan or not candidates:
            conn.execute("""INSERT OR IGNORE INTO mission_planner_ticks(
              candidate_fingerprint,created_utc,decision,detail_json) VALUES(?,?,?,?)""",
              (fingerprint, _utc_text(moment), decision, json.dumps(detail, ensure_ascii=False)))
    return {"should_plan": should_plan, "decision": decision,
            "candidate_fingerprint": fingerprint, "candidates": candidates,
            "cooldown_remaining_seconds": wait_remaining, "diagnosis": diagnosis}


def seed_director_task(tick: dict[str, Any], db_path: Path = DEFAULT_DB) -> dict[str, Any]:
    """Persist one local-Director task for a novel, dependency-ready backlog view."""
    if not tick.get("should_plan") or not tick.get("candidates"):
        return {"created": False, "reason": "planner tick has no new dependency-ready candidates"}
    from src.agent import state_store
    fingerprint = str(tick["candidate_fingerprint"])
    task_id = "AUTO_MISSION_DIRECTOR_" + fingerprint[:16].upper()
    candidates = tick["candidates"]
    spec = {"id": task_id, "stage": "R3", "depends_on": [],
        "hypothesis": "The local Qwen Director can select one novel canonical Mission Pack task from dependency-ready goals.",
        "evidence": [{"source": "mission_tasks", "candidate_fingerprint": fingerprint}],
        "agent": "ollama-mission-pack-director",
        "budget": {"timeout_s": 180, "attempts": 1, "mission_pack_director": True,
                   "candidate_fingerprint": fingerprint, "candidates": candidates,
                   "model_calls": 1, "source_write": False},
        "deliverables": [f"reports/mission_pack/plans/{task_id}.json"],
        "tests": ["Selected canonical ID belongs to this candidate set",
                  "No model text is executed as a command or filesystem path",
                  "Excluded Virtual CID and standalone POI editor remain unscheduled"],
        "next_action": "Queue local research; define and independently test any missing worker capability before considering one budgeted Codex escalation.",
        "retry_limit": 1, "priority": 2}
    created = state_store.add_task(spec, db_path=db_path)
    return {"created": created, "task_id": task_id if created else None,
            "reason": "local Director tick saved" if created else "duplicate Director tick is already persisted"}


def queue_selected_task(director_task_id: str, selected_id: str, reason: str,
                        db_path: Path = DEFAULT_DB) -> dict[str, Any]:
    """Create the stable runtime row chosen by the allowlisted local Director."""
    with _connection(db_path) as conn:
        row = conn.execute("SELECT phase,objective,dependencies_json,expected_artifacts_json,acceptance_json,executor_preference,status "
                           "FROM mission_tasks WHERE canonical_id=?", (selected_id,)).fetchone()
    if not row:
        raise KeyError(f"unknown canonical Mission Pack ID: {selected_id}")
    if row["status"] not in {"PROPOSED", "READY"}:
        return {"created": False, "reason": f"canonical task already has runtime state {row['status']}"}
    dependencies = json.loads(row["dependencies_json"] or "[]")
    phase = str(row["phase"])
    task_id = f"AUTO_MISSION_EXEC_{selected_id}_{hashlib.sha256(director_task_id.encode()).hexdigest()[:8].upper()}"
    spec = {"id": task_id, "stage": phase if phase.startswith("F") else "R3",
        "depends_on": [director_task_id],
        "hypothesis": str(row["objective"]),
        "evidence": [{"mission_task_id": selected_id, "director_task_id": director_task_id,
                      "selection_reason": reason[:500], "depends_on": dependencies}],
        "agent": "mission-pack-executor",
        "budget": {"timeout_s": 900, "attempts": 1, "mission_pack_task": selected_id,
                   "executor_preference": row["executor_preference"], "source_write": False},
        "deliverables": json.loads(row["expected_artifacts_json"]),
        "tests": json.loads(row["acceptance_json"]),
        "next_action": "Run local deterministic work first; verify the saved result independently and use Codex only after a recorded local failure or critical architecture need.",
        "retry_limit": 1, "priority": 3}
    from src.agent import state_store
    created = state_store.add_task(spec, db_path=db_path)
    if created:
        mark_status(selected_id, "RUNNING", runtime_task_id=task_id,
                    evidence={"verifier": "deterministic_scheduler", "verdict": "PASS",
                              "director_task_id": director_task_id,
                              "selected_reason": reason[:500]}, db_path=db_path)
    return {"created": created, "task_id": task_id if created else None,
            "canonical_id": selected_id,
            "reason": "canonical Mission Pack task queued" if created else "runtime task ID already exists"}


def mark_status(canonical_id: str, status: str, *, evidence: dict[str, Any],
                reason: str = "", runtime_task_id: str | None = None,
                db_path: Path = DEFAULT_DB) -> None:
    """Persist a state transition only with explicit independent evidence."""
    if status not in STATUSES:
        raise ValueError(f"invalid Mission Pack status: {status}")
    if not isinstance(evidence, dict) or evidence.get("verifier") in {None, "", "model"}:
        raise ValueError("Mission Pack status requires evidence from a deterministic or independent verifier")
    if status == "DONE" and evidence.get("verdict") != "PASS":
        raise ValueError("DONE requires a verifier PASS")
    ensure_schema(db_path)
    with _connection(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        current = conn.execute(
            "SELECT status,evidence_json FROM mission_tasks WHERE canonical_id=?",
            (canonical_id,)).fetchone()
        if current and current["status"] == "WAITING_EXTERNAL" and status == "WAITING_EXTERNAL":
            # Polling a gate must not erase the evidence that a later retry must supersede.
            evidence = {**json.loads(current["evidence_json"] or "{}"), **evidence}
        if current and current["status"] == "WAITING_EXTERNAL" and status != "WAITING_EXTERNAL":
            previous = json.loads(current["evidence_json"] or "{}")
            external = evidence.get("external_evidence")
            if (not isinstance(external, dict) or external.get("canonical_id") != canonical_id
                    or not external.get("sha256") or not external.get("artifact_path")
                    or external == previous.get("external_evidence")):
                raise ValueError("WAITING_EXTERNAL requires new task-specific external evidence")
            external_path = (PROJECT_ROOT / str(external["artifact_path"])).resolve(strict=True)
            if (not external_path.is_relative_to(PROJECT_ROOT.resolve())
                    or not external_path.is_file()
                    or hashlib.sha256(external_path.read_bytes()).hexdigest() != external["sha256"]):
                raise ValueError("External evidence artifact is invalid")
        cursor = conn.execute("""UPDATE mission_tasks SET status=?,runtime_task_id=COALESCE(?,runtime_task_id),
          evidence_json=?,status_reason=?,updated_utc=? WHERE canonical_id=?""",
          (status, runtime_task_id, json.dumps(evidence, ensure_ascii=False, sort_keys=True),
           reason[:1000], _utc_text(), canonical_id))
        if cursor.rowcount != 1:
            raise KeyError(f"unknown Mission Pack task: {canonical_id}")

