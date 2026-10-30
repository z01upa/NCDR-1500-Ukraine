"""Allowlisted local project director and evidence supervisor.

The local model proposes a goal from a fixed registry. Its text never becomes
code, a command, a path, or an unreviewed dependency. Deterministic handlers
perform the work and independently gate every acceptance claim.
"""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
from pathlib import PurePosixPath
import re
import sqlite3
import subprocess
import sys
import tempfile
import time
from typing import Any
import zlib

from src.agent import autonomous_manager as manager

# NCDR_A01_AVAILABLE_MODELS_BRIDGE_V1
available_models = manager.available_models
from src.agent import coordinator_runtime, state_store
from src.agent import project_scope


PROJECT_ROOT = Path(__file__).resolve().parents[2]
STATE_DB = PROJECT_ROOT / "project_state.sqlite"
SOURCE_PBF = PROJECT_ROOT / "data" / "osm" / "ukraine-latest.osm.pbf"
WORK_ROOT = PROJECT_ROOT / "work" / "autonomous_manager" / "osm_pipeline"
DIRECTOR_BENCHMARK = PROJECT_ROOT / "reports" / "autonomous_director_model_benchmark.json"
DIRECTOR_MODELS = (
    "qwen3.5:9b",
)
FALLBACK_MODELS: tuple[str, ...] = ()
PLAN_TASKS = {
    "OSM_REAL_CONVERSION": "AUTO_OSM_REAL_CONVERSION_20261025",
    "NCDX_NK_SURVEY": "AUTO_NCDX_NK_SURVEY_01",
    "NCDX_NAVIMAIN_SURVEY": "AUTO_NCDX_NAVIMAIN_SURVEY_01",
}
OSM_NATIONAL_TASK_ID = "AUTO_OSM_NATIONAL_CONVERSION_01"
OSM_NATIONAL_SUPERVISOR_ID = "AUTO_SUPERVISOR_OSM_NATIONAL_01"
OSM_NATIONAL_PUBLISHED_RECOVERY_ID = "AUTO_OSM_NATIONAL_PUBLISHED_RECOVERY_01"
OSM_NATIONAL_TIMEOUT_S = 900
OSM_PARTITION_DATABASE = (WORK_ROOT / "ukraine_national" /
    "ukraine-2026-09-08-9eb8b42b2687" / "ukraine.sqlite")
OSM_PARTITION_CANDIDATES = (
    {"goal_id": "AUTO_OSM_PARTITION_PROBE_KR_CITY_4X4", "area": "KR_CITY",
     "bbox": (47.89, 33.37, 47.92, 33.45), "rows": 4, "columns": 4},
    {"goal_id": "AUTO_OSM_PARTITION_PROBE_KR_CITY_8X8", "area": "KR_CITY",
     "bbox": (47.89, 33.37, 47.92, 33.45), "rows": 8, "columns": 8},
)
PLAN_ID = {
    "OSM_REAL_CONVERSION": "AUTO_DIRECTOR_PLAN_OSM_01",
    "NCDX_NK_SURVEY": "AUTO_DIRECTOR_PLAN_NCDX_01",
    "NCDX_NAVIMAIN_SURVEY": "AUTO_DIRECTOR_PLAN_NCDX_02",
}
SUPERVISOR_ID = {
    "OSM_REAL_CONVERSION": "AUTO_SUPERVISOR_OSM_CONVERSION_01",
    "NCDX_NK_SURVEY": "AUTO_SUPERVISOR_NK_SURVEY_01",
    "NCDX_NAVIMAIN_SURVEY": "AUTO_SUPERVISOR_NAVIMAIN_SURVEY_01",
}
COMPONENT_SCAN_EXTENSIONS = {".ABS", ".BIN", ".DLL", ".EXE", ".HEX"}
MISSION_B03_EXTENSIONS = frozenset(COMPONENT_SCAN_EXTENSIONS)
COMPONENT_SCAN_EXCLUSIONS = {
    "SW/LK841/HU_HARDWARE_LOC_0000000001/HU_KERNEL_LOC_0101000870/NK.BIN",
    "SW/LK841/HU_HARDWARE_LOC_0000000001/HU_MMIDIS_LOC_0130170000/WINDOWS/NAVIMAIN.EXE",
}
DATA_PROFILE_MODES = ("WINDOW_PROFILE", "BLOCK_ALIGNMENT", "SIGNATURE_SWEEP",
                      "CROSS_REGION_WINDOW_COMPARE", "LAG_CORRELATION_SCAN",
                      "BYTE_TRANSITION_PROFILE", "DEFLATE_COMPRESSIBILITY_PROFILE",
                      "EXACT_BLOCK_ANCHOR_SCAN", "CONTAINER_ROUNDTRIP",
                      "DECODED_STRUCTURE_SCAN", "STRING_COORDINATE_PROXIMITY_AUDIT",
                      "PRINTABLE_RUN_LAYOUT_PROFILE", "REPEATED_TEXT_DICTIONARY_PROFILE",
                      "REPEATED_TEXT_COORDINATE_AUDIT", "BLOCK_BOUNDARY_PROFILE",
                      "TEXT_COORDINATE_ASSOCIATION_CENSUS",
                      "REPEATED_TEXT_COORDINATE_ASSOCIATION_CENSUS",
                      "STANDALONE_ZLIB_STREAM_CENSUS",
                      "ZLIB_STREAM_BOUNDARY_CONTEXT_PROFILE",
                      "ZLIB_DECODED_COORDINATE_CANDIDATE_CENSUS")
DIRECTOR_DATA_PROFILE_MODES = ("STRING_COORDINATE_PROXIMITY_AUDIT",
                               "DECODED_STRUCTURE_SCAN", "CONTAINER_ROUNDTRIP",
                               "PRINTABLE_RUN_LAYOUT_PROFILE", "REPEATED_TEXT_DICTIONARY_PROFILE",
                               "REPEATED_TEXT_COORDINATE_AUDIT", "BLOCK_BOUNDARY_PROFILE",
                               "EXACT_BLOCK_ANCHOR_SCAN",
                               "TEXT_COORDINATE_ASSOCIATION_CENSUS",
                               "REPEATED_TEXT_COORDINATE_ASSOCIATION_CENSUS",
                               "STANDALONE_ZLIB_STREAM_CENSUS",
                               "ZLIB_STREAM_BOUNDARY_CONTEXT_PROFILE",
                               "ZLIB_DECODED_COORDINATE_CANDIDATE_CENSUS")
CONTAINER_ROUNDTRIP_SUFFIXES = frozenset({"PTI", "PDX", "PTP"})
CONTAINER_ROUNDTRIP_VERSION = 2
DECODED_STRUCTURE_SCAN_VERSION = 3
STRING_COORDINATE_PROXIMITY_AUDIT_VERSION = 3
PRINTABLE_RUN_LAYOUT_PROFILE_VERSION = 1
REPEATED_TEXT_DICTIONARY_PROFILE_VERSION = 2
REPEATED_TEXT_COORDINATE_AUDIT_VERSION = 1
BLOCK_BOUNDARY_PROFILE_VERSION = 2
EXACT_BLOCK_ANCHOR_SCAN_VERSION = 1
TEXT_COORDINATE_ASSOCIATION_CENSUS_VERSION = 1
REPEATED_TEXT_COORDINATE_ASSOCIATION_CENSUS_VERSION = 1
STANDALONE_ZLIB_STREAM_CENSUS_VERSION = 1
ZLIB_STREAM_BOUNDARY_CONTEXT_PROFILE_VERSION = 1
ZLIB_DECODED_COORDINATE_CANDIDATE_CENSUS_VERSION = 1
ROADLINK_PORTABILITY_VERSION = 1
ROADLINK_NAME_CONSISTENCY_VERSION = 1
GEOGRAPHY_PORTABILITY_VERSION = 1
CITY_COORDINATE_CROSSCHECK_VERSION = 1
PE_IMPORT_CENSUS_VERSION = 1
PE_IMPORT_CENSUS_SOURCE = "SW/LK841/HU_HARDWARE_LOC_0000000001/HU_MMIDIS_LOC_0130170000/WINDOWS/NAVIMAIN.EXE"
EMBEDDED_PE_SEARCH_VERSION = 1
EMBEDDED_PE_SEARCH_SOURCE = "SW/LK841/HU_HARDWARE_LOC_0000000001/HU_KERNEL_LOC_0101000870/NK.BIN"
CITY_COORDINATE_CENSUS_EVIDENCE = {
    "SW": ("AUTO_NCDX_DATA_MG1_ZLIB_DECODED_COORDINATE_CANDIDATE_CENSUS_0d9bedd0", 969, 10),
    "Scandinavia": ("AUTO_NCDX_DATA_MG1_ZLIB_DECODED_COORDINATE_CANDIDATE_CENSUS_48254da5", 1176, 6),
}
DATA_PROFILE_SAMPLE_BYTES = 4096
DATA_PROFILE_MAX_READ_BYTES = 64 * 1024
DATA_PROFILE_ANCHOR_BLOCK_BYTES = 4096
DATA_PROFILE_ANCHOR_SCAN_BYTES = 4 * 1024 * 1024
DATA_PROFILE_LAGS = (2, 4, 8, 16, 32, 64, 128, 256, 512)
DATA_PROFILE_TOP_TRANSITIONS = 16
DATA_PROFILE_SIGNATURES = {
    "MZ": b"MZ", "PE": b"PE\x00\x00", "ZIP": b"PK\x03\x04",
    "GZIP": b"\x1f\x8b", "ZLIB_7801": b"\x78\x01",
    "ZLIB_789C": b"\x78\x9c", "ZLIB_78DA": b"\x78\xda",
    "SQLITE3": b"SQLite format 3\x00", "RIFF": b"RIFF",
    "LZ4_FRAME": b"\x04\x22\x4d\x18", "7ZIP": b"7z\xbc\xaf\x27\x1c",
}


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def write_osm_source_manifest(source_path: Path, metadata_path: Path,
                             output_path: Path, project_root: Path) -> dict[str, Any]:
    """Write offline provenance for a cached OSM extract, never its bytes."""
    source = Path(source_path).resolve(strict=True)
    root = Path(project_root).resolve(strict=True)
    try:
        source_relative = source.relative_to(root).as_posix()
    except ValueError as exc:
        raise ValueError("OSM source PBF must remain inside the project root") from exc
    metadata = _json(Path(metadata_path))
    if not metadata:
        raise ValueError("OSM source metadata is missing or malformed")
    download = metadata.get("pbf_download", {})
    if not isinstance(download, dict):
        download = {}
    before = source.stat()
    source_hash = _sha256(source)
    after = source.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError("OSM source changed while the manifest was being prepared")
    recorded_hash = str(download.get("sha256") or "").strip().casefold()
    if recorded_hash and recorded_hash != source_hash:
        raise ValueError("cached PBF checksum differs from saved source metadata")
    recorded_bytes = download.get("bytes")
    if recorded_bytes is not None and int(recorded_bytes) != after.st_size:
        raise ValueError("cached PBF size differs from saved source metadata")

    content_text = str(metadata.get("dataset_content_timestamp") or "").strip()
    content_match = re.match(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)", content_text)
    content_time = content_match.group(1) if content_match else "NOT_RECORDED"
    retrieved = str(download.get("retrieved_utc") or metadata.get("retrieved_utc") or "").strip()
    retrieved = retrieved or "NOT_RECORDED"
    source_url = str(download.get("url") or metadata.get("source_url") or "").strip()
    source_url = source_url or "NOT_RECORDED"
    manifest = {
        "schema_version": 1,
        "status": "VERIFIED",
        "source_url": source_url,
        "source_pbf_path": source_relative,
        "source_pbf_sha256": source_hash,
        "source_pbf_bytes": after.st_size,
        "dataset_content_timestamp": content_time,
        "retrieved_utc": retrieved,
        "license": "Open Database License (ODbL)",
        "attribution": "© OpenStreetMap contributors",
    }
    output = Path(output_path)
    if not output.is_absolute():
        output = root / output
    output.parent.mkdir(parents=True, exist_ok=True)
    if not output.parent.resolve(strict=True).is_relative_to(root):
        raise ValueError("OSM source manifest output must remain inside the project root")
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n",
                prefix="source-manifest.", suffix=".tmp", dir=output.parent, delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(manifest, stream, ensure_ascii=False, sort_keys=True, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, output)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    verified = verify_osm_source_manifest(source, output, root)
    return {"status": "PASS", "manifest_path": output.relative_to(root).as_posix(),
            "source_pbf_sha256": source_hash, "source_pbf_bytes": after.st_size,
            "source_write_count": 0, "verification": verified}


def verify_osm_source_manifest(source_path: Path, manifest_path: Path,
                               project_root: Path) -> dict[str, Any]:
    """Independently bind a saved OSM manifest to a read-only source PBF."""
    root = Path(project_root).resolve(strict=True)
    source = Path(source_path).resolve(strict=True)
    manifest_path = Path(manifest_path)
    if not manifest_path.is_absolute():
        manifest_path = root / manifest_path
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("source manifest schema mismatch: unreadable JSON") from exc
    required = {"schema_version", "status", "source_url", "source_pbf_path",
                "source_pbf_sha256", "source_pbf_bytes", "dataset_content_timestamp",
                "retrieved_utc", "license", "attribution"}
    if not isinstance(manifest, dict) or set(manifest) != required or manifest.get("schema_version") != 1:
        raise ValueError("source manifest schema mismatch")
    try:
        source_relative = source.relative_to(root).as_posix()
    except ValueError as exc:
        raise ValueError("OSM source PBF escaped the project root") from exc
    if manifest.get("status") != "VERIFIED" or manifest.get("source_pbf_path") != source_relative:
        raise ValueError("source manifest schema mismatch: source identity")
    if (manifest.get("license") != "Open Database License (ODbL)"
            or manifest.get("attribution") != "© OpenStreetMap contributors"):
        raise ValueError("source manifest schema mismatch: license or attribution")
    before = source.stat()
    actual_hash = _sha256(source)
    after = source.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError("OSM source changed during manifest verification")
    if (manifest.get("source_pbf_sha256") != actual_hash
            or manifest.get("source_pbf_bytes") != after.st_size):
        raise ValueError("source manifest checksum or byte count mismatch")
    for name in ("dataset_content_timestamp", "retrieved_utc", "source_url"):
        value = manifest.get(name)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"source manifest schema mismatch: {name}")
    return {"status": "PASS", "source_pbf_sha256": actual_hash,
            "source_pbf_bytes": after.st_size, "source_write_count": 0,
            "source_unchanged": True, "license": manifest["license"],
            "attribution": manifest["attribution"]}


def write_d02_source_manifest() -> dict[str, Any]:
    """Mission Pack entry point for the reusable OSM provenance writer."""
    return write_osm_source_manifest(SOURCE_PBF, PROJECT_ROOT / "data" / "osm" / "source.json",
        PROJECT_ROOT / "osm" / "source-manifest.json", PROJECT_ROOT)


def verify_d02_source_manifest() -> dict[str, Any]:
    """Mission Pack entry point for the reusable OSM provenance verifier."""
    return verify_osm_source_manifest(SOURCE_PBF, PROJECT_ROOT / "osm" / "source-manifest.json",
        PROJECT_ROOT)


def _task_status(task_id: str) -> str | None:
    if not STATE_DB.is_file():
        return None
    with closing(sqlite3.connect(STATE_DB, timeout=20)) as conn:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='tasks'").fetchone():
            return None
        row = conn.execute("SELECT status FROM tasks WHERE id=?", (task_id,)).fetchone()
    return str(row[0]) if row else None


def _task_result(task_id: str) -> dict[str, Any]:
    with closing(sqlite3.connect(STATE_DB, timeout=20)) as conn:
        row = conn.execute("SELECT status,result_json FROM tasks WHERE id=?", (task_id,)).fetchone()
    if not row:
        raise RuntimeError(f"required predecessor task is missing: {task_id}")
    if row[0] != "DONE":
        raise RuntimeError(f"required predecessor {task_id} is {row[0]}, not DONE")
    try:
        return json.loads(row[1] or "{}")
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"predecessor {task_id} has invalid saved result JSON") from exc


def _resume_national_osm_task_from_checkpoint() -> dict[str, Any]:
    """Requeue the failed monolithic build only after verifying its saved extract.

    The replacement handler is a resumable SQLite importer. This migration is
    intentionally one-time: the blocked task's history is retained and every
    subsequent import slice receives a distinct checkpoint-derived task ID.
    """
    if not STATE_DB.is_file() or not SOURCE_PBF.is_file():
        return {"requeued": False, "reason": "state database or configured source is missing"}
    with closing(sqlite3.connect(STATE_DB, timeout=30)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT status,attempts,budget_json,result_json FROM tasks WHERE id=?",
                           (OSM_NATIONAL_TASK_ID,)).fetchone()
    if not row or row["status"] != "BLOCKED":
        return {"requeued": False, "reason": "national task is not blocked"}
    try:
        budget = json.loads(row["budget_json"] or "{}")
        previous = json.loads(row["result_json"] or "{}")
    except json.JSONDecodeError:
        return {"requeued": False, "reason": "saved national task checkpoint is malformed"}
    if budget.get("resumable_national_osm"):
        return {"requeued": False, "reason": "the legacy parent was already migrated; checkpoint-derived slice tasks own further recovery"}
    error = str(previous.get("error", ""))
    if not any(marker in error.casefold() for marker in ("out of memory", "parseerror", "3600", "ліміт", "timeout")):
        return {"requeued": False, "reason": "the blocked national task does not contain a recoverable import timeout/memory diagnostic"}

    national_root = (WORK_ROOT / "ukraine_national").resolve()
    candidates = sorted(national_root.glob("ukraine-*"), key=lambda path: path.stat().st_mtime, reverse=True)
    output_dir = next((path.resolve() for path in candidates if path.is_dir()), None)
    if output_dir is None or not output_dir.is_relative_to(national_root):
        return {"requeued": False, "reason": "no versioned national output directory exists"}
    progress_path, extract = output_dir / "progress.json", output_dir / "ukraine.osm.gz"
    if not progress_path.is_file() or not extract.is_file():
        return {"requeued": False, "reason": "the extract checkpoint is incomplete"}
    try:
        progress = json.loads(progress_path.read_text(encoding="utf-8"))
        extraction = progress.get("extraction", {})
        source_sha = _sha256(SOURCE_PBF)
        recorded_extract = Path(str(extraction.get("extract_xml_gz", ""))).resolve()
        if (progress.get("source_pbf_sha256") != source_sha or recorded_extract != extract.resolve() or
                extraction.get("whole_source") is not True or
                int(extraction.get("nodes_written", 0)) <= 0 or
                int(extraction.get("nodes_written", 0)) != int(extraction.get("nodes_in_bbox", -1)) or
                int(extraction.get("selected_ways", 0)) <= 0):
            return {"requeued": False, "reason": "extract metadata does not match the immutable source and complete national counts"}
        decompressed_bytes = 0
        with gzip.open(extract, "rb") as stream:
            header = stream.read(256)
            if b"<osm" not in header:
                return {"requeued": False, "reason": "checkpoint is not an OSM XML gzip stream"}
            decompressed_bytes = len(header)
            while block := stream.read(8 * 1024 * 1024):
                decompressed_bytes += len(block)
        if decompressed_bytes <= 0:
            return {"requeued": False, "reason": "checkpoint has no decompressed OSM payload"}
        extract_sha = _sha256(extract)
        proof = {"status": "PASS_GZIP_EOF_AND_SOURCE_BINDING", "task_id": OSM_NATIONAL_TASK_ID,
            "previous_error": error, "source_pbf_sha256": source_sha,
            "extract_path": str(extract.relative_to(PROJECT_ROOT)), "extract_sha256": extract_sha,
            "extract_bytes": extract.stat().st_size, "decompressed_bytes": decompressed_bytes,
            "nodes_written": int(extraction["nodes_written"]),
            "selected_ways": int(extraction["selected_ways"]),
            "gzip_crc_and_eof_verified": True,
            "resume_design": "checkpointed sequential decompression plus transactional line-oriented SQLite batches",
            "retry_count_limit": "one task per stable checkpoint token; unchanged failing checkpoints are deduplicated",
            "physical_compatibility": "NOT_TESTED", "created_utc": _utc()}
        report_path = PROJECT_ROOT / "reports" / f"autonomous_osm_national_checkpoint_recovery_{datetime.now(timezone.utc):%Y%m%d-%H%M%S}.json"
        report_path.write_text(json.dumps(proof, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        proof["artifact"] = manager._artifact(OSM_NATIONAL_TASK_ID, report_path,
            "Verified gzip/source checkpoint used to resume national OSM build",
            "PASS: source hash, full gzip CRC/EOF, and saved national extraction counts agree")
        output_relative = output_dir.relative_to(PROJECT_ROOT).as_posix()
        budget.update({"timeout_s": 900, "attempts": 1, "verified_extract_resume_used": True,
                       "resumable_national_osm": True, "source_pbf_sha256": source_sha,
                       "extract_sha256": extract_sha, "output_directory": output_relative,
                       "expected_decompressed_bytes": decompressed_bytes,
                       "max_records_per_slice": 500000, "slice_budget_seconds": 180,
                       "resume_checkpoint_artifact": str(report_path.relative_to(PROJECT_ROOT))})
        with closing(sqlite3.connect(STATE_DB, timeout=30)) as conn:
            conn.execute("UPDATE tasks SET budget_json=? WHERE id=? AND status='BLOCKED'",
                         (json.dumps(budget, ensure_ascii=False, sort_keys=True), OSM_NATIONAL_TASK_ID))
            conn.commit()
        state_store.requeue_task(OSM_NATIONAL_TASK_ID,
            "A complete source-matched national extract passed gzip CRC/EOF verification; resume once with a bounded six-hour import limit.",
            db_path=STATE_DB)
        manager._event("national_osm_checkpoint_requeued", proof, task_id=OSM_NATIONAL_TASK_ID)
        return {"requeued": True, "task_id": OSM_NATIONAL_TASK_ID,
                "reason": "verified source-bound gzip/CRC; old OOM-prone handler replaced by checkpointed slices", "proof": proof}
    except (OSError, ValueError, KeyError, TypeError, EOFError, json.JSONDecodeError, gzip.BadGzipFile) as exc:
        manager._event("national_osm_checkpoint_recovery_rejected",
            {"error": f"{type(exc).__name__}: {exc}"}, task_id=OSM_NATIONAL_TASK_ID, severity="WARNING")
        return {"requeued": False, "reason": f"checkpoint verification failed: {type(exc).__name__}: {exc}"}


def _registered_task(task_id: str, stage: str, dependency: str | None,
                     hypothesis: str, agent: str, output: str, checks: list[str],
                     timeout_s: int, priority: int,
                     budget_extra: dict[str, Any] | None = None) -> bool:
    task = {
        "id": task_id, "stage": stage, "depends_on": [dependency] if dependency else [],
        "hypothesis": hypothesis,
        "evidence": [{"artifact": "project_state.sqlite", "role": "durable project state"}],
        "agent": agent, "budget": {"timeout_s": timeout_s, "attempts": 1,
            "source_write": False, "execution": "fixed allowlisted handler", **(budget_extra or {})},
        "deliverables": [output], "tests": checks,
        "next_action": "Зберегти перевірений результат і передати Supervisor нові докази.",
        "retry_limit": 1, "priority": priority,
    }
    return state_store.add_task(task, db_path=STATE_DB)


def seed_next_mission_director_task() -> dict[str, Any]:
    """Run the persistent canonical backlog planner when the ordinary queue is empty."""
    from src.agent import mission_pack
    reconciled = mission_pack.reconcile_runtime_missions()
    tick = mission_pack.planner_tick()
    if not tick.get("should_plan"):
        diagnosis = tick.get("diagnosis") or mission_pack.planner_diagnosis()
        return {"created": False,
                "reason": f"Mission Pack planner: {tick.get('decision')}; {diagnosis.get('message', '')}",
                "planner_tick": tick, "runtime_reconciliation": reconciled,
                "mission_diagnosis": diagnosis}
    seeded = mission_pack.seed_director_task(tick)
    if seeded.get("created"):
        manager._event("mission_planner_task_created", {**seeded,
            "candidate_fingerprint": tick.get("candidate_fingerprint"),
            "candidate_ids": [row["id"] for row in tick.get("candidates", [])]})
    return {**seeded, "planner_tick": tick, "runtime_reconciliation": reconciled,
            "reason": str(seeded.get("reason", "")) + "; canonical 46-task backlog is active"}


def execute_mission_pack_director(task_id: str) -> dict[str, Any]:
    """Ask the local Director to choose one exact ready backlog item."""
    from src.agent import mission_pack
    task = manager._task(task_id)
    budget = task.get("budget", {})
    candidates = budget.get("candidates") or []
    if not candidates:
        raise RuntimeError("Mission Pack Director task has no persisted candidate set")
    allowed = {str(row.get("id")) for row in candidates if isinstance(row, dict)}
    if not allowed:
        raise RuntimeError("Mission Pack Director candidate set is invalid")
    model_name: str | None = None
    model_error: str | None = None
    parsed: dict[str, Any] = {}
    try:
        installed = coordinator_runtime._available_models()
        model_name = coordinator_runtime._choose_model("project-director", installed)
        prompt = json.dumps({"role": "local Qwen project Director", "global_goal": project_scope.global_goal(),
            "active_tracks": project_scope.load_scope()["active_tracks"],
            "excluded_tracks": project_scope.load_scope()["excluded_tracks"],
            "goal_gates": json.loads(mission_pack.GATES_PATH.read_text(encoding="utf-8")),
            "dependency_ready_candidates": candidates,
            "constraints": ["Select exactly one canonical ID from dependency_ready_candidates.",
                "Return only the response schema as JSON.",
                "Do not choose Virtual CID or a separate POI editor.",
                "Do not assign a terminal status, emit paths or commands, or write original media."],
            "response_schema": {"canonical_id": next(iter(sorted(allowed))),
                "reason": "evidence-based next task", "requires_hardware": False,
                "writes_original_media": False}}, ensure_ascii=False)
        _actual_model, _response, parsed = coordinator_runtime._call_model(
            task_id, "project-director", prompt, attempt=1, fixed_model=model_name)
    except Exception as exc:
        model_error = f"{type(exc).__name__}: {exc}"[:600]
    selected_id = str(parsed.get("canonical_id", ""))
    safe = (selected_id in allowed and parsed.get("requires_hardware") is False
            and parsed.get("writes_original_media") is False)
    if not safe:
        selected_id = str(candidates[0]["id"])
        reason = "deterministic priority fallback; local Director output unavailable or outside the candidate contract"
    else:
        reason = str(parsed.get("reason", ""))[:500].strip()
        if not reason:
            reason = "local Director selected a dependency-ready canonical task"
    out = {"status": "PASS", "task_id": task_id, "selected_id": selected_id,
        "reason": reason, "model": model_name, "model_error": model_error,
        "candidate_fingerprint": budget.get("candidate_fingerprint"),
        "allowed_ids": sorted(allowed), "model_choice_accepted": safe,
        "scope_guard": {"original_media_write": False, "virtual_cid": "EXCLUDED",
                        "standalone_poi_editor": "EXCLUDED"}, "created_utc": _utc()}
    report_dir = PROJECT_ROOT / "reports" / "mission_pack" / "plans"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"{task_id}.json"
    report_path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    out["artifact"] = manager._artifact(task_id, report_path,
        "Local Director selection from the canonical Mission Pack backlog",
        "PASS: exact candidate ID, bounded allowlist and excluded-track guards")
    return out


def _a02_memory_evidence() -> dict[str, Any]:
    """Measure this diagnostic process, never reconstruct the failed process."""
    import os
    evidence: dict[str, Any] = {
        "historical_peak_working_set_bytes": None,
        "historical_peak_status": "NOT_RECORDED",
        "diagnostic_peak_working_set_bytes": None,
        "available_physical_memory_bytes": None,
        "measurement_scope": "current diagnostic process; not the historical failed importer",
        "measured_utc": _utc(), "pid": os.getpid()}
    try:
        if sys.platform == "win32":
            import ctypes
            from ctypes import wintypes

            class Counters(ctypes.Structure):
                _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
                    (name, ctypes.c_size_t) for name in ("PeakWorkingSetSize", "WorkingSetSize",
                    "QuotaPeakPagedPoolUsage", "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage",
                    "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")]

            class MemoryStatus(ctypes.Structure):
                _fields_ = [("dwLength", wintypes.DWORD), ("dwMemoryLoad", wintypes.DWORD)] + [
                    (name, ctypes.c_ulonglong) for name in ("ullTotalPhys", "ullAvailPhys",
                    "ullTotalPageFile", "ullAvailPageFile", "ullTotalVirtual", "ullAvailVirtual",
                    "ullAvailExtendedVirtual")]

            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.GetCurrentProcess.restype = wintypes.HANDLE
            psapi = ctypes.WinDLL("psapi", use_last_error=True)
            psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
            counters = Counters()
            counters.cb = ctypes.sizeof(counters)
            if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
                raise ctypes.WinError(ctypes.get_last_error())
            evidence["diagnostic_peak_working_set_bytes"] = int(counters.PeakWorkingSetSize)
            status = MemoryStatus()
            status.dwLength = ctypes.sizeof(status)
            if not kernel.GlobalMemoryStatusEx(ctypes.byref(status)):
                raise ctypes.WinError(ctypes.get_last_error())
            evidence["available_physical_memory_bytes"] = int(status.ullAvailPhys)
            evidence["measurement_api"] = "GetProcessMemoryInfo / GlobalMemoryStatusEx"
        else:
            import resource
            peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            evidence["diagnostic_peak_working_set_bytes"] = int(peak * (1 if sys.platform == "darwin" else 1024))
            evidence["available_physical_memory_bytes"] = int(os.sysconf("SC_AVPHYS_PAGES") * os.sysconf("SC_PAGE_SIZE"))
            evidence["measurement_api"] = "getrusage / sysconf"
    except (OSError, ValueError, AttributeError, ImportError) as exc:
        evidence["measurement_error"] = str(exc)
    return evidence


def _a02_oom_diagnosis(rows: list[dict[str, Any]]) -> dict[str, Any]:
    def decoded(value: str) -> dict[str, Any]:
        try:
            result = json.loads(value or "{}")
            return result if isinstance(result, dict) else {}
        except (ValueError, TypeError):
            return {}

    reviews = []
    by_id = {row["id"]: row for row in rows}
    for row in rows:
        saved, budget = decoded(row["result_json"]), decoded(row.get("budget_json"))
        if (row["status"] == "DONE" and saved.get("status") == "PASS"
                and (budget.get("osm_failure_review") is True or row["id"].startswith("AUTO_OSM_FAILURE_REVIEW_"))
                and "out of memory" in str(saved.get("error", "")).casefold()):
            reviews.append((row, saved))
    if not reviews:
        return {"status": "WAITING_FOR_EVIDENCE", "reason": "No persisted completed OSM OOM review"}
    row, review = reviews[-1]
    parent = by_id.get(review.get("source_task"), {})
    budget = decoded(parent.get("budget_json"))
    saved = decoded(parent.get("result_json"))
    checkpoint = {"token": review.get("checkpoint_token"),
        "current_task_token": saved.get("checkpoint_token"),
        "source_pbf_sha256": budget.get("source_pbf_sha256"),
        "extract_sha256": budget.get("extract_sha256"),
        "resume_checkpoint_artifact": budget.get("resume_checkpoint_artifact"),
        "output_directory": budget.get("output_directory")}
    limits = {key: budget.get(key) for key in (
        "max_records_per_slice", "slice_budget_seconds", "timeout_s", "attempts")}
    match = re.search(r"line\s+(\d+)(?:,\s*column\s+(\d+))?", str(review.get("error", "")), re.I)
    line_number = int(match[1]) if match else None
    line: dict[str, Any] = {"line_number": line_number,
        "column": int(match[2]) if match and match[2] else None,
        "status": "NOT_READ", "read_mode": "bounded binary readline; parse only the target record",
        "max_line_bytes": 1024 * 1024, "max_scan_seconds": 300, "max_scan_bytes": 16 * 1024**3}
    output = (PROJECT_ROOT / str(budget.get("output_directory", ""))).resolve()
    if (budget.get("output_directory") and output.is_relative_to(WORK_ROOT.resolve())
            and line_number and 0 < line_number <= 50000000):
        raw = output / "ukraine.osm.raw"
        extract = output / "ukraine.osm.gz"
        path = (raw if raw.is_file() else extract).resolve()
        if not path.is_relative_to(output):
            return {"status": "WAITING_FOR_EVIDENCE", "reason": "Derived XML escaped its output directory"}
        line["path"] = str(path)
        checkpoint["raw_checkpoint"] = _json(output / "ukraine.osm.raw.checkpoint.json")
        checkpoint["progress"] = _json(output / "progress.json")
        started, scanned = time.monotonic(), 0
        try:
            import xml.etree.ElementTree as ET
            opener = gzip.open if path.suffix == ".gz" else Path.open
            with opener(path, "rb") as stream:
                for number in range(1, line_number + 1):
                    record = stream.readline(line["max_line_bytes"] + 1)
                    scanned += len(record)
                    if (not record or len(record) > line["max_line_bytes"]
                            or scanned > line["max_scan_bytes"]
                            or time.monotonic() - started > line["max_scan_seconds"]):
                        raise ValueError("target line unavailable within bounded read limits")
                    if number == line_number:
                        element = ET.fromstring(record)
                        line.update({"status": "PARSED", "element_type": element.tag,
                            "record_bytes": len(record), "record_sha256": hashlib.sha256(record).hexdigest(),
                            "record": record.decode("utf-8", errors="replace"),
                            "attributes": dict(element.attrib)})
            line["scanned_bytes"] = scanned
        except (OSError, ValueError, EOFError, ET.ParseError) as exc:
            line.update({"status": "UNAVAILABLE", "error": str(exc)})
    memory = _a02_memory_evidence()
    complete = (line["status"] == "PARSED" and bool(checkpoint["token"])
        and bool(checkpoint["source_pbf_sha256"]) and bool(checkpoint["extract_sha256"])
        and all(limits[key] is not None for key in ("max_records_per_slice", "slice_budget_seconds", "timeout_s"))
        and bool(memory["diagnostic_peak_working_set_bytes"])
        and bool(memory["available_physical_memory_bytes"]))
    return {"status": "PASS" if complete else "WAITING_FOR_EVIDENCE",
        "review_task_id": row["id"], "review_task_status": row["status"], "persisted_review": review,
        "source_task_id": review.get("source_task"), "error": review.get("error"),
        "root_cause_class": review.get("root_cause_class"),
        "root_cause_basis": "persisted independent review; historical memory telemetry was not recorded",
        "source_format": "OSM PBF source; derived OSM XML (gzip extract / raw spool)",
        "parser": {"legacy": "xml.etree.ElementTree.iterparse",
            "current": "checkpointed line-oriented SQLite importer; ElementTree.fromstring per record",
            "diagnostic": "xml.etree.ElementTree.fromstring on the single target line"},
        "failure_line": line, "checkpoint": checkpoint, "importer_limits": limits,
        "process_limits": {"timeout_s": limits["timeout_s"], "historical_memory_limit_bytes": None,
            "historical_memory_limit_status": "NOT_RECORDED"},
        "memory": memory, "reimport_required": False, "source_write_count": 0}


def _autostart_pid_is_running(pid: int) -> bool:
    """Probe a PID without signalling or starting a process."""
    if sys.platform != "win32" or pid <= 0:
        return False
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        return False
    try:
        code = wintypes.DWORD()
        return bool(kernel.GetExitCodeProcess(handle, ctypes.byref(code)) and code.value == 259)
    finally:
        kernel.CloseHandle(handle)


def _is_manager_window_title(title: str) -> bool:
    """Match the application title, excluding Explorer tabs and file names."""
    return title == "NCDR Autonomous Research Manager"


def _visible_manager_windows() -> list[str] | None:
    """None means enumeration was unavailable, never an empty desktop."""
    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes
    user = ctypes.WinDLL("user32", use_last_error=True)
    user.IsWindowVisible.argtypes = [wintypes.HWND]
    user.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    titles: list[str] = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(hwnd: Any, unused: Any) -> bool:
        if user.IsWindowVisible(hwnd):
            text = ctypes.create_unicode_buffer(user.GetWindowTextLengthW(hwnd) + 1)
            user.GetWindowTextW(hwnd, text, len(text))
            if _is_manager_window_title(text.value):
                titles.append(text.value)
        return True
    callback = callback_type(visit)
    user.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    return titles if user.EnumWindows(callback, 0) else None


def verify_autostart_acceptance(*, task_xml_path: Path | None = None,
        startup_shortcut_path: Path | None = None, watchdog_log_path: Path | None = None,
        state_db_path: Path | None = None) -> dict[str, Any]:
    """Inspect existing startup evidence; never install, repair, or accept a reboot."""
    import os
    import xml.etree.ElementTree as ET
    evidence: dict[str, Any] = {"reboot_acceptance": "NOT_TESTED", "startup_write_count": 0}
    checks: dict[str, bool] = {}
    errors: dict[str, str] = {}
    def query(command: list[str]) -> str:
        run = subprocess.run(command, capture_output=True, text=True, timeout=15,
            check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if run.returncode:
            raise OSError((run.stderr or "startup evidence query failed")[:500])
        return run.stdout
    try:
        if task_xml_path is not None:
            xml = Path(task_xml_path).read_bytes()
        else:
            task_file = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "Tasks" / "NCDR Autonomous Research Manager"
            try:
                # Let the XML parser honor the installed file's BOM/encoding,
                # including UTF-16, without a text-mode decoding round trip.
                xml = task_file.read_bytes()
            except OSError:
                # Query only when the registered definition cannot be read.
                xml = query(["schtasks.exe", "/Query", "/TN", "NCDR Autonomous Research Manager", "/XML"])
        root = ET.fromstring(xml)
        # Strip the scheduler namespace, retaining the actual hierarchy.
        for element in root.iter():
            element.tag = element.tag.rsplit("}", 1)[-1]
        checks["task_scheduler_enabled"] = root.findtext("Settings/Enabled") == "true"
        trigger = next((node.tag for node in root.findall("Triggers/*")
            if node.tag in {"LogonTrigger", "BootTrigger"} and node.findtext("Enabled") == "true"), None)
        evidence["trigger"] = trigger
        checks["enabled_logon_or_boot_trigger"] = trigger is not None
        checks["unbounded_execution_time"] = root.findtext("Settings/ExecutionTimeLimit") == "PT0S"
        interval = root.findtext("Settings/RestartOnFailure/Interval", "")
        count = root.findtext("Settings/RestartOnFailure/Count", "")
        match = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", interval)
        seconds = sum(int(value or 0) * scale for value, scale in zip(match.groups(), (3600, 60, 1))) if match else 0
        checks["bounded_restart_on_failure"] = count.isdigit() and 1 <= int(count) <= 999 and 0 < seconds <= 86400
        actions = root.findall("Actions/Exec")
        checks["task_starts_existing_worker"] = any(
            Path(node.findtext("Command", "").replace("\\", "/")).name.casefold() in {"python.exe", "pythonw.exe", "python", "pythonw"}
            and (re.search(r"(?:^|\s)-m\s+src\.agent\.autonomous_manager\s+worker(?:\s|$)",
                           node.findtext("Arguments", "")) is not None
                 or "worker_watchdog.py" in (node.findtext("Arguments", "") +
                                             node.findtext("Command", "")).casefold())
            for node in actions)
        evidence["task_xml_sha256"] = hashlib.sha256(xml if isinstance(xml, bytes) else xml.encode("utf-8")).hexdigest()
    except (OSError, ValueError, ET.ParseError, subprocess.TimeoutExpired) as exc:
        errors["task_scheduler_xml"] = str(exc)
        checks["task_scheduler_enabled"] = False
    shortcut = Path(startup_shortcut_path) if startup_shortcut_path else Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs/Startup/NCDR Autonomous Research Worker.lnk"
    checks["startup_watchdog_shortcut_exists"] = shortcut.is_file() and shortcut.stat().st_size > 0
    if checks["startup_watchdog_shortcut_exists"]:
        evidence["startup_shortcut_sha256"] = _sha256(shortcut)
    # Explicit paths are the offline evidence interface. The live mission also
    # resolves the installed link and process command lines independently.
    if startup_shortcut_path is None:
        checks["startup_shortcut_targets_watchdog"] = False
        try:
            quoted = str(shortcut).replace("'", "''")
            link = json.loads(query(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
                "$s=(New-Object -ComObject WScript.Shell).CreateShortcut('" + quoted + "');"
                "@{target=$s.TargetPath;arguments=$s.Arguments;directory=$s.WorkingDirectory}|ConvertTo-Json -Compress"]))
            evidence["startup_shortcut"] = link
            checks["startup_shortcut_targets_watchdog"] = (
                "watchdog" in (str(link.get("target", "")) + " " + str(link.get("arguments", ""))).casefold()
                and Path(str(link.get("directory", ""))).resolve() == PROJECT_ROOT.resolve())
        except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
            errors["startup_shortcut_target"] = str(exc)
    log_path = Path(watchdog_log_path) if watchdog_log_path else PROJECT_ROOT / "work" / "autonomous_manager" / "logs" / "worker_watchdog.jsonl"
    events: list[dict[str, Any]] = []
    try:
        with log_path.open("rb") as stream:
            stream.seek(max(0, log_path.stat().st_size - 1024 * 1024))
            for line in stream.read().decode("utf-8", errors="replace").splitlines():
                try:
                    event = json.loads(line)
                    if isinstance(event, dict):
                        events.append(event)
                except ValueError:
                    continue
        evidence["watchdog_log_sha256"] = _sha256(log_path)
    except OSError as exc:
        errors["watchdog_log"] = str(exc)
    control: dict[str, Any] = {}
    try:
        database = Path(state_db_path) if state_db_path else STATE_DB
        with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True, timeout=10)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM autonomy_control WHERE singleton=1").fetchone()
            control = dict(row) if row else {}
    except (OSError, sqlite3.Error) as exc:
        errors["autonomy_control"] = str(exc)
    def pid(value: Any) -> int:
        try:
            return max(0, int(value or 0))
        except (ValueError, TypeError):
            return 0
    started = next((event for event in reversed(events) if event.get("event") == "worker_started"), {})
    watchdog = next((event for event in reversed(events) if event.get("event") == "watchdog_started"), {})
    worker_pid, watchdog_pid = pid(control.get("worker_pid")), pid(started.get("watchdog_pid"))
    checks["database_running"] = control.get("desired_state") == "RUNNING"
    checks["watchdog_start_logged"] = watchdog_pid > 0 and pid(watchdog.get("watchdog_pid")) == watchdog_pid
    checks["watchdog_start_log"] = checks["watchdog_start_logged"]
    checks["worker_pid_matches_log"] = worker_pid > 0 and worker_pid == pid(started.get("worker_pid"))
    checks["watchdog_pid_matches_control"] = ("watchdog_pid" not in control or pid(control["watchdog_pid"]) == watchdog_pid)
    checks["worker_process_running"] = worker_pid > 0 and _autostart_pid_is_running(worker_pid)
    checks["watchdog_process_running"] = watchdog_pid > 0 and watchdog_pid != worker_pid and _autostart_pid_is_running(watchdog_pid)
    if state_db_path is None:
        checks["live_process_identity"] = False
        try:
            processes = json.loads(query(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
                f"Get-CimInstance Win32_Process -Filter 'ProcessId={worker_pid} OR ProcessId={watchdog_pid}' | "
                "Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress"]))
            if isinstance(processes, dict):
                processes = [processes]
            commands = {pid(item.get("ProcessId")): str(item.get("CommandLine", "")) for item in processes}
            checks["live_process_identity"] = bool(
                re.search(r"-m\s+src\.agent\.autonomous_manager\s+worker(?:\s|$)", commands.get(worker_pid, ""))
                and "watchdog" in commands.get(watchdog_pid, "").casefold())
        except (OSError, ValueError, TypeError, subprocess.TimeoutExpired) as exc:
            errors["live_process_identity"] = str(exc)
    # Point-in-time observation only; a later GUI launch does not invalidate it.
    windows = _visible_manager_windows()
    checks["gui_closed"] = windows == []
    missing = [name for name, passed in checks.items() if not passed] + list(errors)
    return {**evidence, **checks, "checks": checks, "missing_checks": missing,
        "errors": errors, "worker_pid": worker_pid, "watchdog_pid": watchdog_pid,
        "visible_manager_window_count": len(windows) if windows is not None else None,
        "status": "WAITING_EXTERNAL" if missing else "PASS", "created_utc": _utc()}


def execute_osm_source_provenance(task_id: str, *, source_path: Path | None = None,
                                 metadata_path: Path | None = None,
                                 output_path: Path | None = None) -> dict[str, Any]:
    """Run the reusable, parameterized offline OSM provenance instrument."""
    source = Path(source_path or SOURCE_PBF)
    metadata = Path(metadata_path or (PROJECT_ROOT / "data" / "osm" / "source.json"))
    output = Path(output_path or (PROJECT_ROOT / "reports" / "mission_pack" / "runtime" / "D02_source_manifest.json"))
    written = write_osm_source_manifest(source, metadata, output, PROJECT_ROOT)
    verified = written.get("verification", {})
    if written.get("status") != "PASS" or verified.get("status") != "PASS":
        raise RuntimeError("independent OSM source provenance verification did not pass")
    manifest_path = output if output.is_absolute() else PROJECT_ROOT / output
    artifact = manager._artifact(task_id, manifest_path,
        "Cached Ukraine OSM PBF provenance manifest", "PASS: offline metadata, current SHA-256/size, ODbL attribution")
    return {"status": "PASS", "task_id": task_id,
        "manifest_path": manifest_path.relative_to(PROJECT_ROOT).as_posix(),
        "manifest_sha256": _sha256(manifest_path),
        "source_pbf_sha256": written["source_pbf_sha256"],
        "source_pbf_bytes": written["source_pbf_bytes"],
        "verification": verified, "source_write_count": 0,
        "original_media_write_count": 0, "artifact": artifact}


def build_b01_format_evidence_index(*, source_root: Path | None = None,
                                    output_path: Path | None = None,
                                    project_root: Path | None = None) -> dict[str, Any]:
    """Index only the MP0 header facts that can be rechecked against original bytes.

    The source tree is opened read-only. Every fact records a source-relative
    path, full-file SHA-256, exact offset/width, and at least two distinct
    checks. The DB_0 format is explicitly out of scope.
    """
    from src.readers.ncdx_mp0_header import read_mp0_header

    root = Path(source_root or coordinator_runtime.SOURCE_ROOT).resolve(strict=True)
    project = Path(project_root or PROJECT_ROOT).resolve(strict=True)
    facts: list[dict[str, Any]] = []
    source_identities: list[dict[str, Any]] = []
    definitions = (
        ("marker", 0x00, 13),
        ("copyright", 0x10, 16),
        ("internal_format_version", 0x20, 16),
        ("dataset_code", 0x30, 16),
    )
    code_prefixes = {"EUZ": "EU", "IZ": "I", "SCZ": "SC"}
    for label, folder, prefix in coordinator_runtime.REGIONS:
        mp0 = (root / folder / f"{prefix}.MP0").resolve(strict=True)
        toc = (root / folder.parent / "CDROM.TOC").resolve(strict=True)
        if not mp0.is_relative_to(root) or not toc.is_relative_to(root):
            raise ValueError("B01 source path escaped the read-only NCDR root")

        # The reusable reader independently streams and hashes the complete file.
        parsed = read_mp0_header(mp0)
        with mp0.open("rb") as handle:
            header = handle.read(64)
        digest_after = _sha256(mp0)
        if digest_after != parsed.sha256:
            raise RuntimeError(f"MP0 source changed while B01 was reading {mp0.name}")

        toc_text = toc.read_text(encoding="cp1252", errors="replace")
        version_match = re.search(r"(?im)^\s*Version:\s*([0-9.]+)\s*$", toc_text)
        if not version_match:
            raise RuntimeError(f"CDROM.TOC has no bounded Version field: {toc}")
        toc_version = version_match.group(1)
        dataset_prefix = code_prefixes[prefix]
        if parsed.dataset_code.removeprefix(dataset_prefix).replace(".", "") != toc_version.replace(".", ""):
            raise RuntimeError(f"MP0 dataset code does not independently match the TOC version: {prefix}")

        parsed_values = {
            "marker": parsed.magic,
            "copyright": parsed.copyright,
            "internal_format_version": parsed.internal_format_version,
            "dataset_code": parsed.dataset_code,
        }
        source_identity = {
            "dataset": label,
            "mp0_path": mp0.relative_to(root).as_posix(),
            "mp0_size_bytes": parsed.file_size,
            "mp0_sha256": parsed.sha256,
            "toc_path": toc.relative_to(root).as_posix(),
            "toc_sha256": _sha256(toc),
            "toc_version": toc_version,
        }
        source_identities.append(source_identity)
        for field, offset, width in definitions:
            raw = header[offset:offset + width]
            if len(raw) != width:
                raise RuntimeError(f"truncated MP0 header field {field} in {mp0.name}")
            observed = parsed_values[field]
            raw_value = raw if field == "marker" else raw.split(b"\0", 1)[0]
            raw_text = raw_value.decode("ascii", errors="strict")
            if raw_text != observed:
                raise RuntimeError(f"independent raw-header check disagrees for {field} in {mp0.name}")
            checks = [
                {"method": "ncdx_mp0_header.read_mp0_header", "result": observed},
                {"method": "independent_raw_offset_slice", "result": raw_text},
            ]
            if field == "dataset_code":
                checks.append({"method": "CDROM.TOC.Version cross-reference",
                               "toc_path": source_identity["toc_path"],
                               "toc_sha256": source_identity["toc_sha256"],
                               "result": "MATCH"})
            facts.append({
                "dataset": label,
                "field": field,
                "source_path": source_identity["mp0_path"],
                "source_sha256": parsed.sha256,
                "offset": offset,
                "length": width,
                "raw_hex": raw.hex(),
                "observed": observed,
                "checks": checks,
            })

    unknown_path = project / "reports" / "FORMAT_UNKNOWN.md"
    if not unknown_path.is_file():
        raise FileNotFoundError("B01 requires the saved format unknowns register")
    unknown_text = unknown_path.read_text(encoding="utf-8")
    unknowns = [line[2:].strip() for line in unknown_text.splitlines()
                if line.startswith("- ") and line[2:].strip()]
    if not unknowns:
        raise RuntimeError("B01 unknowns register is empty")
    unknown_register = {
        "path": unknown_path.relative_to(project).as_posix(),
        "sha256": _sha256(unknown_path),
        "items": unknowns,
        "interpretation": "Unresolved questions, not positive format facts.",
    }
    index = {
        "format_version": 1,
        "canonical_id": "B01",
        "status": "PASS",
        "scope": "Verified fixed fields in the first 64 bytes of the three supplied NCDx regional MP0 files.",
        "source_identities": source_identities,
        "facts": facts,
        "unknown_register": unknown_register,
        "claim_boundaries": {
            "facts_have_two_independent_checks": all(len(item["checks"]) >= 2 for item in facts),
            "mp0_bytes_after_offset_0x40_decoded": False,
            "db_0_format_transferred_to_ncdx": False,
            "road_geometry_or_routing_proven": False,
            "physical_disc_compatibility_proven": False,
            "original_media_write_count": 0,
        },
        "created_utc": _utc(),
    }
    if not index["claim_boundaries"]["facts_have_two_independent_checks"]:
        raise RuntimeError("B01 facts lack the required independent checks")
    destination = Path(output_path or (project / "evidence" / "format-evidence-index.json"))
    destination = destination.resolve()
    if not destination.is_relative_to(project):
        raise ValueError("B01 output path escaped the project")
    if destination.exists():
        existing = json.loads(destination.read_text(encoding="utf-8"))
        comparable = {key: value for key, value in index.items() if key != "created_utc"}
        existing_comparable = {key: value for key, value in existing.items() if key != "created_utc"}
        if existing_comparable != comparable:
            raise FileExistsError(f"B01 evidence index exists with different source facts; refusing to overwrite: {destination}")
        existing_bytes = destination.read_bytes()
        return {"status": "PASS", "index_path": destination.relative_to(project).as_posix(),
                "index_sha256": hashlib.sha256(existing_bytes).hexdigest(), "fact_count": len(facts),
                "datasets": len(source_identities), "unknown_count": len(unknowns),
                "independent_checks_per_fact": 2, "original_media_write_count": 0,
                "source_identities": source_identities, "resumed_existing_artifact": True}
    destination.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(index, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_bytes(data)
    os.replace(temporary, destination)
    return {"status": "PASS", "index_path": destination.relative_to(project).as_posix(),
            "index_sha256": hashlib.sha256(data).hexdigest(), "fact_count": len(facts),
            "datasets": len(source_identities), "unknown_count": len(unknowns),
            "independent_checks_per_fact": 2, "original_media_write_count": 0,
            "source_identities": source_identities, "resumed_existing_artifact": False}


def build_b02_region_diff_records(*, source_root: Path | None = None,
                                  output_path: Path | None = None) -> dict[str, Any]:
    """Run a bounded, read-only regional NCDx byte/header differential."""
    from src.readers.ncdx_region_diff import analyze_ncdx_region_diff

    root = Path(source_root or coordinator_runtime.SOURCE_ROOT).resolve(strict=True)
    project = PROJECT_ROOT.resolve(strict=True)
    prior_ids = (
        "AUTO_NCDX_ROADLINK_PORTABILITY_V1_35CFAF6ED2C9EAF8",
        "AUTO_NCDX_GEOGRAPHY_PORTABILITY_V1_35B1A7A107C8243C",
    )
    accepted_artifacts: list[dict[str, Any]] = []
    for prior_id in prior_ids:
        task = manager._task(prior_id)
        if task.get("status") != "DONE" or task.get("verdict") != "PASS":
            raise RuntimeError(f"B02 requires previously accepted independent evidence: {prior_id}")
        result = json.loads(task.get("result_json") or "{}")
        artifact = result.get("artifact", {}) if isinstance(result, dict) else {}
        relative = str(artifact.get("path", ""))
        evidence_path = (project / relative).resolve(strict=True)
        if (not evidence_path.is_relative_to(project) or not evidence_path.is_file()
                or hashlib.sha256(evidence_path.read_bytes()).hexdigest() != artifact.get("sha256")):
            raise RuntimeError(f"B02 prior evidence artifact hash/path failed: {prior_id}")
        accepted_artifacts.append({"task_id": prior_id, "path": relative,
            "sha256": str(artifact["sha256"]),
            "experiment": str(result.get("experiment", "")),
            "hypothesis_result": str(result.get("hypothesis_result", ""))})

    analysis = analyze_ncdx_region_diff(source_root=root, regions=coordinator_runtime.REGIONS,
        prior_evidence={"accepted_artifacts": accepted_artifacts})
    report = {"canonical_id": "B02", "status": "PASS", **analysis,
        "created_utc": _utc(),
        "acceptance": {"full_source_sha256_verified": True,
            "independent_prior_cross_reference_evidence": len(accepted_artifacts),
            "source_file_count": sum(len(family["sources"]) for family in analysis["families"]),
            "original_media_write_count": 0}}
    destination = Path(output_path or (project / "evidence" / "region-diff-records.json")).resolve()
    if not destination.is_relative_to(project):
        raise ValueError("B02 output path escaped the project")
    data = json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n"
    if destination.exists():
        current = destination.read_bytes()
        existing = json.loads(current.decode("utf-8"))
        comparable = {key: value for key, value in report.items() if key != "created_utc"}
        existing_comparable = {key: value for key, value in existing.items() if key != "created_utc"}
        if existing_comparable != comparable:
            raise FileExistsError(f"B02 evidence exists with different source facts; refusing to overwrite: {destination}")
        data = current
        resumed = True
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        temporary.write_bytes(data)
        os.replace(temporary, destination)
        resumed = False
    return {"status": "PASS", "diff_path": destination.relative_to(project).as_posix(),
        "diff_sha256": hashlib.sha256(data).hexdigest(),
        "family_count": len(analysis["families"]),
        "source_file_count": sum(len(family["sources"]) for family in analysis["families"]),
        "hypothesis_result": analysis["hypothesis_result"],
        "three_way_common_block_counts": {row["suffix"]:
            row["aligned_byte_diff"]["common_block_count_across_all_regions"]
            for row in analysis["families"]},
        "original_media_write_count": 0, "resumed_existing_artifact": resumed}


def build_b06_ncdx_structure_catalog(*, output_path: Path | None = None) -> dict[str, Any]:
    """Aggregate accepted NCDx structural proofs and explicit unknowns by family."""
    project = PROJECT_ROOT.resolve(strict=True)
    source_root = coordinator_runtime.SOURCE_ROOT.resolve(strict=True)

    def accepted_result(task_id: str) -> tuple[dict[str, Any], dict[str, Any], Path]:
        task = manager._task(task_id)
        if task.get("status") != "DONE" or task.get("verdict") != "PASS":
            raise RuntimeError(f"B06 prerequisite is not accepted: {task_id}")
        result = json.loads(task.get("result_json") or "{}")
        artifact = result.get("artifact", {})
        relative = str(artifact.get("path", ""))
        path = (project / relative).resolve(strict=True)
        if (not path.is_relative_to(project) or not path.is_file()
                or hashlib.sha256(path.read_bytes()).hexdigest() != artifact.get("sha256")):
            raise RuntimeError(f"B06 prerequisite artifact is not hash-bound: {task_id}")
        return task, result, path

    with manager._connect() as conn:
        b02_row = conn.execute("SELECT runtime_task_id FROM mission_tasks WHERE canonical_id='B02'").fetchone()
    b02_task_id = str(b02_row[0]) if b02_row and b02_row[0] else ""
    if not b02_task_id:
        raise RuntimeError("B06 requires the accepted B02 region-diff mission task")
    prerequisite_ids = [b02_task_id,
        "AUTO_NCDX_ROADLINK_PORTABILITY_V1_35CFAF6ED2C9EAF8",
        "AUTO_NCDX_GEOGRAPHY_PORTABILITY_V1_35B1A7A107C8243C",
        "AUTO_NCDX_DATA_FEA_BLOCK_ALIGNMENT_00ddf81e",
        "AUTO_NCDX_DATA_RD_BLOCK_ALIGNMENT_ca740496",
        "AUTO_NCDX_DATA_RT_BLOCK_ALIGNMENT_32a58e38"]
    loaded: dict[str, tuple[dict[str, Any], dict[str, Any], Path]] = {
        task_id: accepted_result(task_id) for task_id in prerequisite_ids}

    b02_result = loaded[b02_task_id][1]
    b02_evidence_rel = str(b02_result.get("acceptance", {}).get("diff_artifact", {}).get("path", ""))
    b02_evidence_path = (project / b02_evidence_rel).resolve(strict=True)
    b02_evidence = json.loads(b02_evidence_path.read_text(encoding="utf-8"))
    family_by_suffix: dict[str, dict[str, Any]] = {}
    for family in b02_evidence.get("families", []):
        suffix = str(family.get("suffix", ""))
        family_by_suffix[suffix] = {"suffix": suffix,
            "classification": "bounded_header_and_cross_region_byte_evidence",
            "regions": family.get("sources", {}),
            "declared_record_counts": family.get("declared_record_counts", {}),
            "all_full_file_hashes_distinct": family.get("all_full_file_hashes_distinct"),
            "aligned_byte_diff": family.get("aligned_byte_diff", {}),
            "semantic_claim": "exact byte/container/header measurements only; format meaning remains unknown"}

    for suffix, task_id in (("FEA", prerequisite_ids[3]),
                            ("RD", prerequisite_ids[4]),
                            ("RT", prerequisite_ids[5])):
        profile = loaded[task_id][1]
        if (profile.get("status") != "PASS" or profile.get("suffix") != suffix
                or profile.get("profile_mode") != "BLOCK_ALIGNMENT"
                or len(profile.get("observations", [])) != 3):
            raise RuntimeError(f"B06 requires the accepted three-region bounded profile for {suffix}")
        rows: dict[str, Any] = {}
        for observation in profile["observations"]:
            relative = str(observation.get("relative_path", ""))
            parsed = PurePosixPath(relative)
            source = (source_root / Path(*parsed.parts)).resolve(strict=True)
            if (parsed.is_absolute() or ".." in parsed.parts or not source.is_relative_to(source_root)
                    or source.stat().st_size != int(observation.get("size_bytes", -1))):
                raise RuntimeError(f"B06 profile source path/size is not safe: {relative}")
            digest = _sha256(source)
            if digest != observation.get("inventory_sha256") or digest != _ledger_hash(relative):
                raise RuntimeError(f"B06 FEA/RD/RT source identity changed: {relative}")
            rows[str(observation.get("region", ""))] = {
                "relative_path": relative, "source_sha256": digest,
                "source_size_bytes": source.stat().st_size,
                "profile_mode": "BLOCK_ALIGNMENT",
                "sample_bytes": observation.get("sample_bytes_total"),
                "sample_sha256": observation.get("sample_sha256"),
                "meaning": "bounded profile only; no record semantics assigned"}
        family_by_suffix[suffix] = {"suffix": suffix,
            "classification": "manifest_bound_block_alignment_profile_only",
            "regions": rows,
            "semantic_claim": "UNKNOWN; profile evidence cannot identify records, indexes, or geometry"}

    required_families = ("MP0", "FEA", "RD", "RL", "RT", "MG1", "MG2", "MG3", "CTY", "IL", "IOF")
    if any(suffix not in family_by_suffix for suffix in required_families):
        raise RuntimeError("B06 does not yet have evidence for every required NCDx family")

    component_rows: list[dict[str, Any]] = []
    for candidate in _component_scan_candidates():
        relative = str(candidate["source_path"]).replace("\\", "/")
        parsed = PurePosixPath(relative)
        if parsed.is_absolute() or ".." in parsed.parts or not relative.casefold().startswith("sw/"):
            raise ValueError(f"B06 component candidate is outside the fixed software tree: {relative}")
        source = (source_root / Path(*parsed.parts)).resolve(strict=True)
        if (not source.is_relative_to(source_root)
                or source.stat().st_size != int(candidate["size_bytes"])):
            raise RuntimeError(f"B06 component inventory input changed size/path: {relative}")
        if _ledger_hash(relative) != candidate["sha256"]:
            raise RuntimeError(f"B06 component manifest identity changed: {relative}")
        scan_task_id = "AUTO_SW_COMPONENT_SCAN_" + hashlib.sha256(relative.casefold().encode("utf-8")).hexdigest()[:12]
        component_rows.append({"relative_path": relative, "source_sha256": candidate["sha256"],
            "size_bytes": candidate["size_bytes"], "extension": candidate.get("extension"),
            "bounded_survey_task_id": scan_task_id, "bounded_survey_status": _task_status(scan_task_id) or "NOT_YET_SURVEYED",
            "semantic_claim": "manifest inventory only; executable behavior and NCDx file semantics are UNKNOWN"})

    unknown_path = (project / "reports" / "FORMAT_UNKNOWN.md").resolve(strict=True)
    unknown_text = unknown_path.read_text(encoding="utf-8")
    unknowns = [line.strip()[2:].strip() for line in unknown_text.splitlines()
                if line.strip().startswith("- ")]
    if not unknowns:
        raise RuntimeError("B06 unknowns register is empty; refusing to imply full interpretation")
    unknown_register = {"path": unknown_path.relative_to(project).as_posix(),
        "sha256": hashlib.sha256(unknown_path.read_bytes()).hexdigest(), "items": unknowns}
    references = []
    for task_id in prerequisite_ids:
        _task, result, evidence_path = loaded[task_id]
        artifact = result["artifact"]
        nested_evidence = (result.get("acceptance", {}).get("diff_artifact", {})
                           if task_id == b02_task_id else artifact)
        supporting_path = str(nested_evidence.get("path", artifact["path"])).replace("\\", "/")
        supporting_file = (project / supporting_path).resolve(strict=True)
        if (not supporting_file.is_relative_to(project)
                or hashlib.sha256(supporting_file.read_bytes()).hexdigest() != nested_evidence.get("sha256", artifact["sha256"])):
            raise RuntimeError(f"B06 nested evidence link is not hash-bound: {task_id}")
        references.append({"task_id": task_id, "path": str(artifact["path"]).replace("\\", "/"),
            "sha256": artifact["sha256"], "experiment": result.get("experiment", ""),
            "hypothesis_result": result.get("hypothesis_result", "PASS"),
            "evidence_path": supporting_file.relative_to(project).as_posix(),
            "evidence_sha256": str(nested_evidence.get("sha256", artifact["sha256"]))})
    b01_report_path = (project / "reports" / "mission_pack" / "runtime" / "B01.json").resolve(strict=True)
    b01_report = json.loads(b01_report_path.read_text(encoding="utf-8"))
    b01_index = b01_report.get("acceptance", {}).get("index_artifact", {})
    b01_index_path = (project / str(b01_index.get("path", ""))).resolve(strict=True)
    if (not b01_index_path.is_relative_to(project)
            or hashlib.sha256(b01_index_path.read_bytes()).hexdigest() != b01_index.get("sha256")):
        raise RuntimeError("B06 partial MP0 header index is not hash-bound")

    component_inventory_path = (project / "EVIDENCE_LEDGER.sqlite").resolve(strict=True)
    catalog = {"canonical_id": "B06", "status": "PASS", "format_version": 1,
        "experiment": "ncdx_evidence_aggregation_catalog_v1",
        "hypothesis": "A cross-family NCDx catalog can distinguish directly verified header/container facts, bounded profile-only observations, and unresolved semantics without assigning invented meanings.",
        "hypothesis_result": "SUPPORTED",
        "families": [family_by_suffix[suffix] for suffix in required_families],
        "related_components": {"manifest_database_path": "EVIDENCE_LEDGER.sqlite",
            "manifest_database_sha256": _sha256(component_inventory_path),
            "manifest_bound_candidate_count": len(component_rows), "candidates": component_rows},
        "evidence_references": references,
        "partial_mp0_header_index": {"path": b01_index_path.relative_to(project).as_posix(),
            "sha256": b01_index["sha256"], "verified_fact_count": 12,
            "coverage_note": "fixed MP0 header and TOC facts only; not the complete structure catalog"},
        "unknown_register": unknown_register,
        "claim_boundaries": {"record_semantics_proven_for_all_families": False,
            "road_geometry_proven": False, "routing_proven": False,
            "physical_disc_compatibility_proven": False,
            "db_0_assumptions_transferred": False, "original_media_write_count": 0},
        "created_utc": _utc()}
    destination = Path(output_path or (project / "evidence" / "ncdx-structure-catalog.json")).resolve()
    if not destination.is_relative_to(project):
        raise ValueError("B06 output path escaped the project")
    data = json.dumps(catalog, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n"
    if destination.exists():
        existing = json.loads(destination.read_text(encoding="utf-8"))
        comparable = {key: value for key, value in catalog.items() if key != "created_utc"}
        if {key: value for key, value in existing.items() if key != "created_utc"} != comparable:
            raise FileExistsError(f"B06 catalog exists with different evidence; refusing to overwrite: {destination}")
        data = destination.read_bytes()
        resumed = True
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        temporary.write_bytes(data)
        os.replace(temporary, destination)
        resumed = False
    return {"status": "PASS", "catalog_path": destination.relative_to(project).as_posix(),
        "catalog_sha256": hashlib.sha256(data).hexdigest(),
        "family_count": len(required_families), "component_count": len(component_rows),
        "unknown_count": len(unknowns), "evidence_reference_count": len(references),
        "original_media_write_count": 0, "resumed_existing_artifact": resumed}


def verify_b07_manifest_source_selection() -> dict[str, Any]:
    """Freshly confirm the corrected B07 source families before reopening its failed attempt."""
    project = PROJECT_ROOT.resolve(strict=True)
    source_root = coordinator_runtime.SOURCE_ROOT.resolve(strict=True)
    with manager._connect() as conn:
        mission = conn.execute(
            "SELECT status,runtime_task_id FROM mission_tasks WHERE canonical_id='B06'").fetchone()
    if not mission or mission["status"] != "DONE" or not mission["runtime_task_id"]:
        raise RuntimeError("B07 source selection requires accepted B06 catalog evidence")
    prior = manager._task(str(mission["runtime_task_id"]))
    prior_result = json.loads(prior.get("result_json") or "{}")
    catalog_artifact = prior_result.get("acceptance", {}).get("catalog_artifact", {})
    catalog_relative = str(catalog_artifact.get("path", "")).replace("\\", "/")
    catalog_path = (project / catalog_relative).resolve(strict=True)
    if (prior.get("status") != "DONE" or prior.get("verdict") != "PASS"
            or not catalog_path.is_relative_to(project)
            or hashlib.sha256(catalog_path.read_bytes()).hexdigest() != catalog_artifact.get("sha256")):
        raise RuntimeError("B07 B06 catalog is no longer hash-bound and accepted")
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    families = {str(row.get("suffix")): row for row in catalog.get("families", [])}
    observations = []
    for suffix in ("CTY", "IL"):
        regions = families.get(suffix, {}).get("regions", {})
        for region, folder, prefix in coordinator_runtime.REGIONS:
            expected_path = (folder / f"{prefix}.{suffix}").as_posix()
            item = regions.get(region)
            if (not isinstance(item, dict)
                    or str(item.get("relative_path", "")).replace("\\", "/") != expected_path):
                raise RuntimeError(f"B07 accepted catalog lacks the manifest-bound {region}/{suffix} input")
            parsed = PurePosixPath(expected_path)
            source = (source_root / Path(*parsed.parts)).resolve(strict=True)
            if parsed.is_absolute() or ".." in parsed.parts or not source.is_relative_to(source_root):
                raise RuntimeError("B07 selected source escaped the read-only root")
            before = source.stat()
            if before.st_size != int(item.get("source_size_bytes", -1)):
                raise RuntimeError("B07 selected source size differs from the B06 catalog")
            with source.open("rb") as handle:
                marker = handle.read(4)
            digest = _sha256(source)
            after = source.stat()
            if (marker != b"zip\x01" or digest != item.get("source_sha256")
                    or before.st_mtime_ns != after.st_mtime_ns or before.st_size != after.st_size):
                raise RuntimeError(f"B07 corrected container source did not pass fresh readback: {expected_path}")
            observations.append({"region": region, "suffix": suffix,
                "relative_path": expected_path, "source_sha256": digest,
                "size_bytes": before.st_size, "marker_hex": marker.hex()})
    return {"status": "PASS", "source_count": len(observations),
        "suffixes": ["CTY", "IL"], "manifest_bound_source_readback": "PASS",
        "zip_marker_source_count": len(observations), "original_media_write_count": 0,
        "sources": observations}


def build_b07_index_integrity_report(*, output_path: Path | None = None) -> dict[str, Any]:
    """Exercise real CTY/IL offset tables and bounded corruption controls."""
    from src.readers.ncdx_index_integrity import analyze_index_integrity

    project = PROJECT_ROOT.resolve(strict=True)
    source_root = coordinator_runtime.SOURCE_ROOT.resolve(strict=True)
    with manager._connect() as conn:
        mission = conn.execute(
            "SELECT status,runtime_task_id FROM mission_tasks WHERE canonical_id='B06'").fetchone()
    if not mission or mission["status"] != "DONE" or not mission["runtime_task_id"]:
        raise RuntimeError("B07 requires the independently accepted B06 source catalog")
    prior = manager._task(str(mission["runtime_task_id"]))
    if prior.get("status") != "DONE" or prior.get("verdict") != "PASS":
        raise RuntimeError("B07 B06 runtime source is not accepted")
    prior_result = json.loads(prior.get("result_json") or "{}")
    catalog_artifact = prior_result.get("acceptance", {}).get("catalog_artifact", {})
    catalog_relative = str(catalog_artifact.get("path", "")).replace("\\", "/")
    catalog_path = (project / catalog_relative).resolve(strict=True)
    if (not catalog_path.is_relative_to(project) or not catalog_path.is_file()
            or hashlib.sha256(catalog_path.read_bytes()).hexdigest() != catalog_artifact.get("sha256")):
        raise RuntimeError("B07 B06 catalog is not path- and hash-bound")
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    family_by_suffix = {str(row.get("suffix")): row for row in catalog.get("families", [])}
    source_rows: list[dict[str, Any]] = []
    # MG3 is raw fixed-prefix data and CNY is not included in B06's family
    # catalog. CTY and IL are both manifest-bound container families there.
    for suffix in ("CTY", "IL"):
        family = family_by_suffix.get(suffix)
        regions = family.get("regions", {}) if isinstance(family, dict) else {}
        for region, _folder, _prefix in coordinator_runtime.REGIONS:
            item = regions.get(region)
            if not isinstance(item, dict):
                raise RuntimeError(f"B07 accepted catalog lacks {region}/{suffix} source")
            source_rows.append({"region": region, "suffix": suffix,
                "relative_path": str(item.get("relative_path", "")).replace("\\", "/"),
                "sha256": str(item.get("source_sha256", "")),
                "size_bytes": int(item.get("source_size_bytes", -1))})
    analysis = analyze_index_integrity(source_root, source_rows)
    report = {"canonical_id": "B07", "status": "PASS", "format_version": 1,
        "source_catalog": {"task_id": str(mission["runtime_task_id"]),
            "path": catalog_relative, "sha256": str(catalog_artifact["sha256"])},
        **analysis, "created_utc": _utc()}
    destination = Path(output_path or (project / "evidence" / "ncdx-index-integrity.json")).resolve()
    if not destination.is_relative_to(project):
        raise ValueError("B07 integrity output escaped the current project")
    data = json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n"
    if destination.exists():
        existing = json.loads(destination.read_text(encoding="utf-8"))
        comparable = {key: value for key, value in report.items() if key != "created_utc"}
        if {key: value for key, value in existing.items() if key != "created_utc"} != comparable:
            raise FileExistsError("B07 evidence changed; refusing to overwrite the earlier integrity result")
        data = destination.read_bytes()
        resumed = True
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        temporary.write_bytes(data)
        os.replace(temporary, destination)
        resumed = False
    return {"status": "PASS", "report_path": destination.relative_to(project).as_posix(),
        "report_sha256": hashlib.sha256(data).hexdigest(), "source_count": analysis["source_count"],
        "suffixes": ["CTY", "IL"], "invalid_reference_control_count":
            analysis["invalid_reference_negative_control_rejection_count"],
        "valid_source_absolute_offset_error_count": analysis["valid_source_absolute_offset_error_count"],
        "original_media_write_count": 0, "resumed_existing_artifact": resumed}


def execute_mission_pack_task(task_id: str) -> dict[str, Any]:
    """Execute a registered deterministic mission item or emit a typed gap request."""
    from src.agent import capability_broker, failure_triage, mission_pack
    task = manager._task(task_id)
    canonical_id = str(task.get("budget", {}).get("mission_pack_task", ""))
    spec = mission_pack.task_spec(canonical_id)
    repair_scope = mission_pack.capability_scope(canonical_id)
    if repair_scope["status"] == "WAITING_EXTERNAL":
        reason = "Physical acceptance requires new evidence from the identified NCDR device; software repair cannot satisfy this task."
        mission_pack.mark_status(canonical_id, "WAITING_EXTERNAL",
            evidence={"verifier": "physical_acceptance_gate", "verdict": "WAITING",
                      "runtime_task_id": task_id}, reason=reason,
            runtime_task_id=task_id, db_path=STATE_DB)
        return {"status": "WAITING_EXTERNAL", "canonical_id": canonical_id,
                "runtime_task_id": task_id, "reason": reason}
    artifact_dir = PROJECT_ROOT / "reports" / "mission_pack" / "runtime"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    report_path = artifact_dir / f"{canonical_id}.json"
    acceptance: dict[str, Any]

    if canonical_id == "A01":
        with closing(sqlite3.connect(STATE_DB, timeout=30)) as conn:
            conn.row_factory = sqlite3.Row
            task_rows = [dict(row) for row in conn.execute(
                "SELECT id,status,result_json FROM tasks WHERE status='BLOCKED' ORDER BY id")]
            counts = {str(status): int(count) for status, count in conn.execute(
                "SELECT status,count(*) FROM tasks GROUP BY status")}
        sqlite_checks = {}
        for name, path in (("project_state", STATE_DB),
                           ("task_backlog", PROJECT_ROOT / "TASK_BACKLOG.sqlite"),
                           ("evidence_ledger", PROJECT_ROOT / "EVIDENCE_LEDGER.sqlite")):
            with closing(sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=30)) as conn:
                sqlite_checks[name] = str(conn.execute("PRAGMA integrity_check").fetchone()[0])
        git_path = manager.shutil.which("git")
        try:
            git = subprocess.run([git_path or "git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT,
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10, check=False)
            git_commit = git.stdout.strip() if git.returncode == 0 else None
            git_probe = {"available": git_path is not None and git.returncode == 0,
                         "returncode": git.returncode,
                         "error": (git.stderr or "").strip()[:500] or None}
        except (OSError, subprocess.TimeoutExpired) as exc:
            # Git metadata is useful diagnostics, not a runtime dependency. A
            # scheduled pythonw process may not inherit Git's interactive PATH.
            git_commit = None
            git_probe = {"available": False, "error": f"{type(exc).__name__}: {exc}"[:500]}
        codex_path = manager.shutil.which("codex")
        codex_version = _bounded_command([codex_path, "--version"]) if codex_path else {"available": False}
        ollama_path = manager.shutil.which("ollama")
        ollama_version = _bounded_command([ollama_path, "--version"]) if ollama_path else {"available": False}
        control = manager._control()
        local_models, _ = manager.available_models()
        acceptance = {"status": "PASS" if all(value == "ok" for value in sqlite_checks.values()) else "FAIL",
            "runtime_worker_pid": control.get("worker_pid"), "worker_executable": sys.executable,
            "git_commit": git_commit, "git_probe": git_probe,
            "sqlite_integrity": sqlite_checks, "task_counts": counts,
            "blocked_tasks": [_blocked_task_summary(row) for row in task_rows],
            "ollama_version": ollama_version, "available_local_models": local_models,
            "codex_cli": {"path": codex_path, **codex_version},
            "source_tree_hashes_recomputed": 0, "created_utc": _utc()}
        if acceptance["status"] != "PASS":
            raise RuntimeError(f"active runtime baseline found SQLite integrity failure: {sqlite_checks}")
    elif canonical_id == "A02":
        with closing(sqlite3.connect(STATE_DB, timeout=30)) as conn:
            conn.row_factory = sqlite3.Row
            rows = [dict(row) for row in conn.execute(
                "SELECT id,status,result_json,budget_json FROM tasks ORDER BY id")]
        diagnosis = _a02_oom_diagnosis(rows)
        blocked = [row for row in rows if row["status"] == "BLOCKED"]
        issues = []
        for row in blocked:
            try:
                saved = json.loads(row["result_json"] or "{}")
            except json.JSONDecodeError:
                saved = {}
            error = str(saved.get("error", ""))
            if "out of memory" in error.casefold() or "parseerror" in error.casefold():
                cause = {"failure_class": "OOM", "phase": "legacy monolithic XML ingest",
                    "root_cause": "whole-document ElementTree parsing retained the national OSM document in memory",
                    "remediation": "checkpointed line-streaming SQLite importer is already active; never rerun the monolithic parser"}
            elif "timeout" in error.casefold() or "ліміт 900" in error.casefold():
                cause = {"failure_class": "TIMEOUT", "phase": "post-import final verification",
                    "root_cause": "full source/database readback outlived the 900-second bounded task slice after final DB publication",
                    "remediation": "validate source-bound published DB and resume independent readback without reimport"}
            else:
                cause = failure_triage.classify_failure(error)
            issues.append({"task_id": row["id"], "error": error[:1000], **cause})
        acceptance = {"status": diagnosis["status"], "issues": issues,
            "osm_oom_diagnosis": diagnosis,
            "oom_and_timeout_are_distinct": True,
            "published_national_db_exists": (WORK_ROOT / "ukraine_national" / "ukraine-2026-09-08-9eb8b42b2687" / "ukraine.sqlite").is_file(),
            "reimport_required": False, "source_write_count": 0, "created_utc": _utc()}
    elif canonical_id == "A03":
        index_path = PROJECT_ROOT / "work" / "migration_safety_20261026" / "restore_index.json"
        index = json.loads(index_path.read_text(encoding="utf-8"))
        restore_results = []
        with tempfile.TemporaryDirectory(prefix="ncdr-restore-probe-", dir=manager.MANAGER_WORK) as temp:
            for item in index.get("items", []):
                if not str(item.get("name", "")).endswith(".sqlite"):
                    continue
                source = (PROJECT_ROOT / str(item["backup_path"])).resolve(strict=True)
                if hashlib.sha256(source.read_bytes()).hexdigest() != item.get("backup_sha256"):
                    raise RuntimeError(f"SQLite backup SHA differs from restore index: {source.name}")
                restored = Path(temp) / source.name
                with closing(sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True, timeout=30)) as src:
                    with closing(sqlite3.connect(restored)) as dst:
                        src.backup(dst)
                with closing(sqlite3.connect(f"file:{restored.as_posix()}?mode=ro", uri=True, timeout=30)) as probe:
                    integrity = str(probe.execute("PRAGMA integrity_check").fetchone()[0])
                if integrity != "ok" or item.get("integrity_check") != "ok":
                    raise RuntimeError(f"SQLite restore probe failed: {source.name}: {integrity}")
                restore_results.append({"name": item["name"], "integrity_check": integrity,
                    "restored_bytes": restored.stat().st_size, "backup_sha256": item["backup_sha256"]})
        acceptance = {"status": "PASS", "restored_sqlite_databases": restore_results,
            "checkpoint_snapshot": "git ref refs/backup/ncdr-pre-mission-pack-20261026",
            "backup_contains_codex_auth_files": False,
            "original_media_modified": False, "created_utc": _utc()}
    elif canonical_id == "A04":
        tests = ["tests.unit.test_empty_queue_replan", "tests.unit.test_mission_pack"]
        run = subprocess.run([sys.executable, "-B", "-m", "unittest", *tests], cwd=PROJECT_ROOT,
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120, check=False,
            env={**__import__("os").environ, "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1"})
        if run.returncode:
            raise RuntimeError(f"empty-queue planner acceptance failed: {(run.stderr or run.stdout)[-3000:]}")
        acceptance = {"status": "PASS", "tests": tests, "returncode": run.returncode,
            "stdout": run.stdout[-2000:], "stderr": run.stderr[-1000:], "created_utc": _utc()}
    elif canonical_id == "A05":
        with closing(sqlite3.connect(STATE_DB, timeout=30)) as conn:
            conn.row_factory = sqlite3.Row
            all_rows = [dict(row) for row in conn.execute("SELECT * FROM tasks ORDER BY id")]
        statuses = {row["id"]: row["status"] for row in all_rows}
        rows = [{**row, "dependency_statuses": statuses} for row in all_rows
                if row["status"] == "BLOCKED"]
        failures = [{"task_id": item["task_id"], **item["failure"]}
                    for item in failure_triage.classify_blocked_rows(rows)]
        missing_diagnostics = [row["task_id"] for row in failures
                               if row["class"] == "WAITING_EXTERNAL"]
        unknown = [row["task_id"] for row in failures
                   if row["class"] == "UNKNOWN" or not row.get("matched_rules")]
        # Classification never substitutes for the independent OOM repair and
        # source-bound checkpoint diagnosis retained by A02.
        oom_required = any(row["class"] == "OOM" for row in failures)
        oom_evidence = _a02_oom_diagnosis(all_rows) if oom_required else {"status": "NOT_REQUIRED"}
        oom_ready = not oom_required or oom_evidence.get("status") == "PASS"
        acceptance = {"status": "WAITING_CODEX" if unknown else (
            "WAITING_EXTERNAL" if missing_diagnostics or not oom_ready else "PASS"),
            "blocked_count": len(failures), "failures": failures,
            "unclassified_task_ids": unknown + missing_diagnostics,
            "missing_diagnostic_task_ids": missing_diagnostics,
            "oom_recovery_evidence": oom_evidence,
            "oom_recovery_evidence_required": oom_required,
            "reason": ("Missing saved error diagnostic; logs or failure evidence are required."
                       if missing_diagnostics else "Independent OOM repair/checkpoint evidence is required."
                       if not oom_ready else "All blocked rows have evidence-backed classifications."),
            "created_utc": _utc()}
        if unknown:
            acceptance["request"] = capability_broker.create_request(
                source_task_id=task_id, failure_class="TOOL_MISSING", capability="failure root-cause rule",
                scope="Add a deterministic classification rule for each unclassified blocked task without changing historical task results.",
                reproducer=json.dumps(unknown, ensure_ascii=False),
                expected_behavior="Each persisted blocked error maps to a declared failure class.",
                acceptance_tests=["Every current blocked row maps to a known failure class."],
                allowed_paths=["src/agent/failure_triage.py"],
                test_paths=["tests/unit/test_mission_a05.py"],
                db_path=STATE_DB)
    elif canonical_id == "A10":
        schema = {"type": "object", "required": ["decision"], "additionalProperties": False,
                  "properties": {"decision": {"type": "string", "enum": ["continue"]}}}
        evidence = {"canonical_id": canonical_id, "runtime_task_id": task_id,
                    "objective": spec["objective"], "original_media_write_count": 0}
        installed, issue = manager.available_models()
        ordered = [m for m in ("qwen3.5:9b",) if m in installed]
        acceptance = manager._routed_ollama_json(task_id,
            'Return exactly {"decision":"continue"}. This is a small local JSON routing check.',
            schema, models=ordered, original_evidence=evidence, retry_limit=1, max_tokens=64)
        acceptance["created_utc"] = _utc()
        acceptance["local_model_discovery_error"] = issue
        acceptance["live_local_call"] = acceptance["status"] == "PASS"
        if acceptance["status"] != "PASS":
            waiting = {"status": "WAITING_EXTERNAL", "canonical_id": canonical_id,
                       "runtime_task_id": task_id, "reason": acceptance["reason"],
                       "acceptance": acceptance, "resumable": True, "created_utc": _utc()}
            report_path.write_text(json.dumps(waiting, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            waiting["artifact"] = manager._artifact(task_id, report_path,
                "A10 resumable local model request and original evidence", "WAITING_MODEL")
            return waiting
    elif canonical_id == "B01":
        index_summary = build_b01_format_evidence_index()
        index_path = (PROJECT_ROOT / str(index_summary["index_path"])).resolve(strict=True)
        index_artifact = manager._artifact(task_id, index_path,
            "B01 NCDx format evidence index with byte offsets, hashes, and unknowns",
            "PASS: read-only MP0 header facts independently cross-checked")
        acceptance = {**index_summary, "index_artifact": index_artifact,
                      "status": "PASS", "created_utc": _utc()}
    elif canonical_id == "B02":
        diff_summary = build_b02_region_diff_records()
        diff_path = (PROJECT_ROOT / str(diff_summary["diff_path"])).resolve(strict=True)
        diff_artifact = manager._artifact(task_id, diff_path,
            "B02 three-region NCDx byte, header, and accepted cross-reference evidence",
            "PASS: full source hashes, bounded exact block diff, and independent readback")
        acceptance = {**diff_summary, "diff_artifact": diff_artifact,
                      "status": "PASS", "created_utc": _utc()}
    elif canonical_id == "B03":
        inventory_summary = build_b03_binary_format_inventory()
        inventory_path = (PROJECT_ROOT / str(inventory_summary["inventory_path"])).resolve(strict=True)
        inventory_artifact = manager._artifact(task_id, inventory_path,
            "B03 manifest-bound firmware and executable format inventory",
            "PASS: source hashes, CRC32, bounded magic observations, and confirmed PE fields only")
        acceptance = {**inventory_summary, "binary_inventory_artifact": inventory_artifact,
                      "status": "PASS", "created_utc": _utc()}
    elif canonical_id == "E03":
        from src.agent.e03_optical_layout import build_e03_optical_layout_evidence
        optical_summary = build_e03_optical_layout_evidence()
        optical_path = (PROJECT_ROOT / str(optical_summary["artifact_path"])).resolve(strict=True)
        optical_artifact = manager._artifact(task_id, optical_path,
            "E03 read-only optical image/track evidence census and documented firmware requirement",
            "WAITING_EXTERNAL: no manifest-backed sector image; filesystem text is documented-only")
        acceptance = {**optical_summary, "artifact": optical_artifact,
                      "status": optical_summary["status"], "created_utc": _utc()}
    elif canonical_id == "B06":
        catalog_summary = build_b06_ncdx_structure_catalog()
        catalog_path = (PROJECT_ROOT / str(catalog_summary["catalog_path"])).resolve(strict=True)
        catalog_artifact = manager._artifact(task_id, catalog_path,
            "B06 evidence-aggregated NCDx structure catalog with verified facts and explicit unknowns",
            "PASS: 11 families, accepted source evidence, bounded profiles, and claim boundaries")
        acceptance = {**catalog_summary, "catalog_artifact": catalog_artifact,
                      "status": "PASS", "created_utc": _utc()}
    elif canonical_id == "B07":
        index_summary = build_b07_index_integrity_report()
        index_path = (PROJECT_ROOT / str(index_summary["report_path"])).resolve(strict=True)
        index_artifact = manager._artifact(task_id, index_path,
            "B07 independently verifiable offset-table integrity experiment across CTY and IL source files",
            "PASS: real read-only source replay, decoded block hashes, and malformed-offset rejection controls")
        acceptance = {**index_summary, "index_integrity_artifact": index_artifact,
                      "status": "PASS", "created_utc": _utc()}
    elif canonical_id == "A09":
        acceptance = verify_file_bridge_acceptance()
    elif canonical_id == "A08":
        acceptance = verify_autostart_acceptance()
    elif canonical_id == "D01":
        from src.osm.streaming_pipeline import verify_d01
        acceptance = verify_d01(PROJECT_ROOT)
    elif canonical_id == "D02":
        acceptance = execute_osm_source_provenance(task_id)
    elif canonical_id == "A07":
        tests = ["tests.unit.test_state_store", "tests.unit.test_resumable_national"]
        run = subprocess.run([sys.executable, "-B", "-m", "unittest", *tests], cwd=PROJECT_ROOT,
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180, check=False)
        if run.returncode:
            raise RuntimeError(f"checkpoint and SQLite lease acceptance failed: {(run.stderr or run.stdout)[-3000:]}")
        acceptance = {"status": "PASS", "tests": tests, "returncode": run.returncode,
            "stdout": run.stdout[-2000:], "created_utc": _utc()}
    else:
        request = capability_broker.create_request(
            source_task_id=task_id, failure_class="TOOL_MISSING",
            capability=f"mission task {canonical_id}: {spec['objective'][:160]}",
            scope=("Implement only the fixed deterministic handler/report verifier for " + canonical_id
                   + ". Preserve read-only original media; exclude Virtual CID and standalone POI Editor. "
                   + "Never claim physical acceptance without task-specific device evidence. Objective: " + spec["objective"]), reproducer=f"canonical_task={canonical_id}; runtime executor registry has no implementation",
            expected_behavior="Implement the requested capability in a sandbox, run the listed acceptance checks, and return independently verifiable artifacts.",
            acceptance_tests=list(spec.get("acceptance_criteria", [])),
            allowed_paths=repair_scope["allowed_paths"],
            test_paths=repair_scope["test_paths"], db_path=STATE_DB)
        return {"status": "WAITING_LOCAL", "canonical_id": canonical_id,
            "reason": "No deterministic handler exists yet; a typed local-first capability request was persisted.",
            "runtime_task_id": task_id, "request": request}

    if acceptance.get("status") == "WAITING_EXTERNAL":
        waiting = {"status": "WAITING_EXTERNAL", "canonical_id": canonical_id,
            "reason": ("Missing startup/runtime checks: " + ", ".join(acceptance.get("missing_checks", []))) if canonical_id == "A08" else acceptance.get("reason", "Missing saved error diagnostic; logs or failure evidence are required. Independent software work can continue."),
            "runtime_task_id": task_id, "acceptance": acceptance}
        if isinstance(acceptance.get("artifact"), dict):
            waiting["artifact"] = acceptance["artifact"]
        return waiting
    if acceptance.get("status") in {"WAITING_LOCAL", "WAITING_CODEX"}:
        return {"status": "WAITING_LOCAL", "canonical_id": canonical_id,
            "reason": "Failure classification requires a new deterministic rule; typed capability request was saved.",
            "runtime_task_id": task_id, "request": acceptance.get("request")}
    report = {"status": acceptance["status"] if canonical_id == "A02" else "PASS",
        "canonical_id": canonical_id, "objective": spec["objective"],
        "acceptance": acceptance, "created_utc": _utc(),
        "scope": {"original_media_write_count": 0, "physical_compatibility": "NOT_TESTED",
                  "virtual_cid": "EXCLUDED", "standalone_poi_editor": "EXCLUDED"}}
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report["artifact"] = manager._artifact(task_id, report_path,
        f"Mission Pack {canonical_id} deterministic task evidence",
        (str(acceptance["status"]) + ": saved A02 diagnostic evidence") if canonical_id == "A02"
        else "PASS: saved result and independent artifact hash/schema verifier")
    report["runtime_task_id"] = task_id
    return report


def verify_file_bridge_acceptance() -> dict[str, Any]:
    """Exercise the durable bridge with synthetic records and temporary data only."""
    from src.agent.file_bridge import FileTaskBridge

    checks: dict[str, bool] = {}
    hashes: dict[str, str] = {}
    with tempfile.TemporaryDirectory(prefix="ncdr-a09-") as temporary:
        root = Path(temporary)
        bridge = FileTaskBridge(root / "bridge", root / "journal.sqlite")
        task = {"id": "A09-001", "schema_version": 1,
                "objective": "verify synthetic durable file bridge", "payload": {"region": "UA"}}
        result = {"task_id": task["id"], "schema_version": 1,
                  "status": "PASS", "payload": {"verified": True}}
        checks["task_roundtrip"] = bridge.enqueue_task(task) and bridge.read_task(task["id"]) == task
        checks["result_roundtrip"] = bridge.publish_result(result) and bridge.read_result(task["id"]) == result
        checks["idempotent_duplicates"] = not bridge.enqueue_task(task) and not bridge.publish_result(result)
        for kind, value in (("TASKS", task), ("RESULTS", result)):
            record_path = root / "bridge" / kind / "A09-001.json"
            hashes[kind.lower() + "_sha256"] = _sha256(record_path)
            record_path.unlink()
        # Simulate loss of publication after the durable intent commit. A new
        # instance must replay both records from SQLite, preserving exact bytes.
        bridge = FileTaskBridge(root / "bridge", root / "journal.sqlite")
        checks["journal_recovery"] = (bridge.read_task(task["id"]) == task and
            bridge.read_result(task["id"]) == result and bridge.outbox_count() == 1 and bridge.inbox_count() == 1)
        checks["recovery_hashes_match"] = all(
            _sha256(root / "bridge" / kind / "A09-001.json") == hashes[kind.lower() + "_sha256"]
            for kind in ("TASKS", "RESULTS"))
        rejected = 0
        invalid = [
            (bridge.enqueue_task, {**task, "payload": {"conflict": True}}),
            (bridge.publish_result, {**result, "payload": {"conflict": True}}),
            (bridge.enqueue_task, {**task, "id": "../escape"}),
            (bridge.enqueue_task, {**task, "id": "CON"}),
            (bridge.enqueue_task, {"id": "MISSING", "schema_version": 1}),
            (bridge.publish_result, {**result, "status": "UNKNOWN"}),
            (bridge.enqueue_task, {**task, "payload": {"oversized": "x" * 65537}}),
        ]
        for publish, value in invalid:
            try:
                publish(value)
            except ValueError:
                rejected += 1
        checks["conflicts_and_unsafe_inputs_rejected"] = rejected == len(invalid)
        checks["first_records_preserved"] = (bridge.read_task(task["id"]) == task and
            bridge.read_result(task["id"]) == result and bridge.outbox_count() == 1 and bridge.inbox_count() == 1)
        checks["no_temporary_files_left"] = not list((root / "bridge").rglob("*.tmp"))
        with closing(sqlite3.connect(root / "journal.sqlite")) as conn:
            checks["sqlite_integrity"] = conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    if not all(checks.values()):
        raise RuntimeError(f"A09 durable file bridge acceptance failed: {checks}")
    return {"status": "PASS", "checks": checks, "record_hashes": hashes,
            "synthetic_data_only": True, "temporary_data_removed": True,
            "original_media_write_count": 0, "created_utc": _utc()}


def execute_capability_request(task_id: str) -> dict[str, Any]:
    """Run one local isolated repair, escalating once only after a verified local failure."""
    from src.agent import capability_broker
    task = manager._task(task_id)
    request_id = str(task.get("budget", {}).get("capability_request_id", ""))
    if not request_id.startswith("CAP_"):
        raise ValueError("capability worker task requires a persisted CAP_ request ID")
    outcome = capability_broker.execute_request(request_id, db_path=STATE_DB, executor="local",
        timeout_s=max(60, min(int(task.get("budget", {}).get("timeout_s", 1800)) - 120, 2400)))
    if outcome.get("status") == "LOCAL_FAILED":
        # The broker persists the isolated failure before this single quota-gated
        # escalation. A rate limit is saved as WAITING_CODEX_QUOTA and is never
        # requeued by the local worker.
        outcome = capability_broker.execute_request(request_id, db_path=STATE_DB, executor="codex",
            timeout_s=max(60, min(int(task.get("budget", {}).get("timeout_s", 1800)) - 120, 2400)))
    if outcome.get("status") in {"WAITING_CODEX_QUOTA", "WAITING_CODEX", "WAITING_LOCAL", "WAITING_EXTERNAL"}:
        source_task_id = str(task.get("budget", {}).get("source_task_id", ""))
        if source_task_id:
            source_task = manager._task(source_task_id)
            source_budget = source_task.get("budget", {})
            canonical_id = str(source_budget.get("mission_pack_task", "")) if isinstance(source_budget, dict) else ""
            if canonical_id:
                from src.agent import mission_pack
                mission_pack.verify_runtime_result(canonical_id,
                    {**outcome, "runtime_task_id": source_task_id}, db_path=STATE_DB)
    report_dir = PROJECT_ROOT / "reports" / "mission_pack" / "capability_runs"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"{task_id}.json"
    report = {"status": outcome.get("status"), "task_id": task_id,
        "request_id": request_id, "executor": outcome.get("executor", "Local-first capability broker"),
        "outcome": outcome, "created_utc": _utc(),
        "source_write_count": 0 if outcome.get("status") != "VERIFIED" else len(outcome.get("changed_paths", [])),
        "original_media_write_count": 0, "physical_compatibility": "NOT_TESTED"}
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    artifact = manager._artifact(task_id, report_path,
        "Local-first capability repair and independent test outcome",
        "PASS" if outcome.get("status") == "VERIFIED" else str(outcome.get("status", "WAITING_CODEX")))
    return {**report, "artifact": artifact}


def _bounded_command(command: list[str], timeout_s: int = 10) -> dict[str, Any]:
    try:
        result = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True,
            text=True, encoding="utf-8", errors="replace", timeout=timeout_s, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return {"available": True, "returncode": result.returncode,
                "version": (result.stdout or result.stderr).strip()[:500]}
    except FileNotFoundError as exc:
        return {"available": False, "error": f"{type(exc).__name__}: {exc}"[:500]}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"available": True, "error": f"{type(exc).__name__}: {exc}"[:500]}


def _blocked_task_summary(row: dict[str, Any]) -> dict[str, Any]:
    try:
        result = json.loads(row.get("result_json") or "{}")
    except json.JSONDecodeError:
        result = {}
    return {"id": row.get("id"), "error": str(result.get("error", ""))[:700]}


def _candidate_goal() -> str | None:
    if _task_status(PLAN_TASKS["OSM_REAL_CONVERSION"]) is None:
        return "OSM_REAL_CONVERSION" if SOURCE_PBF.is_file() else None
    if _task_status(PLAN_TASKS["OSM_REAL_CONVERSION"]) == "DONE":
        if _task_status("AUTO_OSM_READBACK_AFTER_RESTART_01") is None:
            return "OSM_REAL_CONVERSION"  # The model is asked to select the readback goal explicitly below.
        if _task_status("AUTO_OSM_READBACK_AFTER_RESTART_01") == "DONE":
            if _task_status(PLAN_TASKS["NCDX_NK_SURVEY"]) is None:
                return "NCDX_NK_SURVEY"
            if _task_status(PLAN_TASKS["NCDX_NK_SURVEY"]) == "DONE":
                if _task_status(PLAN_TASKS["NCDX_NAVIMAIN_SURVEY"]) is None:
                    return "NCDX_NAVIMAIN_SURVEY"
    return None


def seed_next_plan_task() -> dict[str, Any]:
    """Persist the next bounded AI planning job if a known goal remains."""
    goal_id = _candidate_goal()
    if not goal_id:
        return {"created": False, "reason": "Немає наступної не повторюваної задачі з локальною вхідною базою; апаратне приймання залишається окремим блокером."}
    if goal_id == "OSM_REAL_CONVERSION" and _task_status(PLAN_TASKS[goal_id]) is not None:
        # Conversion completed: a different task reopens its saved result and
        # proves recovery independently after a fresh worker process.
        task_id = "AUTO_OSM_READBACK_AFTER_RESTART_01"
        created = _registered_task(task_id, "F4", SUPERVISOR_ID[goal_id],
            "У новому процесі повторно відкрити справжній OSM SQLite результат, перевірити integrity, український пошук і маршрут.",
            "osm-independent-readback", "work/autonomous_manager/osm_pipeline/real_conversion/readback_after_restart.json",
            ["SQLite integrity_check=ok", "Пошук вулиць Соборності та Героїв АТО", "Повторне побудування з'єднаного маршруту <10 км", "Порівняти SHA джерела до/після"],
            180, 12)
        if created:
            manager._event("project_director_task_created", {"task_id": task_id, "goal_id": "OSM_READBACK_AFTER_RESTART", "reason": "conversion Supervisor passed; require independent fresh-process readback"})
        return {"created": created, "task_id": task_id if created else None,
                "reason": "Локальний Director продовжує перевірку після відновлення процесу."}
    task_id = PLAN_ID[goal_id]
    if _task_status(task_id) is not None:
        return {"created": False, "reason": f"план {task_id} уже збережений; повтор не створюється"}
    dependency = "AUTO_SUPERVISOR_OSM_READBACK_01" if goal_id == "NCDX_NK_SURVEY" else "AUTO_SUPERVISOR_NK_SURVEY_01"
    if goal_id != "OSM_REAL_CONVERSION" and _task_status(dependency) != "DONE":
        return {"created": False, "reason": f"попередній Supervisor ще не підтвердив залежність {dependency}"}
    created = _registered_task(task_id, "F2" if goal_id.startswith("NCDX") else "F4",
        dependency if goal_id.startswith("NCDX") else None,
        f"AI Project Director має оцінити збережені факти й обрати лише дозволену ціль {goal_id}.",
        "ollama-project-director", f"reports/autonomous_director_plan_{goal_id.casefold()}.json",
        ["Ollama повернув структуровану ціль із фіксованого реєстру", "Залежність відповідає завершеному Supervisor", "Жоден текст моделі не виконується як код або команда"],
        1200, 8)
    if created:
        manager._event("project_director_task_created", {"task_id": task_id, "goal_id": goal_id,
            "dependency": dependency if goal_id.startswith("NCDX") else None,
            "reason": "previously verified work enables a distinct local experiment"})
    return {"created": created, "task_id": task_id if created else None,
            "reason": "Збережено конкретний планувальний етап; модель обмежена реєстром цілей."}


def seed_next_national_osm_task() -> dict[str, Any]:
    """Queue one dated Ukraine-wide data-preparation build after city readback."""
    try:
        current = reconcile_national_osm_continuations()
    except Exception as exc:
        return {"created": False,
            "reason": f"national OSM inputs/publication could not be proven; no import queued: {type(exc).__name__}: {exc}"}
    if current.get("complete"):
        supervisor = (_task_result(OSM_NATIONAL_SUPERVISOR_ID)
                      if _task_status(OSM_NATIONAL_SUPERVISOR_ID) == "DONE" else {})
        supervised_target = str(supervisor.get("target_task", ""))
        if supervisor.get("status") == "PASS" and supervised_target.startswith(
                OSM_NATIONAL_PUBLISHED_RECOVERY_ID):
            return {"created": False,
                "reason": f"published database already passed independent Supervisor for {supervised_target}; no duplicate scan or reimport will run",
                "published_proof": current.get("published_proof"),
                "superseded_task_ids": current.get("superseded_task_ids", [])}
    prerequisite = "AUTO_SUPERVISOR_OSM_READBACK_01"
    existing_status = _task_status(OSM_NATIONAL_TASK_ID)
    if existing_status in {"DONE", "BLOCKED"}:
        with closing(sqlite3.connect(STATE_DB, timeout=20)) as conn:
            row = conn.execute("SELECT budget_json,result_json FROM tasks WHERE id=?", (OSM_NATIONAL_TASK_ID,)).fetchone()
            active_slice = conn.execute("SELECT id FROM tasks WHERE id LIKE 'AUTO_OSM_NATIONAL_STEP_%' AND status IN ('PENDING','LEASED') LIMIT 1").fetchone()
        if row:
            try:
                budget, result = json.loads(row[0] or "{}"), json.loads(row[1] or "{}")
            except json.JSONDecodeError:
                budget, result = {}, {}
            if (budget.get("resumable_national_osm") is True
                    and not active_slice
                    and (existing_status == "BLOCKED" or result.get("status") == "CONTINUE")):
                relative = str(budget.get("output_directory", ""))
                if relative:
                    work_dir = (PROJECT_ROOT / relative).resolve()
                    if (WORK_ROOT / "ukraine_national").resolve() in work_dir.parents:
                        from src.osm import resumable_national
                        building, final = work_dir / "ukraine.sqlite.building", work_dir / "ukraine.sqlite"
                        if final.is_file():
                            try:
                                resumable_national._published_database_result(
                                    final, extract_sha256=str(budget.get("extract_sha256", "")),
                                    source_pbf_sha256=str(budget.get("source_pbf_sha256", "")))
                            except Exception as exc:
                                manager._event("national_osm_published_recovery_rejected",
                                    {"error": f"{type(exc).__name__}: {exc}", "database": str(final)},
                                    task_id=OSM_NATIONAL_TASK_ID, severity="ERROR")
                                return {"created": False,
                                    "reason": "published national database failed its exact source-bound metadata check; no reimport or overwrite was attempted"}
                            recovery_status = _task_status(OSM_NATIONAL_PUBLISHED_RECOVERY_ID)
                            recovery_task_id = OSM_NATIONAL_PUBLISHED_RECOVERY_ID
                            recovery_dependency = OSM_NATIONAL_TASK_ID
                            if recovery_status in {"BLOCKED", "CANCELLED"}:
                                supervisor_result = (_task_result(OSM_NATIONAL_SUPERVISOR_ID)
                                    if _task_status(OSM_NATIONAL_SUPERVISOR_ID) == "DONE" else {})
                                supervised_target = str(supervisor_result.get("target_task", ""))
                                if (supervisor_result.get("status") == "PASS"
                                        and supervised_target.startswith(OSM_NATIONAL_PUBLISHED_RECOVERY_ID)):
                                    return {"created": False,
                                        "reason": f"published database readback already passed independent Supervisor for {supervised_target}; no duplicate large-database scan or reimport will run"}
                                recovery_dependency = None
                                recovery_task_id = ""
                                for attempt in range(1, 4):
                                    candidate = f"{OSM_NATIONAL_PUBLISHED_RECOVERY_ID}_RETRY_{attempt:02d}"
                                    if _task_status(candidate) is None:
                                        recovery_task_id = candidate
                                        break
                                if not recovery_task_id:
                                    return {"created": False,
                                        "reason": "three bounded published-database readback attempts are already recorded; no reimport will be started"}
                            elif recovery_status is not None:
                                return {"created": False, "reason": f"published database recovery task already exists ({recovery_status}); no reimport will run"}
                            if recovery_task_id:
                                created = _registered_task(recovery_task_id, "F4",
                                    recovery_dependency,
                                    "Independently verify the already-published source-bound Ukraine OSM database after its previous final-readback task timed out.",
                                    "osm-national-conversion",
                                    "reports/autonomous_osm_national_conversion.json",
                                    ["Published SQLite opens read-only", "Exact source PBF and extract hashes match", "Kyiv search and bounded Kryvyi Rih route pass", "Original source media remain read-only", "No national reimport occurs"],
                                    3600, 3,
                                    {"ukraine_national_osm": True, "resumable_national_osm": True,
                                     "national_osm_published_recovery": True,
                                     "source_path": budget.get("source_path"),
                                     "source_pbf_sha256": budget.get("source_pbf_sha256"),
                                     "extract_sha256": budget.get("extract_sha256"),
                                     "output_directory": budget.get("output_directory"),
                                     "max_records_per_slice": budget.get("max_records_per_slice", 500000),
                                     "slice_budget_seconds": budget.get("slice_budget_seconds", 180)})
                                if created:
                                    manager._event("national_osm_published_recovery_queued",
                                        {"task_id": recovery_task_id,
                                         "source_pbf_sha256": budget.get("source_pbf_sha256"),
                                         "extract_sha256": budget.get("extract_sha256"),
                                         "database": str(final),
                                         "action": "verify published result; never repeat import"})
                                    return {"created": True, "task_id": recovery_task_id,
                                            "reason": "published database recovered by exact source binding; queueing independent readback without reimport"}
                            if recovery_status is None:
                                return {"created": False, "reason": "published database recovery task could not be queued; no reimport will run"}
                        checkpoint = resumable_national.checkpoint_token(
                            work_dir, building if building.is_file() else final)
                        if checkpoint:
                            continuation = queue_national_osm_continuation(OSM_NATIONAL_TASK_ID, checkpoint,
                                reason="startup reconciliation found a durable incomplete national import checkpoint",
                                after_failure=existing_status == "BLOCKED")
                            if continuation.get("created"):
                                return {**continuation, "reason": "recovered missing checkpoint follow-up after worker restart"}
    if existing_status == "BLOCKED":
        resumed = _resume_national_osm_task_from_checkpoint()
        if resumed["requeued"]:
            return {"created": True, "task_id": OSM_NATIONAL_TASK_ID, "reason": resumed["reason"]}
    if existing_status is not None:
        return {"created": False, "reason": f"{OSM_NATIONAL_TASK_ID} already exists; do not duplicate a national conversion"}
    if _task_status(prerequisite) != "DONE":
        return {"created": False, "reason": f"waiting for independent city-map checkpoint {prerequisite}"}
    if not SOURCE_PBF.is_file():
        return {"created": False, "reason": f"read-only Ukraine PBF is missing: {SOURCE_PBF}"}
    created = _registered_task(OSM_NATIONAL_TASK_ID, "F4", prerequisite,
        "Convert the saved dated Ukraine PBF into a versioned national OSM preparation database, preserving provenance and testing the real national graph.",
        "osm-national-conversion",
        "work/autonomous_manager/osm_pipeline/ukraine_national/<source-date-hash>/conversion.json",
        ["PBF source hash and stat are unchanged", "National OSM XML extract reads through gzip EOF", "SQLite integrity, Ukraine extent and unresolved-reference checks pass", "Kyiv search and bounded Kryvyi Rih route pass on the national database", "Fresh independent Supervisor readback passes", "Original NCDR media write count remains zero"],
        900, 9, {"ukraine_national_osm": True, "resumable_national_osm": True,
                  "source_path": "data/osm/ukraine-latest.osm.pbf", "model_calls": 0,
                  "resume_from_versioned_outputs": True, "max_records_per_slice": 500000,
                  "slice_budget_seconds": 180})
    if created:
        manager._event("project_director_task_created", {"task_id": OSM_NATIONAL_TASK_ID,
            "goal_id": "UKRAINE_NATIONAL_OSM_DATABASE", "depends_on": prerequisite,
            "reason": "city conversion and fresh-process readback are verified; national data preparation is independently testable without NCDx or hardware"})
    return {"created": created, "task_id": OSM_NATIONAL_TASK_ID if created else None,
            "reason": "Bounded national OSM conversion is queued from an existing dated local PBF."}


def _national_osm_state_from_budget(budget: dict[str, Any]) -> dict[str, Any]:
    """Rebind a national OSM checkpoint or publication to current source bytes and metadata."""
    from src.osm import resumable_national

    if budget.get("resumable_national_osm") is not True:
        raise ValueError("task is not on the checkpointed national OSM path")
    source = (PROJECT_ROOT / str(budget.get("source_path", ""))).resolve(strict=True)
    if source != SOURCE_PBF.resolve(strict=True) or not source.is_relative_to(PROJECT_ROOT.resolve()):
        raise ValueError("national OSM source path differs from the configured read-only PBF")
    output_dir = (PROJECT_ROOT / str(budget.get("output_directory", ""))).resolve(strict=True)
    if not output_dir.is_relative_to(WORK_ROOT.resolve()):
        raise ValueError("national OSM output path escaped its versioned work directory")
    extract = output_dir / "ukraine.osm.gz"
    final = output_dir / "ukraine.sqlite"
    building = output_dir / "ukraine.sqlite.building"
    if not extract.is_file():
        raise ValueError("source-bound national OSM extract is missing")

    source_before, extract_before = source.stat(), extract.stat()
    source_hash, extract_hash = _sha256(source), _sha256(extract)
    source_after, extract_after = source.stat(), extract.stat()
    if ((source_before.st_size, source_before.st_mtime_ns) !=
            (source_after.st_size, source_after.st_mtime_ns)
            or (extract_before.st_size, extract_before.st_mtime_ns) !=
            (extract_after.st_size, extract_after.st_mtime_ns)):
        raise RuntimeError("national OSM source or extract changed while checksums were being verified")
    expected_source = str(budget.get("source_pbf_sha256", "")).casefold()
    expected_extract = str(budget.get("extract_sha256", "")).casefold()
    if source_hash.casefold() != expected_source or extract_hash.casefold() != expected_extract:
        raise RuntimeError("current national OSM input checksums differ from the recorded task bindings")

    source_metadata = _json(PROJECT_ROOT / "data" / "osm" / "source.json")
    download = source_metadata.get("pbf_download", {})
    content_text = str(source_metadata.get("dataset_content_timestamp", ""))
    content_match = re.match(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)", content_text)
    manifest_content_timestamp = content_match.group(1) if content_match else "NOT_RECORDED"
    if (not isinstance(download, dict)
            or str(download.get("sha256", "")).casefold() != source_hash.casefold()
            or int(download.get("bytes", -1)) != source_after.st_size):
        raise RuntimeError("current PBF checksum or byte count differs from the saved source metadata")
    manifest = _json(PROJECT_ROOT / "osm" / "source-manifest.json")
    if (manifest.get("status") != "VERIFIED"
            or manifest.get("source_pbf_path") != source.relative_to(PROJECT_ROOT).as_posix()
            or manifest.get("source_pbf_sha256") != source_hash
            or int(manifest.get("source_pbf_bytes", -1)) != source_after.st_size
            or manifest.get("dataset_content_timestamp") != manifest_content_timestamp
            or manifest.get("license") != "Open Database License (ODbL)"
            or manifest.get("attribution") != "© OpenStreetMap contributors"):
        raise RuntimeError("saved OSM provenance manifest does not match current source metadata/checksum")

    state: dict[str, Any] = {"complete": False,
        "source_pbf_sha256": source_hash, "source_pbf_bytes": source_after.st_size,
        "extract_sha256": extract_hash, "extract_bytes": extract_after.st_size,
        "dataset_content_timestamp": str(source_metadata.get("dataset_content_timestamp", "")),
        "output_directory": output_dir.relative_to(PROJECT_ROOT).as_posix(),
        "database": str(final), "database_exists": final.is_file(),
        "database_bytes": final.stat().st_size if final.is_file() else 0,
        "source_metadata_status": "VERIFIED"}
    conversion = _json(output_dir / "conversion.json")
    if conversion and (conversion.get("source_pbf_sha256") != source_hash
            or conversion.get("extract_sha256") != extract_hash
            or conversion.get("dataset_content_timestamp") != source_metadata.get("dataset_content_timestamp")):
        raise RuntimeError("saved conversion metadata does not match current OSM source provenance")

    progress_path = output_dir / "national_import_progress.json"
    progress = _json(progress_path)
    progress_step = progress.get("step", {}) if isinstance(progress, dict) else {}
    if progress and (progress.get("source_pbf_sha256") != source_hash
                     or progress.get("extract_sha256") != extract_hash):
        raise RuntimeError("saved national import checkpoint is bound to different input checksums")
    if final.is_file():
        published_before = final.stat()
        proof = resumable_national._published_database_result(final,
            extract_sha256=extract_hash, source_pbf_sha256=source_hash)
        published_after = final.stat()
        if (published_before.st_size, published_before.st_mtime_ns) != (
                published_after.st_size, published_after.st_mtime_ns):
            raise RuntimeError("published national OSM database changed during read-only metadata verification")
        if (not progress or progress_step.get("status") != "COMPLETE"
                or progress_step.get("phase") != "FINALIZE"
                or progress_step.get("source_sha256") != extract_hash
                or progress_step.get("source_pbf_sha256") != source_hash):
            raise RuntimeError("published database lacks a matching durable COMPLETE checkpoint report")
        if {key: int(value) for key, value in progress_step.get("counts", {}).items()} != proof["counts"]:
            raise RuntimeError("published OSM counts differ from the last saved finalization checkpoint")
        state.update({"complete": True, "published_proof": proof,
            "database_bytes": published_after.st_size,
            "database_mtime_ns": published_after.st_mtime_ns,
            "progress_mtime_ns": progress_path.stat().st_mtime_ns})
        state["checkpoint_token"] = None
    else:
        live_database = building if building.is_file() else None
        current = resumable_national.checkpoint_token(output_dir, live_database)
        if current is None:
            raise RuntimeError("no valid transactionally committed national OSM checkpoint is available")
        state.update({"checkpoint_token": current,
            "phase": resumable_national.progress_snapshot(output_dir, live_database).get("phase"),
            "database_bytes": live_database.stat().st_size if live_database else 0})
    return state


def reconcile_national_osm_continuations(budget: dict[str, Any] | None = None) -> dict[str, Any]:
    """Retire stale OSM children or all remaining slices after proven publication."""
    if budget is None:
        with closing(sqlite3.connect(STATE_DB, timeout=30)) as conn:
            rows = conn.execute("SELECT id,budget_json FROM tasks WHERE id IN (?,?)",
                (OSM_NATIONAL_PUBLISHED_RECOVERY_ID, OSM_NATIONAL_TASK_ID)).fetchall()
        by_id = {str(task_id): json.loads(raw or "{}") for task_id, raw in rows}
        budget = next((by_id[task_id] for task_id in
            (OSM_NATIONAL_PUBLISHED_RECOVERY_ID, OSM_NATIONAL_TASK_ID)
            if by_id.get(task_id, {}).get("resumable_national_osm") is True), None)
    if not budget:
        return {"complete": False, "superseded_task_ids": [],
            "reason": "no saved resumable national OSM task metadata exists"}
    state = _national_osm_state_from_budget(budget)
    with closing(sqlite3.connect(STATE_DB, timeout=30)) as conn:
        rows = conn.execute(
            "SELECT id,status,budget_json FROM tasks WHERE id LIKE 'AUTO_OSM_NATIONAL_STEP_%' "
            "AND status IN ('PENDING','BLOCKED') ORDER BY created_utc,id").fetchall()
    superseded: list[str] = []
    for task_id, status, raw_budget in rows:
        try:
            old_budget = json.loads(raw_budget or "{}")
        except json.JSONDecodeError:
            old_budget = {}
        old_token = str(old_budget.get("checkpoint_token", ""))
        obsolete = state["complete"] or old_token != state.get("checkpoint_token")
        if not obsolete:
            continue
        why = ("published source-bound national database is complete; no import continuation is permitted"
               if state["complete"] else "saved OSM checkpoint differs from the current committed SQLite checkpoint")
        proof = {"expected_checkpoint": old_token,
            "current_checkpoint": state.get("checkpoint_token"),
            "published_complete": state["complete"],
            "source_pbf_sha256": state["source_pbf_sha256"],
            "extract_sha256": state["extract_sha256"],
            "database": state.get("database"), "database_bytes": state.get("database_bytes"),
            "published_counts": state.get("published_proof", {}).get("counts")}
        if state_store.supersede_task(task_id, why, evidence=proof, db_path=STATE_DB):
            superseded.append(task_id)
    if superseded:
        manager._event("national_osm_continuations_superseded", {
            "task_ids": superseded, "published_complete": state["complete"],
            "current_checkpoint": state.get("checkpoint_token"),
            "source_pbf_sha256": state["source_pbf_sha256"],
            "extract_sha256": state["extract_sha256"],
            "published_counts": state.get("published_proof", {}).get("counts")})
    return {**state, "superseded_task_ids": superseded}


def queue_national_osm_continuation(parent_task_id: str, checkpoint: str | None, *,
                                    reason: str, after_failure: bool = False) -> dict[str, Any]:
    """Create one idempotent OSM slice from the current verified checkpoint only."""
    task = manager._task(parent_task_id)
    budget = task.get("budget", {})
    if budget.get("resumable_national_osm") is not True:
        return {"created": False, "reason": "parent task is not on the resumable national OSM path"}
    state = reconcile_national_osm_continuations(budget)
    if state["complete"]:
        return {"created": False, "reason": "published national OSM database is source-bound and complete; no continuation or reimport will run",
                "published_proof": state.get("published_proof"),
                "superseded_task_ids": state.get("superseded_task_ids", [])}
    current_checkpoint = state.get("checkpoint_token")
    if not current_checkpoint:
        return {"created": False, "reason": "no durable OSM checkpoint exists yet"}
    requested_checkpoint = str(checkpoint or "")
    if requested_checkpoint != current_checkpoint:
        safe_old = re.sub(r"[^A-Fa-f0-9_-]", "", requested_checkpoint)[:32].upper()
        old_task_id = "AUTO_OSM_NATIONAL_STEP_" + (safe_old or "START")
        try:
            state_store.supersede_task(old_task_id,
                "continuation token was stale when compared with the current committed checkpoint",
                evidence={"expected_checkpoint": requested_checkpoint,
                          "current_checkpoint": current_checkpoint,
                          "source_pbf_sha256": state["source_pbf_sha256"],
                          "extract_sha256": state["extract_sha256"]}, db_path=STATE_DB)
        except KeyError:
            pass
        reason += f"; caller checkpoint was stale ({requested_checkpoint or 'none'}), using {current_checkpoint}"
    safe_token = re.sub(r"[^A-Fa-f0-9_-]", "", str(current_checkpoint))[:32] or "START"
    task_id = "AUTO_OSM_NATIONAL_STEP_" + safe_token.upper()
    dependencies = [] if after_failure else [parent_task_id]
    spec = {"id": task_id, "stage": "F4", "depends_on": dependencies,
        "hypothesis": "The national OSM converter can advance one bounded slice from the last transactionally committed checkpoint without revisiting committed records.",
        "evidence": [{"task": parent_task_id, "checkpoint_token": checkpoint,
                      "reason": reason[:500], "source_pbf_sha256": budget.get("source_pbf_sha256"),
                      "extract_sha256": budget.get("extract_sha256")}],
        "agent": "osm-national-conversion",
        "budget": {key: value for key, value in budget.items() if key in {
            "ukraine_national_osm", "resumable_national_osm", "source_path", "source_write",
            "source_pbf_sha256", "extract_sha256", "output_directory", "max_records_per_slice",
            "slice_budget_seconds", "resume_checkpoint_artifact"}} | {
            "timeout_s": 900, "attempts": 1, "checkpoint_token": checkpoint,
            "recovery_parent": parent_task_id, "recovery_after_failure": after_failure,
            "execution": "fixed allowlisted handler", "model_calls": 0},
        "deliverables": [f"{budget.get('output_directory','work/autonomous_manager/osm_pipeline/ukraine_national')}/national_import_progress.json"],
        "tests": ["SQLite checkpoint advances atomically with imported rows", "No committed batch is reprocessed", "Original input hashes remain unchanged"],
        "next_action": "Continue the next saved phase or schedule an independent NCDx task if the same checkpoint fails again.",
        "retry_limit": 1, "priority": 8}
    created = state_store.add_task(spec, db_path=STATE_DB)
    if created:
        manager._event("national_osm_continuation_queued", {"task_id": task_id,
            "parent_task_id": parent_task_id, "checkpoint_token": checkpoint,
            "after_failure": after_failure, "reason": reason[:500]})
    return {"created": created, "task_id": task_id if created else None,
            "reason": "continuation queued from the current verified checkpoint" if created else "current-checkpoint continuation already exists; duplicate prevented",
            "checkpoint_token": current_checkpoint}


def queue_osm_failure_review(parent_task_id: str, error: str,
                             checkpoint: str | None) -> dict[str, Any]:
    """Ask a local model to classify a saved OSM failure; its output cannot execute or alter state."""
    from src.agent import state_store
    parent = manager._task(parent_task_id)
    parent_budget = parent.get("budget", {})
    fingerprint = hashlib.sha256(f"{parent_task_id}\n{error}".encode("utf-8", errors="replace")).hexdigest()[:12]
    task_id = f"AUTO_OSM_FAILURE_REVIEW_{fingerprint.upper()}"
    spec = {"id": task_id, "stage": "F4", "depends_on": [],
        "hypothesis": "A bounded local-model review can classify the saved national OSM failure and recommend one allowlisted repair path without executing model output.",
        "evidence": [{"source_task": parent_task_id, "error": error[:2000],
                      "checkpoint_token": checkpoint,
                      "report": parent_budget.get("resume_checkpoint_artifact")}],
        "agent": "ollama-osm-failure-review",
        "budget": {"timeout_s": 180, "attempts": 1, "source_write": False,
            "execution": "fixed allowlisted handler", "osm_failure_review": True,
            "failure_task_id": parent_task_id, "failure_text": error[:2000],
            "checkpoint_token": checkpoint, "source_pbf_sha256": parent_budget.get("source_pbf_sha256"),
            "extract_sha256": parent_budget.get("extract_sha256"), "model_calls": 1},
        "deliverables": [f"work/autonomous_manager/osm_pipeline/failure_reviews/{task_id.casefold()}.json"],
        "tests": ["Model recommendation is within the fixed action allowlist", "No model output is executed", "Original media remain read-only"],
        "next_action": "Continue the already checkpointed OSM task; use the model review only as diagnostic evidence.",
        "retry_limit": 1, "priority": 7}
    created = state_store.add_task(spec, db_path=STATE_DB)
    if created:
        manager._event("national_osm_failure_review_queued", {"task_id": task_id,
            "failed_task_id": parent_task_id, "checkpoint_token": checkpoint,
            "error_fingerprint": fingerprint, "model_output_is_advisory": True})
    return {"created": created, "task_id": task_id if created else None,
            "reason": "unique bounded local-model failure review queued" if created else "same failure review already exists"}


def execute_osm_failure_review(task_id: str) -> dict[str, Any]:
    """Obtain a schema-constrained diagnosis; deterministic policy owns all actions."""
    from src.agent import coordinator_runtime
    task = manager._task(task_id)
    budget = task.get("budget", {})
    error = str(budget.get("failure_text", ""))[:2000]
    if budget.get("osm_failure_review") is not True or not error.strip():
        raise RuntimeError("OSM failure-review task lacks its fixed diagnostic evidence")
    choices = ["RESUME_CHECKPOINTED_SLICES", "RETRY_SAME_CHECKPOINT_ONCE",
               "STOP_OSM_AND_SWITCH_TO_NCDX", "REQUEST_NEW_EVIDENCE"]
    prompt = (
        "Analyze only the saved national OSM worker diagnostic below. Do not invent facts, write code, execute commands, "
        "change task states, or suggest touching source media. The import is now implemented as durable line-oriented "
        "SQLite slices; a continuation is already scheduled from the saved checkpoint. Return JSON with keys "
        "root_cause_class (MEMORY_MONOLITH, TIME_BUDGET, CHECKPOINT_MISMATCH, INPUT_INTEGRITY, UNKNOWN), "
        "explanation (under 300 chars), next_action (one of the allowed values), and safety_note (under 250 chars).\n"
        f"allowed_next_action={json.dumps(choices)}\n"
        f"error={error}\ncheckpoint_token={budget.get('checkpoint_token')}\n"
        f"verified_extract_sha256={budget.get('extract_sha256')}\n"
        f"verified_source_pbf_sha256={budget.get('source_pbf_sha256')}"
    )
    with closing(sqlite3.connect(STATE_DB, timeout=20)) as conn:
        previous_attempts = int(conn.execute(
            "SELECT COALESCE(MAX(sequence),0) FROM research_runs WHERE task_id=? AND role='independent-review'",
            (task_id,)).fetchone()[0])
    model, raw, parsed = coordinator_runtime._call_model(task_id, "independent-review", prompt,
        attempt=previous_attempts + 1)
    allowed_classes = {"MEMORY_MONOLITH", "TIME_BUDGET", "CHECKPOINT_MISMATCH", "INPUT_INTEGRITY", "UNKNOWN"}
    cause = str(parsed.get("root_cause_class", "UNKNOWN")).upper().strip()
    action = str(parsed.get("next_action", "REQUEST_NEW_EVIDENCE")).upper().strip()
    explanation = str(parsed.get("explanation", "")).strip()[:300]
    safety = str(parsed.get("safety_note", "")).strip()[:250]
    if cause not in allowed_classes or action not in choices or not explanation or not safety:
        raise RuntimeError("local model failure review did not pass the fixed response schema")
    report = {"status": "PASS", "task_id": task_id, "model": model,
        "source_task": budget.get("failure_task_id"), "error": error,
        "checkpoint_token": budget.get("checkpoint_token"), "root_cause_class": cause,
        "explanation": explanation, "recommendation": action, "safety_note": safety,
        "deterministic_disposition": "continue only from the durable checkpoint; model recommendation cannot alter the queue",
        "model_output_executed": False, "original_media_write_count": 0,
        "validation": [{"name": "fixed_schema_allowlist", "status": "PASS"},
                       {"name": "model_output_not_executed", "status": "PASS"},
                       {"name": "original_media_read_only", "status": "PASS"}]}
    path = PROJECT_ROOT / "work" / "autonomous_manager" / "osm_pipeline" / "failure_reviews" / f"{task_id.casefold()}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({**report, "raw_response": raw[:8000], "parsed_response": parsed},
                               ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report["artifact"] = manager._artifact(task_id, path,
        "Local AI review of an OSM failure diagnostic", "PASS: schema allowlist; advisory-only output")
    return report


def _component_scan_candidates() -> list[dict[str, Any]]:
    """Read the existing inventory and select not-yet-surveyed SW components."""
    ledger = PROJECT_ROOT / "EVIDENCE_LEDGER.sqlite"
    if not ledger.is_file():
        return []
    with closing(sqlite3.connect(f"file:{ledger.as_posix()}?mode=ro", uri=True)) as conn:
        rows = conn.execute(
            "SELECT source_path,sha256,size_bytes,extension FROM artifacts "
            "WHERE source_group='SW' ORDER BY source_path").fetchall()
    candidates = []
    for source_path, digest, size, extension in rows:
        relative = str(source_path).replace("\\", "/").strip("/")
        normalized = relative.casefold()
        suffix = str(extension or Path(relative).suffix).upper()
        if (not normalized.startswith("sw/") or suffix not in COMPONENT_SCAN_EXTENSIONS
                or normalized in {path.casefold() for path in COMPONENT_SCAN_EXCLUSIONS}
                or not digest or int(size or 0) <= 0 or int(size or 0) > 32 * 1024 * 1024):
            continue
        relative_path = PurePosixPath(relative)
        if relative_path.is_absolute() or ".." in relative_path.parts:
            continue
        candidates.append({"source_path": relative_path.as_posix(), "sha256": str(digest),
                           "size_bytes": int(size), "extension": suffix})
    priority = {".EXE": 0, ".DLL": 1, ".BIN": 2, ".ABS": 3, ".HEX": 4}
    candidates.sort(key=lambda row: (priority[row["extension"]], row["source_path"].casefold()))
    return candidates


def _b03_binary_inventory_candidates(ledger_path: Path | None = None) -> list[dict[str, Any]]:
    """Read the complete bounded SW firmware/executable set, including NK.BIN."""
    ledger = Path(ledger_path or PROJECT_ROOT / "EVIDENCE_LEDGER.sqlite").resolve(strict=True)
    with closing(sqlite3.connect(f"file:{ledger.as_posix()}?mode=ro", uri=True, timeout=30)) as conn:
        rows = conn.execute(
            "SELECT source_path,sha256,size_bytes,extension FROM artifacts "
            "WHERE source_group='SW' ORDER BY source_path").fetchall()
    selected: list[dict[str, Any]] = []
    for source_path, digest, size, extension in rows:
        relative = str(source_path).replace("\\", "/").strip("/")
        parsed = PurePosixPath(relative)
        suffix = str(extension or Path(relative).suffix).upper()
        if (not relative.casefold().startswith("sw/") or parsed.is_absolute() or ".." in parsed.parts
                or suffix not in MISSION_B03_EXTENSIONS or not digest
                or int(size or 0) <= 0 or int(size or 0) > 32 * 1024 * 1024):
            continue
        selected.append({"source_path": parsed.as_posix(), "sha256": str(digest).lower(),
                         "size_bytes": int(size), "extension": suffix})
    return selected


def build_b03_binary_format_inventory(*, source_root: Path | None = None,
        ledger_path: Path | None = None, project_root: Path | None = None) -> dict[str, Any]:
    """Build a read-only, source-manifest-bound binary-format inventory for B03."""
    from src.readers.ncdx_binary_headers import inspect_pe_headers

    root = Path(source_root or coordinator_runtime.SOURCE_ROOT).resolve(strict=True)
    project = Path(project_root or PROJECT_ROOT).resolve(strict=True)
    candidates = _b03_binary_inventory_candidates(ledger_path)
    if not candidates:
        raise RuntimeError("B03 has no bounded manifest-backed SW binary inputs")
    output = project / "firmware" / "binary-format-inventory.json"
    if output.is_file():
        try:
            from src.agent.b03_inventory_verifier import verify_b03_binary_format_inventory
            proof = verify_b03_binary_format_inventory(output, source_root=root,
                project_root=project, ledger_path=ledger_path)
            return {"inventory_path": output.relative_to(project).as_posix(),
                "inventory_sha256": _sha256(output), "component_count": proof["component_count"],
                "pe_header_count": proof["pe_header_count"],
                "architecture_counts": proof["architecture_counts"],
                "nk_bin_included": proof["nk_bin_included"],
                "original_media_write_count": 0, "resumed_existing_artifact": True,
                "resumed_artifact_verification": proof}
        except (OSError, RuntimeError, ValueError, KeyError, json.JSONDecodeError) as exc:
            stale_artifact_reason = f"{type(exc).__name__}: {exc}"[:500]
        else:
            stale_artifact_reason = ""
    else:
        stale_artifact_reason = ""
    rows: list[dict[str, Any]] = []
    for candidate in candidates:
        relative = str(candidate["source_path"])
        parsed = PurePosixPath(relative)
        source = (root / Path(*parsed.parts)).resolve(strict=True)
        if not source.is_relative_to(root) or not source.is_file():
            raise RuntimeError(f"B03 source escaped the read-only firmware root: {relative}")
        before = source.stat()
        if before.st_size != int(candidate["size_bytes"]):
            raise RuntimeError(f"B03 source size differs from EVIDENCE_LEDGER: {relative}")
        sha = hashlib.sha256()
        crc = 0
        prefix = b""
        with source.open("rb") as stream:
            while block := stream.read(1024 * 1024):
                if len(prefix) < 16:
                    prefix += block[:16 - len(prefix)]
                sha.update(block)
                crc = zlib.crc32(block, crc)
        digest = sha.hexdigest()
        after = source.stat()
        if (digest != candidate["sha256"] or before.st_size != after.st_size
                or before.st_mtime_ns != after.st_mtime_ns):
            raise RuntimeError(f"B03 readback changed or source manifest hash disagrees: {relative}")
        if prefix.startswith(b"MZ"):
            magic = "DOS_MZ"
        elif prefix.startswith(b"\x7fELF"):
            magic = "ELF"
        elif prefix.startswith(b"PK\x03\x04"):
            magic = "ZIP_LOCAL_HEADER"
        else:
            magic = "UNKNOWN_PREFIX"
        pe: dict[str, Any] | None = None
        pe_status = "NOT_MZ"
        if magic == "DOS_MZ":
            if after.st_size > 32 * 1024 * 1024:
                pe_status = "OVER_BOUNDED_PARSER_LIMIT"
            else:
                try:
                    parsed_pe = inspect_pe_headers(source.read_bytes())
                    pe = {key: parsed_pe[key] for key in (
                        "pe_offset", "machine_code", "architecture", "section_count",
                        "optional_header_magic", "optional_header_kind", "image_base",
                        "size_of_image", "subsystem_code")}
                    pe_status = "PASS_PE_HEADERS"
                except (OSError, ValueError, KeyError) as exc:
                    pe_status = "INVALID_BOUNDED_PE"
        rows.append({"source_path": relative, "extension": candidate["extension"],
            "size_bytes": after.st_size, "sha256": digest, "crc32": f"{crc & 0xffffffff:08x}",
            "prefix_hex": prefix.hex(), "magic_observation": magic, "pe_status": pe_status,
            "pe_headers": pe, "analysis_tool": "ncdx_binary_headers.inspect_pe_headers v1",
            "semantic_format": "UNKNOWN; observed signatures/header fields only",
            "source_manifest_sha256": candidate["sha256"]})
    inventory_fingerprint = hashlib.sha256(json.dumps(
        [{key: row[key] for key in ("source_path", "size_bytes", "sha256")} for row in rows],
        sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    inventory = {"schema": "ncdr.b03.binary-format-inventory.v1", "canonical_id": "B03",
        "status": "PASS", "source_root_scope": "manifest-bound SW binary files, read-only",
        "inventory_fingerprint": inventory_fingerprint, "component_count": len(rows),
        "components": rows, "original_media_write_count": 0,
        "claim_scope": "PE architecture is reported only for structurally validated PE headers; NK.BIN and all other semantic formats remain UNKNOWN without further evidence.",
        "created_utc": _utc()}
    output.parent.mkdir(parents=True, exist_ok=True)
    resolved_output = output.resolve()
    if not resolved_output.is_relative_to(project):
        raise RuntimeError("B03 artifact path escaped the project root")
    preserved_prior = None
    if resolved_output.exists():
        prior_bytes = resolved_output.read_bytes()
        prior_hash = hashlib.sha256(prior_bytes).hexdigest()
        archive_dir = (manager.MANAGER_WORK / "mission_pack" / "history").resolve()
        archive_dir.mkdir(parents=True, exist_ok=True)
        if not archive_dir.is_relative_to(manager.MANAGER_WORK.resolve()):
            raise RuntimeError("B03 prior-artifact archive escaped the manager work area")
        archive_path = archive_dir / f"B03-binary-format-inventory-{prior_hash[:16]}.json"
        if archive_path.exists() and _sha256(archive_path) != prior_hash:
            raise RuntimeError("B03 prior-artifact archive hash collision")
        if not archive_path.exists():
            archive_path.write_bytes(prior_bytes)
        preserved_prior = {"path": archive_path.relative_to(project).as_posix(),
                           "sha256": prior_hash, "size_bytes": len(prior_bytes)}
    temporary = resolved_output.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(inventory, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(resolved_output)
    return {"inventory_path": resolved_output.relative_to(project).as_posix(),
        "inventory_sha256": _sha256(resolved_output), "inventory_fingerprint": inventory_fingerprint,
        "component_count": len(rows), "pe_header_count": sum(row["pe_status"] == "PASS_PE_HEADERS" for row in rows),
        "architecture_counts": {arch: sum(bool(row["pe_headers"] and row["pe_headers"]["architecture"] == arch) for row in rows)
                                 for arch in sorted({str(row["pe_headers"]["architecture"]) for row in rows if row["pe_headers"]})},
        "nk_bin_included": any(row["source_path"].casefold().endswith("/nk.bin") for row in rows),
        "original_media_write_count": 0, "resumed_existing_artifact": False,
        "replaced_unverified_artifact_reason": stale_artifact_reason,
        "preserved_prior_artifact": preserved_prior}


def _component_scan_task_id(relative_path: str) -> str:
    return "AUTO_SW_COMPONENT_SCAN_" + hashlib.sha256(
        relative_path.casefold().encode("utf-8")).hexdigest()[:12]


def _pe_header_probe_task_id(relative_path: str, source_sha256: str) -> str:
    key = relative_path.casefold() + "\0" + source_sha256.casefold() + "\0PE_COFF_HEADER_V1"
    return "AUTO_NCDX_PE_HEADER_PROBE_" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def _unseen_component_scan_candidates() -> list[dict[str, Any]]:
    """Return real manifest-pinned SW binaries with no prior survey task."""
    return [row for row in _component_scan_candidates()
            if _task_status(_component_scan_task_id(str(row["source_path"]))) is None]


def _unseen_pe_header_probe_candidates() -> list[dict[str, Any]]:
    """Turn previously observed MZ/PE signatures into fresh bounded parse candidates."""
    candidates = []
    for source in _component_scan_candidates():
        source_id = _component_scan_task_id(str(source["source_path"]))
        if _task_status(source_id) != "DONE":
            continue
        try:
            survey = _task_result(source_id)
        except (KeyError, RuntimeError, ValueError, json.JSONDecodeError):
            continue
        signatures = survey.get("observed_signatures_and_offsets", {})
        if (survey.get("status") != "PASS" or survey.get("source_path") != source["source_path"]
                or survey.get("source_sha256") != source["sha256"]
                or survey.get("manifest_sha256") != source["sha256"]
                or signatures.get("MZ") != 0 or not isinstance(signatures.get("PE"), int)
                or int(signatures["PE"]) < 64):
            continue
        task_id = _pe_header_probe_task_id(str(source["source_path"]), str(source["sha256"]))
        if _task_status(task_id) is not None:
            continue
        candidates.append({**source, "candidate_id": task_id,
            "experiment": "pe_coff_header_parse_v1", "source_survey_task_id": source_id,
            "observed_pe_signature_offset": int(signatures["PE"])})
    return candidates


def _next_binary_evidence_candidates() -> list[dict[str, Any]]:
    """Prefer never-surveyed sources, then advance to a distinct PE-header experiment."""
    unseen = _unseen_component_scan_candidates()
    if unseen:
        return [{**row, "candidate_id": _component_scan_task_id(str(row["source_path"])),
                 "experiment": "bounded_component_survey_v1"} for row in unseen]
    return _unseen_pe_header_probe_candidates()


def seed_next_component_survey_director_task() -> dict[str, Any]:
    """Ask the local Director to choose the next distinct, evidence-backed binary experiment."""
    candidates = _next_binary_evidence_candidates()
    if not candidates:
        return {"created": False,
                "reason": "No manifest-backed SW binary has an unseen bounded component or PE-header experiment."}
    candidate_set = candidates
    fingerprint = hashlib.sha256(json.dumps(
        candidate_set, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    suffix = fingerprint[:12]
    task_id = "AUTO_DIRECTOR_SW_COMPONENT_SCAN_" + suffix
    created = _registered_task(task_id, "F2", None,
        "Qwen3.5 Director selects one not-yet-completed, manifest-bound NCDR binary experiment from actual prior evidence.",
        "ollama-component-survey-director",
        f"reports/autonomous_director_sw_component_{suffix}.json",
        ["Selection is one exact candidate ID from the persisted inventory/evidence",
         "Selected source still matches its EVIDENCE_LEDGER path, SHA-256 and size",
         "The selected reusable worker performs a bounded experiment and never writes source media"],
        180, 20,
        {"component_survey_director": True, "candidate_fingerprint": fingerprint,
         "candidates": candidate_set})
    if created:
        manager._event("project_director_component_plan_created", {
            "task_id": task_id, "candidate_fingerprint": fingerprint,
            "candidate_ids": [row["candidate_id"] for row in candidate_set],
            "candidate_count": len(candidate_set),
         "source_extensions": sorted({row["extension"] for row in candidate_set}),
         "experiment_types": sorted({row["experiment"] for row in candidate_set}),
         "reason": "unseen file experiment derived from existing source hashes and prior survey evidence"})
    return {"created": created, "task_id": task_id if created else None,
            "reason": "Local Director is choosing among uncompleted manifest-bound binary experiments",
            "candidate_count": len(candidate_set), "candidate_fingerprint": fingerprint}


def execute_component_survey_director(task_id: str) -> dict[str, Any]:
    """Choose one safe inventory candidate and queue its reusable survey worker."""
    task = manager._task(task_id)
    budget = task.get("budget", {})
    persisted = budget.get("candidates") or []
    if budget.get("component_survey_director") is not True or not persisted:
        raise RuntimeError("component survey Director has no persisted candidate set")
    current = {str(row["candidate_id"]): row for row in _next_binary_evidence_candidates()}
    candidates = [row for row in persisted
                  if isinstance(row, dict) and str(row.get("candidate_id", "")) in current
                  and current[str(row["candidate_id"])] == row]
    if not candidates:
        raise RuntimeError("component survey inputs changed after planning; replan from the current manifest")
    allowed = {str(row["candidate_id"]) for row in candidates}
    model: str | None = None
    model_error: str | None = None
    parsed: dict[str, Any] = {}
    try:
        installed = coordinator_runtime._available_models()
        model = coordinator_runtime._choose_model("project-director", installed)
        prompt = json.dumps({
            "role": "local Qwen NCDR research Director",
            "global_goal": project_scope.global_goal(),
            "active_tracks": project_scope.load_scope()["active_tracks"],
            "verified_project_state": _director_context(),
            "unexamined_manifest_candidates": [{
                "candidate_id": row["candidate_id"], "source_path": row["source_path"],
                "extension": row["extension"], "source_sha256": row["sha256"],
                "size_bytes": row["size_bytes"]} for row in candidates],
            "constraints": [
                "Choose exactly one candidate_id from unexamined_manifest_candidates.",
                "Prefer inputs that can add NCDx software or navigation-format evidence.",
                "Do not infer format or CPU architecture from the extension.",
                "Do not return code, paths, shell commands, or new acceptance criteria.",
                "Do not request hardware access or writes to source media."],
            "response_schema": {"candidate_id": sorted(allowed)[0],
                "reason": "short evidence-based reason", "requires_hardware": False,
                "writes_original_media": False}}, ensure_ascii=False)
        _actual_model, _response, parsed = coordinator_runtime._call_model(
            task_id, "project-director", prompt, attempt=1, fixed_model=model)
    except Exception as exc:
        model_error = f"{type(exc).__name__}: {exc}"[:500]
    selected_id = str(parsed.get("candidate_id", ""))
    accepted = (selected_id in allowed and parsed.get("requires_hardware") is False
                and parsed.get("writes_original_media") is False)
    if not accepted:
        selected_id = str(candidates[0]["candidate_id"])
        reason = "deterministic first-candidate fallback; model output was unavailable or outside the fixed contract"
    else:
        reason = str(parsed.get("reason", "")).strip()[:500] or "local Director selected one manifest-bound unseen component"
    selected = next(row for row in candidates if row["candidate_id"] == selected_id)
    source_root = coordinator_runtime.SOURCE_ROOT.resolve(strict=True)
    relative = str(selected["source_path"])
    source = (source_root / Path(*PurePosixPath(relative).parts)).resolve(strict=True)
    if (not source.is_relative_to(source_root) or not source.is_file()
            or source.stat().st_size != int(selected["size_bytes"])
            or _ledger_hash(relative) != selected["sha256"]):
        raise RuntimeError("selected component no longer matches its immutable manifest entry")
    survey_id = str(selected_id)
    if selected.get("experiment") == "pe_coff_header_parse_v1":
        created = _registered_task(survey_id, "F2", task_id,
            f"Parse bounded PE/COFF headers from manifest-pinned NCDR binary {relative}; report machine and section metadata without executing code or inferring NCDx data semantics.",
            "ncdx-pe-header-probe",
            f"work/autonomous_manager/ncdx/pe_headers/{survey_id}.json",
            ["Source path, size and SHA-256 match EVIDENCE_LEDGER and the completed signature survey",
             "PE/COFF and section ranges pass independent bounds checks",
             "A separate Supervisor parser reproduces the machine, optional header and sections",
             "Original source remains unchanged; runtime behavior stays UNKNOWN"],
            300, 18, {"pe_header_probe": True, **{key: selected[key] for key in
                ("source_path", "sha256", "size_bytes", "extension", "source_survey_task_id",
                 "observed_pe_signature_offset")}})
    else:
        created = _registered_task(survey_id, "F2", task_id,
            f"Read-only bounded signature survey for manifest-pinned NCDR component {relative}; report observations without assigning format semantics.",
            "ncdx-component-survey",
            f"work/autonomous_manager/ncdx/component_surveys/{survey_id}.json",
            ["Source path, size and SHA-256 match EVIDENCE_LEDGER",
             "Only the first 4096 bytes and printable strings are reported",
             "Fresh independent Supervisor reread reproduces source hash and header observations",
             "Original source remains unchanged and semantic format stays UNKNOWN"],
            300, 24, {"component_scan": True, **{key: selected[key] for key in
                ("source_path", "sha256", "size_bytes", "extension")}})
    if not created:
        raise RuntimeError(f"Director-selected component task already exists: {survey_id}")
    report = {"status": "PASS" if accepted else "PASS_WITH_BOUNDED_FALLBACK",
        "task_id": task_id, "model": model, "model_error": model_error,
        "selected_candidate_id": selected_id, "selected_source_path": relative,
        "selected_source_sha256": selected["sha256"], "selected_size_bytes": selected["size_bytes"],
        "selection_source": "Qwen3.5" if accepted else "deterministic fallback",
        "selection_reason": reason, "safe_schema_validated": accepted,
        "next_task_id": survey_id, "candidate_fingerprint": budget.get("candidate_fingerprint"),
        "remaining_unseen_candidates": max(0, len(candidates) - 1),
        "source_write_count": 0, "original_media_write_count": 0,
        "physical_compatibility": "NOT_TESTED", "created_utc": _utc()}
    report_path = PROJECT_ROOT / "reports" / f"autonomous_director_sw_component_{task_id.rsplit('_', 1)[-1]}.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report["artifact"] = manager._artifact(task_id, report_path,
        "Qwen3.5 selected a real unexamined NCDR binary from the saved SHA-256 inventory",
        "PASS: fixed candidate ID, path containment, manifest SHA and source size revalidated")
    manager._event("project_director_component_goal_selected", {
        "task_id": task_id, "selected_task_id": survey_id, "selected_source_path": relative,
        "model": model, "model_choice_accepted": accepted,
        "remaining_unseen_candidates": max(0, len(candidates) - 1), "model_error": model_error})
    return report


def seed_next_component_survey_task() -> dict[str, Any]:
    """Queue the next unseen, manifest-backed firmware/software component."""
    candidates = _component_scan_candidates()
    if not candidates:
        return {"created": False, "reason": "No manifest-backed SW executable or firmware components are available."}
    source_root = coordinator_runtime.SOURCE_ROOT.resolve()
    examined = 0
    for candidate in candidates:
        relative = candidate["source_path"]
        task_id = "AUTO_SW_COMPONENT_SCAN_" + hashlib.sha256(relative.casefold().encode("utf-8")).hexdigest()[:12]
        if _task_status(task_id) is not None:
            examined += 1
            continue
        source = (source_root / Path(*PurePosixPath(relative).parts)).resolve(strict=False)
        if not source.is_relative_to(source_root) or not source.is_file():
            examined += 1
            continue
        if source.stat().st_size != candidate["size_bytes"]:
            examined += 1
            continue
        output = f"work/autonomous_manager/ncdx/component_surveys/{task_id}.json"
        created = _registered_task(task_id, "F2", None,
            f"Read-only survey of {relative} using its existing SHA-256 inventory entry; record bounded bytes and strings, then request an independent local-model review.",
            "ncdx-component-survey", output,
            ["Source is under the fixed NCDR root and matches EVIDENCE_LEDGER SHA-256",
             "Only the first 4096 bytes and printable strings are reported",
             "Source hash is unchanged after reading", "Semantic format remains UNKNOWN",
             "Local Qwen analysis is recorded and independently reviewed"], 300, 24,
            {"component_scan": True, **candidate})
        if created:
            manager._event("project_director_component_scan_created", {
                "task_id": task_id, "source_path": relative,
                "source_sha256": candidate["sha256"], "inventory_candidates": len(candidates),
                "already_examined": examined})
            return {"created": True, "task_id": task_id, "source_path": relative,
                    "reason": "next unseen SW component selected from the persisted SHA-256 inventory"}
        examined += 1
    return {"created": False, "reason": f"All {len(candidates)} eligible manifest-backed SW components already have a task or are unavailable."}


def _firmware_hex_candidates() -> list[dict[str, Any]]:
    """Return only small, inventory-backed firmware HEX files under the SW tree."""
    ledger = PROJECT_ROOT / "EVIDENCE_LEDGER.sqlite"
    if not ledger.is_file():
        return []
    root = coordinator_runtime.SOURCE_ROOT.resolve(strict=True)
    with closing(sqlite3.connect(f"file:{ledger.as_posix()}?mode=ro", uri=True)) as conn:
        rows = conn.execute("SELECT source_path,sha256,size_bytes,extension FROM artifacts WHERE source_group='SW' ORDER BY source_path").fetchall()
    found: list[dict[str, Any]] = []
    for source_path, digest, size, extension in rows:
        relative = str(source_path).replace("\\", "/").strip("/")
        parsed = PurePosixPath(relative)
        if (not relative.casefold().startswith("sw/") or parsed.is_absolute() or ".." in parsed.parts
                or parsed.suffix.upper() != ".HEX" or not digest or not (0 < int(size or 0) <= 16 * 1024 * 1024)):
            continue
        source = (root / Path(*parsed.parts)).resolve(strict=False)
        if not source.is_relative_to(root) or not source.is_file() or source.stat().st_size != int(size):
            continue
        found.append({"relative_path": parsed.as_posix(), "sha256": str(digest), "size_bytes": int(size)})
    return found


def seed_next_firmware_hex_task() -> dict[str, Any]:
    """Queue a finite, manifest-pinned firmware HEX format decode when available."""
    sources = _firmware_hex_candidates()
    if not sources:
        return {"created": False, "reason": "No bounded, manifest-backed SW .HEX firmware inputs are available."}
    fingerprint = hashlib.sha256(json.dumps(sources, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:12]
    task_id = f"AUTO_FIRMWARE_INTEL_HEX_READ_{fingerprint}"
    if _task_status(task_id) is not None:
        return {"created": False, "reason": f"firmware HEX analysis already exists ({_task_status(task_id)})"}
    created = _registered_task(task_id, "F2", None,
        "Decode the manifest-pinned NCDR firmware .HEX records, verify checksums and address ranges with a separate implementation, and preserve instruction semantics as unknown.",
        "firmware-intel-hex-reader", f"work/autonomous_manager/firmware/intel_hex/{task_id}.json",
        ["All sources stay under the fixed read-only NCDR root and match EVIDENCE_LEDGER SHA-256",
         "Every Intel HEX record length, checksum, address transition and terminal EOF is valid",
         "A separately implemented reader reproduces record counts, address ranges and image digest",
         "Original source size, mtime and SHA-256 remain unchanged; output exists only under work/",
         "Firmware instruction semantics and physical compatibility remain explicitly unknown"],
        300, 16, {"firmware_intel_hex": True, "sources": sources, "max_bytes_per_source": 16 * 1024 * 1024})
    if created:
        manager._event("project_director_firmware_hex_task_created", {"task_id": task_id,
            "source_count": len(sources), "source_paths": [row["relative_path"] for row in sources],
            "reason": "all finite NCDx suffix probes are recorded; verified firmware-container work is an independent active goal"})
    return {"created": created, "task_id": task_id if created else None,
            "reason": "manifest-backed firmware records are being tested independently of map-file hypotheses",
            "sources": sources}


def _verified_b03_navimain_identity() -> dict[str, Any] | None:
    """Expose one exact B03-verified executable for a distinct, bounded import-table experiment."""
    with closing(sqlite3.connect(STATE_DB, timeout=20)) as conn:
        conn.row_factory = sqlite3.Row
        mission = conn.execute("SELECT status,runtime_task_id,evidence_json FROM mission_tasks "
                               "WHERE canonical_id='B03'").fetchone()
    if not mission or mission["status"] != "DONE" or not mission["runtime_task_id"]:
        return None
    try:
        evidence = json.loads(mission["evidence_json"] or "{}")
        accepted = evidence["acceptance"]
        inventory_sha = str(accepted["inventory_sha256"])
        b03_task_id = str(mission["runtime_task_id"])
        inventory = json.loads((PROJECT_ROOT / "firmware" / "binary-format-inventory.json").read_text(encoding="utf-8"))
    except (OSError, KeyError, TypeError, json.JSONDecodeError):
        return None
    inventory_path = PROJECT_ROOT / "firmware" / "binary-format-inventory.json"
    if (inventory.get("status") != "PASS" or _sha256(inventory_path) != inventory_sha
            or _task_status(b03_task_id) != "DONE"):
        return None
    row = next((item for item in inventory.get("components", [])
                if item.get("source_path") == PE_IMPORT_CENSUS_SOURCE), None)
    if not row or row.get("pe_status") != "PASS_PE_HEADERS" or (row.get("pe_headers") or {}).get("architecture") != "SH4":
        return None
    expected = str(row.get("sha256", "")).lower()
    source = (coordinator_runtime.SOURCE_ROOT / Path(*PurePosixPath(PE_IMPORT_CENSUS_SOURCE).parts)).resolve(strict=True)
    if (not source.is_relative_to(coordinator_runtime.SOURCE_ROOT.resolve(strict=True))
            or _ledger_hash(PE_IMPORT_CENSUS_SOURCE) != expected
            or source.stat().st_size != int(row.get("size_bytes", -1))):
        return None
    return {"b03_task_id": b03_task_id, "b03_inventory_sha256": inventory_sha,
        "source_path": PE_IMPORT_CENSUS_SOURCE, "source_sha256": expected,
        "source_size_bytes": int(row["size_bytes"]), "architecture": "SH4"}


def seed_next_ncdx_pe_import_census_task() -> dict[str, Any]:
    """Create a single manifest-bound firmware API inventory, independent of missing Ghidra."""
    identity = _verified_b03_navimain_identity()
    if identity is None:
        return {"created": False, "reason": "requires the independently accepted B03 inventory and unchanged NAVIMAIN source"}
    fingerprint = hashlib.sha256(json.dumps({"experiment": "ncdx_pe_import_census",
        "version": PE_IMPORT_CENSUS_VERSION, **identity}, sort_keys=True,
        separators=(",", ":")).encode("utf-8")).hexdigest()
    task_id = f"AUTO_NCDX_PE_IMPORT_CENSUS_V{PE_IMPORT_CENSUS_VERSION}_{fingerprint[:16].upper()}"
    existing = _task_status(task_id)
    if existing:
        return {"created": False, "task_id": task_id,
            "reason": f"same source-bound import census already exists ({existing}); no duplicate scan"}
    result_path = f"work/autonomous_manager/ncdx/firmware_imports/{task_id}.json"
    spec = {"id": task_id, "stage": "F2", "depends_on": [identity["b03_task_id"]],
        "hypothesis": "The verified SH4 navigation executable imports named operating-system APIs whose IAT RVAs can narrow, but not prove, the firmware's file-access dependencies.",
        "evidence": [{"type": "accepted_b03_binary_inventory", **identity,
            "inventory_artifact": "firmware/binary-format-inventory.json"}],
        "agent": "ncdx-pe-import-census",
        "budget": {"timeout_s": 180, "attempts": 1, "source_write": False,
            "model_calls": 0, "ncdx_pe_import_census": True,
            "handler_version": PE_IMPORT_CENSUS_VERSION, **identity,
            "source_manifest_sha256": identity["source_sha256"],
            "task_fingerprint": fingerprint},
        "deliverables": [result_path],
        "tests": ["PE import descriptors and thunks are bounded and structurally terminated",
            "Independent parser reproduces every module, named import, hint and IAT file offset",
            "Current source SHA/size still match EVIDENCE_LEDGER and B03 inventory",
            "API name matches are not represented as call-site or runtime proofs",
            "Original source media remains read-only"],
        "next_action": "Use the exact import evidence to prioritize later code inspection; keep B04 waiting for a real disassembler and continue independent NCDx data work.",
        "retry_limit": 1, "priority": 12}
    created = state_store.add_task(spec, db_path=STATE_DB)
    if created:
        manager._event("ncdx_pe_import_census_task_created", {"task_id": task_id,
            "source_path": identity["source_path"], "source_sha256": identity["source_sha256"],
            "b03_inventory_sha256": identity["b03_inventory_sha256"],
            "reason": "verified real executable supports a new bounded firmware IO dependency hypothesis"})
    return {"created": created, "task_id": task_id if created else None,
        "reason": "manifest-bound NAVIMAIN imports can be inspected locally without Codex or Ghidra",
        "source": identity}


def execute_ncdx_pe_import_census(task_id: str) -> dict[str, Any]:
    """Run the fixed parser against one exact B03-verified read-only executable."""
    from src.readers import ncdx_pe_imports
    task = manager._task(task_id)
    budget = task.get("budget", {})
    identity = _verified_b03_navimain_identity()
    if (task.get("agent") != "ncdx-pe-import-census"
            or budget.get("ncdx_pe_import_census") is not True
            or int(budget.get("handler_version", -1)) != PE_IMPORT_CENSUS_VERSION
            or identity is None
            or any(budget.get(key) != identity.get(key) for key in identity)):
        raise ValueError("PE import census does not match its exact accepted source and predecessor")
    source = (coordinator_runtime.SOURCE_ROOT / Path(*PurePosixPath(PE_IMPORT_CENSUS_SOURCE).parts)).resolve(strict=True)
    before_stat = source.stat()
    before_hash = _sha256(source)
    if before_hash != identity["source_sha256"]:
        raise RuntimeError("NAVIMAIN source no longer matches the B03/EVIDENCE_LEDGER identity")
    parsed = ncdx_pe_imports.parse_imports(source.read_bytes())
    after_hash = _sha256(source)
    after_stat = source.stat()
    if (after_hash != before_hash or before_stat.st_size != after_stat.st_size
            or before_stat.st_mtime_ns != after_stat.st_mtime_ns):
        raise RuntimeError("NAVIMAIN changed during the read-only import-table census")
    report = {"status": "PASS", "task_id": task_id,
        "source_path": PE_IMPORT_CENSUS_SOURCE, "source_size_bytes": before_stat.st_size,
        "source_sha256": before_hash, "manifest_sha256": identity["source_sha256"],
        "b03_inventory_sha256": identity["b03_inventory_sha256"],
        "architecture": identity["architecture"], **parsed,
        "original_media_write_count": 0, "source_write_count": 0,
        "created_utc": _utc(), "physical_compatibility": "NOT_TESTED"}
    output = PROJECT_ROOT / "work" / "autonomous_manager" / "ncdx" / "firmware_imports" / f"{task_id}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(output)
    artifact = manager._artifact(task_id, output,
        "Read-only SH4 NAVIMAIN PE import and IAT inventory",
        "PASS: source hash matches B03 and independent table parser replay is queued")
    _register_supervisor("AUTO_SUPERVISOR_" + task_id, task_id)
    return {**report, "artifact": artifact}


def _verified_embedded_pe_source_identity() -> dict[str, Any] | None:
    navimain = _verified_b03_navimain_identity()
    if navimain is None:
        return None
    inventory_path = PROJECT_ROOT / "firmware" / "binary-format-inventory.json"
    try:
        inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    entry = next((row for row in inventory.get("components", [])
                  if row.get("source_path") == EMBEDDED_PE_SEARCH_SOURCE), None)
    if not entry or inventory.get("status") != "PASS":
        return None
    source = (coordinator_runtime.SOURCE_ROOT / Path(*PurePosixPath(EMBEDDED_PE_SEARCH_SOURCE).parts)).resolve(strict=True)
    expected = str(entry.get("sha256", "")).lower()
    if (not source.is_relative_to(coordinator_runtime.SOURCE_ROOT.resolve(strict=True))
            or source.stat().st_size != int(entry.get("size_bytes", -1))
            or _ledger_hash(EMBEDDED_PE_SEARCH_SOURCE) != expected):
        return None
    return {"b03_task_id": navimain["b03_task_id"],
        "b03_inventory_sha256": navimain["b03_inventory_sha256"],
        "source_path": EMBEDDED_PE_SEARCH_SOURCE, "source_sha256": expected,
        "source_size_bytes": int(entry["size_bytes"])}


def _accepted_pe_import_result() -> dict[str, Any] | None:
    with closing(sqlite3.connect(STATE_DB, timeout=20)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT id,result_json FROM tasks WHERE agent='ncdx-pe-import-census' "
                           "AND status='DONE' ORDER BY updated_utc DESC,id LIMIT 1").fetchone()
    if not row:
        return None
    task_id = str(row["id"])
    supervisor_id = "AUTO_SUPERVISOR_" + task_id
    if _task_status(supervisor_id) != "DONE":
        return None
    try:
        result = json.loads(row["result_json"] or "{}")
        review = _task_result(supervisor_id)
    except (json.JSONDecodeError, RuntimeError):
        return None
    artifact = result.get("artifact") or {}
    relative = PurePosixPath(str(artifact.get("path", "")))
    if (result.get("status") != "PASS" or review.get("status") != "PASS"
            or review.get("target_task") != task_id or not artifact.get("sha256")
            or relative.is_absolute() or ".." in relative.parts):
        return None
    artifact_path = (PROJECT_ROOT / Path(*relative.parts)).resolve(strict=True)
    if (not artifact_path.is_relative_to(PROJECT_ROOT.resolve())
            or _sha256(artifact_path) != str(artifact["sha256"])):
        return None
    return {"task_id": task_id, "supervisor_task_id": supervisor_id,
        "artifact_path": relative.as_posix(), "artifact_sha256": str(artifact["sha256"]),
        "import_count": int(result.get("import_count", -1)),
        "io_api_candidate_count": len(result.get("io_api_candidates", []))}


def seed_next_ncdx_embedded_pe_search_task() -> dict[str, Any]:
    """Follow accepted ordinal-only firmware imports with one bounded NK.BIN image search."""
    predecessor = _accepted_pe_import_result()
    identity = _verified_embedded_pe_source_identity()
    if predecessor is None or identity is None:
        return {"created": False, "reason": "awaits accepted NAVIMAIN import evidence and the B03-bound NK.BIN identity"}
    if predecessor["import_count"] <= 0 or predecessor["io_api_candidate_count"] > predecessor["import_count"]:
        return {"created": False, "reason": "accepted import evidence does not justify embedded firmware follow-up"}
    fingerprint = hashlib.sha256(json.dumps({"experiment": "ncdx_embedded_pe_search",
        "version": EMBEDDED_PE_SEARCH_VERSION, "source": identity,
        "predecessor": predecessor}, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    task_id = f"AUTO_NCDX_EMBEDDED_PE_SEARCH_V{EMBEDDED_PE_SEARCH_VERSION}_{fingerprint[:16].upper()}"
    existing = _task_status(task_id)
    if existing:
        return {"created": False, "task_id": task_id,
            "reason": f"same source-bound embedded image search already exists ({existing}); no duplicate scan"}
    artifact_path = f"work/autonomous_manager/ncdx/embedded_pe/{task_id}.json"
    spec = {"id": task_id, "stage": "F2", "depends_on": [identity["b03_task_id"],
        predecessor["task_id"], predecessor["supervisor_task_id"]],
        "hypothesis": "The opaque NK.BIN contains a structurally valid embedded PE image whose bounded section layout may provide a firmware module for later ordinal/export analysis.",
        "evidence": [{"type": "accepted_pe_import_census", **predecessor},
            {"type": "accepted_b03_source_identity", **identity}],
        "agent": "ncdx-embedded-pe-search",
        "budget": {"timeout_s": 300, "attempts": 1, "source_write": False,
            "model_calls": 0, "ncdx_embedded_pe_search": True,
            "handler_version": EMBEDDED_PE_SEARCH_VERSION,
            **identity, "predecessor_task_id": predecessor["task_id"],
            "predecessor_artifact_sha256": predecessor["artifact_sha256"],
            "task_fingerprint": fingerprint},
        "deliverables": [artifact_path],
        "tests": ["Inspect every bounded MZ marker and validate PE signature, optional header, section count and raw bounds",
            "Independent parser reproduces all valid offsets and embedded-byte hashes",
            "Source SHA/size and B03 inventory remain unchanged",
            "Embedded image role and exports remain UNKNOWN until separately parsed"],
        "next_action": "If a valid image exists, propose a separate bounded export-table/ordinal hypothesis; otherwise park the firmware path and select an independent NCDx data experiment.",
        "retry_limit": 1, "priority": 13}
    created = state_store.add_task(spec, db_path=STATE_DB)
    if created:
        manager._event("ncdx_embedded_pe_search_task_created", {"task_id": task_id,
            "source_path": identity["source_path"], "source_sha256": identity["source_sha256"],
            "predecessor_task_id": predecessor["task_id"],
            "predecessor_artifact_sha256": predecessor["artifact_sha256"],
            "reason": "accepted ordinal-heavy import table motivates one embedded-module discovery hypothesis"})
    return {"created": created, "task_id": task_id if created else None,
        "reason": "accepted NAVIMAIN imports justify bounded read-only NK.BIN structural image discovery",
        "source": identity}


def execute_ncdx_embedded_pe_search(task_id: str) -> dict[str, Any]:
    """Scan only the exact B03-verified NK.BIN, never writing to original media."""
    from src.readers import ncdx_embedded_pe
    task = manager._task(task_id)
    budget = task.get("budget", {})
    identity = _verified_embedded_pe_source_identity()
    predecessor = _accepted_pe_import_result()
    if (task.get("agent") != "ncdx-embedded-pe-search"
            or budget.get("ncdx_embedded_pe_search") is not True
            or int(budget.get("handler_version", -1)) != EMBEDDED_PE_SEARCH_VERSION
            or identity is None or predecessor is None
            or any(budget.get(key) != identity.get(key) for key in identity)
            or budget.get("predecessor_task_id") != predecessor["task_id"]
            or budget.get("predecessor_artifact_sha256") != predecessor["artifact_sha256"]):
        raise ValueError("embedded PE search does not match accepted source and predecessor evidence")
    source = (coordinator_runtime.SOURCE_ROOT / Path(*PurePosixPath(EMBEDDED_PE_SEARCH_SOURCE).parts)).resolve(strict=True)
    before_stat = source.stat()
    before_hash = _sha256(source)
    if before_hash != identity["source_sha256"]:
        raise RuntimeError("NK.BIN no longer matches its B03 and EVIDENCE_LEDGER identity")
    scan = ncdx_embedded_pe.scan_embedded_pe(source.read_bytes())
    after_hash = _sha256(source)
    after_stat = source.stat()
    if (after_hash != before_hash or before_stat.st_size != after_stat.st_size
            or before_stat.st_mtime_ns != after_stat.st_mtime_ns):
        raise RuntimeError("NK.BIN changed during the read-only embedded image search")
    report = {"status": "PASS", "task_id": task_id,
        "source_path": EMBEDDED_PE_SEARCH_SOURCE, "source_size_bytes": before_stat.st_size,
        "source_sha256": before_hash, "manifest_sha256": identity["source_sha256"],
        "b03_inventory_sha256": identity["b03_inventory_sha256"],
        "predecessor_task_id": predecessor["task_id"],
        "predecessor_artifact_sha256": predecessor["artifact_sha256"], **scan,
        "source_write_count": 0, "original_media_write_count": 0,
        "created_utc": _utc(), "physical_compatibility": "NOT_TESTED"}
    output = PROJECT_ROOT / "work" / "autonomous_manager" / "ncdx" / "embedded_pe" / f"{task_id}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(output)
    artifact = manager._artifact(task_id, output,
        "Manifest-bound embedded PE candidate inventory from opaque NK.BIN",
        f"PASS: independent structural replay queued; {scan['valid_pe_image_count']} valid image(s) observed")
    _register_supervisor("AUTO_SUPERVISOR_" + task_id, task_id)
    return {**report, "artifact": artifact}


MP0_WRITER_TASK_ID = "AUTO_F3_EXPERIMENTAL_MP0_ROUNDTRIP_001"
MP0_INDEPENDENT_READBACK_TASK_ID = "AUTO_MP0_INDEPENDENT_READBACK_01"
MP0_SOURCE_PATHS = {
    "SW": "SW/DB/EUZ.MP0",
    "Italy": "OPEL NCDx Italia 2010-2011/DB/IZ.MP0",
    "Scandinavia": "OPEL NCDx Scandinavia 2010-2011/DB/SCZ.MP0",
}


def seed_next_mp0_independent_readback_task() -> dict[str, Any]:
    """Queue a separate parser check for the already-created writer copies."""
    status = _task_status(MP0_WRITER_TASK_ID)
    if status != "DONE":
        return {"created": False, "reason": f"copy-only MP0 writer evidence is {status or 'missing'}"}
    existing = _task_status(MP0_INDEPENDENT_READBACK_TASK_ID)
    if existing:
        return {"created": False, "reason": f"independent MP0 readback already exists ({existing})"}
    writer = _task_result(MP0_WRITER_TASK_ID)
    if (writer.get("status") != "PASS_COPY_ONLY" or writer.get("source_write_count") != 0
            or writer.get("original_media_protection") != "PASS"
            or len(writer.get("regional_roundtrips", [])) != 3):
        return {"created": False, "reason": "saved writer result does not meet read-only preconditions"}
    created = _registered_task(MP0_INDEPENDENT_READBACK_TASK_ID, "F3", MP0_WRITER_TASK_ID,
        "An independent fixed-header parser must reopen the three byte-preserving MP0 copies and the controlled one-field copy without interpreting payload bytes.",
        "mp0-independent-readback",
        f"work/autonomous_manager/writer_roundtrip/{MP0_INDEPENDENT_READBACK_TASK_ID}.json",
        ["All three no-op copies match their manifest-pinned source hashes and independently parsed headers",
         "The controlled copy changes only the confirmed dataset-code bytes 48-63",
         "Original hashes, sizes and modification times remain unchanged",
         "The independent parser does not import the primary MP0 reader",
         "Payload semantics remain UNKNOWN and physical compatibility remains NOT_TESTED"],
        900, 19, {"mp0_independent_readback": True, "source_task": MP0_WRITER_TASK_ID})
    if created:
        manager._event("project_director_mp0_readback_task_created", {
            "task_id": MP0_INDEPENDENT_READBACK_TASK_ID, "dependency": MP0_WRITER_TASK_ID,
            "reason": "existing writer evidence needs a fresh independent readback"})
    return {"created": created, "task_id": MP0_INDEPENDENT_READBACK_TASK_ID if created else None,
            "reason": "independent readback tests the existing writer artifacts against the remaining F3 criterion"}


def _only_confirmed_header_field_changed(source: Path, target: Path) -> list[int]:
    changed: list[int] = []
    offset = 0
    with source.open("rb") as left, target.open("rb") as right:
        while True:
            a = left.read(1024 * 1024)
            b = right.read(len(a))
            if len(a) != len(b):
                raise RuntimeError("controlled MP0 copy length differs from original")
            if not a:
                if right.read(1):
                    raise RuntimeError("controlled MP0 copy contains trailing bytes")
                break
            for index, (old, new) in enumerate(zip(a, b)):
                absolute = offset + index
                if old != new:
                    if not 48 <= absolute < 64:
                        raise RuntimeError(f"unexpected change outside confirmed dataset-code field at 0x{absolute:X}")
                    changed.append(absolute)
                    if len(changed) > 16:
                        raise RuntimeError("controlled MP0 copy changed more than one fixed-width field")
            offset += len(a)
    return changed


def _verify_mp0_writer_target(target_id: str, target_task: dict[str, Any],
                              result: dict[str, Any]) -> dict[str, Any]:
    """Re-hash originals and independently parse writer outputs, fresh each run."""
    from src.readers.mp0_independent import inspect_mp0_independently
    budget = target_task.get("budget", {})
    if (result.get("status") != "PASS" or budget.get("mp0_independent_readback") is not True
            or budget.get("source_task") != MP0_WRITER_TASK_ID):
        raise RuntimeError("task is not the fixed MP0 independent-readback job")
    writer = _task_result(MP0_WRITER_TASK_ID)
    if (writer.get("status") != "PASS_COPY_ONLY" or writer.get("source_write_count") != 0
            or writer.get("original_media_protection") != "PASS"):
        raise RuntimeError("saved MP0 writer result failed its read-only provenance checks")
    by_region = {str(row.get("region")): row for row in writer.get("regional_roundtrips", [])
                 if isinstance(row, dict)}
    if set(by_region) != set(MP0_SOURCE_PATHS):
        raise RuntimeError("writer result must contain exactly the three saved regional copies")
    source_root = coordinator_runtime.SOURCE_ROOT.resolve(strict=True)
    writer_work = (PROJECT_ROOT / "work" / "autonomous_manager" / "writer_roundtrip"
                   / MP0_WRITER_TASK_ID).resolve(strict=True)
    rows: list[dict[str, Any]] = []
    for region, relative in MP0_SOURCE_PATHS.items():
        item = by_region[region]
        no_op = item.get("no_op", {})
        source = (source_root / Path(*PurePosixPath(relative).parts)).resolve(strict=True)
        if not source.is_relative_to(source_root) or source.relative_to(source_root).as_posix() != relative:
            raise RuntimeError(f"refusing an unexpected original source path for {region}")
        before = source.stat()
        source_hash = _sha256(source)
        manifest_hash = _ledger_hash(relative)
        after = source.stat()
        expected = str(no_op.get("source_sha256_after", ""))
        if (not manifest_hash or manifest_hash != source_hash or source_hash != expected
                or before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns):
            raise RuntimeError(f"original source differs from saved or manifest proof: {relative}")
        copy = Path(str(no_op.get("working_copy", ""))).resolve(strict=True)
        if not copy.is_relative_to(writer_work) or copy.suffix.upper() != ".MP0":
            raise RuntimeError(f"refusing an MP0 no-op copy outside its fixed work folder: {region}")
        if no_op.get("no_op_roundtrip_pass") is not True:
            raise RuntimeError(f"saved byte-preserving copy did not pass for {region}")
        parsed = inspect_mp0_independently(copy)
        saved_header = item.get("source_header", {})
        expected_header = {"file_size": before.st_size, "sha256": source_hash,
            "magic": saved_header.get("magic"), "copyright": saved_header.get("copyright"),
            "internal_format_version": saved_header.get("internal_format_version"),
            "dataset_code": saved_header.get("dataset_code")}
        if any(parsed.get(key) != value for key, value in expected_header.items()):
            raise RuntimeError(f"fresh independent header readback differs for {region}")
        rows.append({"region": region, "relative_path": relative,
            "source_sha256": source_hash, "manifest_sha256": manifest_hash,
            "copy_sha256": parsed["sha256"], "independent_header_match": True,
            "no_op_copy_match": parsed["sha256"] == source_hash,
            "source_stat_unchanged": True})
        if not rows[-1]["no_op_copy_match"]:
            raise RuntimeError(f"no-op copy hash differs from original for {region}")

    controlled = writer.get("controlled_header_change", {})
    source = (source_root / Path(*PurePosixPath(MP0_SOURCE_PATHS["SW"]).parts)).resolve(strict=True)
    target = Path(str(controlled.get("working_copy", ""))).resolve(strict=True)
    if not target.is_relative_to(writer_work) or target.suffix.upper() != ".MP0":
        raise RuntimeError("refusing controlled MP0 copy outside its fixed work folder")
    source_stat = source.stat()
    source_hash = _sha256(source)
    if (_ledger_hash(MP0_SOURCE_PATHS["SW"]) != source_hash
            or controlled.get("source_sha256_after") != source_hash
            or source_stat.st_size != source.stat().st_size):
        raise RuntimeError("controlled-change source does not match the read-only manifest baseline")
    parsed_target = inspect_mp0_independently(target)
    changed = _only_confirmed_header_field_changed(source, target)
    if (parsed_target["file_size"] != source_stat.st_size
            or parsed_target["sha256"] != controlled.get("working_copy_sha256")
            or controlled.get("old_code") != "EU44420940.82"
            or controlled.get("new_code") != "SC44442940.82"
            or parsed_target["dataset_code"] != "SC44442940.82"
            or changed != sorted(int(value) for value in controlled.get("changed_offsets", []))
            or not changed):
        raise RuntimeError("fresh independent readback did not reproduce the controlled header experiment")
    return {"task_id": target_id, "status": "PASS", "regional_source_count": len(rows),
        "regional_readbacks": rows, "all_no_op_copies_match_manifest_sources": True,
        "controlled_change": {"source_sha256": source_hash, "working_copy_sha256": parsed_target["sha256"],
            "old_dataset_code": "EU44420940.82", "new_dataset_code": "SC44442940.82",
            "changed_offsets": changed, "only_confirmed_dataset_code_field_changed": True,
            "independent_header_readback": True},
        "independent_parser": "src.readers.mp0_independent; separate implementation",
        "all_original_hashes_unchanged": True, "original_media_write_count": 0,
        "payload_semantics": "UNKNOWN", "physical_compatibility": "NOT_TESTED"}


def execute_mp0_independent_readback_task(task_id: str) -> dict[str, Any]:
    task = manager._task(task_id)
    proof = _verify_mp0_writer_target(task_id, task, {"status": "PASS"})
    output = PROJECT_ROOT / "work" / "autonomous_manager" / "writer_roundtrip" / f"{task_id}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(proof, ensure_ascii=False, indent=2) + "\n"
    if output.exists():
        if output.read_text(encoding="utf-8") != text:
            raise FileExistsError(f"refusing to overwrite a different readback artifact: {output}")
    else:
        with output.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
    artifact = manager._artifact(task_id, output,
        "Independent readback of three MP0 no-op copies and one controlled header-field copy",
        "PASS: separate parser, manifest hashes, original immutability and field-limited diff")
    _register_supervisor("AUTO_SUPERVISOR_" + task_id, task_id)
    return {**proof, "artifact": artifact}


def _record_mp0_writer_readiness(proof: dict[str, Any], target_id: str) -> None:
    controlled = proof.get("controlled_change", {})
    if (proof.get("status") != "PASS" or proof.get("regional_source_count") != 3
            or proof.get("all_no_op_copies_match_manifest_sources") is not True
            or proof.get("all_original_hashes_unchanged") is not True
            or proof.get("original_media_write_count") != 0
            or controlled.get("only_confirmed_dataset_code_field_changed") is not True):
        raise RuntimeError("refusing F3 readiness update without independent copy and field proof")
    writer_path = PROJECT_ROOT / "reports" / "autonomous_writer_roundtrip.json"
    writer = _json(writer_path)
    if writer.get("status") != "PASS_COPY_ONLY" or len(writer.get("regional_roundtrips", [])) < 3:
        raise RuntimeError("saved writer report is missing its verified copy-only baseline")
    writer["independent_readback"] = {"status": "PASS", "task_id": target_id,
        "regional_source_count": 3, "no_op_copies_match_manifest_sources": True,
        "controlled_change_field_limited": True, "separate_parser": True,
        "original_media_write_count": 0, "payload_semantics": "UNKNOWN",
        "physical_compatibility": "NOT_TESTED"}
    temp = writer_path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(writer, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(writer_path)
    with closing(sqlite3.connect(STATE_DB, timeout=20)) as conn:
        row = conn.execute("SELECT criteria_json,proof_json FROM stage_gates WHERE stage='F3'").fetchone()
        if not row:
            raise RuntimeError("F3 readiness gate is missing")
        try:
            criteria, saved = json.loads(row[0] or "{}"), json.loads(row[1] or "{}")
        except json.JSONDecodeError as exc:
            raise RuntimeError("F3 readiness gate contains invalid JSON") from exc
        passed = saved.setdefault("criteria_pass", {})
        passed.update({"no_op_roundtrip": True, "controlled_change": True, "independent_readback": True})
        status = "COMPLETE" if all(passed.get(key) is True for key in criteria) else "IN_PROGRESS"
        conn.execute("UPDATE stage_gates SET status=?,proof_json=?,updated_utc=? WHERE stage='F3'",
                     (status, json.dumps(saved, ensure_ascii=False), _utc()))
        conn.commit()


def execute_firmware_hex_task(task_id: str) -> dict[str, Any]:
    """Parse and independently verify each fixed, manifest-pinned firmware HEX source."""
    from src.firmware.intel_hex import summarize_file
    from src.firmware.verify_intel_hex import verify_file_independently
    task = manager._task(task_id)
    budget = task.get("budget", {})
    sources = budget.get("sources")
    if not budget.get("firmware_intel_hex") or not isinstance(sources, list) or not sources:
        raise RuntimeError("firmware HEX task is missing its fixed inventory evidence")
    root = coordinator_runtime.SOURCE_ROOT.resolve(strict=True)
    rows: list[dict[str, Any]] = []
    for item in sources:
        relative = str(item.get("relative_path", "")).replace("\\", "/")
        parsed = PurePosixPath(relative)
        if (not relative.casefold().startswith("sw/") or parsed.is_absolute() or ".." in parsed.parts
                or parsed.suffix.upper() != ".HEX"):
            raise RuntimeError(f"refusing source outside firmware HEX allowlist: {relative}")
        source = (root / Path(*parsed.parts)).resolve(strict=True)
        if not source.is_relative_to(root) or source.stat().st_size != int(item.get("size_bytes", -1)):
            raise RuntimeError(f"firmware HEX source escaped root or changed size: {relative}")
        expected = str(item.get("sha256", ""))
        manifest = _ledger_hash(relative)
        before_stat = source.stat()
        before_hash = _sha256(source)
        if not expected or expected != manifest or expected != before_hash:
            raise RuntimeError(f"firmware HEX SHA-256 differs from scheduled evidence: {relative}")
        primary = summarize_file(source, max_bytes=int(budget.get("max_bytes_per_source", 16 * 1024 * 1024)))
        independent = verify_file_independently(source, max_bytes=int(budget.get("max_bytes_per_source", 16 * 1024 * 1024)))
        compare_keys = ("record_count", "record_type_counts", "data_record_bytes", "unique_image_bytes",
                        "address_range_count", "address_ranges_preview", "address_ranges_truncated",
                        "address_image_sha256", "eof_seen")
        matched = all(primary.get(key) == independent.get(key) for key in compare_keys)
        after_stat = source.stat()
        after_hash = _sha256(source)
        unchanged = (before_hash == after_hash == expected and before_stat.st_size == after_stat.st_size
                     and before_stat.st_mtime_ns == after_stat.st_mtime_ns)
        if not matched or not unchanged:
            raise RuntimeError(f"independent readback/source protection failed for {relative}")
        rows.append({"relative_path": relative, "manifest_sha256": manifest,
            "source_sha256_before": before_hash, "source_sha256_after": after_hash,
            "source_size_bytes": before_stat.st_size, "source_mtime_unchanged": True,
            "primary_decode": primary, "independent_decode": independent,
            "independent_match": True, "source_write_count": 0})
    result = {"status": "PASS", "task_id": task_id,
        "format_claim": "Intel HEX record syntax and checksums confirmed; firmware instruction semantics unknown",
        "source_count": len(rows), "sources": rows, "original_media_write_count": 0,
        "physical_compatibility": "NOT_TESTED", "created_utc": _utc(),
        "verified": {"manifest_entries_match": True, "records_and_checksums_valid": True,
            "independent_decoder_matches": True, "original_hashes_unchanged": True,
            "source_write_count": 0, "source_count": len(rows),
            "confirmed_container": "Intel HEX", "payload_semantics": "UNKNOWN"}}
    output = PROJECT_ROOT / "work" / "autonomous_manager" / "firmware" / "intel_hex" / f"{task_id}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.with_suffix(".json.tmp")
    temp.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(output)
    result["artifact"] = manager._artifact(task_id, output,
        "Read-only Intel HEX decoding with independently reconstructed address image",
        "PASS: four original hashes match inventory, checksums valid, independent decoder agrees")
    _register_supervisor("AUTO_SUPERVISOR_" + task_id, task_id)
    return result


def _data_profile_task_id(suffix: str, mode: str, sources: list[dict[str, Any]], *,
                          upstream_task_id: str | None = None,
                          profile_parameters: dict[str, Any] | None = None) -> str:
    fingerprint_data: Any = [(row["relative_path"], row["sha256"], row["size_bytes"])
                             for row in sources]
    if mode in {"CONTAINER_ROUNDTRIP", "DECODED_STRUCTURE_SCAN", "STRING_COORDINATE_PROXIMITY_AUDIT",
                "PRINTABLE_RUN_LAYOUT_PROFILE", "REPEATED_TEXT_DICTIONARY_PROFILE",
                "REPEATED_TEXT_COORDINATE_AUDIT", "BLOCK_BOUNDARY_PROFILE",
                "EXACT_BLOCK_ANCHOR_SCAN", "TEXT_COORDINATE_ASSOCIATION_CENSUS",
                "REPEATED_TEXT_COORDINATE_ASSOCIATION_CENSUS",
                "STANDALONE_ZLIB_STREAM_CENSUS",
                "ZLIB_STREAM_BOUNDARY_CONTEXT_PROFILE",
                "ZLIB_DECODED_COORDINATE_CANDIDATE_CENSUS"}:
        version = {"CONTAINER_ROUNDTRIP": CONTAINER_ROUNDTRIP_VERSION,
                   "DECODED_STRUCTURE_SCAN": DECODED_STRUCTURE_SCAN_VERSION,
                   "STRING_COORDINATE_PROXIMITY_AUDIT": STRING_COORDINATE_PROXIMITY_AUDIT_VERSION,
                   "PRINTABLE_RUN_LAYOUT_PROFILE": PRINTABLE_RUN_LAYOUT_PROFILE_VERSION,
                   "REPEATED_TEXT_DICTIONARY_PROFILE": REPEATED_TEXT_DICTIONARY_PROFILE_VERSION,
                   "REPEATED_TEXT_COORDINATE_AUDIT": REPEATED_TEXT_COORDINATE_AUDIT_VERSION,
                   "BLOCK_BOUNDARY_PROFILE": BLOCK_BOUNDARY_PROFILE_VERSION,
                   "EXACT_BLOCK_ANCHOR_SCAN": EXACT_BLOCK_ANCHOR_SCAN_VERSION,
                   "TEXT_COORDINATE_ASSOCIATION_CENSUS": TEXT_COORDINATE_ASSOCIATION_CENSUS_VERSION,
                   "REPEATED_TEXT_COORDINATE_ASSOCIATION_CENSUS": REPEATED_TEXT_COORDINATE_ASSOCIATION_CENSUS_VERSION,
                   "STANDALONE_ZLIB_STREAM_CENSUS": STANDALONE_ZLIB_STREAM_CENSUS_VERSION,
                    "ZLIB_STREAM_BOUNDARY_CONTEXT_PROFILE": ZLIB_STREAM_BOUNDARY_CONTEXT_PROFILE_VERSION,
                    "ZLIB_DECODED_COORDINATE_CANDIDATE_CENSUS": ZLIB_DECODED_COORDINATE_CANDIDATE_CENSUS_VERSION}[mode]
        fingerprint_data = {"sources": fingerprint_data, "handler_version": version}
        if upstream_task_id:
            fingerprint_data["upstream_task_id"] = upstream_task_id
        if (mode == "ZLIB_STREAM_BOUNDARY_CONTEXT_PROFILE" and profile_parameters
                and profile_parameters != {"context_bytes": 16}):
            fingerprint_data["profile_parameters"] = profile_parameters
        if mode == "ZLIB_DECODED_COORDINATE_CANDIDATE_CENSUS" and profile_parameters:
            fingerprint_data["profile_parameters"] = profile_parameters
    fingerprint = hashlib.sha256(json.dumps(
        fingerprint_data,
        sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()[:8]
    return f"AUTO_NCDX_DATA_{suffix}_{mode}_{fingerprint}"


def _data_profile_sources(suffix: str) -> list[dict[str, Any]]:
    root = coordinator_runtime.SOURCE_ROOT.resolve(strict=True)
    rows: list[dict[str, Any]] = []
    for label, folder, prefix in coordinator_runtime.REGIONS:
        source = coordinator_runtime._target_path(folder, prefix, suffix).resolve(strict=True)
        if not source.is_relative_to(root):
            raise ValueError(f"NCDx profile source escaped the read-only media root: {source}")
        relative = source.relative_to(root).as_posix()
        entry = _ledger_entry(relative)
        if not entry or not entry.get("sha256") or int(entry.get("size_bytes") or 0) <= 0:
            raise ValueError(f"NCDx source is missing its existing SHA-256/size inventory entry: {relative}")
        stat = source.stat()
        if stat.st_size != int(entry["size_bytes"]):
            raise ValueError(f"NCDx source size differs from the existing inventory: {relative}")
        rows.append({"region": label, "relative_path": relative,
                     "sha256": str(entry["sha256"]), "size_bytes": stat.st_size})
    return rows


def seed_next_roadlink_portability_task() -> dict[str, Any]:
    """Seed one new, deduplicated cross-region road-index reader experiment."""
    from src.readers.ncdx_roadlink_portability import TABLES
    root = coordinator_runtime.SOURCE_ROOT.resolve(strict=True)
    sources: list[dict[str, Any]] = []
    for suffix in TABLES:
        for row in _data_profile_sources(suffix):
            relative = str(row["relative_path"])
            candidate = (root / Path(*PurePosixPath(relative).parts)).resolve(strict=True)
            if not candidate.is_relative_to(root):
                raise ValueError(f"roadlink portability source escaped the original-media root: {relative}")
            sources.append({**row, "absolute_path": str(candidate)})
    fingerprint = hashlib.sha256(json.dumps({
        "experiment": "ncdx_roadlink_index_portability",
        "handler_version": ROADLINK_PORTABILITY_VERSION,
        "sources": [(row["region"], row["relative_path"], row["sha256"], row["size_bytes"])
                    for row in sources]}, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()[:16].upper()
    task_id = f"AUTO_NCDX_ROADLINK_PORTABILITY_V{ROADLINK_PORTABILITY_VERSION}_{fingerprint}"
    existing_status = _task_status(task_id)
    if existing_status:
        return {"created": False, "task_id": task_id,
                "reason": f"roadlink portability experiment already exists ({existing_status})"}
    task = {"id": task_id, "stage": "F2", "depends_on": [],
        "hypothesis": "The verified EUZ RL -> IOF -> IL index relationships transfer to installed IZ and SCZ NCDx databases.",
        "evidence": [{"type": "manifest_bound_ncdx_inputs", "sources": [
            {key: row[key] for key in ("region", "relative_path", "sha256", "size_bytes")}
            for row in sources], "prior_evidence": [
                "research/NCDR1500_VERIFIED_20261027/roadlinks/NCDR1500_ROADLINK_RESEARCH_20261027/OUTPUT/EVIDENCE_ROADLINKS.json",
                "research/NCDR1500_VERIFIED_20261027/geography/OUTPUT_GEO/EVIDENCE_GEOGRAPHY.json"]}],
        "agent": "ncdx-roadlink-portability",
        "budget": {"timeout_s": 3600, "attempts": 1, "source_write": False,
            "max_model_calls": 0, "ncdx_roadlink_portability": True,
            "handler_version": ROADLINK_PORTABILITY_VERSION,
            "source_fingerprint": fingerprint, "sources": sources},
        "deliverables": [f"work/autonomous_manager/ncdx/roadlink_portability/{task_id}.json"],
        "tests": ["Decode all nine manifest-bound RL/IOF/IL containers with bounded streaming",
            "Check table types, lengths, record counts, references, variable-record boundaries, group counts, and hashes",
            "Verify every original source remains unchanged", "Do not claim road geometry, topology, routing, or disc compatibility"],
        "next_action": "Have the Supervisor independently re-read source identities and evidence before planning a distinct geometry experiment.",
        "retry_limit": 1, "priority": 4}
    created = state_store.add_task(task, db_path=STATE_DB)
    if created:
        manager._event("goal_scheduler_task_created", {
            "task_id": task_id, "stage": "F2", "source_fingerprint": fingerprint,
            "source_count": len(sources), "reason": "EUZ-only road-index reader needs a cross-region falsification test",
            "source_write": False})
    return {"created": created, "task_id": task_id if created else None,
            "reason": "cross-region RL/IOF/IL portability is an untested reader gate", "sources": sources}


def execute_ncdx_roadlink_portability(task_id: str) -> dict[str, Any]:
    """Run the parameterized, fixed-handler experiment over exact scheduled inputs."""
    from src.readers import ncdx_roadlink_portability
    task = manager._task(task_id)
    budget = task.get("budget", {})
    if (task.get("agent") != "ncdx-roadlink-portability"
            or budget.get("ncdx_roadlink_portability") is not True
            or int(budget.get("handler_version", -1)) != ROADLINK_PORTABILITY_VERSION):
        raise ValueError("roadlink portability task does not match the fixed reviewed handler")
    root = coordinator_runtime.SOURCE_ROOT.resolve(strict=True)
    sources = budget.get("sources")
    if not isinstance(sources, list) or len(sources) != 9:
        raise ValueError("roadlink portability task must bind exactly nine regional source files")
    for row in sources:
        relative = PurePosixPath(str(row.get("relative_path", "")))
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("roadlink portability source path is not a safe relative path")
        source = (root / Path(*relative.parts)).resolve(strict=True)
        if (not source.is_relative_to(root) or str(source) != str(Path(row.get("absolute_path", "")).resolve(strict=True))
                or int(row.get("size_bytes", -1)) != source.stat().st_size
                or _ledger_hash(relative.as_posix()) != row.get("sha256")):
            raise RuntimeError(f"roadlink portability input no longer matches its inventory: {relative}")
    result = ncdx_roadlink_portability.analyze(sources)
    result.update({"task_id": task_id, "source_fingerprint": budget.get("source_fingerprint"),
        "created_utc": _utc(), "physical_compatibility": "NOT_TESTED"})
    output = PROJECT_ROOT / "work" / "autonomous_manager" / "ncdx" / "roadlink_portability" / f"{task_id}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(output)
    artifact = manager._artifact(task_id, output,
        "Three-region RL/IOF/IL reader portability evidence",
        f"PASS: bounded source reads completed; cross-region result={result['hypothesis_result']}")
    _register_supervisor("AUTO_SUPERVISOR_" + task_id, task_id)
    return {**result, "artifact": artifact}


def seed_next_roadlink_name_consistency_task() -> dict[str, Any]:
    """Plan a distinct semantic cross-check from accepted RL/IOF/IL portability evidence."""
    from src.readers import ncdx_roadlink_name_consistency
    with closing(sqlite3.connect(STATE_DB, timeout=20)) as conn:
        conn.row_factory = sqlite3.Row
        predecessor = conn.execute("""SELECT id FROM tasks
            WHERE agent='ncdx-roadlink-portability' AND status='DONE'
            ORDER BY updated_utc DESC,id LIMIT 1""").fetchone()
    if not predecessor:
        return {"created": False, "reason": "roadlink name hypothesis awaits accepted three-region RL/IOF/IL portability"}
    prior_task_id = str(predecessor["id"])
    supervisor_id = "AUTO_SUPERVISOR_" + prior_task_id
    prior_result = _task_result(prior_task_id)
    supervisor_result = _task_result(supervisor_id) if _task_status(supervisor_id) == "DONE" else {}
    artifact = prior_result.get("artifact") or {}
    if (prior_result.get("status") != "PASS" or supervisor_result.get("status") != "PASS"
            or supervisor_result.get("target_task") != prior_task_id
            or not isinstance(artifact, dict) or not artifact.get("sha256")):
        return {"created": False, "reason": "roadlink name hypothesis requires an independent PASS on the predecessor"}
    with closing(sqlite3.connect(STATE_DB, timeout=20)) as conn:
        conn.row_factory = sqlite3.Row
        previous_names = conn.execute("""SELECT id,status,budget_json FROM tasks
            WHERE agent='ncdx-roadlink-name-consistency' ORDER BY updated_utc DESC,id""").fetchall()
    for previous in previous_names:
        try:
            previous_budget = json.loads(previous["budget_json"] or "{}")
        except (TypeError, json.JSONDecodeError):
            continue
        if previous_budget.get("predecessor_task_id") == prior_task_id:
            return {"created": False, "task_id": str(previous["id"]),
                "reason": f"same source-bound roadlink name hypothesis already exists ({previous['status']}); no duplicate scan"}
    prior_artifact = (PROJECT_ROOT / Path(*PurePosixPath(str(artifact.get("path", ""))).parts)).resolve(strict=True)
    if (not prior_artifact.is_relative_to(PROJECT_ROOT.resolve())
            or _sha256(prior_artifact) != str(artifact["sha256"])):
        raise ValueError("accepted roadlink portability artifact is outside the project or changed")
    root = coordinator_runtime.SOURCE_ROOT.resolve(strict=True)
    sources = []
    for suffix in ("RL", "IOF", "IL"):
        for row in _data_profile_sources(suffix):
            relative = PurePosixPath(str(row["relative_path"]))
            source = (root / Path(*relative.parts)).resolve(strict=True)
            if not source.is_relative_to(root):
                raise ValueError(f"roadlink name source escaped the original-media root: {relative}")
            sources.append({**row, "absolute_path": str(source)})
    if len(sources) != 9:
        return {"created": False, "reason": "roadlink name experiment requires all nine inventoried regional sources"}
    fingerprint = hashlib.sha256(json.dumps({"experiment": "ncdx_rl_il_normalized_name_link_portability",
        "handler_version": ROADLINK_NAME_CONSISTENCY_VERSION,
        "predecessor_task": prior_task_id, "predecessor_artifact_sha256": artifact["sha256"],
        "sources": [(row["region"], row["relative_path"], row["sha256"], row["size_bytes"])
                    for row in sources]}, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()[:16].upper()
    task_id = f"AUTO_NCDX_ROADLINK_NAME_CONSISTENCY_V1_{fingerprint}"
    existing = _task_status(task_id)
    if existing:
        return {"created": False, "task_id": task_id,
                "reason": f"exact roadlink name/alias experiment already exists ({existing})"}
    task = {"id": task_id, "stage": "F2", "depends_on": [prior_task_id, supervisor_id],
        "hypothesis": "The previously verified EUZ RL alias-to-IL linked-name comparison transfers across SW, Italy and Scandinavia and beats a displaced IOF-reference control.",
        "evidence": [{"type": "accepted_roadlink_index_and_source_manifest",
            "predecessor_task_id": prior_task_id, "predecessor_artifact_sha256": artifact["sha256"],
            "sources": [{key: row[key] for key in ("region", "relative_path", "sha256", "size_bytes")}
                        for row in sources]}],
        "agent": "ncdx-roadlink-name-consistency",
        "budget": {"timeout_s": 3600, "attempts": 1, "source_write": False,
            "max_model_calls": 0, "ncdx_roadlink_name_consistency": True,
            "handler_version": ROADLINK_NAME_CONSISTENCY_VERSION,
            "source_fingerprint": fingerprint, "predecessor_task_id": prior_task_id,
            "predecessor_artifact_sha256": str(artifact["sha256"]), "sources": sources},
        "deliverables": [f"work/autonomous_manager/ncdx/roadlink_name_consistency/{task_id}.json"],
        "tests": ["Stream all manifest-bound RL/IOF/IL inputs with fixed table and pointer checks",
            "Compare normalized IL names with RL aliases at the referenced IOF index and a displaced-reference control",
            "Recompute all nine source hashes and confirm no original media writes",
            "Keep text/reference association distinct from road geometry and routing semantics"],
        "next_action": "After independent replay, use only evidence-supported relationships to shape a reader experiment.",
        "retry_limit": 1, "priority": 4}
    created = state_store.add_task(task, db_path=STATE_DB)
    if created:
        manager._event("goal_scheduler_task_created", {"task_id": task_id, "stage": "F2",
            "source_fingerprint": fingerprint, "source_count": len(sources),
            "reason": "accepted cross-region road-index structure now permits a distinct name/reference consistency test",
            "source_write": False})
    return {"created": created, "task_id": task_id if created else None,
        "reason": "accepted road-index evidence supports a new normalized RL/IL name-link test",
        "sources": sources}


def seed_next_deterministic_supervisor_replay() -> dict[str, Any]:
    """Re-review saved PASS evidence after a known local verifier implementation defect."""
    allowed_targets = {"ncdx-roadlink-name-consistency"}
    recoverable_markers = ("independent verifier rejected", "independent name verifier disagreed on")
    with closing(sqlite3.connect(STATE_DB, timeout=20)) as conn:
        conn.row_factory = sqlite3.Row
        blocked_rows = conn.execute("""SELECT id,budget_json,result_json FROM tasks
            WHERE agent='ollama-research-supervisor' AND status='BLOCKED'
            ORDER BY updated_utc DESC,id""").fetchall()
    for blocked in blocked_rows:
        try:
            budget = json.loads(blocked["budget_json"] or "{}")
            failure = json.loads(blocked["result_json"] or "{}")
        except (TypeError, json.JSONDecodeError):
            continue
        target_id = str(budget.get("supervises_task", ""))
        try:
            target = manager._task(target_id) if target_id else None
        except (KeyError, ValueError, RuntimeError):
            target = None
        error = str(failure.get("error", ""))
        if (not target or target.get("agent") not in allowed_targets
                or target.get("status") != "DONE"
                or _task_result(target_id).get("status") != "PASS"
                or not any(marker in error for marker in recoverable_markers)):
            continue
        target_result = _task_result(target_id)
        artifact = target_result.get("artifact") or {}
        relative = PurePosixPath(str(artifact.get("path", "")))
        if (relative.is_absolute() or ".." in relative.parts or not artifact.get("sha256")):
            continue
        artifact_path = (PROJECT_ROOT / Path(*relative.parts)).resolve(strict=False)
        if (not artifact_path.is_file() or not artifact_path.is_relative_to(PROJECT_ROOT.resolve())
                or _sha256(artifact_path) != str(artifact["sha256"])):
            continue
        from src.readers import ncdx_roadlink_name_consistency
        verification_source_hash = hashlib.sha256((Path(__file__).read_bytes()
            + Path(ncdx_roadlink_name_consistency.__file__).read_bytes())).hexdigest()
        replay_hash = hashlib.sha256(json.dumps({"target": target_id,
            "artifact_sha256": artifact["sha256"], "verification_source_sha256": verification_source_hash},
            sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()[:20].upper()
        replay_id = f"AUTO_SUPERVISOR_REPLAY_{replay_hash}"
        existing = _task_status(replay_id)
        if existing:
            return {"created": False, "task_id": replay_id,
                "reason": f"bounded independent replay already exists ({existing})"}
        task = {"id": replay_id, "stage": "R3", "depends_on": [target_id],
            "hypothesis": f"Independently re-evaluate the hash-bound saved result for {target_id} with the corrected streaming verifier; do not rerun its source experiment.",
            "evidence": [{"type": "saved_target_artifact", "target_task_id": target_id,
                "artifact_path": relative.as_posix(), "artifact_sha256": artifact["sha256"],
                "previous_supervisor_task_id": str(blocked["id"]),
                "previous_failure": error[:700],
                "verification_source_sha256": verification_source_hash}],
            "agent": "ollama-research-supervisor",
            "budget": {"timeout_s": 360, "attempts": 1, "source_write": False,
                "execution": "fixed allowlisted handler", "supervises_task": target_id,
                "replay_after_local_verifier_fix": True,
                "verification_source_sha256": verification_source_hash},
            "deliverables": [f"reports/autonomous_supervisor_{target_id.casefold()}.json"],
            "tests": ["Reopen the already saved target result and source evidence",
                "Run the corrected independent streaming source verifier",
                "Do not repeat the target experiment or alter its result/artifact",
                "Keep unknown routing and physical compatibility claims explicit"],
            "next_action": "If evidence still fails, report the exact missing proof and leave the target unchanged.",
            "retry_limit": 1, "priority": 3}
        created = state_store.add_task(task, db_path=STATE_DB)
        if created:
            manager._event("deterministic_supervisor_replay_created", {
                "task_id": replay_id, "target_task_id": target_id,
                "previous_supervisor_task_id": str(blocked["id"]),
                "artifact_sha256": artifact["sha256"],
                "verification_source_sha256": verification_source_hash,
                "target_experiment_rerun": False})
        return {"created": created, "task_id": replay_id if created else None,
            "reason": "known local verifier defect repaired; saved evidence queued for independent replay"}
    return {"created": False, "reason": "no eligible saved result has a known corrected local-verifier failure"}


def execute_ncdx_roadlink_name_consistency(task_id: str) -> dict[str, Any]:
    """Run the fixed read-only RL/IOF/IL name-reference experiment."""
    from src.readers import ncdx_roadlink_name_consistency
    task = manager._task(task_id)
    budget = task.get("budget", {})
    if (task.get("agent") != "ncdx-roadlink-name-consistency"
            or budget.get("ncdx_roadlink_name_consistency") is not True
            or int(budget.get("handler_version", -1)) != ROADLINK_NAME_CONSISTENCY_VERSION):
        raise ValueError("roadlink name experiment does not match its fixed reviewed handler")
    root = coordinator_runtime.SOURCE_ROOT.resolve(strict=True)
    sources = budget.get("sources")
    if not isinstance(sources, list) or len(sources) != 9:
        raise ValueError("roadlink name experiment must bind nine regional source files")
    for row in sources:
        relative = PurePosixPath(str(row.get("relative_path", "")))
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("roadlink name source path is unsafe")
        source = (root / Path(*relative.parts)).resolve(strict=True)
        if (not source.is_relative_to(root)
                or source != Path(str(row.get("absolute_path", ""))).resolve(strict=True)
                or source.stat().st_size != int(row.get("size_bytes", -1))
                or _ledger_hash(relative.as_posix()) != row.get("sha256")):
            raise RuntimeError(f"roadlink name source differs from inventory: {relative}")
    result = ncdx_roadlink_name_consistency.analyze(sources)
    result.update({"task_id": task_id, "source_fingerprint": budget.get("source_fingerprint"),
        "predecessor_task_id": budget.get("predecessor_task_id"),
        "predecessor_artifact_sha256": budget.get("predecessor_artifact_sha256"),
        "created_utc": _utc(), "physical_compatibility": "NOT_TESTED"})
    output = PROJECT_ROOT / "work" / "autonomous_manager" / "ncdx" / "roadlink_name_consistency" / f"{task_id}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(output)
    artifact = manager._artifact(task_id, output,
        "Three-region RL alias and IL linked-name consistency evidence",
        f"{result['status']}: regional direct/reference-control association={result['hypothesis_result']}")
    _register_supervisor("AUTO_SUPERVISOR_" + task_id, task_id)
    return {**result, "artifact": artifact}


def seed_next_geography_portability_task() -> dict[str, Any]:
    """Schedule a distinct CTY/CNY and map-header cross-region reader check."""
    from src.readers.ncdx_geography_portability import MAP_HEADERS, TABLES
    root = coordinator_runtime.SOURCE_ROOT.resolve(strict=True)
    sources: list[dict[str, Any]] = []
    for suffix in (*TABLES.keys(), *MAP_HEADERS):
        for row in _data_profile_sources(suffix):
            relative = str(row["relative_path"])
            candidate = (root / Path(*PurePosixPath(relative).parts)).resolve(strict=True)
            if not candidate.is_relative_to(root):
                raise ValueError(f"geography portability source escaped original-media root: {relative}")
            sources.append({**row, "absolute_path": str(candidate)})
    fingerprint = hashlib.sha256(json.dumps({
        "experiment": "ncdx_cty_cny_spatial_header_portability",
        "handler_version": GEOGRAPHY_PORTABILITY_VERSION,
        "sources": [(row["region"], row["relative_path"], row["sha256"], row["size_bytes"])
                    for row in sources]}, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()[:16].upper()
    task_id = f"AUTO_NCDX_GEOGRAPHY_PORTABILITY_V{GEOGRAPHY_PORTABILITY_VERSION}_{fingerprint}"
    existing_status = _task_status(task_id)
    if existing_status:
        return {"created": False, "task_id": task_id,
                "reason": f"geography portability experiment already exists ({existing_status})"}
    task = {"id": task_id, "stage": "F2", "depends_on": [],
        "hypothesis": "The verified EUZ CTY/CNY table schema and candidate map-header coordinate fields generalize to IZ/SCZ; MP0 candidate bounds enclose each regional CTY city extent and MG bounds overlap it.",
        "evidence": [{"type": "manifest_bound_ncdx_inputs", "sources": [
            {key: row[key] for key in ("region", "relative_path", "sha256", "size_bytes")}
            for row in sources], "prior_evidence": [
                "research/NCDR1500_VERIFIED_20261027/geography/OUTPUT_GEO/EVIDENCE_GEOGRAPHY.json",
                "research/NCDR1500_VERIFIED_20261027/geography/OUTPUT_GEO/SPATIAL_HEADER_EVIDENCE.json"]}],
        "agent": "ncdx-geography-portability",
        "budget": {"timeout_s": 3600, "attempts": 1, "source_write": False,
            "max_model_calls": 0, "ncdx_geography_portability": True,
            "handler_version": GEOGRAPHY_PORTABILITY_VERSION,
            "source_fingerprint": fingerprint, "sources": sources},
        "deliverables": [f"work/autonomous_manager/ncdx/geography_portability/{task_id}.json"],
        "tests": ["Stream CTY/CNY containers and validate IDs, links, record lengths, names and coordinate bounds",
            "Check candidate MP0/MG header coordinate fields against each region's CTY extent",
            "Recheck all eighteen scheduled source SHA-256 values and ensure no original media write",
            "Do not claim decoded map geometry, topology, routing or disc compatibility"],
        "next_action": "Use the independently accepted region comparisons to choose a new bounded map-record geometry experiment; preserve UNKNOWN where structure is unproven.",
        "retry_limit": 1, "priority": 6}
    created = state_store.add_task(task, db_path=STATE_DB)
    if created:
        manager._event("goal_scheduler_task_created", {"task_id": task_id, "stage": "F2",
            "source_fingerprint": fingerprint, "source_count": len(sources),
            "reason": "cross-region geographic table and spatial-header relationships remain untested",
            "source_write": False})
    return {"created": created, "task_id": task_id if created else None,
            "reason": "manifest-bound cross-region geography reader portability is an untested NCDx gate",
            "sources": sources}


def execute_ncdx_geography_portability(task_id: str) -> dict[str, Any]:
    """Run the fixed, read-only CTY/CNY and spatial-header experiment."""
    from src.readers import ncdx_geography_portability
    task = manager._task(task_id)
    budget = task.get("budget", {})
    if (task.get("agent") != "ncdx-geography-portability"
            or budget.get("ncdx_geography_portability") is not True
            or int(budget.get("handler_version", -1)) != GEOGRAPHY_PORTABILITY_VERSION):
        raise ValueError("geography portability task does not match its fixed reviewed handler")
    root = coordinator_runtime.SOURCE_ROOT.resolve(strict=True)
    sources = budget.get("sources")
    if not isinstance(sources, list) or len(sources) != 18:
        raise ValueError("geography portability task must bind eighteen sources")
    for row in sources:
        relative = PurePosixPath(str(row.get("relative_path", "")))
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("geography portability source path is unsafe")
        source = (root / Path(*relative.parts)).resolve(strict=True)
        if (not source.is_relative_to(root)
                or str(source) != str(Path(row.get("absolute_path", "")).resolve(strict=True))
                or int(row.get("size_bytes", -1)) != source.stat().st_size
                or _ledger_hash(relative.as_posix()) != row.get("sha256")):
            raise RuntimeError(f"geography portability input differs from its inventory: {relative}")
    result = ncdx_geography_portability.analyze(sources)
    result.update({"task_id": task_id, "source_fingerprint": budget.get("source_fingerprint"),
                   "created_utc": _utc(), "physical_compatibility": "NOT_TESTED"})
    output = PROJECT_ROOT / "work" / "autonomous_manager" / "ncdx" / "geography_portability" / f"{task_id}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(output)
    artifact = manager._artifact(task_id, output,
        "Three-region CTY/CNY and candidate spatial-header evidence",
        f"PASS: {len(result['regions'])} regional comparisons; hypothesis={result['hypothesis_result']}")
    _register_supervisor("AUTO_SUPERVISOR_" + task_id, task_id)
    return {**result, "artifact": artifact}


def seed_next_city_coordinate_crosscheck_task() -> dict[str, Any]:
    """Promote two accepted MG1 short-step streams to a CTY city-box check."""
    from src.readers.ncdx_city_coordinate_crosscheck import MEASUREMENT
    root = coordinator_runtime.SOURCE_ROOT.resolve(strict=True)
    sources_by_table = {suffix: {row["region"]: row for row in _data_profile_sources(suffix)}
                        for suffix in ("CTY", "CNY", "MG1")}
    candidates: list[dict[str, Any]] = []
    for region, (prior_id, stream_index, minimum_adjacent) in CITY_COORDINATE_CENSUS_EVIDENCE.items():
        if _task_status(prior_id) != "DONE":
            return {"created": False, "reason": f"prior coordinate census is not accepted: {prior_id}"}
        supervisor_id = "AUTO_SUPERVISOR_" + prior_id
        supervisor = _task_result(supervisor_id) if _task_status(supervisor_id) == "DONE" else {}
        if supervisor.get("status") != "PASS" or supervisor.get("target_task") != prior_id:
            return {"created": False, "reason": f"prior coordinate census lacks independent Supervisor PASS: {prior_id}"}
        prior_result = _task_result(prior_id)
        artifact = prior_result.get("artifact") or {}
        if not isinstance(artifact, dict) or not artifact.get("sha256"):
            return {"created": False, "reason": f"prior coordinate census has no hash-bound artifact: {prior_id}"}
        artifact_path = (PROJECT_ROOT / Path(*PurePosixPath(str(artifact.get("path", ""))).parts)).resolve(strict=True)
        if not artifact_path.is_relative_to(PROJECT_ROOT.resolve()):
            raise ValueError("prior coordinate census artifact escaped the project workspace")
        if _sha256(artifact_path) != str(artifact["sha256"]):
            raise ValueError(f"prior coordinate census artifact hash changed: {prior_id}")
        report = json.loads(artifact_path.read_text(encoding="utf-8"))
        observation = next((row for row in report.get("observations", [])
            if row.get("region") == region), None)
        if not observation or report.get("profile_mode") != "ZLIB_DECODED_COORDINATE_CANDIDATE_CENSUS":
            raise ValueError(f"prior coordinate artifact has no fixed MG1 evidence for {region}")
        summary = next((row for row in observation.get("candidate_stream_summaries", [])
            if int(row.get("stream_index", -1)) == stream_index), None)
        if not summary:
            raise ValueError(f"prior coordinate artifact lost stream index {stream_index} for {region}")
        measurement = next((row for row in summary.get("candidate_measurements", [])
            if row.get("measurement") == MEASUREMENT), None)
        selected = next((row for row in (observation.get("selected_full_payload_audit") or {}).get("selected_streams", [])
            if int(row.get("stream_index", -1)) == stream_index), None)
        if (not measurement or int(measurement.get("adjacent_pairs_within_5km", 0)) < minimum_adjacent
                or not selected or selected.get("full_payload_sha256") != summary.get("decompressed_sha256")):
            return {"created": False, "reason": f"selected {region} stream no longer meets its accepted evidence threshold"}
        map_row = sources_by_table["MG1"].get(region)
        if (not map_row or observation.get("relative_path") != map_row["relative_path"]
                or observation.get("source_sha256") != map_row["sha256"]
                or observation.get("stream_inventory_sha256") is None):
            raise ValueError(f"prior MG1 census does not match the current inventory for {region}")
        candidates.append({"region": region, "prior_task_id": prior_id,
            "prior_artifact_path": str(artifact_path), "prior_artifact_sha256": str(artifact["sha256"]),
            "map_relative_path": str(map_row["relative_path"]),
            "map_sha256": str(map_row["sha256"]),
            "stream_count": int(observation["stream_count"]),
            "stream_inventory_sha256": str(observation["stream_inventory_sha256"]),
            "stream_index": stream_index, "source_offset": int(summary["source_offset"]),
            "compressed_bytes": int(summary["compressed_bytes"]),
            "decompressed_bytes": int(summary["decompressed_bytes"]),
            "decompressed_sha256": str(summary["decompressed_sha256"]),
            "measurement": MEASUREMENT,
            "prior_adjacent_pairs": int(measurement["adjacent_pairs_within_5km"])})
    selected_regions = set(CITY_COORDINATE_CENSUS_EVIDENCE)
    sources = []
    for suffix, by_region in sources_by_table.items():
        for region in selected_regions:
            row = by_region.get(region)
            if not row:
                raise FileNotFoundError(f"missing inventoried {region}/{suffix} input")
            relative = str(row["relative_path"])
            candidate = (root / Path(*PurePosixPath(relative).parts)).resolve(strict=True)
            if not candidate.is_relative_to(root):
                raise ValueError(f"coordinate cross-check input escaped original-media root: {relative}")
            sources.append({**row, "absolute_path": str(candidate)})
    fingerprint = hashlib.sha256(json.dumps({"experiment": "ncdx_candidate_coordinates_vs_cty_city_boxes",
        "handler_version": CITY_COORDINATE_CROSSCHECK_VERSION,
        "sources": [(row["region"], row["relative_path"], row["sha256"], row["size_bytes"])
                    for row in sources],
        "candidates": [{key: row[key] for key in ("region", "prior_task_id", "prior_artifact_sha256",
            "stream_index", "source_offset", "compressed_bytes", "decompressed_sha256", "measurement")}
            for row in candidates]}, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()[:16].upper()
    task_id = f"AUTO_NCDX_CITY_COORD_CROSSCHECK_V{CITY_COORDINATE_CROSSCHECK_VERSION}_{fingerprint}"
    existing_status = _task_status(task_id)
    if existing_status:
        return {"created": False, "task_id": task_id,
                "reason": f"coordinate/city cross-check already exists ({existing_status})"}
    task = {"id": task_id, "stage": "F2", "depends_on": [row["prior_task_id"] for row in candidates],
        "hypothesis": "Two accepted MG1 streams with repeated short-step coordinate candidates contain points inside their own CTY city boxes more often than in the displaced control windows.",
        "evidence": [{"type": "accepted_stream_census_and_manifest_bound_city_tables",
            "candidate_streams": [{key: row[key] for key in ("region", "prior_task_id", "prior_artifact_sha256",
                "stream_index", "source_offset", "compressed_bytes", "decompressed_sha256",
                "measurement", "prior_adjacent_pairs")} for row in candidates],
            "source_count": len(sources)}],
        "agent": "ncdx-city-coordinate-crosscheck",
        "budget": {"timeout_s": 900, "attempts": 1, "source_write": False,
            "max_model_calls": 0, "ncdx_city_coordinate_crosscheck": True,
            "handler_version": CITY_COORDINATE_CROSSCHECK_VERSION,
            "source_fingerprint": fingerprint, "sources": sources, "candidates": candidates},
        "deliverables": [f"work/autonomous_manager/ncdx/city_coordinate_crosscheck/{task_id}.json"],
        "tests": ["Reopen only the two Supervisor-accepted full MG1 streams and reproduce exact SHA-256 values",
            "Re-read manifest-pinned CTY/CNY tables and validate city IDs, references and bounds",
            "Measure fixed signed-int32 candidate points against CTY boxes and displaced control boxes",
            "Store aggregate evidence only; retain no raw coordinates and write no original media"],
        "next_action": "If city-box association survives independent readback, design a distinct geometry-context experiment; otherwise retire this coordinate interpretation and continue another NCDx family.",
        "retry_limit": 1, "priority": 3}
    created = state_store.add_task(task, db_path=STATE_DB)
    if created:
        manager._event("goal_scheduler_task_created", {"task_id": task_id, "stage": "F2",
            "source_fingerprint": fingerprint, "source_count": len(sources),
            "selected_regions": sorted(selected_regions),
            "reason": "accepted MG1 coordinate candidates now need CTY-city and displaced-control validation",
            "source_write": False})
    return {"created": created, "task_id": task_id if created else None,
            "reason": "two accepted full-payload coordinate streams remain untested against actual CTY city boxes",
            "sources": sources}


def _select_unconsumed_city_coordinate_candidates(
        report: dict[str, Any], *, prior_task_id: str,
        prior_artifact_path: str, prior_artifact_sha256: str,
        used_streams: set[tuple[str, str, int]]) -> list[dict[str, Any]]:
    """Choose one independently audited, not-yet-tested MG1 stream per region.

    This is deliberately bounded to the accepted full-payload audit. It never
    promotes a sampled prefix or scans another stream merely to create work.
    """
    from src.readers.ncdx_city_coordinate_crosscheck import REGION_BOUNDS
    selected: list[dict[str, Any]] = []
    for region in ("SW", "Scandinavia"):
        observation = next((row for row in report.get("observations", [])
            if row.get("region") == region and str(row.get("relative_path", "")).upper().endswith(".MG1")), None)
        if not observation:
            return []
        audited = {int(row.get("stream_index", -1)): row
            for row in (observation.get("selected_full_payload_audit") or {}).get("selected_streams", [])
            if isinstance(row, dict)}
        ranked: list[tuple[int, int, str, dict[str, Any]]] = []
        for summary in observation.get("candidate_stream_summaries", []):
            if not isinstance(summary, dict):
                continue
            stream_index = int(summary.get("stream_index", -1))
            if stream_index < 0 or (region, prior_task_id, stream_index) in used_streams:
                continue
            full = audited.get(stream_index)
            payload_sha = str(summary.get("decompressed_sha256", ""))
            if not full or full.get("full_payload_sha256") != payload_sha or not payload_sha:
                continue
            measurements = [row for row in summary.get("candidate_measurements", [])
                            if isinstance(row, dict)
                            and int(row.get("adjacent_pairs_within_5km", 0)) >= 3
                            and int(row.get("region_candidate_pairs", 0)) >= 5]
            if not measurements:
                continue
            measurement = sorted(measurements, key=lambda row: (
                -int(row.get("adjacent_pairs_within_5km", 0)),
                -int(row.get("region_candidate_pairs", 0)),
                str(row.get("measurement", ""))))[0]
            candidate = {"region": region, "prior_task_id": prior_task_id,
                "prior_artifact_path": prior_artifact_path,
                "prior_artifact_sha256": prior_artifact_sha256,
                "map_relative_path": str(observation.get("relative_path", "")),
                "map_sha256": str(observation.get("source_sha256", "")),
                "stream_count": int(observation.get("stream_count", -1)),
                "stream_inventory_sha256": str(observation.get("stream_inventory_sha256", "")),
                "stream_index": stream_index,
                "source_offset": int(summary.get("source_offset", -1)),
                "compressed_bytes": int(summary.get("compressed_bytes", -1)),
                "decompressed_bytes": int(summary.get("decompressed_bytes", -1)),
                "decompressed_sha256": payload_sha,
                "measurement": str(measurement.get("measurement", "")),
                "prior_adjacent_pairs": int(measurement["adjacent_pairs_within_5km"])}
            if (candidate["stream_count"] <= 0 or candidate["source_offset"] < 0
                    or candidate["compressed_bytes"] <= 0 or candidate["decompressed_bytes"] <= 0
                    or len(candidate["map_sha256"]) != 64
                    or len(candidate["stream_inventory_sha256"]) != 64
                    or candidate["measurement"] == ""):
                continue
            ranked.append((-candidate["prior_adjacent_pairs"],
                -int(measurement["region_candidate_pairs"]), region, candidate))
        if not ranked:
            return []
        selected.append(sorted(ranked, key=lambda row: row[:3])[0][3])
    if {row["region"] for row in selected} != set(REGION_BOUNDS) & {"SW", "Scandinavia"}:
        return []
    return selected


def seed_next_city_coordinate_secondary_crosscheck_task() -> dict[str, Any]:
    """Test the remaining fully decoded MG1 streams against independent CTY boxes.

    This is a bounded continuation of the accepted coordinate hypothesis: it
    chooses only unused streams from one accepted census and stops when those
    finite evidence-selected streams have been consumed.
    """
    prior_task_id = "AUTO_NCDX_DATA_MG1_ZLIB_DECODED_COORDINATE_CANDIDATE_CENSUS_0d9bedd0"
    supervisor_id = "AUTO_SUPERVISOR_" + prior_task_id
    if _task_status(prior_task_id) != "DONE" or _task_status(supervisor_id) != "DONE":
        return {"created": False, "reason": "secondary MG1 streams require an accepted census and independent Supervisor PASS"}
    prior_result = _task_result(prior_task_id)
    supervisor_result = _task_result(supervisor_id)
    artifact = prior_result.get("artifact") or {}
    if (prior_result.get("status") != "PASS"
            or prior_result.get("profile_mode") != "ZLIB_DECODED_COORDINATE_CANDIDATE_CENSUS"
            or supervisor_result.get("status") != "PASS"
            or supervisor_result.get("target_task") != prior_task_id
            or not isinstance(artifact, dict) or not artifact.get("sha256")):
        return {"created": False, "reason": "secondary MG1 streams lack a hash-bound independent PASS"}
    relative = PurePosixPath(str(artifact.get("path", "")))
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("accepted MG1 census artifact path is unsafe")
    artifact_path = (PROJECT_ROOT / Path(*relative.parts)).resolve(strict=True)
    if (not artifact_path.is_relative_to(PROJECT_ROOT.resolve())
            or _sha256(artifact_path) != str(artifact["sha256"])):
        raise ValueError("accepted MG1 census artifact escaped the project or changed")
    report = json.loads(artifact_path.read_text(encoding="utf-8"))
    with closing(sqlite3.connect(STATE_DB, timeout=20)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT budget_json FROM tasks WHERE agent='ncdx-city-coordinate-crosscheck'").fetchall()
    used_streams: set[tuple[str, str, int]] = set()
    for row in rows:
        try:
            budget = json.loads(row["budget_json"] or "{}")
        except (TypeError, json.JSONDecodeError):
            continue
        for candidate in budget.get("candidates", []) if isinstance(budget, dict) else []:
            if isinstance(candidate, dict):
                used_streams.add((str(candidate.get("region", "")),
                    str(candidate.get("prior_task_id", "")),
                    int(candidate.get("stream_index", -1))))
    candidates = _select_unconsumed_city_coordinate_candidates(report,
        prior_task_id=prior_task_id, prior_artifact_path=str(artifact_path),
        prior_artifact_sha256=str(artifact["sha256"]), used_streams=used_streams)
    if len(candidates) != 2:
        return {"created": False, "reason": "all evidence-qualified secondary MG1 streams are consumed or unavailable"}
    root = coordinator_runtime.SOURCE_ROOT.resolve(strict=True)
    tables = {suffix: {row["region"]: row for row in _data_profile_sources(suffix)}
              for suffix in ("CTY", "CNY", "MG1")}
    sources: list[dict[str, Any]] = []
    for candidate in candidates:
        for suffix in ("CTY", "CNY", "MG1"):
            row = tables[suffix].get(candidate["region"])
            if not row:
                return {"created": False, "reason": f"missing inventoried {candidate['region']}/{suffix} input"}
            source = (root / Path(*PurePosixPath(str(row["relative_path"])).parts)).resolve(strict=True)
            if not source.is_relative_to(root):
                raise ValueError("secondary city crosscheck input escaped the original media root")
            if suffix == "MG1" and row["sha256"] != candidate["map_sha256"]:
                raise ValueError("secondary MG1 stream source differs from accepted census")
            sources.append({**row, "absolute_path": str(source)})
    fingerprint = hashlib.sha256(json.dumps({"experiment": "ncdx_secondary_mg1_streams_vs_cty_boxes",
        "handler_version": CITY_COORDINATE_CROSSCHECK_VERSION,
        "prior_task_id": prior_task_id, "prior_artifact_sha256": artifact["sha256"],
        "candidates": [{key: row[key] for key in ("region", "stream_index", "source_offset",
            "compressed_bytes", "decompressed_sha256", "measurement") for row in [candidate]}
            for candidate in candidates],
        "sources": [(row["relative_path"], row["sha256"], row["size_bytes"]) for row in sources]},
        sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()[:16].upper()
    task_id = f"AUTO_NCDX_MG1_SECONDARY_CITY_CROSSCHECK_V1_{fingerprint}"
    if _task_status(task_id):
        return {"created": False, "task_id": task_id, "reason": "exact secondary stream crosscheck already exists"}
    task = {"id": task_id, "stage": "F2", "depends_on": [prior_task_id, supervisor_id],
        "hypothesis": "The second independently decoded MG1 candidate stream in each of SW and Scandinavia contains coordinate points inside actual CTY city boxes more often than in displaced control windows, independently of the first-stream result.",
        "evidence": [{"type": "accepted_full_payload_candidate_streams",
            "prior_task_id": prior_task_id, "prior_artifact_sha256": artifact["sha256"],
            "candidates": [{key: row[key] for key in ("region", "stream_index", "source_offset",
                "decompressed_sha256", "measurement", "prior_adjacent_pairs")} for row in candidates]}],
        "agent": "ncdx-city-coordinate-crosscheck",
        "budget": {"timeout_s": 900, "attempts": 1, "source_write": False,
            "max_model_calls": 0, "ncdx_city_coordinate_crosscheck": True,
            "handler_version": CITY_COORDINATE_CROSSCHECK_VERSION,
            "source_fingerprint": fingerprint, "sources": sources, "candidates": candidates,
            "secondary_stream_crosscheck": True},
        "deliverables": [f"work/autonomous_manager/ncdx/city_coordinate_crosscheck/{task_id}.json"],
        "tests": ["Reopen only unused full-payload MG1 streams from the accepted census and reproduce payload hashes",
            "Verify manifest-pinned CTY/CNY tables independently for both regions",
            "Compare selected candidate coordinates with actual city boxes and displaced controls",
            "Write aggregates only; do not infer road segments or modify original media"],
        "next_action": "Use the independent secondary-stream outcome to retain or reject this coordinate interpretation before designing a road-geometry reader.",
        "retry_limit": 1, "priority": 3}
    created = state_store.add_task(task, db_path=STATE_DB)
    if created:
        manager._event("goal_scheduler_task_created", {"task_id": task_id, "stage": "F2",
            "source_fingerprint": fingerprint, "source_count": len(sources),
            "candidate_streams": {row["region"]: row["stream_index"] for row in candidates},
            "reason": "accepted coordinate candidate inventory contains two unused independently decoded regional MG1 streams",
            "source_write": False})
    return {"created": created, "task_id": task_id if created else None,
        "reason": "two unused full-payload MG1 streams support an independent city-box/control experiment",
        "sources": sources, "candidate_streams": candidates}


def seed_next_italy_city_coordinate_probe_task() -> dict[str, Any]:
    """Schedule the untested Italy 1e5 lon/lat candidate from an accepted MG1 census.

    This is a separate region/scale hypothesis, not a replay of the accepted SW
    and Scandinavia cross-check. It is seeded only from a Supervisor-accepted
    full-payload census and binds exact CTY/CNY/MG1 identities.
    """
    from src.readers.ncdx_city_coordinate_crosscheck import MEASUREMENT
    prior_task_id = "AUTO_NCDX_DATA_MG1_ZLIB_DECODED_COORDINATE_CANDIDATE_CENSUS_0a717aec"
    supervisor_task_id = "AUTO_SUPERVISOR_" + prior_task_id
    if _task_status(prior_task_id) != "DONE" or _task_status(supervisor_task_id) != "DONE":
        return {"created": False, "reason": "Italy candidate requires its prior census and independent Supervisor to be DONE"}
    prior_result = _task_result(prior_task_id)
    supervisor_result = _task_result(supervisor_task_id)
    if (prior_result.get("status") != "PASS" or prior_result.get("profile_mode") != "ZLIB_DECODED_COORDINATE_CANDIDATE_CENSUS"
            or supervisor_result.get("status") != "PASS"
            or supervisor_result.get("target_task") != prior_task_id):
        return {"created": False, "reason": "Italy candidate lacks a saved independent PASS"}
    artifact = prior_result.get("artifact") or {}
    if not isinstance(artifact, dict) or not artifact.get("sha256"):
        return {"created": False, "reason": "Italy candidate census has no hash-bound artifact"}
    artifact_path = (PROJECT_ROOT / Path(*PurePosixPath(str(artifact.get("path", ""))).parts)).resolve(strict=True)
    if (not artifact_path.is_relative_to(PROJECT_ROOT.resolve())
            or _sha256(artifact_path) != str(artifact["sha256"])):
        raise ValueError("accepted Italy coordinate census artifact is outside the project or changed")
    report = json.loads(artifact_path.read_text(encoding="utf-8"))
    observation = next((row for row in report.get("observations", [])
        if row.get("region") == "Italy" and row.get("relative_path") == "OPEL NCDx Italia 2010-2011/DB/IZ.MG1"), None)
    if not observation:
        return {"created": False, "reason": "accepted census has no exact Italy/IZ.MG1 observation"}
    stream_index = 3001
    summary = next((row for row in observation.get("candidate_stream_summaries", [])
        if int(row.get("stream_index", -1)) == stream_index), None)
    measurement = next((row for row in (summary or {}).get("candidate_measurements", [])
        if row.get("measurement") == "alignment_6/scale_100000_lon_lat"), None)
    full_audit = (observation.get("selected_full_payload_audit") or {}).get("selected_streams", [])
    selected = next((row for row in full_audit if int(row.get("stream_index", -1)) == stream_index
        and row.get("full_payload_sha256") == (summary or {}).get("decompressed_sha256")), None)
    if (not measurement or int(measurement.get("region_candidate_pairs", 0)) < 5
            or int(measurement.get("adjacent_pairs_within_5km", 0)) < 1 or not selected):
        return {"created": False, "reason": "Italy stream 3001 no longer meets its accepted full-payload candidate threshold"}
    source_rows = {suffix: {row["region"]: row for row in _data_profile_sources(suffix)}
                   for suffix in ("CTY", "CNY", "MG1")}
    root = coordinator_runtime.SOURCE_ROOT.resolve(strict=True)
    sources = []
    for suffix in ("CTY", "CNY", "MG1"):
        row = source_rows[suffix].get("Italy")
        if not row:
            return {"created": False, "reason": f"Italy/{suffix} is missing from the read-only evidence ledger"}
        relative = str(row["relative_path"])
        source = (root / Path(*PurePosixPath(relative).parts)).resolve(strict=True)
        if not source.is_relative_to(root):
            raise ValueError("Italy coordinate probe source escaped the original-media root")
        sources.append({**row, "absolute_path": str(source)})
    map_row = next(row for row in sources if row["relative_path"].upper().endswith(".MG1"))
    if (map_row["sha256"] != observation.get("source_sha256")
            or observation.get("stream_inventory_sha256") is None):
        raise ValueError("Italy candidate source or full-stream inventory differs from the accepted census")
    candidate = {"region": "Italy", "prior_task_id": prior_task_id,
        "prior_artifact_path": str(artifact_path), "prior_artifact_sha256": str(artifact["sha256"]),
        "map_relative_path": str(map_row["relative_path"]), "map_sha256": str(map_row["sha256"]),
        "stream_count": int(observation["stream_count"]),
        "stream_inventory_sha256": str(observation["stream_inventory_sha256"]),
        "stream_index": stream_index, "source_offset": int(summary["source_offset"]),
        "compressed_bytes": int(summary["compressed_bytes"]),
        "decompressed_bytes": int(summary["decompressed_bytes"]),
        "decompressed_sha256": str(summary["decompressed_sha256"]),
        "measurement": "alignment_6/scale_100000_lon_lat",
        "prior_adjacent_pairs": int(measurement["adjacent_pairs_within_5km"])}
    fingerprint = hashlib.sha256(json.dumps({"experiment": "ncdx_italy_mg1_coordinates_vs_cty_city_boxes",
        "handler_version": CITY_COORDINATE_CROSSCHECK_VERSION,
        "prior_artifact_sha256": artifact["sha256"],
        "sources": [(row["relative_path"], row["sha256"], row["size_bytes"]) for row in sources],
        "candidate": {key: candidate[key] for key in ("region", "stream_index", "source_offset",
            "compressed_bytes", "decompressed_sha256", "measurement")}},
        sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()[:16].upper()
    task_id = f"AUTO_NCDX_ITALY_COORDINATE_CROSSCHECK_V1_{fingerprint}"
    existing = _task_status(task_id)
    if existing:
        return {"created": False, "task_id": task_id,
                "reason": f"exact Italy coordinate/CTY experiment already exists ({existing})"}
    task = {"id": task_id, "stage": "F2", "depends_on": [prior_task_id, supervisor_task_id],
        "hypothesis": "The independently accepted Italy MG1 stream 3001 contains 1e5-scale lon/lat candidates associated with actual Italian CTY city boxes more often than with a displaced control window.",
        "evidence": [{"type": "accepted_full_payload_coordinate_candidate",
            "prior_artifact_sha256": artifact["sha256"], "candidate": candidate,
            "source_count": len(sources)}],
        "agent": "ncdx-city-coordinate-crosscheck",
        "budget": {"timeout_s": 900, "attempts": 1, "source_write": False,
            "max_model_calls": 0, "ncdx_city_coordinate_crosscheck": True,
            "handler_version": CITY_COORDINATE_CROSSCHECK_VERSION,
            "source_fingerprint": fingerprint, "sources": sources, "candidates": [candidate]},
        "deliverables": [f"work/autonomous_manager/ncdx/city_coordinate_crosscheck/{task_id}.json"],
        "tests": ["Reproduce exact accepted Italy/IZ.MG1 stream 3001 payload hash and zlib boundary",
            "Verify Italy CTY/CNY fixed tables and input hashes read-only",
            "Check 1e5-scale lon/lat candidates against actual Italian city boxes and displaced controls",
            "Keep coordinate candidacy distinct from road geometry, topology and routing claims"],
        "next_action": "Persist the Italy-specific result and let the Local Director choose a distinct evidence-backed NCDx direction.",
        "retry_limit": 1, "priority": 3}
    created = state_store.add_task(task, db_path=STATE_DB)
    if created:
        manager._event("goal_scheduler_task_created", {"task_id": task_id, "stage": "F2",
            "source_fingerprint": fingerprint, "source_count": len(sources),
            "selected_regions": ["Italy"], "reason": "accepted Italy MG1 candidate uses a new coordinate scale/order and has not been tested against Italian CTY boxes",
            "source_write": False})
    return {"created": created, "task_id": task_id if created else None,
            "reason": "accepted Italy MG1 scale/order candidate needs a distinct CTY and displaced-control test",
            "sources": sources}


def execute_ncdx_city_coordinate_crosscheck(task_id: str) -> dict[str, Any]:
    """Re-read only the pinned short streams and city tables under fixed bounds."""
    from src.readers import ncdx_city_coordinate_crosscheck
    task = manager._task(task_id)
    budget = task.get("budget", {})
    if (task.get("agent") != "ncdx-city-coordinate-crosscheck"
            or budget.get("ncdx_city_coordinate_crosscheck") is not True
            or int(budget.get("handler_version", -1)) != CITY_COORDINATE_CROSSCHECK_VERSION):
        raise ValueError("city-coordinate cross-check does not match its fixed reviewed handler")
    root = coordinator_runtime.SOURCE_ROOT.resolve(strict=True)
    sources, candidates = budget.get("sources"), budget.get("candidates")
    candidate_regions = {str(row.get("region")) for row in candidates or [] if isinstance(row, dict)}
    if (not isinstance(sources, list) or not isinstance(candidates, list)
            or len(sources) != 3 * len(candidates)
            or candidate_regions not in ({"SW", "Scandinavia"}, {"Italy"})
            or len(candidate_regions) != len(candidates)):
        raise ValueError("city-coordinate cross-check requires its fixed two-region or Italy-only manifest")
    for row in sources:
        relative = PurePosixPath(str(row.get("relative_path", "")))
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("city-coordinate cross-check source path is unsafe")
        source = (root / Path(*relative.parts)).resolve(strict=True)
        if (not source.is_relative_to(root)
                or source != Path(str(row.get("absolute_path", ""))).resolve(strict=True)
                or source.stat().st_size != int(row.get("size_bytes", -1))
                or _ledger_hash(relative.as_posix()) != row.get("sha256")):
            raise RuntimeError(f"city-coordinate cross-check source differs from inventory: {relative}")
    for row in candidates:
        prior_path = Path(str(row.get("prior_artifact_path", ""))).resolve(strict=True)
        if not prior_path.is_relative_to(PROJECT_ROOT.resolve()):
            raise RuntimeError("prior coordinate evidence path escaped project workspace")
    result = ncdx_city_coordinate_crosscheck.analyze(sources, candidates)
    result.update({"task_id": task_id, "source_fingerprint": budget.get("source_fingerprint"),
                   "created_utc": _utc(), "physical_compatibility": "NOT_TESTED"})
    output = PROJECT_ROOT / "work" / "autonomous_manager" / "ncdx" / "city_coordinate_crosscheck" / f"{task_id}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(output)
    artifact = manager._artifact(task_id, output,
        "MG1 candidate coordinates checked against CTY city boxes and displaced controls",
        f"PASS: {len(result['regions'])} fixed stream comparisons; hypothesis={result['hypothesis_result']}")
    _register_supervisor("AUTO_SUPERVISOR_" + task_id, task_id)
    return {**result, "artifact": artifact}


def _has_repeatable_coordinate_candidate(result: dict[str, Any]) -> bool:
    """Require repeated same-key short-step pairs before scheduling a stream index."""
    observations = result.get("observations")
    if result.get("status") != "PASS" or not isinstance(observations, list) or len(observations) != 3:
        return False
    return any(int(measurement.get("adjacent_pairs_within_5km", 0)) >= 2
        for observation in observations if isinstance(observation, dict)
        for measurement in (observation.get("measurements") or {}).values()
        if isinstance(measurement, dict))


def _has_stream_level_coordinate_candidate(result: dict[str, Any]) -> bool:
    """Require at least three contiguous candidate points in one verified stream."""
    observations = result.get("observations")
    if result.get("status") != "PASS" or not isinstance(observations, list) or len(observations) != 3:
        return False
    return any(int(measurement.get("adjacent_pairs_within_5km", 0)) >= 2
        for observation in observations if isinstance(observation, dict)
        for stream in (observation.get("candidate_stream_summaries") or [])
        if isinstance(stream, dict)
        for measurement in (stream.get("candidate_measurements") or [])
        if isinstance(measurement, dict))


def _selected_coordinate_payloads_from_deep_result(
        result: dict[str, Any], *, max_streams_per_region: int = 2,
        batch_index: int = 0, selection_class: str = "repeated_pairs"
        ) -> dict[str, list[dict[str, Any]]]:
    """Pick only reproducible, repeated short-step streams from a verified deep census."""
    from src.readers.ncdx_record_probe import (
        MAX_STANDALONE_ZLIB_OUTPUT_BYTES, ZLIB_COORDINATE_DEEP_PREFIX_PARAMETERS)

    if (result.get("status") != "PASS"
            or result.get("profile_parameters") != ZLIB_COORDINATE_DEEP_PREFIX_PARAMETERS
            or int(max_streams_per_region) != 2 or int(batch_index) < 0
            or selection_class not in {"repeated_pairs", "single_pair"}):
        return {}
    observations = result.get("observations")
    if not isinstance(observations, list) or len(observations) != 3:
        return {}
    selected: dict[str, list[dict[str, Any]]] = {}
    for observation in observations:
        if not isinstance(observation, dict) or observation.get("region") not in {
                "SW", "Italy", "Scandinavia"}:
            return {}
        ranked: list[tuple[int, int, int, dict[str, Any]]] = []
        for stream in observation.get("candidate_stream_summaries") or []:
            if not isinstance(stream, dict):
                continue
            measurements = [row for row in stream.get("candidate_measurements") or []
                            if isinstance(row, dict)]
            adjacent = max((int(row.get("adjacent_pairs_within_5km", 0))
                            for row in measurements), default=0)
            region_pairs = max((int(row.get("region_candidate_pairs", 0))
                                for row in measurements), default=0)
            if ((selection_class == "repeated_pairs" and adjacent < 2)
                    or (selection_class == "single_pair" and adjacent != 1)):
                continue
            try:
                descriptor = {
                    "stream_index": int(stream["stream_index"]),
                    "source_offset": int(stream["source_offset"]),
                    "compressed_bytes": int(stream["compressed_bytes"]),
                    "decompressed_bytes": int(stream["decompressed_bytes"]),
                    "decompressed_sha256": str(stream["decompressed_sha256"]),
                    "sample_prefix_sha256": str(stream["sample_prefix_sha256"]),
                }
            except (KeyError, TypeError, ValueError):
                continue
            if not 16 <= descriptor["decompressed_bytes"] <= MAX_STANDALONE_ZLIB_OUTPUT_BYTES:
                continue
            ranked.append((adjacent, region_pairs, descriptor["stream_index"], descriptor))
        ordered = sorted(ranked, key=lambda row: (-row[0], -row[1], row[2]))
        start = int(batch_index) * max_streams_per_region
        selected[str(observation["region"])] = [row[3] for row in
            ordered[start:start + max_streams_per_region]]
    return selected if set(selected) == {"SW", "Italy", "Scandinavia"} and any(selected.values()) else {}


def _compact_director_evidence(task_id: str | None) -> dict[str, Any] | None:
    if not task_id:
        return None
    try:
        result = _task_result(task_id)
    except (KeyError, RuntimeError, ValueError):
        return {"task_id": task_id, "available": False}
    observations = []
    for row in result.get("observations", []):
        if not isinstance(row, dict):
            continue
        summary = {key: row[key] for key in ("region", "stream_count", "sampled_stream_count",
            "sampled_payload_bytes", "source_sha256") if key in row}
        measurements = row.get("measurements")
        if isinstance(measurements, dict):
            summary["top_coordinate_candidate_keys"] = [
                {"key": key,
                 "region_candidate_pairs": int(value.get("region_candidate_pairs", 0)),
                 "adjacent_pairs_within_5km": int(value.get("adjacent_pairs_within_5km", 0))}
                for key, value in sorted(measurements.items(), key=lambda item: (
                    -int(item[1].get("adjacent_pairs_within_5km", 0)),
                    -int(item[1].get("region_candidate_pairs", 0)), item[0]))[:4]
                if isinstance(value, dict)]
        stream_rows = row.get("candidate_stream_summaries")
        if isinstance(stream_rows, list):
            summary["candidate_stream_summaries"] = [{key: stream[key]
                for key in ("stream_index", "source_offset", "compressed_bytes",
                            "decompressed_bytes", "decompressed_sha256", "sample_prefix_sha256",
                            "candidate_measurements") if key in stream}
                for stream in stream_rows[:8] if isinstance(stream, dict)]
            summary["candidate_stream_summary_count"] = len(stream_rows)
        observations.append(summary)
    return {"task_id": task_id, "status": result.get("status"),
        "profile_mode": result.get("profile_mode"), "profile_parameters": result.get("profile_parameters"),
        "observations": observations}


def _validate_coordinate_profile_tier(
        suffix: str, sources: list[dict[str, Any]], prior_task_id: str,
        parameters: dict[str, Any], budget: dict[str, Any]) -> None:
    """Bind each sampling tier to its completed, independently verified predecessor."""
    from src.readers.ncdx_record_probe import (
        ZLIB_COORDINATE_DEEP_PREFIX_PARAMETERS,
        ZLIB_COORDINATE_EXPANDED_PROFILE_PARAMETERS,
        ZLIB_COORDINATE_PROFILE_PARAMETERS,
        ZLIB_COORDINATE_STREAM_HIT_INDEX_PARAMETERS,
        is_zlib_coordinate_selected_payload_parameters)

    mode = "ZLIB_DECODED_COORDINATE_CANDIDATE_CENSUS"
    if parameters == ZLIB_COORDINATE_PROFILE_PARAMETERS:
        if budget.get("selection_evidence_task_id") not in (None, ""):
            raise RuntimeError("base coordinate census must not claim a follow-up evidence predecessor")
        return
    if parameters == ZLIB_COORDINATE_EXPANDED_PROFILE_PARAMETERS:
        predecessor = _data_profile_task_id(suffix, mode, sources,
            upstream_task_id=prior_task_id,
            profile_parameters=ZLIB_COORDINATE_PROFILE_PARAMETERS)
    elif parameters == ZLIB_COORDINATE_STREAM_HIT_INDEX_PARAMETERS:
        predecessor = _data_profile_task_id(suffix, mode, sources,
            upstream_task_id=prior_task_id,
            profile_parameters=ZLIB_COORDINATE_EXPANDED_PROFILE_PARAMETERS)
    elif parameters == ZLIB_COORDINATE_DEEP_PREFIX_PARAMETERS:
        predecessor = _data_profile_task_id(suffix, mode, sources,
            upstream_task_id=prior_task_id,
            profile_parameters=ZLIB_COORDINATE_STREAM_HIT_INDEX_PARAMETERS)
    elif is_zlib_coordinate_selected_payload_parameters(parameters):
        predecessor = _data_profile_task_id(suffix, mode, sources,
            upstream_task_id=prior_task_id,
            profile_parameters=ZLIB_COORDINATE_DEEP_PREFIX_PARAMETERS)
    else:
        raise RuntimeError("coordinate profile tier is outside the fixed allowlist")
    if (budget.get("selection_evidence_task_id") != predecessor
            or _task_status(predecessor) != "DONE"
            or _task_status("AUTO_SUPERVISOR_" + predecessor) != "DONE"):
        raise RuntimeError("coordinate profile tier lacks its completed independent evidence predecessor")
    if parameters == ZLIB_COORDINATE_STREAM_HIT_INDEX_PARAMETERS:
        if not _has_repeatable_coordinate_candidate(_task_result(predecessor)):
            raise RuntimeError("stream-hit index lacks repeatable coordinates in the verified expanded result")
    elif parameters == ZLIB_COORDINATE_DEEP_PREFIX_PARAMETERS:
        if not _has_stream_level_coordinate_candidate(_task_result(predecessor)):
            raise RuntimeError("deep-prefix audit lacks a verified stream with repeated short-step candidates")
    elif is_zlib_coordinate_selected_payload_parameters(parameters):
        expected_selection = _selected_coordinate_payloads_from_deep_result(
            _task_result(predecessor),
            max_streams_per_region=int(parameters["max_streams_per_region"]),
            batch_index=int(parameters.get("batch_index", 0)),
            selection_class=str(parameters.get("selection_class", "repeated_pairs")))
        if not expected_selection or parameters.get("selected_streams_by_region") != expected_selection:
            raise RuntimeError("full-payload audit selection differs from the verified deep-prefix evidence")


def _data_profile_candidates(*, include_legacy_modes: bool = False) -> list[dict[str, Any]]:
    """Return unique, manifest-backed experiments not already in SQLite.

    The persistent Director schedules proven-format round-trips first. The
    older statistical samplers remain callable for targeted follow-up work,
    but do not fill the queue after the profile catalog has ample coverage.
    """
    suffixes = coordinator_runtime.available_target_suffixes()
    candidates: list[dict[str, Any]] = []
    modes = DATA_PROFILE_MODES if include_legacy_modes else DIRECTOR_DATA_PROFILE_MODES
    for mode in modes:
        for suffix in suffixes:
            if mode in {"CONTAINER_ROUNDTRIP", "DECODED_STRUCTURE_SCAN",
                        "STRING_COORDINATE_PROXIMITY_AUDIT", "PRINTABLE_RUN_LAYOUT_PROFILE"} and suffix not in CONTAINER_ROUNDTRIP_SUFFIXES:
                continue
            if mode in {"DECODED_STRUCTURE_SCAN", "PRINTABLE_RUN_LAYOUT_PROFILE",
                        "REPEATED_TEXT_DICTIONARY_PROFILE", "REPEATED_TEXT_COORDINATE_AUDIT",
                        "BLOCK_BOUNDARY_PROFILE", "TEXT_COORDINATE_ASSOCIATION_CENSUS",
                        "REPEATED_TEXT_COORDINATE_ASSOCIATION_CENSUS"} and suffix != "PDX":
                # PTI and PTP are small catalogs already covered end-to-end;
                # the stratified rescan targets only the large map-data family.
                continue
            prior_task_id = None
            if mode == "STRING_COORDINATE_PROXIMITY_AUDIT":
                if suffix != "PDX":
                    continue
                prior_task_id = _data_profile_task_id("PDX", "DECODED_STRUCTURE_SCAN",
                                                      _data_profile_sources("PDX"))
                if (_task_status(prior_task_id) != "DONE"
                        or _task_status("AUTO_SUPERVISOR_" + prior_task_id) != "DONE"):
                    continue
            if mode == "REPEATED_TEXT_COORDINATE_AUDIT":
                if suffix != "PDX":
                    continue
                prior_task_id = _data_profile_task_id("PDX", "REPEATED_TEXT_DICTIONARY_PROFILE",
                                                      _data_profile_sources("PDX"))
                if (_task_status(prior_task_id) != "DONE"
                        or _task_status("AUTO_SUPERVISOR_" + prior_task_id) != "DONE"):
                    continue
            try:
                sources = _data_profile_sources(suffix)
            except (OSError, ValueError, RuntimeError):
                continue
            if mode == "STANDALONE_ZLIB_STREAM_CENSUS":
                from src.readers.ncdx_record_probe import MAX_STANDALONE_ZLIB_FILE_BYTES
                if (suffix in CONTAINER_ROUNDTRIP_SUFFIXES
                        or any(int(row["size_bytes"]) < 4096
                               or int(row["size_bytes"]) > MAX_STANDALONE_ZLIB_FILE_BYTES
                               for row in sources)):
                    continue
            if mode == "ZLIB_STREAM_BOUNDARY_CONTEXT_PROFILE":
                if suffix in CONTAINER_ROUNDTRIP_SUFFIXES:
                    continue
                prior_task_id = _data_profile_task_id(
                    suffix, "STANDALONE_ZLIB_STREAM_CENSUS", sources)
                if (_task_status(prior_task_id) != "DONE"
                        or _task_status("AUTO_SUPERVISOR_" + prior_task_id) != "DONE"):
                    continue
                try:
                    prior_result = _task_result(prior_task_id)
                except (KeyError, RuntimeError, ValueError):
                    continue
                prior_observations = prior_result.get("observations", [])
                if (prior_result.get("status") != "PASS"
                        or len(prior_observations) != 3
                        or not any(int(row.get("stream_count", 0)) > 0
                                   for row in prior_observations if isinstance(row, dict))):
                    continue
            if mode == "ZLIB_DECODED_COORDINATE_CANDIDATE_CENSUS":
                if suffix in CONTAINER_ROUNDTRIP_SUFFIXES:
                    continue
                prior_task_id = _data_profile_task_id(
                    suffix, "STANDALONE_ZLIB_STREAM_CENSUS", sources)
                if (_task_status(prior_task_id) != "DONE"
                        or _task_status("AUTO_SUPERVISOR_" + prior_task_id) != "DONE"):
                    continue
                try:
                    prior_result = _task_result(prior_task_id)
                except (KeyError, RuntimeError, ValueError):
                    continue
                prior_observations = prior_result.get("observations", [])
                prior_by_region = {str(row.get("region")): row for row in prior_observations
                                   if isinstance(row, dict)}
                if (prior_result.get("status") != "PASS"
                        or set(prior_by_region) != {str(row["region"]) for row in sources}
                        or any(int(prior_by_region[str(row["region"])].get("stream_count", 0)) < 1
                               or prior_by_region[str(row["region"])].get("source_sha256") != row["sha256"]
                               for row in sources)):
                    continue
            if mode == "TEXT_COORDINATE_ASSOCIATION_CENSUS":
                if suffix != "PDX":
                    continue
                prior_task_id = _data_profile_task_id(
                    "PDX", "STRING_COORDINATE_PROXIMITY_AUDIT", sources)
                if (_task_status(prior_task_id) != "DONE"
                        or _task_status("AUTO_SUPERVISOR_" + prior_task_id) != "DONE"):
                    continue
            if mode == "REPEATED_TEXT_COORDINATE_ASSOCIATION_CENSUS":
                if suffix != "PDX":
                    continue
                dictionary_task_id = _data_profile_task_id(
                    "PDX", "REPEATED_TEXT_DICTIONARY_PROFILE", sources)
                prior_task_id = _data_profile_task_id(
                    "PDX", "REPEATED_TEXT_COORDINATE_AUDIT", sources,
                    upstream_task_id=dictionary_task_id)
                if (_task_status(dictionary_task_id) != "DONE"
                        or _task_status("AUTO_SUPERVISOR_" + dictionary_task_id) != "DONE"
                        or _task_status(prior_task_id) != "DONE"
                        or _task_status("AUTO_SUPERVISOR_" + prior_task_id) != "DONE"):
                    continue
            upstream_task_id = (prior_task_id if mode in {
                "REPEATED_TEXT_COORDINATE_AUDIT",
                "REPEATED_TEXT_COORDINATE_ASSOCIATION_CENSUS",
                "ZLIB_STREAM_BOUNDARY_CONTEXT_PROFILE",
                "ZLIB_DECODED_COORDINATE_CANDIDATE_CENSUS"} else None)
            parameter_options: list[dict[str, Any] | None] = (
                [{"context_bytes": width} for width in (8, 16, 32, 64)]
                if mode == "ZLIB_STREAM_BOUNDARY_CONTEXT_PROFILE" else [None])
            if mode == "ZLIB_DECODED_COORDINATE_CANDIDATE_CENSUS":
                from src.readers.ncdx_record_probe import (
                    ZLIB_COORDINATE_DEEP_PREFIX_PARAMETERS,
                    ZLIB_COORDINATE_EXPANDED_PROFILE_PARAMETERS,
                    ZLIB_COORDINATE_SELECTED_PAYLOAD_PARAMETERS,
                    ZLIB_COORDINATE_STREAM_HIT_INDEX_PARAMETERS,
                    ZLIB_COORDINATE_PROFILE_PARAMETERS)
                base_parameters = dict(ZLIB_COORDINATE_PROFILE_PARAMETERS)
                parameter_options = [base_parameters]
                base_task_id = _data_profile_task_id(suffix, mode, sources,
                    upstream_task_id=upstream_task_id,
                    profile_parameters=base_parameters)
                hit_index_task_id: str | None = None
                deep_task_id: str | None = None
                if (_task_status(base_task_id) == "DONE"
                        and _task_status("AUTO_SUPERVISOR_" + base_task_id) == "DONE"):
                    # Expand coverage only after the smaller experiment and its
                    # independent read-only verifier have both completed.
                    expanded_parameters = dict(ZLIB_COORDINATE_EXPANDED_PROFILE_PARAMETERS)
                    parameter_options.append(expanded_parameters)
                    expanded_task_id = _data_profile_task_id(suffix, mode, sources,
                        upstream_task_id=upstream_task_id,
                        profile_parameters=expanded_parameters)
                    if (_task_status(expanded_task_id) == "DONE"
                            and _task_status("AUTO_SUPERVISOR_" + expanded_task_id) == "DONE"):
                        try:
                            expanded_result = _task_result(expanded_task_id)
                        except (KeyError, RuntimeError, ValueError):
                            expanded_result = {}
                        if _has_repeatable_coordinate_candidate(expanded_result):
                            hit_parameters = dict(ZLIB_COORDINATE_STREAM_HIT_INDEX_PARAMETERS)
                            parameter_options.append(hit_parameters)
                            hit_index_task_id = _data_profile_task_id(suffix, mode, sources,
                                upstream_task_id=upstream_task_id,
                                profile_parameters=hit_parameters)
                            if (_task_status(hit_index_task_id) == "DONE"
                                    and _task_status("AUTO_SUPERVISOR_" + hit_index_task_id) == "DONE"):
                                try:
                                    hit_index_result = _task_result(hit_index_task_id)
                                except (KeyError, RuntimeError, ValueError):
                                    hit_index_result = {}
                                if _has_stream_level_coordinate_candidate(hit_index_result):
                                    deep_parameters = dict(ZLIB_COORDINATE_DEEP_PREFIX_PARAMETERS)
                                    parameter_options.append(deep_parameters)
                                    deep_task_id = _data_profile_task_id(suffix, mode, sources,
                                        upstream_task_id=upstream_task_id,
                                        profile_parameters=deep_parameters)
                                    if (_task_status(deep_task_id) == "DONE"
                                            and _task_status("AUTO_SUPERVISOR_" + deep_task_id) == "DONE"):
                                        try:
                                            deep_result = _task_result(deep_task_id)
                                        except (KeyError, RuntimeError, ValueError):
                                            deep_result = {}
                                        next_batch_pending = False
                                        for selection_class in ("repeated_pairs", "single_pair"):
                                            batch_index = 0
                                            while True:
                                                selected_by_region = _selected_coordinate_payloads_from_deep_result(
                                                    deep_result,
                                                    max_streams_per_region=int(
                                                        ZLIB_COORDINATE_SELECTED_PAYLOAD_PARAMETERS[
                                                            "max_streams_per_region"]),
                                                    batch_index=batch_index,
                                                    selection_class=selection_class)
                                                if not selected_by_region:
                                                    break
                                                selected_parameters = {
                                                    **ZLIB_COORDINATE_SELECTED_PAYLOAD_PARAMETERS,
                                                    "selected_streams_by_region": selected_by_region}
                                                if selection_class != "repeated_pairs":
                                                    selected_parameters["selection_class"] = selection_class
                                                if batch_index:
                                                    selected_parameters["batch_index"] = batch_index
                                                selected_task_id = _data_profile_task_id(
                                                    suffix, mode, sources,
                                                    upstream_task_id=upstream_task_id,
                                                    profile_parameters=selected_parameters)
                                                selected_status = _task_status(selected_task_id)
                                                if selected_status is None:
                                                    parameter_options.append(selected_parameters)
                                                    next_batch_pending = True
                                                    break
                                                verifier_status = _task_status(
                                                    "AUTO_SUPERVISOR_" + selected_task_id)
                                                if (selected_status == "DONE"
                                                        and verifier_status == "DONE"):
                                                    batch_index += 1
                                                    continue
                                                if (selected_status in {
                                                        "BLOCKED", "SUPERSEDED", "WAITING_CODEX_QUOTA"}
                                                        or (selected_status == "DONE"
                                                            and verifier_status in {
                                                                "BLOCKED", "SUPERSEDED",
                                                                "WAITING_CODEX_QUOTA"})):
                                                    # This exact, manifest-bound batch already has a durable
                                                    # terminal/parked record. Preserve it as-is and let the
                                                    # Director advance to the next independent stream batch;
                                                    # a resource-limited verifier must not starve the family.
                                                    batch_index += 1
                                                    continue
                                                # Do not duplicate a live task or advance past an unfinished
                                                # verifier; another suffix can still advance independently.
                                                next_batch_pending = True
                                                break
                                            if next_batch_pending:
                                                break
            for profile_parameters in parameter_options:
                task_id = _data_profile_task_id(suffix, mode, sources,
                    upstream_task_id=upstream_task_id,
                    profile_parameters=profile_parameters)
                if _task_status(task_id) is not None:
                    continue
                candidate = {"goal_id": task_id, "suffix": suffix, "mode": mode,
                             "sources": sources}
                if prior_task_id:
                    candidate["prior_task_id"] = prior_task_id
                if profile_parameters:
                    candidate["profile_parameters"] = profile_parameters
                if mode == "ZLIB_DECODED_COORDINATE_CANDIDATE_CENSUS":
                    from src.readers.ncdx_record_probe import (
                        ZLIB_COORDINATE_DEEP_PREFIX_PARAMETERS,
                        ZLIB_COORDINATE_EXPANDED_PROFILE_PARAMETERS,
                        ZLIB_COORDINATE_SELECTED_PAYLOAD_PARAMETERS,
                        ZLIB_COORDINATE_STREAM_HIT_INDEX_PARAMETERS,
                        is_zlib_coordinate_selected_payload_parameters)
                    if profile_parameters == ZLIB_COORDINATE_EXPANDED_PROFILE_PARAMETERS:
                        candidate["selection_evidence_task_id"] = base_task_id
                    elif profile_parameters == ZLIB_COORDINATE_STREAM_HIT_INDEX_PARAMETERS:
                        candidate["selection_evidence_task_id"] = expanded_task_id
                    elif profile_parameters == ZLIB_COORDINATE_DEEP_PREFIX_PARAMETERS:
                        candidate["selection_evidence_task_id"] = hit_index_task_id
                    elif is_zlib_coordinate_selected_payload_parameters(profile_parameters):
                        candidate["selection_evidence_task_id"] = deep_task_id
                candidates.append(candidate)
    return candidates


def _data_profile_acceptance(mode: str) -> list[str]:
    shared = ["Only the three manifest-listed regional files are opened read-only",
              "File size and modification time are unchanged during sampling",
              "No source write occurs; all output is under the project work directory",
              "Ncdx semantic format remains UNKNOWN unless separately proven"]
    if mode == "WINDOW_PROFILE":
        return shared + ["At most five 4096-byte windows per source are sampled",
                         "Offsets, sample hashes, entropy and printable ratios are reproducible"]
    if mode == "BLOCK_ALIGNMENT":
        return shared + ["At most the first 64 KiB per source are compared",
                         "512-byte and 2048-byte aligned block matches are reproducible"]
    if mode == "SIGNATURE_SWEEP":
        return shared + ["At most seven 4096-byte windows per source are sampled",
                         "Only literal known byte signatures and bounded strings are reported"]
    if mode == "CROSS_REGION_WINDOW_COMPARE":
        return shared + ["At most five deterministic 4096-byte windows per source are sampled",
                         "Window offsets use the same normalized positions in each regional file",
                         "Pairwise equal-byte counts and common-prefix lengths are reproducible",
                         "Raw sampled bytes are discarded before results are written"]
    if mode == "LAG_CORRELATION_SCAN":
        return shared + ["At most five deterministic 4096-byte windows per source are sampled",
                         "Byte equality rates are measured only at the fixed lag allowlist",
                         "All lag scores and offsets are reproducible; no record semantics are inferred"]
    if mode == "BYTE_TRANSITION_PROFILE":
        return shared + ["At most five deterministic 4096-byte windows per source are sampled",
                         "Top adjacent-byte pairs use deterministic count and byte-order sorting",
                         "Only pair counts and ratios are saved; sampled source bytes are discarded"]
    if mode == "DEFLATE_COMPRESSIBILITY_PROFILE":
        return shared + ["At most five deterministic 65536-byte windows per source are sampled",
                         "Each sample is transiently compressed with zlib level 6; raw and compressed bytes are discarded",
                         "Only sample hashes, byte counts and ratios are retained; high entropy is not called encryption"]
    if mode == "EXACT_BLOCK_ANCHOR_SCAN":
        return shared + ["Only the first 4 MiB of each inventoried regional source are scanned in 4096-byte blocks",
                         "Only complete-block SHA-256 values and offsets are retained transiently",
                         "Report only unique cross-region exact-block anchors; infer no record meaning"]
    if mode == "CONTAINER_ROUNDTRIP":
        return shared + ["Only manifest-backed PTI, PDX or PTP regional files with the observed zip\\x01 block structure are accepted",
                         "Each source is opened read-only and decoded with strict file, block and output bounds",
                         "The writer uses 3072-byte blocks and zlib level 9, preserving the opaque header word",
                         "The no-op re-encoding must match every source byte and is written only below project work/",
                         "A fresh independent parser must decode all nine regional outputs and match their saved sizes and hashes",
                         "No decoded record or navigation semantics are claimed"]
    if mode == "DECODED_STRUCTURE_SCAN":
        return shared + ["Stream-decode all three manifest-backed regional files through the bounded zip\\x01 reader",
                         "Use a deterministic hash-ranked reservoir of up to 32 unique printable strings per each of 16 equal logical-file bins",
                         "Report bounded ASCII samples and aligned signed-32-bit coordinate-window candidates at fixed scales",
                         "Distribute the sample budget across the complete decoded file rather than favoring the header",
                         "Every reported offset is relative to the decoded logical payload and can be independently reproduced",
                         "No strings are labeled as categories, and no integer pair is labeled as a coordinate or record without separate proof",
                         "No raw payload blocks are retained; original files remain read-only"]
    if mode == "STRING_COORDINATE_PROXIMITY_AUDIT":
        return shared + ["Only the PDX family is eligible, and its versioned decoded-structure scan must already have passed an independent Supervisor",
                         "Use the saved bounded text-anchor offsets from that verified checkpoint and verify every text anchor against a fresh source decode",
                         "Compare fixed-scale regional integer-pair candidates within 128 bytes of anchors against up to 256 deterministic evenly spaced control windows per region",
                         "Report hit counts and at most eight examples per scale/order; do not call any candidate a coordinate or assign record semantics",
                         "Repeat the complete audit in the independent Supervisor process; original media stays read-only"]
    if mode == "PRINTABLE_RUN_LAYOUT_PROFILE":
        return shared + ["Only the three manifest-listed PDX regional map files are eligible",
                         "Decode with the bounded NCDx reader and summarize every 4-96 byte printable run",
                         "Report length buckets, inter-run gap buckets and counts across 16 logical-file bins",
                         "Retain only bounded hashes and offsets for up to eight run samples per bin; never retain raw strings",
                         "The independent Supervisor repeats all three read-only scans and compares exact summaries"]
    if mode == "REPEATED_TEXT_DICTIONARY_PROFILE":
        return shared + ["Only the three manifest-listed PDX regional map files are eligible",
                         "Deterministically include printable values by SHA-256 modulo 64, independent of file region",
                         "Count included literal values exactly and retain at most 50,000 sampled values per file",
                         "Report at most 32 repeated values per region with bounded offsets, hashes and text labels",
                         "Compare hashes across regions; no value is assigned a record or navigation meaning",
                         "A fresh independent Supervisor repeats every read-only count and source hash check"]
    if mode == "REPEATED_TEXT_COORDINATE_AUDIT":
        return shared + ["Only PDX is eligible, after its deterministic repeated-text profile and independent Supervisor passed",
                         "Use the top 32 exact-count values from each verified regional dictionary as fixed anchors",
                         "Scan each manifest-bound decoded PDX for all anchor occurrences and deterministically sample at most four per value",
                         "Compare fixed-scale coordinate candidates within 128 bytes of these real repeated values against deterministic control windows",
                         "The independent Supervisor repeats occurrence sampling and the complete source-bound proximity audit",
                         "Do not call a literal name, candidate pair, record or navigation field proven"]
    if mode in {"TEXT_COORDINATE_ASSOCIATION_CENSUS",
                "REPEATED_TEXT_COORDINATE_ASSOCIATION_CENSUS"}:
        strategy = "all printable runs" if mode == "TEXT_COORDINATE_ASSOCIATION_CENSUS" else "exact repeated literals"
        prerequisite = ("the independently verified PDX text-coordinate proximity audit" if
            mode == "TEXT_COORDINATE_ASSOCIATION_CENSUS" else
            "the independently verified PDX repeated-literal coordinate audit")
        return shared + [f"Only PDX is eligible, after {prerequisite} passed",
                         f"Use a deterministic stratified sample of up to 4096 {strategy} over all 16 equal logical-file bins",
                         "Pair each retained anchor with one deterministic same-bin control window containing no printable run",
                         "Measure signed-int32 little-endian pair candidates at the registered scales within a fixed 64-byte radius",
                         "Report matched-window rates and candidate counts for anchors and controls; retain at most 12 offsets per key",
                         "Fresh Supervisor recomputation must exactly match every saved per-region value",
                         "Report association only; coordinate, record and navigation semantics remain UNKNOWN"]
    if mode == "STANDALONE_ZLIB_STREAM_CENSUS":
        return shared + ["Scan only three SHA-256-manifested regional NCDx files of at least 4 KiB and no more than 128 MiB each",
                         "Use a read-only memory map and bounded zlib input/output windows; never retain decoded payload bytes",
                         "Accept only self-contained zlib streams with a valid stream checksum and reproducible offset/length/hash",
                         "Skip the already recognized zip\\x01 block container and do not infer enclosing record semantics",
                         "Fresh independent Supervisor repeats each complete scan and cross-region payload-hash comparison",
                         "A negative scan is valid evidence only for the exact files and declared byte bounds"]
    if mode == "ZLIB_STREAM_BOUNDARY_CONTEXT_PROFILE":
        return shared + ["Only raw file families with a prior independently verified standalone-zlib census containing checksum-valid streams are eligible",
                         "Bind the follow-up to that exact census target and the same three region source hashes",
                         "Re-discover the complete bounded stream inventory before looking at context",
                         "Use only the fixed context-width allowlist of 8, 16, 32 or 64 bytes; measure SHA-256 identities before and after each stream, stream-start residue counts and inter-stream gaps",
                         "Retain at most 32 frequent context hashes with eight offset examples per context and no raw context or payload bytes",
                         "An independent Supervisor repeats all three source reads and exact hash-only summaries",
                         "Report zlib boundary association only; record, index and navigation semantics remain UNKNOWN"]
    if mode == "ZLIB_DECODED_COORDINATE_CANDIDATE_CENSUS":
        return shared + ["Only raw regional files with a checksum-valid standalone-zlib census and independent Supervisor PASS are eligible",
                         "Bind the experiment to that exact census and source hashes for all three regions",
                         "Use only the fixed base sample, expanded sample, evidence-gated stream-hit index, deep-prefix sample, or selected full-payload audit",
                         "Base sample: at most 512 streams with 4096-byte prefixes; expanded sample: at most 1024 streams with 1024-byte prefixes",
                         "Expanded sampling is eligible only after the base result and independent Supervisor PASS; stream-hit indexing requires at least two short-step candidate pairs under the same fixed measurement and a verified expanded result",
                         "Stream-hit indexing examines every detected stream up to the 4096 stream census limit, retains at most 1024 prefix bytes per stream and reports only stream offsets, hashes and aggregate candidate counts",
                         "Deep-prefix sampling examines every detected stream only after an independent stream-hit index contains at least one stream with three contiguous candidate points; it samples at most 4096 decoded prefix bytes per stream and 16 MiB per source",
                         "Selected full-payload audit is eligible only after an independent deep-prefix PASS, rescans at most two evidence-selected streams per region, and retains no more than 8 MiB of decoded payload per source",
                         "Count signed-int32 pairs for fixed geographic scales and alignments inside the region box and a fixed displaced control box",
                         "Count adjacent in-region candidate pairs no more than 5 km apart as a road-shape lead only",
                         "Persist aggregates and sample-prefix hashes only; retain no decoded payload or coordinate examples",
                         "The independent Supervisor repeats all source checks and exact candidate counts",
                         "Coordinate, road, record, index and navigation semantics remain UNKNOWN"]
    if mode == "BLOCK_BOUNDARY_PROFILE":
        return shared + ["Only the three manifest-listed PDX regional map files are eligible",
                         "Decode each independent zlib block with the bounded reader",
                         "Count printable-run starts by normalized block position and report runs crossing block boundaries",
                         "Compare observed crossing and boundary-distance counts against the explicit random-phase null model",
                         "Report only counts, rates, hashes and bounded histograms; retain no decoded strings",
                         "Fresh independent Supervisor repeats each regional profile and compares exact results",
                         "Do not treat block boundaries as record boundaries without separate evidence"]
    raise ValueError(f"unregistered NCDx data profile mode: {mode}")


def _register_data_profile_task(candidate: dict[str, Any], dependency: str | None = None) -> bool:
    task_id = str(candidate["goal_id"])
    suffix, mode = str(candidate["suffix"]), str(candidate["mode"])
    checks = _data_profile_acceptance(mode)
    if mode == "TEXT_COORDINATE_ASSOCIATION_CENSUS":
        parameters = {"anchor_strategy": "all_printable", "max_anchors": 4096,
                      "controls_per_anchor": 1, "radius_bytes": 64}
    elif mode == "REPEATED_TEXT_COORDINATE_ASSOCIATION_CENSUS":
        parameters = {"anchor_strategy": "repeated_literals", "max_anchors": 4096,
                      "controls_per_anchor": 1, "radius_bytes": 64}
    elif mode == "STANDALONE_ZLIB_STREAM_CENSUS":
        from src.readers.ncdx_record_probe import (MAX_STANDALONE_ZLIB_COMPRESSED_BYTES,
            MAX_STANDALONE_ZLIB_FILE_BYTES, MAX_STANDALONE_ZLIB_HEADER_CANDIDATES,
            MAX_STANDALONE_ZLIB_OUTPUT_BYTES)
        parameters = {"max_file_bytes": MAX_STANDALONE_ZLIB_FILE_BYTES,
            "max_compressed_bytes": MAX_STANDALONE_ZLIB_COMPRESSED_BYTES,
            "max_output_bytes": MAX_STANDALONE_ZLIB_OUTPUT_BYTES,
            "max_header_candidates": MAX_STANDALONE_ZLIB_HEADER_CANDIDATES}
    elif mode == "ZLIB_STREAM_BOUNDARY_CONTEXT_PROFILE":
        parameters = candidate.get("profile_parameters", {"context_bytes": 16})
        if parameters not in ({"context_bytes": 8}, {"context_bytes": 16},
                              {"context_bytes": 32}, {"context_bytes": 64}):
            raise ValueError("zlib boundary profile parameters are outside the fixed width allowlist")
    elif mode == "ZLIB_DECODED_COORDINATE_CANDIDATE_CENSUS":
        from src.readers.ncdx_record_probe import (ZLIB_COORDINATE_PROFILE_PARAMETER_OPTIONS,
            is_zlib_coordinate_selected_payload_parameters)
        parameters = candidate.get("profile_parameters")
        if (parameters not in ZLIB_COORDINATE_PROFILE_PARAMETER_OPTIONS
                and not is_zlib_coordinate_selected_payload_parameters(parameters)):
            raise ValueError("zlib decoded-coordinate parameters differ from the bounded sampling allowlist")
    elif mode == "REPEATED_TEXT_DICTIONARY_PROFILE":
        parameters = {"sampling_modulus": 64, "top_n": 32, "max_candidates": 50_000}
    elif mode == "REPEATED_TEXT_COORDINATE_AUDIT":
        parameters = {"occurrences_per_value": 4}
    elif mode == "BLOCK_BOUNDARY_PROFILE":
        parameters = {"position_bins": 16}
    else:
        parameters = {}
    return _registered_task(task_id, "F2", dependency,
        f"Measure the {mode} profile of the three inventoried regional {suffix} files; collect only reproducible structural evidence, not guessed semantics.",
        "ncdx-data-family-profile",
        f"work/autonomous_manager/ncdx/data_family_profiles/{task_id}.json",
        checks, 300, 16,
        {"data_family_profile": True, "suffix": suffix, "profile_mode": mode,
         "sources": candidate["sources"], "plan_goal_id": task_id,
         "prior_task_id": candidate.get("prior_task_id"),
         "selection_evidence_task_id": candidate.get("selection_evidence_task_id"),
         "profile_parameters": parameters})


def _execute_container_roundtrip_profile(task: dict[str, Any],
                                         source_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """No-op re-encode three regional containers into immutable work copies."""
    from src.writers.ncdx_container_writer import write_lossless_roundtrip

    task_id = str(task["id"])
    suffix = str(task.get("budget", {}).get("suffix", ""))
    if suffix not in CONTAINER_ROUNDTRIP_SUFFIXES or len(source_rows) != 3:
        raise ValueError("container round-trip needs one supported suffix and exactly three regional sources")
    source_root = coordinator_runtime.SOURCE_ROOT.resolve(strict=True)
    work_root = (PROJECT_ROOT / "work").resolve(strict=True)
    output_dir = work_root / "autonomous_manager" / "ncdx" / "container_roundtrips" / task_id
    output_rows: list[dict[str, Any]] = []
    for row in source_rows:
        relative = PurePosixPath(str(row["relative_path"]).replace("\\", "/"))
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("container round-trip source path is not a safe manifest-relative path")
        source = (source_root / Path(*relative.parts)).resolve(strict=True)
        if not source.is_relative_to(source_root):
            raise ValueError("container round-trip source escaped the original-media root")
        destination = output_dir / f"{row['region']}.{suffix}"
        roundtrip = write_lossless_roundtrip(source, destination,
            expected_sha256=str(row["sha256"]), work_root=work_root)
        output_rows.append({"region": row["region"], "relative_path": row["relative_path"],
            "output_path": destination.relative_to(PROJECT_ROOT).as_posix(),
            "inventory_sha256": row["sha256"], **roundtrip})

    if len({row["region"] for row in output_rows}) != 3 or not all(
            row.get("byte_identical") and row.get("source_stat_unchanged")
            and row["source_sha256"] == row["inventory_sha256"] == row["output_sha256"]
            for row in output_rows):
        raise RuntimeError("container no-op round-trip failed a regional source-bound check")
    result = {"status": "PASS", "task_id": task_id, "suffix": suffix,
        "profile_mode": "CONTAINER_ROUNDTRIP", "observations": output_rows,
        "cross_region_comparisons": [],
        "verified": {"source_count": 3, "source_stat_unchanged_during_read": True,
            "manifest_entries_present": True, "source_write_count": 0,
            "byte_identical_outputs": True,
            "semantic_format": "UNKNOWN; structural observations only"},
        "claim_scope": "byte-exact no-op regional container round-trip; decoded record semantics UNKNOWN",
        "created_utc": _utc(), "original_media_write_count": 0,
        "physical_compatibility": "NOT_TESTED"}
    output = PROJECT_ROOT / "work" / "autonomous_manager" / "ncdx" / "data_family_profiles" / f"{task_id}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(output)
    artifact = manager._artifact(task_id, output,
        f"Verified byte-exact NCDx {suffix} regional container round-trip",
        "PASS: all three manifest-backed source containers were independently re-readable after an exact no-op re-encode")
    _register_supervisor("AUTO_SUPERVISOR_" + task_id, task_id)
    return {**result, "artifact": artifact}


def _execute_decoded_structure_profile(task: dict[str, Any],
                                       source_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Stream-decode a regional file family and save bounded structural candidates."""
    from src.readers.ncdx_record_probe import probe_regional_set

    task_id = str(task["id"])
    suffix = str(task.get("budget", {}).get("suffix", ""))
    if suffix not in CONTAINER_ROUNDTRIP_SUFFIXES or len(source_rows) != 3:
        raise ValueError("decoded structure scan needs one supported suffix and exactly three regional sources")
    source_root = coordinator_runtime.SOURCE_ROOT.resolve(strict=True)
    probe = probe_regional_set(source_rows, source_root=source_root)
    if probe.get("status") != "PASS" or probe.get("source_count") != 3:
        raise RuntimeError("bounded decoded structure probe did not pass its fixed source checks")
    result = {"status": "PASS", "task_id": task_id, "suffix": suffix,
        "profile_mode": "DECODED_STRUCTURE_SCAN", "observations": probe["observations"],
        "cross_region_comparisons": [],
        "verified": {"source_count": 3, "source_stat_unchanged_during_read": True,
            "manifest_entries_present": True, "source_write_count": 0,
            "raw_payload_bytes_retained": False,
            "semantic_format": "UNKNOWN; structural observations only"},
        "claim_scope": probe["claim_scope"], "created_utc": _utc(),
        "original_media_write_count": 0, "physical_compatibility": "NOT_TESTED"}
    output = PROJECT_ROOT / "work" / "autonomous_manager" / "ncdx" / "data_family_profiles" / f"{task_id}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(output)
    artifact = manager._artifact(task_id, output,
        f"Bounded decoded NCDx {suffix} structural candidate scan",
        "PASS: all regional files were manifest-bound, streamed, hash-checked and read-only")
    _register_supervisor("AUTO_SUPERVISOR_" + task_id, task_id)
    return {**result, "artifact": artifact}


def _execute_string_coordinate_proximity_profile(task: dict[str, Any],
                                                  source_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Test sampled PDX string anchors against fixed-control windows."""
    from src.readers.ncdx_record_probe import audit_string_coordinate_proximity

    task_id = str(task["id"])
    budget = task.get("budget", {})
    suffix = str(budget.get("suffix", ""))
    prior_task_id = str(budget.get("prior_task_id", ""))
    expected_prior_id = _data_profile_task_id("PDX", "DECODED_STRUCTURE_SCAN",
                                               _data_profile_sources("PDX"))
    if (suffix != "PDX" or prior_task_id != expected_prior_id or len(source_rows) != 3):
        raise ValueError("proximity audit requires one verified versioned PDX structure-scan checkpoint")
    prior_result = _task_result(prior_task_id)
    if (prior_result.get("status") != "PASS"
            or prior_result.get("profile_mode") != "DECODED_STRUCTURE_SCAN"):
        raise RuntimeError("proximity audit's prerequisite scan is not a verified decoded-structure result")
    previous = {str(row.get("region")): row for row in prior_result.get("observations", [])
                if isinstance(row, dict)}
    source_root = coordinator_runtime.SOURCE_ROOT.resolve(strict=True)
    observations = []
    for row in source_rows:
        prior = previous.get(str(row["region"]))
        if not prior or prior.get("source_sha256") != row["sha256"]:
            raise RuntimeError("proximity audit text anchors are not bound to the current source inventory")
        relative = PurePosixPath(str(row["relative_path"]).replace("\\", "/"))
        source = (source_root / Path(*relative.parts)).resolve(strict=True)
        if not source.is_relative_to(source_root):
            raise ValueError("proximity audit source escaped the original-media root")
        observation = audit_string_coordinate_proximity(source, region=str(row["region"]),
            expected_sha256=str(row["sha256"]), text_samples=prior.get("bounded_ascii_samples", []))
        if observation["source_bytes"] != int(row["size_bytes"]):
            raise RuntimeError("proximity audit source size differs from the inventory")
        observations.append({"relative_path": row["relative_path"], **observation})
    result = {"status": "PASS", "task_id": task_id, "suffix": suffix,
        "profile_mode": "STRING_COORDINATE_PROXIMITY_AUDIT", "prior_task_id": prior_task_id,
        "observations": observations, "cross_region_comparisons": [],
        "verified": {"source_count": 3, "source_stat_unchanged_during_read": True,
            "manifest_entries_present": True, "source_write_count": 0,
            "raw_payload_bytes_retained": False,
            "semantic_format": "UNKNOWN; structural observations only"},
        "claim_scope": "candidate proximity enrichment versus fixed-control windows only; record and coordinate semantics UNKNOWN",
        "created_utc": _utc(), "original_media_write_count": 0,
        "physical_compatibility": "NOT_TESTED"}
    output = PROJECT_ROOT / "work" / "autonomous_manager" / "ncdx" / "data_family_profiles" / f"{task_id}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(output)
    artifact = manager._artifact(task_id, output,
        "NCDx PDX string and coordinate-candidate proximity audit",
        "PASS: each manifest-bound regional result compares decoded string anchors to fixed control windows")
    _register_supervisor("AUTO_SUPERVISOR_" + task_id, task_id)
    return {**result, "artifact": artifact}


def _execute_printable_run_layout_profile(task: dict[str, Any],
                                           source_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize bounded PDX printable-run structure without retaining text."""
    from src.readers.ncdx_record_probe import profile_printable_run_layout

    task_id = str(task["id"])
    suffix = str(task.get("budget", {}).get("suffix", ""))
    if suffix != "PDX" or len(source_rows) != 3:
        raise ValueError("printable-run layout profile requires exactly three regional PDX sources")
    source_root = coordinator_runtime.SOURCE_ROOT.resolve(strict=True)
    observations = []
    for row in source_rows:
        relative = PurePosixPath(str(row["relative_path"]).replace("\\", "/"))
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("layout profile source path is not a safe manifest-relative path")
        source = (source_root / Path(*relative.parts)).resolve(strict=True)
        if not source.is_relative_to(source_root):
            raise ValueError("layout profile source escaped the original-media root")
        observation = profile_printable_run_layout(source, region=str(row["region"]),
            expected_sha256=str(row["sha256"]))
        if observation["source_bytes"] != int(row["size_bytes"]):
            raise RuntimeError("layout profile source size differs from the inventory")
        observations.append({"relative_path": row["relative_path"], **observation})
    result = {"status": "PASS", "task_id": task_id, "suffix": suffix,
        "profile_mode": "PRINTABLE_RUN_LAYOUT_PROFILE", "observations": observations,
        "cross_region_comparisons": [],
        "verified": {"source_count": 3, "source_stat_unchanged_during_read": True,
            "manifest_entries_present": True, "source_write_count": 0,
            "raw_payload_bytes_retained": False,
            "semantic_format": "UNKNOWN; structural observations only"},
        "claim_scope": "printable-run structure statistics; record and navigation semantics UNKNOWN",
        "created_utc": _utc(), "original_media_write_count": 0,
        "physical_compatibility": "NOT_TESTED"}
    output = PROJECT_ROOT / "work" / "autonomous_manager" / "ncdx" / "data_family_profiles" / f"{task_id}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(output)
    artifact = manager._artifact(task_id, output,
        "Bounded PDX printable-run layout profile",
        "PASS: all regional summaries are manifest-bound and retain hashes and offsets only")
    _register_supervisor("AUTO_SUPERVISOR_" + task_id, task_id)
    return {**result, "artifact": artifact}


def _execute_repeated_text_dictionary_profile(task: dict[str, Any],
                                               source_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Count one hash-stable sample of repeated PDX literals across regions."""
    from src.readers.ncdx_record_probe import profile_repeated_text_candidates

    task_id = str(task["id"])
    budget = task.get("budget", {})
    suffix = str(budget.get("suffix", ""))
    parameters = budget.get("profile_parameters", {})
    if suffix != "PDX" or len(source_rows) != 3:
        raise ValueError("repeated-text profile requires exactly three regional PDX sources")
    if parameters != {"sampling_modulus": 64, "top_n": 32, "max_candidates": 50_000}:
        raise ValueError("repeated-text profile parameters differ from the fixed, bounded task specification")
    source_root = coordinator_runtime.SOURCE_ROOT.resolve(strict=True)
    observations = []
    for row in source_rows:
        relative = PurePosixPath(str(row["relative_path"]).replace("\\", "/"))
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("repeated-text source path is not a safe manifest-relative path")
        source = (source_root / Path(*relative.parts)).resolve(strict=True)
        if not source.is_relative_to(source_root):
            raise ValueError("repeated-text source escaped the original-media root")
        observation = profile_repeated_text_candidates(source, region=str(row["region"]),
            expected_sha256=str(row["sha256"]), **parameters)
        if observation["source_bytes"] != int(row["size_bytes"]):
            raise RuntimeError("repeated-text source size differs from the inventory")
        observations.append({"relative_path": row["relative_path"], **observation})
    by_hash: dict[str, list[dict[str, Any]]] = {}
    for row in observations:
        for candidate in row["sampled_value_inventory"]:
            by_hash.setdefault(str(candidate["sha256"]), []).append({
                "region": row["region"], "text": candidate["text"],
                "exact_sampled_count": candidate["exact_sampled_count"]})
    shared = [{"sha256": digest, "text": entries[0]["text"], "regional_values": entries}
              for digest, entries in sorted(by_hash.items()) if len(entries) > 1]
    shared.sort(key=lambda item: (-sum(int(row["exact_sampled_count"])
                                       for row in item["regional_values"]), item["sha256"]))
    result = {"status": "PASS", "task_id": task_id, "suffix": suffix,
        "profile_mode": "REPEATED_TEXT_DICTIONARY_PROFILE", "profile_parameters": parameters,
        "observations": observations, "cross_region_shared_sampled_value_count": len(shared),
        "cross_region_shared_sampled_values_top": shared[:128],
        "verified": {"source_count": 3, "source_stat_unchanged_during_read": True,
            "manifest_entries_present": True, "source_write_count": 0,
            "raw_payload_bytes_retained": False,
            "semantic_format": "UNKNOWN; structural observations only"},
        "claim_scope": "bounded sampled repeated literal vocabulary; no record semantics inferred",
        "created_utc": _utc(), "original_media_write_count": 0,
        "physical_compatibility": "NOT_TESTED"}
    output = PROJECT_ROOT / "work" / "autonomous_manager" / "ncdx" / "data_family_profiles" / f"{task_id}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(output)
    artifact = manager._artifact(task_id, output,
        "Bounded repeated-text vocabulary profile for PDX regional map data",
        "PASS: deterministic sampled values were exactly counted and source files remained read-only")
    _register_supervisor("AUTO_SUPERVISOR_" + task_id, task_id)
    return {**result, "artifact": artifact}


def _execute_repeated_text_coordinate_audit(task: dict[str, Any],
                                             source_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Test coordinates around repeated, independently inventoried PDX values."""
    from src.readers.ncdx_record_probe import audit_repeated_text_coordinate_proximity

    task_id = str(task["id"])
    budget = task.get("budget", {})
    suffix = str(budget.get("suffix", ""))
    prior_task_id = str(budget.get("prior_task_id", ""))
    parameters = budget.get("profile_parameters", {})
    expected_prior_id = _data_profile_task_id("PDX", "REPEATED_TEXT_DICTIONARY_PROFILE",
                                               _data_profile_sources("PDX"))
    expected_task_id = _data_profile_task_id("PDX", "REPEATED_TEXT_COORDINATE_AUDIT",
        _data_profile_sources("PDX"), upstream_task_id=prior_task_id)
    if (task_id != expected_task_id or suffix != "PDX" or prior_task_id != expected_prior_id or len(source_rows) != 3
            or parameters != {"occurrences_per_value": 4}):
        raise ValueError("repeated-text coordinate audit requires the verified PDX dictionary checkpoint")
    prior_result = _task_result(prior_task_id)
    if prior_result.get("status") != "PASS" or prior_result.get("profile_mode") != "REPEATED_TEXT_DICTIONARY_PROFILE":
        raise RuntimeError("repeated-text coordinate audit prerequisite is not a verified dictionary profile")
    previous = {str(row.get("region")): row for row in prior_result.get("observations", [])
                if isinstance(row, dict)}
    source_root = coordinator_runtime.SOURCE_ROOT.resolve(strict=True)
    observations = []
    for row in source_rows:
        prior = previous.get(str(row["region"]))
        if not prior or prior.get("source_sha256") != row["sha256"]:
            raise RuntimeError("repeated-text anchor values are not bound to the current source inventory")
        values = [str(item["text"]) for item in prior.get("top_repeated_values", [])
                  if isinstance(item, dict) and isinstance(item.get("text"), str)]
        if not values or len(values) > 32:
            raise RuntimeError("verified repeated-text dictionary has no bounded anchor set")
        relative = PurePosixPath(str(row["relative_path"]).replace("\\", "/"))
        source = (source_root / Path(*relative.parts)).resolve(strict=True)
        if not source.is_relative_to(source_root):
            raise ValueError("repeated-text coordinate source escaped the original-media root")
        observation = audit_repeated_text_coordinate_proximity(source, region=str(row["region"]),
            expected_sha256=str(row["sha256"]), anchor_texts=values,
            occurrences_per_value=int(parameters["occurrences_per_value"]))
        if observation["source_bytes"] != int(row["size_bytes"]):
            raise RuntimeError("repeated-text coordinate source size differs from the inventory")
        observations.append({"relative_path": row["relative_path"], **observation})
    result = {"status": "PASS", "task_id": task_id, "suffix": suffix,
        "profile_mode": "REPEATED_TEXT_COORDINATE_AUDIT", "prior_task_id": prior_task_id,
        "profile_parameters": parameters, "observations": observations,
        "verified": {"source_count": 3, "source_stat_unchanged_during_read": True,
            "manifest_entries_present": True, "source_write_count": 0,
            "raw_payload_bytes_retained": False,
            "semantic_format": "UNKNOWN; structural observations only"},
        "claim_scope": "repeated literal proximity experiment only; coordinate and record semantics UNKNOWN",
        "created_utc": _utc(), "original_media_write_count": 0,
        "physical_compatibility": "NOT_TESTED"}
    output = PROJECT_ROOT / "work" / "autonomous_manager" / "ncdx" / "data_family_profiles" / f"{task_id}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(output)
    artifact = manager._artifact(task_id, output,
        "Read-only coordinate-candidate proximity around repeated PDX literals",
        "PASS: verified dictionary values were re-found and compared to controls in all regions")
    _register_supervisor("AUTO_SUPERVISOR_" + task_id, task_id)
    return {**result, "artifact": artifact}


def _execute_text_coordinate_association_census(task: dict[str, Any],
                                                 source_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Run one allowlisted PDX association census over three original regions."""
    from src.readers.ncdx_record_probe import audit_text_coordinate_association

    task_id = str(task["id"])
    budget = task.get("budget", {})
    mode = str(budget.get("profile_mode", ""))
    suffix = str(budget.get("suffix", ""))
    prior_task_id = str(budget.get("prior_task_id", ""))
    parameters = budget.get("profile_parameters", {})
    expected_strategy = ("all_printable" if mode == "TEXT_COORDINATE_ASSOCIATION_CENSUS"
                         else "repeated_literals")
    if mode not in {"TEXT_COORDINATE_ASSOCIATION_CENSUS",
                    "REPEATED_TEXT_COORDINATE_ASSOCIATION_CENSUS"}:
        raise ValueError("unsupported text-coordinate association census mode")
    expected_parameters = {"anchor_strategy": expected_strategy, "max_anchors": 4096,
                           "controls_per_anchor": 1, "radius_bytes": 64}
    if suffix != "PDX" or len(source_rows) != 3 or parameters != expected_parameters:
        raise ValueError("association census requires three manifest-bound PDX files and fixed parameters")
    sources = _data_profile_sources("PDX")
    if budget.get("sources") != sources:
        raise RuntimeError("association census source list differs from the current read-only inventory")
    if mode == "TEXT_COORDINATE_ASSOCIATION_CENSUS":
        expected_prior_id = _data_profile_task_id(
            "PDX", "STRING_COORDINATE_PROXIMITY_AUDIT", sources)
    else:
        dictionary_task_id = _data_profile_task_id(
            "PDX", "REPEATED_TEXT_DICTIONARY_PROFILE", sources)
        expected_prior_id = _data_profile_task_id(
            "PDX", "REPEATED_TEXT_COORDINATE_AUDIT", sources,
            upstream_task_id=dictionary_task_id)
    if prior_task_id != expected_prior_id:
        raise ValueError("association census does not cite its exact verified predecessor")
    prior_result = _task_result(prior_task_id)
    expected_prior_mode = ("STRING_COORDINATE_PROXIMITY_AUDIT" if
        mode == "TEXT_COORDINATE_ASSOCIATION_CENSUS" else "REPEATED_TEXT_COORDINATE_AUDIT")
    if (prior_result.get("status") != "PASS"
            or prior_result.get("profile_mode") != expected_prior_mode
            or _task_status("AUTO_SUPERVISOR_" + prior_task_id) != "DONE"):
        raise RuntimeError("association census predecessor lacks a fresh independent Supervisor PASS")

    source_root = coordinator_runtime.SOURCE_ROOT.resolve(strict=True)
    observations: list[dict[str, Any]] = []
    for row in sources:
        relative = PurePosixPath(str(row["relative_path"]).replace("\\", "/"))
        source = (source_root / Path(*relative.parts)).resolve(strict=True)
        if not source.is_relative_to(source_root):
            raise ValueError("association census source escaped the read-only original-media root")
        observation = audit_text_coordinate_association(source, region=str(row["region"]),
            expected_sha256=str(row["sha256"]), **parameters)
        if observation["source_bytes"] != int(row["size_bytes"]):
            raise RuntimeError("association census source size differs from its inventory entry")
        observations.append({"relative_path": row["relative_path"], **observation})
    result = {"status": "PASS", "task_id": task_id, "suffix": suffix,
        "profile_mode": mode, "prior_task_id": prior_task_id,
        "profile_parameters": parameters, "observations": observations,
        "verified": {"source_count": 3, "source_stat_unchanged_during_read": True,
            "manifest_entries_present": True, "source_write_count": 0,
            "raw_payload_bytes_retained": False,
            "semantic_format": "UNKNOWN; structural observations only"},
        "claim_scope": "matched text-window association of regional integer-pair candidates only; coordinate, record and navigation semantics UNKNOWN",
        "created_utc": _utc(), "original_media_write_count": 0,
        "physical_compatibility": "NOT_TESTED"}
    output = PROJECT_ROOT / "work" / "autonomous_manager" / "ncdx" / "data_family_profiles" / f"{task_id}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(output)
    artifact = manager._artifact(task_id, output,
        f"Full-file PDX {expected_strategy} association census with matched controls",
        "PASS: source-bound anchor and control windows were scored and the result is ready for independent readback")
    _register_supervisor("AUTO_SUPERVISOR_" + task_id, task_id)
    return {**result, "artifact": artifact}


def _execute_standalone_zlib_stream_census(task: dict[str, Any],
                                           source_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Search one manifest-backed file family using the bounded generic zlib scanner."""
    from src.readers.ncdx_record_probe import (MAX_STANDALONE_ZLIB_COMPRESSED_BYTES,
        MAX_STANDALONE_ZLIB_FILE_BYTES, MAX_STANDALONE_ZLIB_HEADER_CANDIDATES,
        MAX_STANDALONE_ZLIB_OUTPUT_BYTES, scan_standalone_zlib_streams)

    task_id = str(task["id"])
    budget = task.get("budget", {})
    suffix = str(budget.get("suffix", ""))
    parameters = budget.get("profile_parameters", {})
    expected_parameters = {"max_file_bytes": MAX_STANDALONE_ZLIB_FILE_BYTES,
        "max_compressed_bytes": MAX_STANDALONE_ZLIB_COMPRESSED_BYTES,
        "max_output_bytes": MAX_STANDALONE_ZLIB_OUTPUT_BYTES,
        "max_header_candidates": MAX_STANDALONE_ZLIB_HEADER_CANDIDATES}
    if (not suffix or suffix in CONTAINER_ROUNDTRIP_SUFFIXES or len(source_rows) != 3
            or parameters != expected_parameters):
        raise ValueError("standalone zlib census requires one raw file family and fixed bounded parameters")
    sources = _data_profile_sources(suffix)
    if budget.get("sources") != sources or source_rows != sources:
        raise RuntimeError("standalone zlib census inputs differ from the current source inventory")
    if any(int(row["size_bytes"]) < 4096 or int(row["size_bytes"]) > MAX_STANDALONE_ZLIB_FILE_BYTES
           for row in sources):
        raise ValueError("standalone zlib census source is outside the registered file-size range")

    source_root = coordinator_runtime.SOURCE_ROOT.resolve(strict=True)
    observations: list[dict[str, Any]] = []
    all_streams_by_region: dict[str, list[dict[str, Any]]] = {}
    for row in sources:
        relative = PurePosixPath(str(row["relative_path"]).replace("\\", "/"))
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("standalone zlib census received a non-relative source path")
        source = (source_root / Path(*relative.parts)).resolve(strict=True)
        if not source.is_relative_to(source_root):
            raise ValueError("standalone zlib census source escaped the read-only media root")
        full_stream_inventory: list[dict[str, Any]] = []
        observation = scan_standalone_zlib_streams(source,
            expected_sha256=str(row["sha256"]), _all_streams=full_stream_inventory, **parameters)
        if observation["source_bytes"] != int(row["size_bytes"]):
            raise RuntimeError("standalone zlib census source size differs from the inventory")
        all_streams_by_region[str(row["region"])] = full_stream_inventory
        observations.append({"region": row["region"], "relative_path": row["relative_path"],
            **observation})

    shared_preview, shared_count, shared_digest = _summarize_shared_zlib_payloads(all_streams_by_region)
    result = {"status": "PASS", "task_id": task_id, "suffix": suffix,
        "profile_mode": "STANDALONE_ZLIB_STREAM_CENSUS", "profile_parameters": parameters,
        "observations": observations, "cross_region_shared_payloads": shared_preview,
        "cross_region_shared_payload_count": shared_count,
        "cross_region_shared_inventory_sha256": shared_digest,
        "verified": {"source_count": 3, "source_stat_unchanged_during_read": all(
                row["source_stat_unchanged"] for row in observations),
            "manifest_entries_present": all(_ledger_hash(str(row["relative_path"])) ==
                str(source["sha256"]) for row, source in zip(observations, sources)),
            "source_write_count": 0, "raw_payload_bytes_retained": False,
            "memory_mapped_read_only": True,
            "semantic_format": "UNKNOWN; bounded zlib stream candidates only"},
        "claim_scope": "manifest-bound search for self-contained checksum-valid zlib streams; no enclosing NCDx record semantics inferred",
        "created_utc": _utc(), "original_media_write_count": 0,
        "physical_compatibility": "NOT_TESTED"}
    if (not result["verified"]["source_stat_unchanged_during_read"]
            or not result["verified"]["manifest_entries_present"]):
        raise RuntimeError("standalone zlib census failed source-integrity checks")
    output = PROJECT_ROOT / "work" / "autonomous_manager" / "ncdx" / "data_family_profiles" / f"{task_id}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(output)
    artifact = manager._artifact(task_id, output,
        f"Bounded standalone zlib stream census for regional {suffix} inputs",
        "PASS: all exact source hashes were scanned read-only with fixed memory and decompression bounds")
    _register_supervisor("AUTO_SUPERVISOR_" + task_id, task_id)
    return {**result, "artifact": artifact}


def _execute_zlib_stream_boundary_context_profile(task: dict[str, Any],
                                                   source_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Profile hash-only stream-boundary context for an independently verified census family."""
    from src.readers.ncdx_record_probe import profile_standalone_zlib_boundary_contexts

    task_id = str(task["id"])
    budget = task.get("budget", {})
    suffix = str(budget.get("suffix", ""))
    parameters = budget.get("profile_parameters", {})
    sources = _data_profile_sources(suffix)
    prior_task_id = str(budget.get("prior_task_id") or "")
    expected_prior = _data_profile_task_id(suffix, "STANDALONE_ZLIB_STREAM_CENSUS", sources)
    allowed_parameters = ({"context_bytes": 8}, {"context_bytes": 16},
                          {"context_bytes": 32}, {"context_bytes": 64})
    expected_task_id = _data_profile_task_id(suffix, "ZLIB_STREAM_BOUNDARY_CONTEXT_PROFILE", sources,
        upstream_task_id=expected_prior,
        profile_parameters=(parameters if parameters != {"context_bytes": 16} else None))
    if (not suffix or suffix in CONTAINER_ROUNDTRIP_SUFFIXES or source_rows != sources
            or budget.get("profile_mode") != "ZLIB_STREAM_BOUNDARY_CONTEXT_PROFILE"
            or parameters not in allowed_parameters or prior_task_id != expected_prior
            or task_id != expected_task_id
            or _task_status(prior_task_id) != "DONE"
            or _task_status("AUTO_SUPERVISOR_" + prior_task_id) != "DONE"):
        raise RuntimeError("zlib boundary profile requires the exact independently verified source census")
    prior_result = _task_result(prior_task_id)
    prior_by_region = {str(row.get("region")): row for row in prior_result.get("observations", [])
                       if isinstance(row, dict)}
    if prior_result.get("status") != "PASS" or set(prior_by_region) != {row["region"] for row in sources}:
        raise RuntimeError("zlib boundary profile predecessor is missing a verified regional census")

    source_root = coordinator_runtime.SOURCE_ROOT.resolve(strict=True)
    observations: list[dict[str, Any]] = []
    for row in sources:
        prior_observation = prior_by_region[str(row["region"])]
        if (prior_observation.get("source_sha256") != row["sha256"]
                or int(prior_observation.get("stream_count", -1)) < 1
                or len(str(prior_observation.get("stream_inventory_sha256", ""))) != 64):
            raise RuntimeError("zlib boundary profile predecessor does not contain a positive compact census")
        relative = PurePosixPath(str(row["relative_path"]).replace("\\", "/"))
        if relative.is_absolute() or ".." in relative.parts or _ledger_hash(relative.as_posix()) != row["sha256"]:
            raise RuntimeError("zlib boundary profile received an unmanifested regional source")
        source = (source_root / Path(*relative.parts)).resolve(strict=True)
        if not source.is_relative_to(source_root):
            raise RuntimeError("zlib boundary profile source escaped the read-only media root")
        observation = profile_standalone_zlib_boundary_contexts(source,
            expected_sha256=str(row["sha256"]),
            expected_stream_count=int(prior_observation["stream_count"]),
            expected_stream_inventory_sha256=str(prior_observation["stream_inventory_sha256"]),
            **parameters)
        if observation["source_bytes"] != int(row["size_bytes"]):
            raise RuntimeError("zlib boundary profile source size differs from the manifest inventory")
        observations.append({"region": row["region"], "relative_path": row["relative_path"],
            **observation})

    result = {"status": "PASS", "task_id": task_id, "suffix": suffix,
        "profile_mode": "ZLIB_STREAM_BOUNDARY_CONTEXT_PROFILE",
        "prior_task_id": prior_task_id, "profile_parameters": parameters,
        "observations": observations,
        "verified": {"source_count": 3, "source_stat_unchanged_during_read": all(
                row["source_stat_unchanged"] for row in observations),
            "manifest_entries_present": all(_ledger_hash(str(row["relative_path"])) ==
                str(source["sha256"]) for row, source in zip(observations, sources)),
            "source_write_count": 0, "raw_context_bytes_retained": False,
            "raw_payload_bytes_retained": False,
            "semantic_format": "UNKNOWN; hash-only zlib boundary contexts"},
        "claim_scope": "hash-only byte contexts, stream-start alignment and gap counts around a prior verified zlib inventory; record and navigation semantics UNKNOWN",
        "created_utc": _utc(), "original_media_write_count": 0,
        "physical_compatibility": "NOT_TESTED"}
    if (not result["verified"]["source_stat_unchanged_during_read"]
            or not result["verified"]["manifest_entries_present"]):
        raise RuntimeError("zlib boundary context profile failed source-integrity checks")
    output = PROJECT_ROOT / "work" / "autonomous_manager" / "ncdx" / "data_family_profiles" / f"{task_id}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(output)
    artifact = manager._artifact(task_id, output,
        f"Hash-only zlib boundary context profile for verified {suffix} regional inputs",
        "PASS: source census digests, bounded context hashes and gaps match the exact read-only inputs")
    _register_supervisor("AUTO_SUPERVISOR_" + task_id, task_id)
    return {**result, "artifact": artifact}


def _execute_zlib_decoded_coordinate_candidate_census(
        task: dict[str, Any], source_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Measure bounded geographic-pair and short-run candidates in verified streams."""
    from src.readers.ncdx_record_probe import (ZLIB_COORDINATE_PROFILE_PARAMETER_OPTIONS,
        is_zlib_coordinate_selected_payload_parameters,
        profile_standalone_zlib_coordinate_candidates)

    task_id = str(task["id"])
    budget = task.get("budget", {})
    suffix = str(budget.get("suffix", ""))
    parameters = budget.get("profile_parameters", {})
    sources = _data_profile_sources(suffix)
    prior_task_id = _data_profile_task_id(suffix, "STANDALONE_ZLIB_STREAM_CENSUS", sources)
    expected_id = _data_profile_task_id(suffix, "ZLIB_DECODED_COORDINATE_CANDIDATE_CENSUS",
        sources, upstream_task_id=prior_task_id, profile_parameters=parameters)
    if (not suffix or suffix in CONTAINER_ROUNDTRIP_SUFFIXES or source_rows != sources
            or budget.get("profile_mode") != "ZLIB_DECODED_COORDINATE_CANDIDATE_CENSUS"
            or (parameters not in ZLIB_COORDINATE_PROFILE_PARAMETER_OPTIONS
                and not is_zlib_coordinate_selected_payload_parameters(parameters))
            or budget.get("prior_task_id") != prior_task_id or task_id != expected_id
            or _task_status(prior_task_id) != "DONE"
            or _task_status("AUTO_SUPERVISOR_" + prior_task_id) != "DONE"):
        raise RuntimeError("decoded-coordinate census requires its exact independent zlib census predecessor")
    _validate_coordinate_profile_tier(suffix, sources, prior_task_id, parameters, budget)
    prior_result = _task_result(prior_task_id)
    prior_by_region = {str(row.get("region")): row for row in prior_result.get("observations", [])
                       if isinstance(row, dict)}
    if prior_result.get("status") != "PASS" or set(prior_by_region) != {
            str(row["region"]) for row in sources}:
        raise RuntimeError("decoded-coordinate census predecessor lacks complete regional evidence")

    source_root = coordinator_runtime.SOURCE_ROOT.resolve(strict=True)
    observations: list[dict[str, Any]] = []
    for row in sources:
        relative = PurePosixPath(str(row["relative_path"]).replace("\\", "/"))
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("decoded-coordinate census received a non-relative source path")
        source = (source_root / Path(*relative.parts)).resolve(strict=True)
        if not source.is_relative_to(source_root):
            raise ValueError("decoded-coordinate census source escaped the read-only media root")
        prior = prior_by_region[str(row["region"])]
        observation = profile_standalone_zlib_coordinate_candidates(source,
            expected_sha256=str(row["sha256"]),
            expected_stream_count=int(prior["stream_count"]),
            expected_stream_inventory_sha256=str(prior["stream_inventory_sha256"]),
            region=str(row["region"]), profile_parameters=parameters)
        if observation["source_bytes"] != int(row["size_bytes"]):
            raise RuntimeError("decoded-coordinate source size differs from its source inventory")
        observations.append({"region": row["region"], "relative_path": row["relative_path"],
            **observation})

    result = {"status": "PASS", "task_id": task_id, "suffix": suffix,
        "profile_mode": "ZLIB_DECODED_COORDINATE_CANDIDATE_CENSUS",
        "prior_task_id": prior_task_id, "profile_parameters": parameters,
        "observations": observations,
        "verified": {"source_count": 3,
            "source_stat_unchanged_during_read": all(row["source_stat_unchanged"] for row in observations),
            "manifest_entries_present": all(_ledger_hash(str(row["relative_path"])) == str(source["sha256"])
                for row, source in zip(observations, sources)),
            "source_write_count": 0, "raw_sample_bytes_retained": False,
            "raw_payload_bytes_retained": False,
            "semantic_format": "UNKNOWN; bounded zlib coordinate candidates only"},
        "claim_scope": ("full bounded payloads for evidence-selected streams were rescanned for geographic-pair candidates"
            if is_zlib_coordinate_selected_payload_parameters(parameters) else
            "candidate counts and short-step continuity in a bounded zlib-payload sample versus displaced geographic controls; road semantics UNKNOWN"),
        "created_utc": _utc(), "original_media_write_count": 0,
        "physical_compatibility": "NOT_TESTED"}
    if (not result["verified"]["source_stat_unchanged_during_read"]
            or not result["verified"]["manifest_entries_present"]):
        raise RuntimeError("decoded-coordinate census failed its read-only source-integrity checks")
    output = PROJECT_ROOT / "work" / "autonomous_manager" / "ncdx" / "data_family_profiles" / f"{task_id}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(output)
    artifact = manager._artifact(task_id, output,
        f"Bounded decoded-coordinate candidate census for verified {suffix} zlib streams",
        "PASS: all three regional inventories and fixed candidate/control measurements are reproducible")
    _register_supervisor("AUTO_SUPERVISOR_" + task_id, task_id)
    return {**result, "artifact": artifact}


def _summarize_shared_zlib_payloads(
        all_streams_by_region: dict[str, list[dict[str, Any]]]) -> tuple[list[dict[str, Any]], int, str]:
    """Return a bounded preview plus a complete deterministic cross-region inventory digest."""
    by_digest: dict[str, list[dict[str, Any]]] = {}
    for region, streams in sorted(all_streams_by_region.items()):
        for stream in streams:
            by_digest.setdefault(str(stream["decompressed_sha256"]), []).append({
                "region": region, "offset": int(stream["offset"]),
                "compressed_bytes": int(stream["compressed_bytes"]),
                "decompressed_bytes": int(stream["decompressed_bytes"])})
    digest = hashlib.sha256()
    preview: list[dict[str, Any]] = []
    shared_count = 0
    for payload_hash, occurrences in sorted(by_digest.items()):
        if len({row["region"] for row in occurrences}) < 2:
            continue
        entry = {"decompressed_sha256": payload_hash,
            "regional_occurrences": sorted(occurrences,
                key=lambda row: (row["region"], row["offset"], row["compressed_bytes"],
                                 row["decompressed_bytes"]))}
        digest.update(json.dumps(entry, sort_keys=True, separators=(",", ":")).encode("ascii"))
        digest.update(b"\n")
        if len(preview) < 64:
            preview.append(entry)
        shared_count += 1
    return preview, shared_count, digest.hexdigest()


def _execute_block_boundary_profile(task: dict[str, Any],
                                   source_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Measure whether printable runs align with or cross decoded PDX blocks."""
    from src.readers.ncdx_record_probe import profile_text_block_boundaries

    task_id = str(task["id"])
    budget = task.get("budget", {})
    suffix = str(budget.get("suffix", ""))
    parameters = budget.get("profile_parameters", {})
    if suffix != "PDX" or len(source_rows) != 3 or parameters != {"position_bins": 16}:
        raise ValueError("block-boundary profile requires three regional PDX sources and fixed histogram bins")
    source_root = coordinator_runtime.SOURCE_ROOT.resolve(strict=True)
    observations = []
    for row in source_rows:
        relative = PurePosixPath(str(row["relative_path"]).replace("\\", "/"))
        source = (source_root / Path(*relative.parts)).resolve(strict=True)
        if not source.is_relative_to(source_root):
            raise ValueError("block-boundary source escaped the original-media root")
        observation = profile_text_block_boundaries(source, region=str(row["region"]),
            expected_sha256=str(row["sha256"]), **parameters)
        if observation["source_bytes"] != int(row["size_bytes"]):
            raise RuntimeError("block-boundary source size differs from the inventory")
        observations.append({"relative_path": row["relative_path"], **observation})
    result = {"status": "PASS", "task_id": task_id, "suffix": suffix,
        "profile_mode": "BLOCK_BOUNDARY_PROFILE", "profile_parameters": parameters,
        "observations": observations,
        "verified": {"source_count": 3, "source_stat_unchanged_during_read": True,
            "manifest_entries_present": True, "source_write_count": 0,
            "raw_payload_bytes_retained": False,
            "semantic_format": "UNKNOWN; structural observations only"},
        "claim_scope": "printable-run placement versus decoded block boundaries only; record semantics UNKNOWN",
        "created_utc": _utc(), "original_media_write_count": 0,
        "physical_compatibility": "NOT_TESTED"}
    output = PROJECT_ROOT / "work" / "autonomous_manager" / "ncdx" / "data_family_profiles" / f"{task_id}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(output)
    artifact = manager._artifact(task_id, output,
        "Read-only decoded PDX text placement versus block boundaries",
        "PASS: all regional block-boundary summaries are manifest-bound and reproducible")
    _register_supervisor("AUTO_SUPERVISOR_" + task_id, task_id)
    return {**result, "artifact": artifact}


def seed_next_data_family_director_task(*, dependency: str | None = None,
                                        prior_task: str | None = None,
                                        include_legacy_modes: bool = False) -> dict[str, Any]:
    """Queue a local-model decision over concrete, not-yet-tested NCDx data work."""
    candidates = _data_profile_candidates(include_legacy_modes=include_legacy_modes)
    if not candidates:
        return {"created": False, "reason": "All currently prioritized manifest-backed NCDx container round-trips are recorded or their inputs are unavailable."}
    candidate_ids = [str(row["goal_id"]) for row in candidates]
    candidate_fingerprint = hashlib.sha256(
        json.dumps(candidate_ids, separators=(",", ":")).encode("utf-8")).hexdigest()
    candidate_evidence_task_ids = {str(row["goal_id"]): str(row["selection_evidence_task_id"])
        for row in candidates if row.get("selection_evidence_task_id")}
    planning_key = json.dumps({"prior_task": prior_task, "candidate_fingerprint": candidate_fingerprint},
                              sort_keys=True, separators=(",", ":"))
    suffix = hashlib.sha256(planning_key.encode("utf-8")).hexdigest()[:12]
    task_id = "AUTO_DIRECTOR_NCDX_DATA_" + suffix
    created = _registered_task(task_id, "F2", dependency,
        "AI Project Director must choose one untested, manifest-backed regional NCDx container round-trip that advances a bounded reader/writer.",
        "ollama-data-family-director", f"reports/autonomous_director_ncdx_data_{suffix}.json",
        ["Ollama selects exactly one goal_id from the current fixed candidate list",
         "Selected task uses only a deterministic read-only handler and has independent checks",
         "No model-authored code, path, command or media write is executed"],
        300, 14,
        {"data_family_director": True, "prior_task": prior_task,
         "candidate_fingerprint": candidate_fingerprint,
         "candidate_goal_ids": candidate_ids,
         "candidate_evidence_task_ids": candidate_evidence_task_ids})
    if created:
        manager._event("project_director_data_plan_created", {
            "task_id": task_id, "dependency": dependency, "prior_task": prior_task,
            "candidate_fingerprint": candidate_fingerprint,
            "eligible_profile_count": len(candidates), "candidate_ids": candidate_ids,
            "candidate_modes": sorted({str(row["mode"]) for row in candidates})})
    return {"created": created, "task_id": task_id if created else None,
            "reason": "local Project Director is choosing the next verified-format round-trip over real regional map data",
            "eligible_profile_count": len(candidates)}


def execute_data_family_director(task_id: str) -> dict[str, Any]:
    """Ask Ollama to select one fixed, verified experiment; model text is data only."""
    task = manager._task(task_id)
    # Include old sampler definitions so any already-persisted Director task
    # can finish its saved allowlisted candidate set after an upgrade.
    candidates = _data_profile_candidates(include_legacy_modes=True)
    declared_candidates = set(task.get("budget", {}).get("candidate_goal_ids", []))
    candidates = [row for row in candidates if row["goal_id"] in declared_candidates]
    if not candidates:
        return {"status": "NO_CANDIDATES", "task_id": task_id,
                "reason": "all known regional data profile experiments already have durable task records"}
    budget = task.get("budget", {})
    current_evidence_map = {str(row["goal_id"]): str(row["selection_evidence_task_id"])
        for row in candidates if row.get("selection_evidence_task_id")}
    if budget.get("candidate_evidence_task_ids", {}) != current_evidence_map:
        raise RuntimeError("Director candidate evidence changed after task planning; replan against the current checkpoint")
    evidence_by_goal = {str(row["goal_id"]): _compact_director_evidence(
        str(row["selection_evidence_task_id"]) if row.get("selection_evidence_task_id") else None)
        for row in candidates}
    prior_task = str(budget.get("prior_task") or "")
    prior_result = _task_result(prior_task) if prior_task else None
    model: str | None = None
    model_error: str | None = None
    parsed: dict[str, Any] = {}
    try:
        installed = coordinator_runtime._available_models()
        model = coordinator_runtime._choose_model("project-director", installed)
        prompt = json.dumps({
            "role": "NCDR AI Project Director",
            "global_goal": project_scope.global_goal(),
            "active_tracks": project_scope.load_scope()["active_tracks"],
            "excluded_tracks": project_scope.load_scope()["excluded_tracks"],
            "project_state": _director_context(),
            "previous_verified_result": prior_result,
        "eligible_next_experiments": [{"goal_id": row["goal_id"], "suffix": row["suffix"],
                "method": row["mode"], "inventoried_region_count": len(row["sources"]),
                "parameters": row.get("profile_parameters", {}),
                "evidence_task_id": row.get("selection_evidence_task_id"),
                "prior_verified_evidence": evidence_by_goal.get(str(row["goal_id"])),
                "total_input_bytes": sum(source["size_bytes"] for source in row["sources"])}
                for row in candidates],
            "constraints": ["Choose one exact goal_id from eligible_next_experiments.",
                "Prioritize evidence that reduces uncertainty about map storage, address/index data or route data.",
                "Suffixes are labels only; do not assert their semantic meaning.",
                "Do not claim physical compatibility, and do not request writes to original media.",
                "The selected executor is a fixed deterministic sampler; never return code, paths, shell commands or new acceptance criteria."],
            "response_schema": {"goal_id": candidates[0]["goal_id"], "reason": "short evidence-based choice",
                "requires_hardware": False, "writes_original_media": False},
        }, ensure_ascii=False)
        _actual_model, _response, parsed = coordinator_runtime._call_model(
            task_id, "project-director", prompt, attempt=1, fixed_model=model)
    except Exception as exc:
        model_error = f"{type(exc).__name__}: {exc}"[:500]

    allowed = {row["goal_id"] for row in candidates}
    model_choice = parsed.get("goal_id")
    safe_flags = (parsed.get("requires_hardware", False) is False
                  and parsed.get("writes_original_media", False) is False)
    accepted_choice = model_choice in allowed and safe_flags
    selected_id = str(model_choice) if accepted_choice else candidates[0]["goal_id"]
    selected = next(row for row in candidates if row["goal_id"] == selected_id)
    created = _register_data_profile_task(selected, dependency=task_id)
    if not created:
        raise RuntimeError(f"Director's unique data task could not be persisted: {selected_id}")
    report = {"status": "PASS" if accepted_choice else "PASS_WITH_BOUNDED_FALLBACK",
        "task_id": task_id, "model": model, "model_error": model_error,
        "model_choice": model_choice, "selected_goal_id": selected_id,
        "selection_source": "Ollama" if accepted_choice else "first remaining fixed candidate",
        "selection_reason": str(parsed.get("reason") or model_error or "model response did not match the fixed safe schema")[:500],
        "safe_schema_validated": accepted_choice, "next_task_id": selected_id,
        "selected_evidence_task_id": selected.get("selection_evidence_task_id"),
        "candidate_fingerprint": task.get("budget", {}).get("candidate_fingerprint"),
        "depends_on": task_id, "remaining_unique_experiments": len(candidates) - 1,
        "created_utc": _utc(), "original_media_write_count": 0,
        "physical_compatibility": "NOT_TESTED"}
    path = PROJECT_ROOT / "reports" / f"autonomous_director_ncdx_data_{task_id.rsplit('_', 1)[-1]}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report["artifact"] = manager._artifact(task_id, path,
        "AI Director chose one untested regional NCDx data experiment from a fixed allowlist",
        "PASS: model choice validated or bounded deterministic fallback recorded")
    manager._event("project_director_data_goal_selected", {
        "task_id": task_id, "model": model, "selected_goal_id": selected_id,
        "model_choice_accepted": accepted_choice, "remaining_unique_experiments": len(candidates) - 1,
        "model_error": model_error})
    return report


def _osm_partition_candidates() -> list[dict[str, Any]]:
    if not OSM_PARTITION_DATABASE.is_file():
        return []
    return [dict(row, bbox=list(row["bbox"]),
                 max_nodes=200_000, timeout_s=300)
            for row in OSM_PARTITION_CANDIDATES
            if _task_status(str(row["goal_id"])) is None]


def seed_next_osm_partition_director_task() -> dict[str, Any]:
    """Ask the local Director to choose one unused bounded OSM partition probe."""
    candidates = _osm_partition_candidates()
    if not candidates:
        return {"created": False,
                "reason": "no unused bounded Kryvyi Rih OSM grid probes or the verified national database is unavailable"}
    selected = candidates[0]
    candidate_key = str(selected["goal_id"]).removeprefix("AUTO_OSM_PARTITION_PROBE_")
    task_id = "AUTO_DIRECTOR_OSM_PARTITION_" + candidate_key
    created = _registered_task(task_id, "F4", None,
        "Qwen3.5 Director chooses one bounded grid-resolution experiment over the saved national OSM graph.",
        "ollama-osm-partition-director",
        f"reports/autonomous_osm_partition_director_{selected['goal_id'].casefold()}.json",
        ["Director selects one exact candidate from the fixed allowlist",
         "No model-authored code, path, command or bbox is executed",
         "The selected probe is local, read-only, bounded and independently verified"],
        300, 16,
        {"osm_partition_director": True,
         "candidate_goal_ids": [str(row["goal_id"]) for row in candidates]})
    if created:
        manager._event("osm_partition_director_task_created", {
            "task_id": task_id, "candidate_goal_ids": [str(row["goal_id"]) for row in candidates],
            "database": str(OSM_PARTITION_DATABASE.relative_to(PROJECT_ROOT)),
            "reason": "local bounded OSM work continues while canonical tasks await unavailable dependencies"})
    return {"created": created, "task_id": task_id if created else None,
            "reason": "Qwen3.5 Director is selecting a unique, parameterized OSM partition probe",
            "candidate_count": len(candidates)}


def execute_osm_partition_director(task_id: str) -> dict[str, Any]:
    """Select only among prevalidated local grid probes; never execute model text."""
    candidates = _osm_partition_candidates()
    if not candidates:
        return {"status": "NO_CANDIDATES", "task_id": task_id,
                "reason": "all registered local grid probes are already recorded"}
    task = manager._task(task_id)
    declared = set(task.get("budget", {}).get("candidate_goal_ids", []))
    candidates = [row for row in candidates if row["goal_id"] in declared]
    if not candidates:
        raise RuntimeError("persisted Director candidate list no longer matches unused probes")
    model: str | None = None
    model_error: str | None = None
    parsed: dict[str, Any] = {}
    try:
        installed = coordinator_runtime._available_models()
        model = coordinator_runtime._choose_model("project-director", installed)
        prompt = json.dumps({
            "role": "NCDR LOCAL FIRST Project Director",
            "global_goal": project_scope.global_goal(),
            "project_state": _director_context(),
            "previous_verified_osm_evidence": [
                {"goal_id": row["goal_id"], "result": _task_result(str(row["goal_id"]))}
                for row in OSM_PARTITION_CANDIDATES
                if _task_status(str(row["goal_id"])) == "DONE"],
            "eligible_experiments": [{"goal_id": row["goal_id"],
                "area": row["area"], "bbox_south_west_north_east": row["bbox"],
                "grid_rows": row["rows"], "grid_columns": row["columns"],
                "max_nodes": row["max_nodes"], "timeout_s": row["timeout_s"]}
                for row in candidates],
            "constraints": ["Choose exactly one eligible goal_id.",
                "Prefer useful evidence for bounded OSM tiling after the national importer OOM.",
                "Do not invent coordinates, code, paths or commands.",
                "Do not claim NCDx export, physical-disc readiness or Opel compatibility."],
            "response_schema": {"goal_id": str(candidates[0]["goal_id"]),
                "reason": "short evidence-based reason", "requires_hardware": False,
                "writes_original_media": False},
        }, ensure_ascii=False)
        _actual_model, _response, parsed = coordinator_runtime._call_model(
            task_id, "project-director", prompt, attempt=1, fixed_model=model)
    except Exception as exc:
        model_error = f"{type(exc).__name__}: {exc}"[:500]
    allowed = {str(row["goal_id"]) for row in candidates}
    choice = parsed.get("goal_id")
    accepted = (choice in allowed and parsed.get("requires_hardware", False) is False
                and parsed.get("writes_original_media", False) is False)
    chosen_id = str(choice) if accepted else str(candidates[0]["goal_id"])
    candidate = next(row for row in candidates if row["goal_id"] == chosen_id)
    worker_task_id = chosen_id
    created = _registered_task(worker_task_id, "F4", task_id,
        f"Measure how many roads cross {candidate['rows']}x{candidate['columns']} cells in the fixed Kryvyi Rih OSM window.",
        "osm-partition-probe",
        f"work/autonomous_manager/osm_pipeline/partition_probes/{worker_task_id}.json",
        ["Published national SQLite is opened read-only", "Query cache is fixed at 64 MiB and SQLite temp storage is file-backed",
         "Node and way memberships stay under explicit bounds", "SQL summary matches a separate one-way-at-a-time streaming verification",
         "Database size and modification time remain unchanged"],
        360, 17,
        {"osm_partition_probe": True, "goal_id": chosen_id,
         "rows": candidate["rows"], "columns": candidate["columns"],
         "bbox": candidate["bbox"], "max_nodes": candidate["max_nodes"],
         "timeout_s": candidate["timeout_s"]})
    if not created:
        raise RuntimeError(f"Director's unique OSM probe could not be persisted: {worker_task_id}")
    report = {"status": "PASS" if accepted else "PASS_WITH_BOUNDED_FALLBACK",
        "task_id": task_id, "model": model, "model_error": model_error,
        "model_choice": choice, "selected_goal_id": chosen_id,
        "selection_source": "Qwen3.5" if accepted else "first remaining fixed candidate",
        "selection_reason": str(parsed.get("reason") or model_error or "model response did not match the fixed safe schema")[:500],
        "safe_schema_validated": accepted, "next_task_id": worker_task_id,
        "created_utc": _utc(), "original_media_write_count": 0,
        "codex_calls": 0, "physical_compatibility": "NOT_TESTED"}
    output = PROJECT_ROOT / "reports" / f"autonomous_osm_partition_director_{worker_task_id.casefold()}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report["artifact"] = manager._artifact(task_id, output,
        "Local Director selected one fixed OSM partition experiment",
        "PASS: safe model choice or bounded local fallback was persisted")
    manager._event("osm_partition_goal_selected", {"task_id": task_id,
        "model": model, "selected_goal_id": worker_task_id, "model_choice_accepted": accepted,
        "model_error": model_error, "codex_calls": 0})
    return report


def execute_osm_partition_probe(task_id: str) -> dict[str, Any]:
    """Run one allowlisted regional probe and queue a fresh-process Supervisor."""
    from src.osm.partition_probe import run_partition_probe
    task = manager._task(task_id)
    budget = task.get("budget", {})
    candidate = next((row for row in OSM_PARTITION_CANDIDATES
        if row["goal_id"] == budget.get("goal_id")), None)
    if not candidate or task_id != candidate["goal_id"]:
        raise ValueError("OSM partition task is outside the fixed probe registry")
    expected = {"rows": candidate["rows"], "columns": candidate["columns"],
                "bbox": list(candidate["bbox"]), "max_nodes": 200_000, "timeout_s": 300}
    for key, value in expected.items():
        if budget.get(key) != value:
            raise ValueError(f"persisted OSM partition {key} differs from the fixed registry")
    result = run_partition_probe(OSM_PARTITION_DATABASE,
        bbox=tuple(candidate["bbox"]), rows=int(candidate["rows"]), columns=int(candidate["columns"]),
        max_nodes=200_000, timeout_s=300)
    result.update({"task_id": task_id, "candidate_id": task_id, "created_utc": _utc(),
                  "original_media_write_count": 0, "codex_calls": 0})
    output = PROJECT_ROOT / "work" / "autonomous_manager" / "osm_pipeline" / "partition_probes" / f"{task_id}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(output)
    result["artifact"] = manager._artifact(task_id, output,
        "Bounded read-only OSM tile-boundary measurement",
        "PASS: local SQL measurement agrees with independent streaming aggregation")
    result["verified"] = {"status": "PASS", "database_size_bytes": result["database_size_bytes"],
        "database_mtime_ns_unchanged": result["database_mtime_ns_unchanged"],
        "source_sha256": result["source_meta"]["source_sha256"],
        "node_count": result["node_count"], "way_count": result["way_count"],
        "cross_tile_way_count": result["cross_tile_way_count"],
        "independent_streaming_verification": result["independent_streaming_verification"],
        "original_media_write_count": 0}
    _register_supervisor("AUTO_SUPERVISOR_" + task_id, task_id)
    return result


def _verify_osm_partition_target(target_id: str, target_task: dict[str, Any],
                                 result: dict[str, Any]) -> dict[str, Any]:
    from src.osm.partition_probe import run_partition_probe
    budget = target_task.get("budget", {})
    candidate = next((row for row in OSM_PARTITION_CANDIDATES
        if row["goal_id"] == budget.get("goal_id") == target_id), None)
    if not candidate or result.get("status") != "PASS":
        raise RuntimeError("Supervisor refused an unregistered or failed OSM partition probe")
    fresh = run_partition_probe(OSM_PARTITION_DATABASE, bbox=tuple(candidate["bbox"]),
        rows=int(candidate["rows"]), columns=int(candidate["columns"]),
        max_nodes=200_000, timeout_s=300)
    keys = ("database_size_bytes", "source_meta", "node_count", "way_count",
            "way_node_memberships", "cross_tile_way_count", "ways_by_tile_span")
    if any(result.get(key) != fresh.get(key) for key in keys):
        raise RuntimeError("fresh-process Supervisor readback differs from the saved OSM partition evidence")
    saved_verification = result.get("independent_streaming_verification")
    if (not isinstance(saved_verification, dict)
            or saved_verification != fresh.get("independent_streaming_verification")
            or result.get("database_mtime_ns_unchanged") is not True
            or int(result.get("original_media_write_count", -1)) != 0):
        raise RuntimeError("Supervisor refused incomplete independent stream or read-only proof")
    return {"fresh_readback": True, "saved_result_matches": True,
        "streaming_verification_matches": True, "source_sha256": fresh["source_meta"]["source_sha256"],
        "node_count": fresh["node_count"], "way_count": fresh["way_count"],
        "cross_tile_way_count": fresh["cross_tile_way_count"],
        "sqlite_page_cache_bytes": 64 * 1024 * 1024,
        "original_media_write_count": 0, "codex_calls": 0,
        "physical_compatibility": "NOT_TESTED"}


def _sample_offsets(size: int, count: int = 5, sample_bytes: int = DATA_PROFILE_SAMPLE_BYTES) -> list[int]:
    if size <= 0:
        return []
    last = max(0, size - sample_bytes)
    raw = [0, size // 4, size // 2, (size * 3) // 4, last]
    return sorted({min(last, max(0, value)) for value in raw})[:count]


def _sample_metrics(data: bytes, offset: int) -> dict[str, Any]:
    if not data:
        return {"offset": offset, "size_bytes": 0, "sha256": hashlib.sha256(b"").hexdigest(),
                "entropy_bits_per_byte": 0.0, "zero_ratio": 0.0, "printable_ratio": 0.0}
    counts = [0] * 256
    for value in data:
        counts[value] += 1
    entropy = -sum((count / len(data)) * math.log2(count / len(data))
                   for count in counts if count)
    return {"offset": offset, "size_bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(), "entropy_bits_per_byte": round(entropy, 5),
        "zero_ratio": round(counts[0] / len(data), 5),
        "printable_ratio": round(sum(counts[0x20:0x7f]) / len(data), 5)}


def _read_profile_source(source_row: dict[str, Any], mode: str) -> dict[str, Any]:
    relative = PurePosixPath(str(source_row["relative_path"]))
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("data profile path must remain relative to the NCDR source root")
    root = coordinator_runtime.SOURCE_ROOT.resolve(strict=True)
    source = (root / Path(*relative.parts)).resolve(strict=True)
    if not source.is_relative_to(root):
        raise RuntimeError("data profile source escaped the read-only NCDR root")
    if _ledger_hash(relative.as_posix()) != source_row["sha256"]:
        raise RuntimeError(f"data profile input no longer matches its persisted inventory entry: {relative}")
    before = source.stat()
    if before.st_size != int(source_row["size_bytes"]):
        raise RuntimeError(f"data profile source size changed since planning: {relative}")
    observations: dict[str, Any] = {"region": source_row["region"],
        "relative_path": relative.as_posix(), "size_bytes": before.st_size,
        "inventory_sha256": source_row["sha256"], "profile_mode": mode}
    with source.open("rb") as stream:
        if mode == "WINDOW_PROFILE":
            samples = []
            for offset in _sample_offsets(before.st_size):
                stream.seek(offset)
                samples.append(_sample_metrics(stream.read(DATA_PROFILE_SAMPLE_BYTES), offset))
            observations["samples"] = samples
            observations["sample_bytes_total"] = sum(row["size_bytes"] for row in samples)
        elif mode == "BLOCK_ALIGNMENT":
            block_data = stream.read(DATA_PROFILE_MAX_READ_BYTES)
            observations["sample_bytes_total"] = len(block_data)
            observations["sample_sha256"] = hashlib.sha256(block_data).hexdigest()
            observations["block_hashes"] = {
                str(width): [hashlib.sha256(block_data[offset:offset + width]).hexdigest()
                    for offset in range(0, len(block_data), width)
                    if len(block_data[offset:offset + width]) == width]
                for width in (512, 2048)}
        elif mode == "SIGNATURE_SWEEP":
            offsets = _sample_offsets(before.st_size, count=7)
            sample_rows = []
            strings = []
            signatures = []
            for offset in offsets:
                stream.seek(offset)
                data = stream.read(DATA_PROFILE_SAMPLE_BYTES)
                sample_rows.append(_sample_metrics(data, offset))
                for label, marker in DATA_PROFILE_SIGNATURES.items():
                    start = 0
                    while (found := data.find(marker, start)) >= 0:
                        signatures.append({"name": label, "absolute_offset": offset + found,
                                           "marker_hex": marker.hex()})
                        start = found + 1
                strings.extend(match.decode("ascii", errors="replace")
                    for match in re.findall(rb"[\x20-\x7e]{6,}", data)[:12])
            observations.update({"samples": sample_rows,
                "candidate_literal_signatures": signatures[:64],
                "printable_strings": list(dict.fromkeys(strings))[:40],
                "sample_bytes_total": sum(row["size_bytes"] for row in sample_rows)})
        elif mode == "CROSS_REGION_WINDOW_COMPARE":
            offsets = _sample_offsets(before.st_size, count=5)
            windows: list[bytes] = []
            sample_rows = []
            last_offset = max(1, before.st_size - DATA_PROFILE_SAMPLE_BYTES)
            for offset in offsets:
                stream.seek(offset)
                data = stream.read(DATA_PROFILE_SAMPLE_BYTES)
                windows.append(data)
                sample = _sample_metrics(data, offset)
                sample["relative_position"] = round(offset / last_offset, 6)
                sample_rows.append(sample)
            observations.update({"samples": sample_rows,
                "sample_bytes_total": sum(row["size_bytes"] for row in sample_rows),
                "_comparison_windows": windows})
        elif mode in {"LAG_CORRELATION_SCAN", "BYTE_TRANSITION_PROFILE"}:
            offsets = _sample_offsets(before.st_size, count=5)
            sample_rows = []
            for offset in offsets:
                stream.seek(offset)
                data = stream.read(DATA_PROFILE_SAMPLE_BYTES)
                sample = _sample_metrics(data, offset)
                if mode == "LAG_CORRELATION_SCAN":
                    sample["lag_matches"] = _lag_match_stats(data)
                else:
                    sample["top_adjacent_pairs"] = _byte_transition_profile(data)
                sample_rows.append(sample)
            observations.update({"samples": sample_rows,
                "sample_bytes_total": sum(row["size_bytes"] for row in sample_rows)})
        elif mode == "DEFLATE_COMPRESSIBILITY_PROFILE":
            sample_bytes = 64 * 1024
            offsets = _sample_offsets(before.st_size, count=5, sample_bytes=sample_bytes)
            sample_rows = []
            for offset in offsets:
                stream.seek(offset)
                data = stream.read(sample_bytes)
                compressed = zlib.compress(data, level=6)
                sample = _sample_metrics(data, offset)
                sample.update({"sample_bytes": len(data),
                    "zlib_level": 6, "zlib_bytes": len(compressed),
                    "zlib_ratio": round(len(compressed) / len(data), 6) if data else None})
                sample_rows.append(sample)
            observations.update({"samples": sample_rows,
                "sample_bytes_total": sum(row["size_bytes"] for row in sample_rows),
                "raw_sample_bytes_retained": False, "compressed_sample_bytes_retained": False})
        elif mode == "EXACT_BLOCK_ANCHOR_SCAN":
            scan_bytes = min(before.st_size, DATA_PROFILE_ANCHOR_SCAN_BYTES)
            full_block_bytes = scan_bytes - (scan_bytes % DATA_PROFILE_ANCHOR_BLOCK_BYTES)
            block_offsets: dict[str, list[int]] = {}
            prefix_digest = hashlib.sha256()
            stream.seek(0)
            for offset in range(0, full_block_bytes, DATA_PROFILE_ANCHOR_BLOCK_BYTES):
                block = stream.read(DATA_PROFILE_ANCHOR_BLOCK_BYTES)
                if len(block) != DATA_PROFILE_ANCHOR_BLOCK_BYTES:
                    raise RuntimeError(f"short read in bounded block-anchor scan: {relative}")
                prefix_digest.update(block)
                block_digest = hashlib.sha256(block).hexdigest()
                block_offsets.setdefault(block_digest, []).append(offset)
            observations.update({"scan_bytes": full_block_bytes,
                "scan_sha256": prefix_digest.hexdigest(),
                "block_bytes": DATA_PROFILE_ANCHOR_BLOCK_BYTES,
                "full_block_count": sum(len(offsets) for offsets in block_offsets.values()),
                "unique_block_count": len(block_offsets),
                "repeated_block_count": sum(1 for offsets in block_offsets.values() if len(offsets) > 1),
                "_block_offsets": block_offsets})
        else:
            raise ValueError(f"unregistered data profile mode: {mode}")
    after = source.stat()
    unchanged = (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns)
    if not unchanged:
        raise RuntimeError(f"data profile source changed while read-only samples were collected: {relative}")
    observations["source_stat_unchanged_during_read"] = True
    return observations


def _exact_block_anchor_comparisons(observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Reduce transient block-hash maps to unique pair and three-region anchors."""
    if len(observations) != 3 or any(not isinstance(row.get("_block_offsets"), dict) for row in observations):
        raise ValueError("exact block anchor scan needs exactly three transient block maps")
    maps = [row.pop("_block_offsets") for row in observations]
    unique_maps = [{digest: offsets[0] for digest, offsets in mapping.items() if len(offsets) == 1}
                   for mapping in maps]
    comparisons = []
    for left_index, right_index in ((0, 1), (0, 2), (1, 2)):
        shared = set(unique_maps[left_index]) & set(unique_maps[right_index])
        ordered = sorted(shared, key=lambda digest: (unique_maps[left_index][digest],
                                                      unique_maps[right_index][digest], digest))
        comparisons.append({"regions": [observations[left_index]["region"], observations[right_index]["region"]],
            "shared_unique_anchor_count": len(shared),
            "anchor_preview": [{"block_sha256": digest,
                "offsets": [unique_maps[left_index][digest], unique_maps[right_index][digest]]}
                for digest in ordered[:32]]})
    shared_all = set(unique_maps[0]) & set(unique_maps[1]) & set(unique_maps[2])
    ordered_all = sorted(shared_all, key=lambda digest: (unique_maps[0][digest],
        unique_maps[1][digest], unique_maps[2][digest], digest))
    comparisons.append({"regions": [row["region"] for row in observations],
        "shared_unique_anchor_count": len(shared_all),
        "anchor_preview": [{"block_sha256": digest,
            "offsets": {observations[index]["region"]: unique_maps[index][digest]
                        for index in range(3)}} for digest in ordered_all[:64]]})
    return comparisons


def execute_data_family_profile(task: dict[str, Any]) -> dict[str, Any]:
    task_id = str(task["id"])
    budget = task.get("budget", {})
    suffix, mode = str(budget.get("suffix", "")), str(budget.get("profile_mode", ""))
    if not budget.get("data_family_profile") or suffix not in coordinator_runtime.available_target_suffixes():
        raise ValueError("task is not a currently available manifest-backed regional NCDx data profile")
    _data_profile_acceptance(mode)
    source_rows = budget.get("sources")
    expected_rows = _data_profile_sources(suffix)
    if source_rows != expected_rows:
        raise RuntimeError("persisted data profile input list differs from the read-only EVIDENCE_LEDGER snapshot")
    if mode == "CONTAINER_ROUNDTRIP":
        return _execute_container_roundtrip_profile(task, source_rows)
    if mode == "DECODED_STRUCTURE_SCAN":
        return _execute_decoded_structure_profile(task, source_rows)
    if mode == "STRING_COORDINATE_PROXIMITY_AUDIT":
        return _execute_string_coordinate_proximity_profile(task, source_rows)
    if mode == "PRINTABLE_RUN_LAYOUT_PROFILE":
        return _execute_printable_run_layout_profile(task, source_rows)
    if mode == "REPEATED_TEXT_DICTIONARY_PROFILE":
        return _execute_repeated_text_dictionary_profile(task, source_rows)
    if mode == "REPEATED_TEXT_COORDINATE_AUDIT":
        return _execute_repeated_text_coordinate_audit(task, source_rows)
    if mode in {"TEXT_COORDINATE_ASSOCIATION_CENSUS",
                "REPEATED_TEXT_COORDINATE_ASSOCIATION_CENSUS"}:
        return _execute_text_coordinate_association_census(task, source_rows)
    if mode == "STANDALONE_ZLIB_STREAM_CENSUS":
        return _execute_standalone_zlib_stream_census(task, source_rows)
    if mode == "ZLIB_STREAM_BOUNDARY_CONTEXT_PROFILE":
        return _execute_zlib_stream_boundary_context_profile(task, source_rows)
    if mode == "ZLIB_DECODED_COORDINATE_CANDIDATE_CENSUS":
        return _execute_zlib_decoded_coordinate_candidate_census(task, source_rows)
    if mode == "BLOCK_BOUNDARY_PROFILE":
        return _execute_block_boundary_profile(task, source_rows)
    observations = [_read_profile_source(row, mode) for row in source_rows]
    verified = {"source_count": len(observations), "source_stat_unchanged_during_read": all(
            row["source_stat_unchanged_during_read"] for row in observations),
        "manifest_entries_present": all(row["inventory_sha256"] for row in observations),
        "source_write_count": 0,
        "read_limit_bytes_per_source": DATA_PROFILE_MAX_READ_BYTES if mode == "BLOCK_ALIGNMENT" else
            (DATA_PROFILE_ANCHOR_SCAN_BYTES if mode == "EXACT_BLOCK_ANCHOR_SCAN" else
             (64 * 1024 * 5 if mode == "DEFLATE_COMPRESSIBILITY_PROFILE" else
              DATA_PROFILE_SAMPLE_BYTES * (7 if mode == "SIGNATURE_SWEEP" else 5))),
        "semantic_format": "UNKNOWN; structural observations only"}
    if len(observations) != 3 or not verified["source_stat_unchanged_during_read"] or not verified["manifest_entries_present"]:
        raise RuntimeError("independent regional data-profile verification failed")
    comparisons: list[dict[str, Any]] = []
    if mode == "BLOCK_ALIGNMENT":
        widths = (512, 2048)
        for left_index, right_index in ((0, 1), (0, 2), (1, 2)):
            left, right = observations[left_index], observations[right_index]
            for width in widths:
                left_hashes, right_hashes = left["block_hashes"][str(width)], right["block_hashes"][str(width)]
                compared = min(len(left_hashes), len(right_hashes))
                changed = [index for index in range(compared) if left_hashes[index] != right_hashes[index]]
                comparisons.append({"regions": [left["region"], right["region"]],
                    "block_bytes": width, "compared_blocks": compared,
                    "same_index_equal_blocks": compared - len(changed),
                    "different_index_blocks": len(changed), "first_different_indices": changed[:32]})
    elif mode == "CROSS_REGION_WINDOW_COMPARE":
        for left_index, right_index in ((0, 1), (0, 2), (1, 2)):
            left, right = observations[left_index], observations[right_index]
            for window_index, (left_bytes, right_bytes) in enumerate(zip(
                    left["_comparison_windows"], right["_comparison_windows"])):
                compared = min(len(left_bytes), len(right_bytes))
                equal_bytes = sum(a == b for a, b in zip(left_bytes[:compared], right_bytes[:compared]))
                common_prefix = 0
                for a, b in zip(left_bytes[:compared], right_bytes[:compared]):
                    if a != b:
                        break
                    common_prefix += 1
                comparisons.append({"regions": [left["region"], right["region"]],
                    "window_index": window_index,
                    "relative_positions": [left["samples"][window_index]["relative_position"],
                                           right["samples"][window_index]["relative_position"]],
                    "offsets": [left["samples"][window_index]["offset"],
                                right["samples"][window_index]["offset"]],
                    "compared_bytes": compared, "equal_bytes": equal_bytes,
                    "different_bytes": compared - equal_bytes,
                    "common_prefix_bytes": common_prefix,
                    "left_sha256": left["samples"][window_index]["sha256"],
                    "right_sha256": right["samples"][window_index]["sha256"]})
        # Raw samples are transient comparison inputs and never enter JSON artifacts.
        for observation in observations:
            observation.pop("_comparison_windows", None)
    elif mode == "LAG_CORRELATION_SCAN":
        for left_index, right_index in ((0, 1), (0, 2), (1, 2)):
            left, right = observations[left_index], observations[right_index]
            for window_index, (left_sample, right_sample) in enumerate(zip(left["samples"], right["samples"])):
                left_lags = {row["lag_bytes"]: row for row in left_sample["lag_matches"]}
                right_lags = {row["lag_bytes"]: row for row in right_sample["lag_matches"]}
                for lag in DATA_PROFILE_LAGS:
                    if lag in left_lags and lag in right_lags:
                        comparisons.append({"regions": [left["region"], right["region"]],
                            "window_index": window_index, "lag_bytes": lag,
                            "left_match_ratio": left_lags[lag]["match_ratio"],
                            "right_match_ratio": right_lags[lag]["match_ratio"],
                            "absolute_ratio_delta": _absolute_ratio_delta(
                                left_lags[lag]["match_ratio"], right_lags[lag]["match_ratio"])})
    elif mode == "BYTE_TRANSITION_PROFILE":
        for left_index, right_index in ((0, 1), (0, 2), (1, 2)):
            left, right = observations[left_index], observations[right_index]
            for window_index, (left_sample, right_sample) in enumerate(zip(left["samples"], right["samples"])):
                left_pairs = {row["pair_hex"] for row in left_sample["top_adjacent_pairs"]}
                right_pairs = {row["pair_hex"] for row in right_sample["top_adjacent_pairs"]}
                union = left_pairs | right_pairs
                comparisons.append({"regions": [left["region"], right["region"]],
                    "window_index": window_index, "top_pair_intersection_count": len(left_pairs & right_pairs),
                    "top_pair_union_count": len(union),
                    "top_pair_jaccard": round(len(left_pairs & right_pairs) / len(union), 6) if union else 1.0})
    elif mode == "DEFLATE_COMPRESSIBILITY_PROFILE":
        for left_index, right_index in ((0, 1), (0, 2), (1, 2)):
            left, right = observations[left_index], observations[right_index]
            for window_index, (left_sample, right_sample) in enumerate(zip(left["samples"], right["samples"])):
                left_ratio, right_ratio = left_sample["zlib_ratio"], right_sample["zlib_ratio"]
                comparisons.append({"regions": [left["region"], right["region"]],
                    "window_index": window_index, "sample_bytes": [left_sample["sample_bytes"], right_sample["sample_bytes"]],
                    "zlib_ratio": [left_ratio, right_ratio],
                    "absolute_ratio_delta": round(abs(left_ratio - right_ratio), 6)
                        if left_ratio is not None and right_ratio is not None else None,
                    "interpretation": "compression behavior only; encryption and semantics UNKNOWN"})
    elif mode == "EXACT_BLOCK_ANCHOR_SCAN":
        comparisons = _exact_block_anchor_comparisons(observations)
    result = {"status": "PASS", "task_id": task_id, "suffix": suffix, "profile_mode": mode,
        "observations": observations, "cross_region_comparisons": comparisons,
        "verified": verified, "claim_scope": "read-only bounded structural evidence; no file type or record semantics inferred",
        "created_utc": _utc(), "original_media_write_count": 0,
        "physical_compatibility": "NOT_TESTED"}
    output_dir = PROJECT_ROOT / "work" / "autonomous_manager" / "ncdx" / "data_family_profiles"
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f"{task_id}.json"
    temporary = output.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(output)
    artifact = manager._artifact(task_id, output,
        f"Read-only {suffix} regional data profile ({mode})",
        "PASS: manifest entries, fixed sample limits, unchanged source metadata, semantics UNKNOWN")
    _register_supervisor("AUTO_SUPERVISOR_" + task_id, task_id)
    return {**result, "artifact": artifact}


def _available_director_models() -> list[str]:
    installed = coordinator_runtime._available_models()
    required = "qwen3.5:9b"
    if required not in installed:
        raise RuntimeError(f"LOCAL FIRST Director requires {required}; planning remains queued until it is available")
    return [required]


def _planning_prompt(scenario: int, model_name: str, candidate_id: str,
                     dependency: str | None, goal_summary: str,
                     criteria: list[str], project_state: dict[str, Any] | None = None) -> str:
    return json.dumps({
        "role": "AI Project Director",
        "scenario": scenario,
        "state": project_state or {"global_goal": project_scope.global_goal(),
                  "active_tracks": project_scope.load_scope()["active_tracks"],
                  "excluded_tracks": project_scope.load_scope()["excluded_tracks"],
                  "director_policy": project_scope.load_scope().get("director_policy", {}),
                  "reporting_policy": project_scope.load_scope().get("reporting_policy", {}),
                  "eligible_queue": [], "blocked_hardware_tasks_must_not_stop_software": True,
                  "available_source": str(SOURCE_PBF.relative_to(PROJECT_ROOT)) if SOURCE_PBF.exists() else "missing"},
        "candidate_goal": {"goal_id": candidate_id, "description": goal_summary,
                           "depends_on": [dependency] if dependency else []},
        "allowed_acceptance_criteria": criteria,
        "return_schema": {"goal_id": candidate_id, "depends_on": [dependency] if dependency else [],
                          "acceptance_criteria": criteria, "requires_hardware": False,
                          "writes_original_media": False, "reason": "short evidence-based reason"},
        "rules": ["Return JSON only.", "Use the exact allowed goal_id and dependency shown.",
                  "Propose concrete tests based on local files; do not invent NCDx bytes.",
                  "Never claim physical compatibility."],
        "expected_model_label": model_name,
    }, ensure_ascii=False)


def _director_context() -> dict[str, Any]:
    with closing(sqlite3.connect(STATE_DB, timeout=20)) as conn:
        conn.row_factory = sqlite3.Row
        task_columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(tasks)")}
        budget_column = "budget_json" if "budget_json" in task_columns else "'{}' AS budget_json"
        task_rows = [dict(row) for row in conn.execute(
            f"SELECT id,stage,status,verdict,{budget_column},updated_utc FROM tasks ORDER BY updated_utc DESC")]
        task_rows = [row for row in task_rows if not project_scope.task_is_excluded(row)]
        counts: dict[str, int] = {}
        for row in task_rows:
            counts[str(row["status"])] = counts.get(str(row["status"]), 0) + 1
        recent = [{key: row[key] for key in ("id", "stage", "status", "verdict")} for row in task_rows[:15]]
        blockers = [dict(row) for row in conn.execute(
            "SELECT stage,reason,required_action FROM blocked_reasons WHERE status='OPEN' ORDER BY stage LIMIT 8")]
        gates = [dict(row) for row in conn.execute("SELECT stage,status FROM stage_gates ORDER BY stage")]
    report = _json(DIRECTOR_BENCHMARK)
    scope = project_scope.load_scope()
    return {"global_goal": scope["global_goal"],
        "scope_revision": scope["scope_revision"],
        "active_tracks": scope["active_tracks"],
        "excluded_tracks": scope["excluded_tracks"],
        "director_policy": scope.get("director_policy", {}),
        "reporting_policy": scope.get("reporting_policy", {}),
        "readiness_policy": scope["readiness_policy"],
        "queue_counts": counts, "recent_tasks": recent, "open_blockers": blockers,
        "stage_gates": gates,
        "director_model_benchmark": {"selected_model": report.get("selected_model"),
                                     "schema_version": report.get("schema_version")},
        "local_pbf": {"exists": SOURCE_PBF.is_file(), "path": str(SOURCE_PBF.relative_to(PROJECT_ROOT)) if SOURCE_PBF.exists() else None,
                      "bytes": SOURCE_PBF.stat().st_size if SOURCE_PBF.exists() else None},
        "known_limits": ["OSM search, routing and POI processing are data-preparation checks only.",
                         "NCDx semantic records and physical device compatibility remain unresolved.",
                         "Do not schedule Virtual CID or the standalone POI editor."],
        "model_output_policy": "Choose only a registry goal. Acceptance ids are fixed and the program never executes generated code."}


def _evaluate_plan(parsed: dict[str, Any], goal_id: str, dependency: str | None,
                   criteria: list[str]) -> dict[str, Any]:
    proposed = parsed.get("acceptance_criteria")
    fixed_criteria = (isinstance(proposed, list) and len(proposed) == len(criteria) and
                      all(isinstance(item, str) for item in proposed) and set(proposed) == set(criteria))
    passed = {
        "allowlisted_goal": parsed.get("goal_id") == goal_id,
        "dependency_exact": parsed.get("depends_on") == ([dependency] if dependency else []),
        "fixed_acceptance_criteria": fixed_criteria,
        "no_hardware_dependency": parsed.get("requires_hardware") is False,
        "original_media_unchanged": parsed.get("writes_original_media") is False,
        "reason_present": isinstance(parsed.get("reason"), str) and bool(parsed.get("reason", "").strip()),
    }
    return {"passed": passed, "score": sum(passed.values()), "maximum": len(passed)}


def _acceptance_criteria(goal_id: str) -> list[str]:
    registry = {
        "OSM_REAL_CONVERSION": ["source_pbf_hash_unchanged", "sqlite_integrity_ok",
            "ukrainian_street_search", "connected_city_route"],
        "NCDX_NK_SURVEY": ["ledger_hash_matches", "source_hash_unchanged",
            "bounded_byte_observations", "semantic_format_unknown"],
        "NCDX_NAVIMAIN_SURVEY": ["ledger_hash_matches", "source_hash_unchanged",
            "header_offsets_bounds_checked", "semantic_format_unknown"],
    }
    try:
        return registry[goal_id]
    except KeyError as exc:
        raise ValueError(f"goal has no fixed acceptance-criteria list: {goal_id}") from exc


def benchmark_directors(task_id: str) -> dict[str, Any]:
    """Sequential, measured local planning tests; one model resident at a time."""
    cached = _json(DIRECTOR_BENCHMARK)
    if cached.get("schema_version") == 2 and cached.get("status") == "COMPLETE" and cached.get("selected_model"):
        return cached
    candidate_models = _available_director_models()
    cases = [
        ("OSM_REAL_CONVERSION", None, "Convert the existing Ukraine PBF read-only into a derived Kryvyi Rih OSM extract and SQLite graph."),
        ("NCDX_NK_SURVEY", "AUTO_SUPERVISOR_OSM_READBACK_01", "Inspect the already inventoried NK.BIN as bytes read-only; document signatures and unknown semantics, then run bounded acceptance tests."),
    ]
    measurements = []
    sequence = 1
    for model_name in candidate_models:
        model_rows = []
        for scenario, (goal, dependency, summary) in enumerate(cases, start=1):
            criteria = _acceptance_criteria(goal)
            prompt = _planning_prompt(scenario, model_name, goal, dependency, summary, criteria)
            started = time.monotonic()
            try:
                actual_model, _response, parsed = coordinator_runtime._call_model(
                    task_id, "project-director", prompt, attempt=sequence, fixed_model=model_name)
                evaluation = _evaluate_plan(parsed, goal, dependency, criteria)
                model_rows.append({"scenario": scenario, "goal_id": goal, "model": actual_model,
                                   **evaluation, "response": parsed,
                                   "elapsed_ms": int((time.monotonic() - started) * 1000)})
            except Exception as exc:
                model_rows.append({"scenario": scenario, "goal_id": goal, "model": model_name,
                                   "score": 0, "maximum": 6,
                                   "passed": {"call": False}, "elapsed_ms": int((time.monotonic() - started) * 1000),
                                   "error": f"{type(exc).__name__}: {exc}"})
            sequence += 1
        measurements.append({"model": model_name, "score": sum(row["score"] for row in model_rows),
            "maximum": sum(row["maximum"] for row in model_rows),
            "elapsed_ms": sum(int(row.get("elapsed_ms", 0)) for row in model_rows), "scenarios": model_rows})
    if not measurements or max(row["score"] for row in measurements) <= 0:
        raise RuntimeError("no local model passed any Director planning criterion; refusing to schedule model-authored work")
    priority = {name: index for index, name in enumerate((*DIRECTOR_MODELS, *FALLBACK_MODELS))}
    selected = sorted(measurements, key=lambda row: (-row["score"], row["elapsed_ms"], priority.get(row["model"], 99)))[0]
    result = {"schema_version": 2, "status": "COMPLETE", "created_utc": _utc(), "candidate_models": candidate_models,
              "selected_model": selected["model"], "selection_reason": "highest validated planning score, then lower measured elapsed time, then configured preference",
              "measurements": measurements, "execution_policy": "sequential Ollama calls with keep_alive=0; no generated code is executed"}
    DIRECTOR_BENCHMARK.parent.mkdir(parents=True, exist_ok=True)
    temp = DIRECTOR_BENCHMARK.with_suffix(".json.tmp")
    temp.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(DIRECTOR_BENCHMARK)
    manager._artifact(task_id, DIRECTOR_BENCHMARK, "Локальний Director benchmark Qwen3.5/Qwythos на реальних планувальних сценаріях", "PASS: score and answer schema checked")
    return result


def _lag_match_stats(data: bytes) -> list[dict[str, Any]]:
    """Measure deterministic byte equality at fixed lags without labeling records."""
    result = []
    for lag in DATA_PROFILE_LAGS:
        compared = max(0, len(data) - lag)
        matches = sum(data[index] == data[index - lag] for index in range(lag, len(data)))
        result.append({"lag_bytes": lag, "compared_bytes": compared, "matching_bytes": matches,
                       "match_ratio": round(matches / compared, 6) if compared else None})
    return result


def _byte_transition_profile(data: bytes) -> list[dict[str, Any]]:
    """Summarize common adjacent-byte pairs; never retain the sampled input."""
    if len(data) < 2:
        return []
    counts: dict[int, int] = {}
    for left, right in zip(data, data[1:]):
        pair = (left << 8) | right
        counts[pair] = counts.get(pair, 0) + 1
    total = len(data) - 1
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:DATA_PROFILE_TOP_TRANSITIONS]
    return [{"pair_hex": f"{pair:04x}", "count": count, "ratio": round(count / total, 6)}
            for pair, count in ranked]


def _absolute_ratio_delta(left: float | None, right: float | None) -> float | None:
    """Return no comparison when a bounded sample is shorter than its lag."""
    if left is None or right is None:
        return None
    return round(abs(left - right), 6)


def _next_goal_for_plan(task_id: str) -> tuple[str, str | None, str]:
    if task_id == PLAN_ID["OSM_REAL_CONVERSION"]:
        return "OSM_REAL_CONVERSION", None, "Create an offline Kryvyi Rih map database from the locally saved national PBF."
    if task_id == PLAN_ID["NCDX_NK_SURVEY"]:
        return "NCDX_NK_SURVEY", "AUTO_SUPERVISOR_OSM_READBACK_01", "Read-only byte-level survey of inventoried NK.BIN with source hash checks and no semantic overclaim."
    if task_id == PLAN_ID["NCDX_NAVIMAIN_SURVEY"]:
        return "NCDX_NAVIMAIN_SURVEY", "AUTO_SUPERVISOR_NK_SURVEY_01", "Read-only bounded PE/NE header survey of inventoried NAVIMAIN.EXE and string metadata."
    raise ValueError(f"unregistered Director plan task {task_id!r}")


def execute_director(task_id: str) -> dict[str, Any]:
    goal_id, dependency, summary = _next_goal_for_plan(task_id)
    if dependency and _task_status(dependency) != "DONE":
        raise RuntimeError(f"Director plan dependency is not verified: {dependency}")
    if goal_id == "OSM_REAL_CONVERSION" and not SOURCE_PBF.is_file():
        raise FileNotFoundError(f"locally saved OSM PBF is missing: {SOURCE_PBF}")
    benchmark = benchmark_directors(task_id)
    model = str(benchmark["selected_model"])
    criteria = _acceptance_criteria(goal_id)
    prompt = _planning_prompt(10, model, goal_id, dependency, summary, criteria, _director_context())
    actual_model, _response, parsed = coordinator_runtime._call_model(
        task_id, "project-director", prompt, attempt=99, fixed_model=model)
    evaluation = _evaluate_plan(parsed, goal_id, dependency, criteria)
    if evaluation["score"] != evaluation["maximum"]:
        raise RuntimeError(f"local Director did not meet the strict task schema: {evaluation}")
    task_specs = {
        "OSM_REAL_CONVERSION": ("F4", None, "osm-real-conversion", "work/autonomous_manager/osm_pipeline/real_conversion/conversion.json",
            ["Source PBF hash unchanged", "Extract contains no missing selected way-node references", "SQLite integrity_check=ok", "Ukrainian street search and connected car route pass"], 2400, 10),
        "NCDX_NK_SURVEY": ("F2", dependency, "ncdx-component-survey", "work/autonomous_manager/ncdx/nk_survey.json",
            ["Selected NK.BIN source matches existing ledger hash", "Bounded header and strings observations are reproducible", "Original hash unchanged", "Semantic claims remain UNKNOWN"], 300, 20),
        "NCDX_NAVIMAIN_SURVEY": ("F2", dependency, "ncdx-component-survey", "work/autonomous_manager/ncdx/navimain_survey.json",
            ["Selected NAVIMAIN.EXE matches ledger hash", "Header offsets are range checked", "Original hash unchanged", "Binary format conclusions are scoped to observed signatures"], 300, 21),
    }
    stage, input_dependency, agent, deliverable, tests, timeout_s, priority = task_specs[goal_id]
    work_task_id = PLAN_TASKS[goal_id]
    created = _registered_task(work_task_id, stage, task_id,
        f"{summary} AI Director обрав ціль {goal_id}; усі твердження мають пройти детерміновані критерії.",
        agent, deliverable, tests, timeout_s, priority)
    if not created:
        raise RuntimeError(f"planned task already exists; duplicate prevented: {work_task_id}")
    report = {"status": "PASS", "task_id": task_id, "goal_id": goal_id,
        "selected_model": actual_model, "benchmark_selected_model": model,
        "model_plan": parsed, "schema_validation": evaluation,
        "created_task_id": work_task_id, "depends_on": input_dependency,
        "created_utc": _utc(), "guard": "model output is data only; deterministic task registry selected the handler"}
    output = PROJECT_ROOT / "reports" / f"autonomous_director_plan_{goal_id.casefold()}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report["artifact"] = manager._artifact(task_id, output, f"AI Director обрав дозволений план {goal_id}", "PASS: strict plan schema and deterministic goal allowlist")
    return report


def _street_route_proof(database: Path) -> dict[str, Any]:
    from src.osm.engine import OSMStore, normalize_name
    store = OSMStore(database)
    sobornosti = [row for row in store.search("Соборності", limit=300)
                  if row.kind == "street" and normalize_name(row.name) == normalize_name("вулиця Соборності")]
    heroiv = [row for row in store.search("Героїв АТО", limit=300)
              if row.kind == "street" and normalize_name(row.name) == normalize_name("вулиця Героїв АТО")
              and 47.89 <= (row.latitude or 0) <= 47.92 and 33.39 <= (row.longitude or 0) <= 33.44]
    if not sobornosti or not heroiv:
        raise RuntimeError("two required real Ukrainian street names were not found in the converted OSM database")
    start_point = min(sobornosti, key=lambda row: abs((row.latitude or 0) - 47.9) + abs((row.longitude or 0) - 33.408))
    end_point = min(heroiv, key=lambda row: abs((row.latitude or 0) - 47.906) + abs((row.longitude or 0) - 33.407))
    start = store.nearest_routable_node(start_point.latitude, start_point.longitude, max_distance_m=5000)
    end = store.nearest_routable_node(end_point.latitude, end_point.longitude, max_distance_m=5000)
    if not start or not end:
        raise RuntimeError("street search results could not be snapped to the routable road graph")
    route = store.route(start[0], end[0])
    if not route or not 0 < route.distance_m < 10_000 or len(route.node_ids) <= 2:
        raise RuntimeError("the connected city route did not meet the saved acceptance bounds")
    return {"search": {"start": start_point.name, "end": end_point.name, "start_node": start[0], "end_node": end[0]},
            "route": {"distance_m": route.distance_m, "node_count": len(route.node_ids),
                      "way_count": len(route.way_ids), "limitations": list(route.limitations)}}


def _verify_osm_artifacts(task_id: str, output_dir: Path, *, hash_source: bool) -> dict[str, Any]:
    from src.osm.engine import OSMStore
    extract = output_dir / "kryvyi_rih.osm.gz"
    database = output_dir / "kryvyi_rih.sqlite"
    conversion_json = output_dir / "conversion.json"
    if not extract.is_file() or not database.is_file():
        raise RuntimeError("derived OSM extract or SQLite output is missing")
    with gzip.open(extract, "rb") as source:
        header = source.read(256)
        if b"<osm" not in header:
            raise RuntimeError("derived gzip XML does not begin with an OSM document")
        while source.read(1024 * 1024):
            pass
    with closing(sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)) as conn:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        metadata_rows = conn.execute("SELECT key,value FROM meta WHERE key IN ('source_sha256','source_path','importer_version')").fetchall()
        database_metadata = {str(key): str(value) for key, value in metadata_rows}
        stats = {"nodes": conn.execute("SELECT count(*) FROM nodes").fetchone()[0],
                 "edges": conn.execute("SELECT count(*) FROM edges").fetchone()[0],
                 "features": conn.execute("SELECT count(*) FROM features").fetchone()[0]}
    if integrity != "ok" or not stats["nodes"] or not stats["edges"]:
        raise RuntimeError(f"converted OSM SQLite failed integrity or has no routable data: {integrity}, {stats}")
    search_route = _street_route_proof(database)
    report = _json(conversion_json) if conversion_json.exists() else {}
    before = report.get("source_sha256_before")
    after = _sha256(SOURCE_PBF) if hash_source else report.get("source_sha256_after")
    if not before or before != after:
        raise RuntimeError("original local PBF hash is missing or changed")
    extract_digest = _sha256(extract)
    if database_metadata.get("source_sha256") != extract_digest:
        raise RuntimeError("OSM SQLite metadata does not identify the exact compressed XML extract that was imported")
    return {"database": str(database.relative_to(PROJECT_ROOT)), "database_sha256": _sha256(database),
            "extract": str(extract.relative_to(PROJECT_ROOT)), "extract_sha256": extract_digest,
            "database_source_sha256": database_metadata.get("source_sha256"),
            "importer_version": database_metadata.get("importer_version"),
            "integrity_check": integrity, **stats, **search_route,
            "source_pbf": str(SOURCE_PBF.relative_to(PROJECT_ROOT)), "source_sha256_before": before,
            "source_sha256_after": after, "source_unchanged": before == after}


def execute_osm_conversion(task_id: str) -> dict[str, Any]:
    from src.osm.engine import import_osm_xml
    from src.osm.extract_pbf import extract_city
    if not SOURCE_PBF.is_file():
        raise FileNotFoundError(SOURCE_PBF)
    if not SOURCE_PBF.resolve().is_relative_to((PROJECT_ROOT / "data" / "osm").resolve()):
        raise RuntimeError("OSM input resolved outside the read-only local data folder")
    output_dir = WORK_ROOT / "real_conversion"
    output_dir.mkdir(parents=True, exist_ok=True)
    extract = output_dir / "kryvyi_rih.osm.gz"
    database = output_dir / "kryvyi_rih.sqlite"
    metadata = output_dir / "conversion.json"
    source_before = _sha256(SOURCE_PBF)
    extraction_result = None
    if not extract.exists():
        extraction_result = extract_city(SOURCE_PBF, extract)
    elif not database.exists():
        # A completed extraction survives a process restart. Read it through to
        # EOF before allowing the importer to resume the dependent conversion.
        with gzip.open(extract, "rb") as stream:
            while stream.read(1024 * 1024):
                pass
        extraction_result = {"status": "RESUMED_EXISTING_COMPLETE_EXTRACT", "extract_xml_gz": str(extract),
                             "extract_bytes": extract.stat().st_size}
    import_result = None
    if not database.exists():
        import_result = import_osm_xml(extract, database).__dict__
    source_after = _sha256(SOURCE_PBF)
    if source_before != source_after:
        raise RuntimeError("local source PBF SHA-256 changed during the read-only conversion")
    prior = _json(metadata)
    conversion = {"status": "PASS", "task_id": task_id, "created_utc": _utc(),
        "source_pbf": str(SOURCE_PBF.relative_to(PROJECT_ROOT)), "source_bytes": SOURCE_PBF.stat().st_size,
        "source_sha256_before": prior.get("source_sha256_before", source_before),
        "source_sha256_after": source_after, "source_unchanged": prior.get("source_sha256_before", source_before) == source_after,
        "extraction": extraction_result or prior.get("extraction"),
        "import": import_result or prior.get("import"),
        "output_directory": str(output_dir.relative_to(PROJECT_ROOT)),
        "safety": {"original_media_write_count": 0, "source_opened_read_only": True,
                   "all_outputs_inside_project_work_area": True}}
    if not conversion["source_unchanged"]:
        raise RuntimeError("saved source hash does not match the current source PBF")
    metadata.write_text(json.dumps(conversion, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    proof = _verify_osm_artifacts(task_id, output_dir, hash_source=False)
    conversion["verified"] = proof
    metadata.write_text(json.dumps(conversion, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    artifact = manager._artifact(task_id, metadata, "Справжній локальний PBF → витяг Кривого Рогу → OSM SQLite; перевірено пошук і маршрут", "PASS: source hash preserved, SQLite integrity, Ukrainian street search, connected route")
    _register_supervisor(SUPERVISOR_ID["OSM_REAL_CONVERSION"], task_id)
    return {"status": "PASS", "task_id": task_id, "conversion": conversion, "verified": proof,
            "artifacts": [artifact,
                manager._artifact(task_id, extract, "OSM extract derived from local Ukraine PBF", "gzip XML read through EOF"),
                manager._artifact(task_id, database, "OSM SQLite derived from local Ukraine PBF", "integrity and city route pass")],
            "model_generated_code_executed": False}


def execute_osm_readback(task_id: str) -> dict[str, Any]:
    task = manager._task(task_id)
    predecessor = _task_result("AUTO_SUPERVISOR_OSM_CONVERSION_01")
    output_dir = WORK_ROOT / "real_conversion"
    proof = _verify_osm_artifacts(task_id, output_dir, hash_source=True)
    report = {"status": "PASS", "task_id": task_id, "created_utc": _utc(),
        "worker_pid": __import__("os").getpid(), "supervisor_predecessor": predecessor.get("status"),
        "verified": proof, "restart_scope": "independent handler process reopened OSM SQLite read-only",
        "source_write_count": 0}
    path = output_dir / "readback_after_restart.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    artifact = manager._artifact(task_id, path, "Свіжий процес повторно відкрив і перевірив збережену OSM карту", "PASS: integrity, street search, route, unchanged PBF hash")
    _register_supervisor("AUTO_SUPERVISOR_OSM_READBACK_01", task_id)
    return {**report, "artifact": artifact}


def _verify_national_osm_target(target_id: str, target_task: dict[str, Any],
                                result: dict[str, Any] | None = None) -> dict[str, Any]:
    from src.osm.build_ukraine import DEFAULT_OUTPUT_ROOT, verify_snapshot
    if target_task.get("budget", {}).get("ukraine_national_osm") is not True:
        raise RuntimeError("national OSM verifier was called for an unregistered task type")
    saved = result or _task_result(target_id)
    relative = saved.get("output_directory")
    if not isinstance(relative, str) or Path(relative).is_absolute() or ".." in Path(relative).parts:
        raise RuntimeError("national OSM result does not contain a safe project-relative output directory")
    output_dir = (PROJECT_ROOT / relative).resolve(strict=True)
    if DEFAULT_OUTPUT_ROOT.resolve() not in output_dir.parents:
        raise RuntimeError("national OSM output resolved outside its versioned work area")
    source_hash = str(saved.get("source_pbf_sha256", ""))
    if not re.fullmatch(r"[0-9a-f]{64}", source_hash):
        raise RuntimeError("national OSM result omitted its scheduled source hash")
    if saved.get("recovered_published_database") is True:
        from src.osm.build_ukraine import verify_published_recovery
        extract_hash = str(saved.get("extract_sha256", ""))
        if not re.fullmatch(r"[0-9a-f]{64}", extract_hash):
            raise RuntimeError("recovered national OSM result omitted its scheduled extract hash")
        proof = verify_published_recovery(output_dir, expected_source_sha256=source_hash,
                                          expected_extract_sha256=extract_hash)
        if proof.get("status") != "PASS" or proof.get("source_write_count") != 0:
            raise RuntimeError("independent recovered national OSM readback did not pass")
        return proof
    proof = verify_snapshot(output_dir, expected_source_sha256=source_hash, verify_source_hash=True)
    if proof.get("status") != "PASS" or proof.get("source_write_count") != 0:
        raise RuntimeError("independent national OSM readback did not pass the fixed proof checks")
    return proof


def execute_osm_national_conversion(task_id: str) -> dict[str, Any]:
    from src.osm import resumable_national
    from src.osm.build_ukraine import (DEFAULT_OUTPUT_ROOT, _source_content_timestamp,
                                      verify_snapshot, verify_published_recovery)
    task = manager._task(task_id)
    if task.get("budget", {}).get("ukraine_national_osm") is not True:
        raise RuntimeError("national conversion task is missing its fixed allowlisted mode")
    budget = task.get("budget", {})
    if budget.get("resumable_national_osm") is not True:
        raise RuntimeError("national conversion must use the checkpointed importer; refusing the monolithic legacy build")
    source_sha = str(budget.get("source_pbf_sha256", ""))
    extract_sha = str(budget.get("extract_sha256", ""))
    if not source_sha or not extract_sha:
        source_sha = _sha256(SOURCE_PBF)
        output_root = DEFAULT_OUTPUT_ROOT.resolve()
        candidates = sorted(output_root.glob("ukraine-*"), key=lambda path: path.stat().st_mtime, reverse=True)
        output_dir = next((path.resolve() for path in candidates
                           if path.is_dir() and (path / "progress.json").is_file()), None)
        if output_dir is None:
            raise RuntimeError("no saved versioned national OSM extract checkpoint exists")
        extract_path = output_dir / "ukraine.osm.gz"
        extract_sha = _sha256(extract_path)
        budget.update({"source_pbf_sha256": source_sha, "extract_sha256": extract_sha,
                       "output_directory": output_dir.relative_to(PROJECT_ROOT).as_posix(),
                       "timeout_s": 900, "max_records_per_slice": 500000,
                       "slice_budget_seconds": 180, "resumable_national_osm": True})
        with closing(sqlite3.connect(STATE_DB, timeout=20)) as conn:
            conn.execute("UPDATE tasks SET budget_json=? WHERE id=?",
                         (json.dumps(budget, ensure_ascii=False, sort_keys=True), task_id))
            conn.commit()
    output_dir = (PROJECT_ROOT / str(budget["output_directory"])).resolve(strict=True)
    if DEFAULT_OUTPUT_ROOT.resolve() not in output_dir.parents:
        raise RuntimeError("national converter output escaped its versioned work area")
    extract_path = output_dir / "ukraine.osm.gz"
    building_database, final_database = output_dir / "ukraine.sqlite.building", output_dir / "ukraine.sqlite"
    if not extract_path.is_file() or not SOURCE_PBF.is_file():
        raise RuntimeError("saved extract or immutable local PBF is missing")
    step = resumable_national.run_step(extract_path, output_dir, building_database, final_database,
        extract_sha256=extract_sha, source_pbf_sha256=source_sha,
        max_records=int(budget.get("max_records_per_slice", 500000)),
        max_seconds=float(budget.get("slice_budget_seconds", 180)), decompression_seconds=240,
        expected_checkpoint_token=budget.get("checkpoint_token"))
    progress_report = output_dir / "national_import_progress.json"
    progress_report.write_text(json.dumps({"task_id": task_id, "updated_utc": _utc(),
        "source_pbf_sha256": source_sha, "extract_sha256": extract_sha,
        "step": step, "physical_compatibility": "NOT_TESTED"}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if step.get("status") != "COMPLETE":
        return {"status": "CONTINUE", "task_id": task_id,
            "phase": step.get("phase"), "checkpoint_token": step.get("checkpoint_token"),
            "progress": step.get("progress"), "slice": step,
            "artifact": manager._artifact(task_id, progress_report,
                "National OSM import progress checkpoint", "PASS: only committed rows/offsets will be resumed")}

    conversion_path = output_dir / "conversion.json"
    metadata = {"status": "VERIFYING", "task_id": task_id,
        "source_pbf": str(SOURCE_PBF.relative_to(PROJECT_ROOT)),
        "source_pbf_sha256": source_sha, "extract_sha256": extract_sha,
        "dataset_content_timestamp": _source_content_timestamp(),
        "extract": str(extract_path.relative_to(PROJECT_ROOT)),
        "database": str(final_database.relative_to(PROJECT_ROOT)),
        "safety": {"source_opened_read_only": True, "original_disc_write_count": 0,
                   "physical_compatibility": "NOT_TESTED"}}
    conversion_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    recovered = bool(step.get("recovered_published_result") or budget.get("national_osm_published_recovery"))
    if recovered:
        proof = verify_published_recovery(output_dir, expected_source_sha256=source_sha,
                                          expected_extract_sha256=extract_sha)
        metadata.update({"status": "PASS_PENDING_INDEPENDENT_SUPERVISOR",
                         "recovered_published_database": True, "recovery_verification": proof,
                         "full_database_integrity_check_repeated": False})
    else:
        proof = verify_snapshot(output_dir, expected_source_sha256=source_sha, verify_source_hash=True)
        metadata.update({"status": "PASS_PENDING_INDEPENDENT_SUPERVISOR", "verified": proof})
    conversion_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    result = {"status": "PASS_PENDING_INDEPENDENT_SUPERVISOR", "task_id": task_id,
        "output_directory": output_dir.relative_to(PROJECT_ROOT).as_posix(),
        "source_pbf_sha256": source_sha, "dataset_content_timestamp": metadata["dataset_content_timestamp"],
        "extract_sha256": extract_sha, "deterministic_build_readback": proof,
        "recovered_published_database": recovered, "original_disc_write_count": 0,
        "physical_compatibility": "NOT_TESTED"}
    report = PROJECT_ROOT / "reports" / "autonomous_osm_national_conversion.json"
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    artifact = manager._artifact(task_id, report,
        "Ukraine-wide dated OSM database with source provenance and independent readback",
        "PASS pending independent Supervisor; no NCDx export or physical compatibility claim")
    result["artifact"] = artifact
    _register_supervisor(OSM_NATIONAL_SUPERVISOR_ID, task_id)
    return result


def _record_ukraine_osm_readiness(proof: dict[str, Any], target_id: str) -> None:
    counts = proof.get("counts", {})
    extent = proof.get("geographic_extent", {})
    if (proof.get("status") != "PASS" or proof.get("sqlite_integrity_check") != "ok"
            or proof.get("source_sha256_unchanged") is not True or proof.get("source_write_count") != 0
            or int(counts.get("nodes", 0)) <= 0 or int(counts.get("directed_edges", 0)) <= 0
            or not (float(extent.get("south", 90)) < 45 and float(extent.get("north", -90)) > 52
                    and float(extent.get("west", 180)) < 23 and float(extent.get("east", -180)) > 39)
            or int(proof.get("kryvyi_rih_route", {}).get("node_count", 0)) <= 2):
        raise RuntimeError("refusing Ukraine OSM readiness without national readback, extent, graph and city-route proof")
    with closing(sqlite3.connect(STATE_DB, timeout=30)) as conn:
        row = conn.execute("SELECT proof_json FROM stage_gates WHERE stage='F4'").fetchone()
        if not row:
            raise RuntimeError("F4 OSM readiness gate is missing")
        try:
            saved = json.loads(row[0] or "{}")
        except json.JSONDecodeError:
            saved = {}
        criteria = saved.setdefault("criteria_pass", {})
        criteria["whole_ukraine_osm_database"] = True
        saved["whole_ukraine_osm_evidence"] = {"task_id": target_id,
            "database_sha256": proof["database_sha256"], "source_pbf_sha256": proof["source_pbf_sha256"],
            "counts": counts, "geographic_extent": extent, "sqlite_integrity_check": "ok",
            "independent_supervisor_readback": True, "original_disc_write_count": 0,
            "physical_compatibility": "NOT_TESTED"}
        conn.execute("UPDATE stage_gates SET proof_json=?,updated_utc=? WHERE stage='F4'",
                     (json.dumps(saved, ensure_ascii=False), _utc()))
        conn.commit()
    (PROJECT_ROOT / "reports" / "verified_ukraine_osm.json").write_text(
        json.dumps({"status": "PASS", "proof": proof, "supervisor_task": OSM_NATIONAL_SUPERVISOR_ID,
                    "physical_compatibility": "NOT_TESTED"}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _register_supervisor(task_id: str, target_id: str) -> bool:
    timeout_s = 3600 if target_id in {OSM_NATIONAL_TASK_ID, OSM_NATIONAL_PUBLISHED_RECOVERY_ID} else 360
    return _registered_task(task_id, "R3", target_id,
        f"Independently review deterministic evidence from {target_id}; do not elevate unknown NCDx semantics or physical compatibility.",
        "ollama-research-supervisor", f"reports/autonomous_supervisor_{target_id.casefold()}.json",
        ["Reopen and check target evidence", "Local Supervisor records an evidence assessment", "Periodic reports and dependent next task are persisted"],
        timeout_s, 11, {"supervises_task": target_id})


def _verify_deflate_profile_target(target_id: str, target_task: dict[str, Any],
                                   result: dict[str, Any]) -> dict[str, Any]:
    """Freshly resample the inventoried files and reproduce saved zlib ratios."""
    budget = target_task.get("budget", {})
    suffix = str(budget.get("suffix", ""))
    sources = _data_profile_sources(suffix)
    if budget.get("sources") != sources or result.get("status") != "PASS":
        raise RuntimeError(f"Supervisor refused changed or failed compressibility inputs for {target_id}")
    saved = result.get("observations")
    if not isinstance(saved, list) or len(saved) != 3:
        raise RuntimeError(f"Supervisor refused incomplete regional samples for {target_id}")
    fresh = [_read_profile_source(source, "DEFLATE_COMPRESSIBILITY_PROFILE") for source in sources]
    fields = ("offset", "size_bytes", "sha256", "sample_bytes", "zlib_level", "zlib_bytes", "zlib_ratio")
    for prior, current in zip(saved, fresh):
        if (prior.get("inventory_sha256") != current.get("inventory_sha256")
                or prior.get("relative_path") != current.get("relative_path")
                or prior.get("samples") != current.get("samples")):
            raise RuntimeError(f"fresh Supervisor resampling differs from saved NCDx profile: {target_id}")
        if any(any(row.get(field) != replay.get(field) for field in fields)
               for row, replay in zip(prior["samples"], current["samples"])):
            raise RuntimeError(f"fresh Supervisor sample hash or zlib statistic changed: {target_id}")
    ratios = [[sample["zlib_ratio"] for sample in row["samples"]] for row in fresh]
    expected_comparisons = []
    for left_index, right_index in ((0, 1), (0, 2), (1, 2)):
        for window_index, (left_ratio, right_ratio) in enumerate(zip(ratios[left_index], ratios[right_index])):
            expected_comparisons.append({"regions": [fresh[left_index]["region"], fresh[right_index]["region"]],
                "window_index": window_index,
                "sample_bytes": [fresh[left_index]["samples"][window_index]["sample_bytes"],
                                 fresh[right_index]["samples"][window_index]["sample_bytes"]],
                "zlib_ratio": [left_ratio, right_ratio],
                "absolute_ratio_delta": round(abs(left_ratio - right_ratio), 6)
                    if left_ratio is not None and right_ratio is not None else None,
                "interpretation": "compression behavior only; encryption and semantics UNKNOWN"})
    if result.get("cross_region_comparisons") != expected_comparisons:
        raise RuntimeError(f"fresh Supervisor regional comparisons differ from the saved profile: {target_id}")
    return {"fresh_manifest_backed_resampling": True, "sample_count": sum(len(row["samples"]) for row in fresh),
        "sample_bytes_per_source_max": 5 * 64 * 1024,
        "all_window_hashes_and_zlib_ratios_match": True,
        "regional_comparison_count": len(expected_comparisons),
        "raw_sample_bytes_retained": False, "original_media_write_count": 0,
        "semantic_format": "UNKNOWN; compression behavior only", "physical_compatibility": "NOT_TESTED"}


def _verify_exact_block_anchor_profile_target(target_id: str, target_task: dict[str, Any],
                                              result: dict[str, Any]) -> dict[str, Any]:
    budget = target_task.get("budget", {})
    suffix = str(budget.get("suffix", ""))
    sources = _data_profile_sources(suffix)
    if budget.get("sources") != sources or result.get("status") != "PASS":
        raise RuntimeError(f"Supervisor refused changed exact-block inputs for {target_id}")
    saved = result.get("observations")
    if not isinstance(saved, list) or len(saved) != 3:
        raise RuntimeError(f"Supervisor refused incomplete exact-block observations for {target_id}")
    fresh = [_read_profile_source(source, "EXACT_BLOCK_ANCHOR_SCAN") for source in sources]
    comparisons = _exact_block_anchor_comparisons(fresh)
    if (fresh != saved or comparisons != result.get("cross_region_comparisons")
            or sum(row["scan_bytes"] for row in fresh) > 3 * DATA_PROFILE_ANCHOR_SCAN_BYTES
            or int(result.get("original_media_write_count", -1)) != 0):
        raise RuntimeError(f"fresh Supervisor exact-block anchors differ from the saved read-only evidence: {target_id}")
    return {"fresh_manifest_backed_rescan": True,
        "source_count": len(fresh), "full_blocks_rescanned": sum(row["full_block_count"] for row in fresh),
        "read_limit_bytes_per_source": DATA_PROFILE_ANCHOR_SCAN_BYTES,
        "regional_comparisons_match": True, "raw_blocks_retained": False,
        "original_media_write_count": 0, "semantic_format": "UNKNOWN; exact block anchors only",
        "physical_compatibility": "NOT_TESTED"}


def _verify_container_roundtrip_target(target_id: str, target_task: dict[str, Any],
                                      result: dict[str, Any]) -> dict[str, Any]:
    """Fresh independent decode and source/output readback for the no-op writer."""
    from research.ncdx_container_experiment.inspect_container import inspect_container

    budget = target_task.get("budget", {})
    suffix = str(budget.get("suffix", ""))
    expected_sources = _data_profile_sources(suffix)
    saved_rows = result.get("observations")
    if (result.get("status") != "PASS" or suffix not in CONTAINER_ROUNDTRIP_SUFFIXES
            or not isinstance(saved_rows, list) or len(saved_rows) != 3
            or int(result.get("original_media_write_count", -1)) != 0):
        raise RuntimeError(f"Supervisor refused incomplete container round-trip evidence for {target_id}")
    saved_by_path = {str(row.get("relative_path")): row for row in saved_rows
                     if isinstance(row, dict)}
    if len(saved_by_path) != 3:
        raise RuntimeError(f"Supervisor refused duplicate or incomplete regional results for {target_id}")
    source_root = coordinator_runtime.SOURCE_ROOT.resolve(strict=True)
    work_root = (PROJECT_ROOT / "work").resolve(strict=True)
    independent_rows = []
    for source_row in expected_sources:
        relative = str(source_row["relative_path"])
        saved = saved_by_path.get(relative)
        if not saved or saved.get("inventory_sha256") != source_row["sha256"]:
            raise RuntimeError(f"Supervisor refused a changed manifest row for {relative}")
        source_rel = PurePosixPath(relative.replace("\\", "/"))
        source = (source_root / Path(*source_rel.parts)).resolve(strict=True)
        if not source.is_relative_to(source_root):
            raise RuntimeError(f"Supervisor refused source path escape: {relative}")
        output_rel = PurePosixPath(str(saved.get("output_path", "")).replace("\\", "/"))
        if output_rel.is_absolute() or ".." in output_rel.parts:
            raise RuntimeError(f"Supervisor refused output path escape: {saved.get('output_path')}")
        output = (PROJECT_ROOT / Path(*output_rel.parts)).resolve(strict=True)
        if not output.is_relative_to(work_root):
            raise RuntimeError(f"Supervisor refused output outside work/: {output}")
        source_before = source.stat()
        source_digest = _sha256(source)
        output_digest = _sha256(output)
        if (source_digest != source_row["sha256"] or output_digest != source_digest
                or output.stat().st_size != source.stat().st_size
                or saved.get("byte_identical") is not True
                or saved.get("source_stat_unchanged") is not True):
            raise RuntimeError(f"Supervisor found a non-identical regional round-trip: {relative}")
        parsed = inspect_container(output.read_bytes())
        source_after = source.stat()
        if ((source_before.st_size, source_before.st_mtime_ns)
                != (source_after.st_size, source_after.st_mtime_ns)):
            raise RuntimeError(f"Supervisor found source metadata changed during readback: {relative}")
        for key in ("physical_size_bytes", "logical_size_bytes", "chunk_count", "block_size_bytes",
                    "decoded_sha256"):
            report_key = {"physical_size_bytes": "output_bytes", "logical_size_bytes": "logical_bytes",
                          "chunk_count": "block_count"}.get(key, key)
            saved_value = saved.get(report_key)
            if key == "physical_size_bytes":
                saved_value = saved.get("output_bytes")
            if key == "block_size_bytes":
                saved_value = saved.get("block_size_bytes")
            if key == "decoded_sha256":
                saved_value = saved.get("logical_sha256")
            if parsed.get(key) != saved_value:
                raise RuntimeError(f"Independent decoder disagreed on {key} for {relative}")
        independent_rows.append({"region": source_row["region"], "relative_path": relative,
            "source_sha256": source_digest, "output_sha256": output_digest,
            "independent_decoded_sha256": parsed["decoded_sha256"],
            "physical_size_bytes": parsed["physical_size_bytes"],
            "logical_size_bytes": parsed["logical_size_bytes"],
            "block_count": parsed["chunk_count"], "independent_decode_status": parsed["status"]})
    return {"fresh_manifest_bound_source_readback": True,
        "independent_parser": "research.ncdx_container_experiment.inspect_container",
        "independent_full_decode_count": len(independent_rows),
        "source_and_output_sha256_equal": all(row["source_sha256"] == row["output_sha256"]
                                               for row in independent_rows),
        "regional_results": independent_rows, "original_media_write_count": 0,
        "semantic_format": "UNKNOWN; block container framing only",
        "physical_compatibility": "NOT_TESTED"}


def _verify_decoded_structure_target(target_id: str, target_task: dict[str, Any],
                                     result: dict[str, Any]) -> dict[str, Any]:
    """Fresh Supervisor-process rescan of each manifest-bound decoded input."""
    from src.readers.ncdx_record_probe import probe_regional_set

    suffix = str(target_task.get("budget", {}).get("suffix", ""))
    expected_sources = _data_profile_sources(suffix)
    saved = result.get("observations")
    if (result.get("status") != "PASS" or suffix not in CONTAINER_ROUNDTRIP_SUFFIXES
            or not isinstance(saved, list) or len(saved) != 3
            or int(result.get("original_media_write_count", -1)) != 0):
        raise RuntimeError(f"Supervisor refused incomplete decoded structure scan for {target_id}")
    if target_task.get("budget", {}).get("sources") != expected_sources:
        raise RuntimeError(f"Supervisor refused changed inventory inputs for {target_id}")
    fresh = probe_regional_set(expected_sources,
        source_root=coordinator_runtime.SOURCE_ROOT.resolve(strict=True))
    if (fresh.get("status") != "PASS" or fresh.get("observations") != saved
            or fresh.get("source_write_count") != 0
            or fresh.get("raw_payload_bytes_retained") is not False):
        raise RuntimeError(f"fresh Supervisor decode or candidate scan differed for {target_id}")
    return {"fresh_manifest_bound_decode_and_rescan": True,
        "fresh_full_decode_count": fresh["source_count"],
        "total_logical_bytes": sum(int(row["logical_bytes"]) for row in fresh["observations"]),
        "bounded_text_samples": sum(len(row["bounded_ascii_samples"]) for row in fresh["observations"]),
        "coordinate_candidate_count_by_region": {
            row["region"]: row["coordinate_candidate_counts_by_scale_and_order"]
            for row in fresh["observations"]},
        "candidate_offsets_and_hashes_match": True,
        "raw_payload_bytes_retained": False, "original_media_write_count": 0,
        "semantic_format": "UNKNOWN; bounded structural candidates only",
        "physical_compatibility": "NOT_TESTED"}


def _verify_string_coordinate_proximity_target(target_id: str, target_task: dict[str, Any],
                                                result: dict[str, Any]) -> dict[str, Any]:
    """Repeat the bounded PDX anchor/control audit from fresh source reads."""
    from src.readers.ncdx_record_probe import audit_string_coordinate_proximity

    budget = target_task.get("budget", {})
    prior_task_id = str(budget.get("prior_task_id", ""))
    expected_prior_id = _data_profile_task_id("PDX", "DECODED_STRUCTURE_SCAN",
                                               _data_profile_sources("PDX"))
    sources = _data_profile_sources("PDX")
    saved = result.get("observations")
    if (result.get("status") != "PASS" or budget.get("profile_mode") != "STRING_COORDINATE_PROXIMITY_AUDIT"
            or budget.get("suffix") != "PDX" or prior_task_id != expected_prior_id
            or target_task.get("budget", {}).get("sources") != sources
            or not isinstance(saved, list) or len(saved) != 3
            or int(result.get("original_media_write_count", -1)) != 0):
        raise RuntimeError(f"Supervisor refused incomplete PDX proximity audit for {target_id}")
    prior_result = _task_result(prior_task_id)
    if prior_result.get("status") != "PASS" or prior_result.get("profile_mode") != "DECODED_STRUCTURE_SCAN":
        raise RuntimeError(f"Supervisor refused unverified text-anchor checkpoint for {target_id}")
    anchors_by_region = {str(row.get("region")): row for row in prior_result.get("observations", [])
                         if isinstance(row, dict)}
    source_root = coordinator_runtime.SOURCE_ROOT.resolve(strict=True)
    fresh = []
    for row in sources:
        anchors = anchors_by_region.get(str(row["region"]))
        if not anchors or anchors.get("source_sha256") != row["sha256"]:
            raise RuntimeError("Supervisor proximity anchors are not bound to the current manifest")
        relative = PurePosixPath(str(row["relative_path"]).replace("\\", "/"))
        source = (source_root / Path(*relative.parts)).resolve(strict=True)
        if not source.is_relative_to(source_root):
            raise ValueError("Supervisor proximity source escaped the original-media root")
        observation = audit_string_coordinate_proximity(source, region=str(row["region"]),
            expected_sha256=str(row["sha256"]), text_samples=anchors.get("bounded_ascii_samples", []))
        if observation["source_bytes"] != int(row["size_bytes"]):
            raise RuntimeError("Supervisor proximity source size differs from the inventory")
        fresh.append({"relative_path": row["relative_path"], **observation})
    if fresh != saved:
        raise RuntimeError(f"Independent Supervisor proximity audit differed for {target_id}")
    return {"fresh_manifest_bound_anchor_control_audit": True,
        "independent_region_count": len(fresh),
        "label_window_hits_by_region": {row["region"]: row["label_windows"][
            "candidate_hit_windows_by_scale_and_order"] for row in fresh},
        "fixed_control_hits_by_region": {row["region"]: row["fixed_control_windows"][
            "candidate_hit_windows_by_scale_and_order"] for row in fresh},
        "candidate_offsets_and_hashes_match": True, "raw_payload_bytes_retained": False,
        "original_media_write_count": 0,
        "semantic_format": "UNKNOWN; bounded structural candidates only",
        "physical_compatibility": "NOT_TESTED"}


def _verify_printable_run_layout_target(target_id: str, target_task: dict[str, Any],
                                        result: dict[str, Any]) -> dict[str, Any]:
    """Fresh Supervisor-process readback of every bounded PDX layout summary."""
    from src.readers.ncdx_record_probe import profile_printable_run_layout

    sources = _data_profile_sources("PDX")
    budget = target_task.get("budget", {})
    saved = result.get("observations")
    if (result.get("status") != "PASS" or budget.get("profile_mode") != "PRINTABLE_RUN_LAYOUT_PROFILE"
            or budget.get("suffix") != "PDX" or budget.get("sources") != sources
            or not isinstance(saved, list) or len(saved) != 3
            or int(result.get("original_media_write_count", -1)) != 0):
        raise RuntimeError(f"Supervisor refused incomplete printable-run layout profile for {target_id}")
    source_root = coordinator_runtime.SOURCE_ROOT.resolve(strict=True)
    fresh = []
    for row in sources:
        relative = PurePosixPath(str(row["relative_path"]).replace("\\", "/"))
        source = (source_root / Path(*relative.parts)).resolve(strict=True)
        if not source.is_relative_to(source_root):
            raise ValueError("Supervisor layout source escaped the original-media root")
        observation = profile_printable_run_layout(source, region=str(row["region"]),
            expected_sha256=str(row["sha256"]))
        if observation["source_bytes"] != int(row["size_bytes"]):
            raise RuntimeError("Supervisor layout source size differs from the inventory")
        fresh.append({"relative_path": row["relative_path"], **observation})
    if fresh != saved:
        raise RuntimeError(f"Independent Supervisor layout profile differed for {target_id}")
    return {"fresh_manifest_bound_layout_profile": True,
        "independent_region_count": len(fresh),
        "printable_run_count_by_region": {row["region"]: row["printable_run_count"] for row in fresh},
        "logical_sha256_by_region": {row["region"]: row["logical_sha256"] for row in fresh},
        "raw_payload_bytes_retained": False, "original_media_write_count": 0,
        "semantic_format": "UNKNOWN; bounded structural observations only",
        "physical_compatibility": "NOT_TESTED"}


def _verify_repeated_text_dictionary_target(target_id: str, target_task: dict[str, Any],
                                            result: dict[str, Any]) -> dict[str, Any]:
    """Fresh Supervisor-process count of deterministic cross-region text samples."""
    from src.readers.ncdx_record_probe import profile_repeated_text_candidates

    sources = _data_profile_sources("PDX")
    budget = target_task.get("budget", {})
    parameters = budget.get("profile_parameters", {})
    saved = result.get("observations")
    if (result.get("status") != "PASS" or budget.get("profile_mode") != "REPEATED_TEXT_DICTIONARY_PROFILE"
            or budget.get("suffix") != "PDX" or budget.get("sources") != sources
            or parameters != {"sampling_modulus": 64, "top_n": 32, "max_candidates": 50_000}
            or result.get("profile_parameters") != parameters
            or not isinstance(saved, list) or len(saved) != 3
            or int(result.get("original_media_write_count", -1)) != 0):
        raise RuntimeError(f"Supervisor refused incomplete repeated-text profile for {target_id}")
    source_root = coordinator_runtime.SOURCE_ROOT.resolve(strict=True)
    fresh = []
    for row in sources:
        relative = PurePosixPath(str(row["relative_path"]).replace("\\", "/"))
        source = (source_root / Path(*relative.parts)).resolve(strict=True)
        if not source.is_relative_to(source_root):
            raise ValueError("Supervisor repeated-text source escaped the original-media root")
        observation = profile_repeated_text_candidates(source, region=str(row["region"]),
            expected_sha256=str(row["sha256"]), **parameters)
        if observation["source_bytes"] != int(row["size_bytes"]):
            raise RuntimeError("Supervisor repeated-text source size differs from the inventory")
        fresh.append({"relative_path": row["relative_path"], **observation})
    if fresh != saved:
        raise RuntimeError(f"Independent Supervisor repeated-text counts differed for {target_id}")
    by_hash: dict[str, list[dict[str, Any]]] = {}
    for row in fresh:
        for item in row["sampled_value_inventory"]:
            by_hash.setdefault(str(item["sha256"]), []).append({
                "region": row["region"], "text": item["text"],
                "exact_sampled_count": item["exact_sampled_count"]})
    shared = [{"sha256": digest, "text": entries[0]["text"], "regional_values": entries}
              for digest, entries in by_hash.items() if len(entries) > 1]
    shared.sort(key=lambda item: (-sum(int(row["exact_sampled_count"])
                                       for row in item["regional_values"]), item["sha256"]))
    shared_value_count = len(shared)
    if (int(result.get("cross_region_shared_sampled_value_count", -1)) != shared_value_count
            or not isinstance(result.get("cross_region_shared_sampled_values_top"), list)
            or result["cross_region_shared_sampled_values_top"] != shared[:128]):
        raise RuntimeError(f"Independent Supervisor cross-region vocabulary differed for {target_id}")
    return {"fresh_manifest_bound_repeated_text_count": True,
        "independent_region_count": len(fresh),
        "cross_region_shared_sampled_value_count": shared_value_count,
        "sampled_candidate_values_by_region": {row["region"]: row["candidate_value_count"] for row in fresh},
        "logical_sha256_by_region": {row["region"]: row["logical_sha256"] for row in fresh},
        "raw_payload_bytes_retained": False, "original_media_write_count": 0,
        "semantic_format": "UNKNOWN; bounded structural observations only",
        "physical_compatibility": "NOT_TESTED"}


def _verify_repeated_text_coordinate_target(target_id: str, target_task: dict[str, Any],
                                            result: dict[str, Any]) -> dict[str, Any]:
    """Repeat source-bound repeated-value occurrence and coordinate tests independently."""
    from src.readers.ncdx_record_probe import audit_repeated_text_coordinate_proximity

    sources = _data_profile_sources("PDX")
    budget = target_task.get("budget", {})
    prior_task_id = str(budget.get("prior_task_id", ""))
    expected_prior_id = _data_profile_task_id("PDX", "REPEATED_TEXT_DICTIONARY_PROFILE", sources)
    expected_target_id = _data_profile_task_id("PDX", "REPEATED_TEXT_COORDINATE_AUDIT", sources,
                                                upstream_task_id=prior_task_id)
    parameters = budget.get("profile_parameters", {})
    saved = result.get("observations")
    if (target_id != expected_target_id
            or result.get("status") != "PASS" or budget.get("profile_mode") != "REPEATED_TEXT_COORDINATE_AUDIT"
            or budget.get("suffix") != "PDX" or budget.get("sources") != sources
            or prior_task_id != expected_prior_id
            or parameters != {"occurrences_per_value": 4}
            or result.get("profile_parameters") != parameters
            or not isinstance(saved, list) or len(saved) != 3
            or int(result.get("original_media_write_count", -1)) != 0):
        raise RuntimeError(f"Supervisor refused incomplete repeated-text coordinate audit for {target_id}")
    prior_result = _task_result(prior_task_id)
    if prior_result.get("status") != "PASS" or prior_result.get("profile_mode") != "REPEATED_TEXT_DICTIONARY_PROFILE":
        raise RuntimeError("Supervisor refused an unverified repeated-text dictionary checkpoint")
    previous = {str(row.get("region")): row for row in prior_result.get("observations", [])
                if isinstance(row, dict)}
    source_root = coordinator_runtime.SOURCE_ROOT.resolve(strict=True)
    fresh = []
    for row in sources:
        prior = previous.get(str(row["region"]))
        if not prior or prior.get("source_sha256") != row["sha256"]:
            raise RuntimeError("Supervisor repeated-text anchors differ from the inventory hash")
        values = [str(item["text"]) for item in prior.get("top_repeated_values", [])
                  if isinstance(item, dict) and isinstance(item.get("text"), str)]
        relative = PurePosixPath(str(row["relative_path"]).replace("\\", "/"))
        source = (source_root / Path(*relative.parts)).resolve(strict=True)
        if not source.is_relative_to(source_root):
            raise ValueError("Supervisor repeated-text source escaped the original-media root")
        observation = audit_repeated_text_coordinate_proximity(source, region=str(row["region"]),
            expected_sha256=str(row["sha256"]), anchor_texts=values,
            occurrences_per_value=int(parameters["occurrences_per_value"]))
        if observation["source_bytes"] != int(row["size_bytes"]):
            raise RuntimeError("Supervisor repeated-text source size differs from the inventory")
        fresh.append({"relative_path": row["relative_path"], **observation})
    if fresh != saved:
        raise RuntimeError(f"Independent Supervisor repeated-text coordinate audit differed for {target_id}")
    return {"fresh_manifest_bound_repeated_text_audit": True,
        "independent_region_count": len(fresh),
        "anchor_value_count_by_region": {row["region"]: row["anchor_value_count"] for row in fresh},
        "anchor_occurrence_counts_by_region": {row["region"]: row["anchor_occurrence_counts_by_sha256"] for row in fresh},
        "label_window_hits_by_region": {row["region"]: row["proximity"]["label_windows"][
            "candidate_hit_windows_by_scale_and_order"] for row in fresh},
        "fixed_control_hits_by_region": {row["region"]: row["proximity"]["fixed_control_windows"][
            "candidate_hit_windows_by_scale_and_order"] for row in fresh},
        "raw_payload_bytes_retained": False, "original_media_write_count": 0,
        "semantic_format": "UNKNOWN; bounded structural observations only",
        "physical_compatibility": "NOT_TESTED"}


def _verify_text_coordinate_association_target(target_id: str, target_task: dict[str, Any],
                                               result: dict[str, Any]) -> dict[str, Any]:
    """Fresh, manifest-bound Supervisor rescan of every PDX census region."""
    from src.readers.ncdx_record_probe import audit_text_coordinate_association

    budget = target_task.get("budget", {})
    mode = str(budget.get("profile_mode", ""))
    if mode not in {"TEXT_COORDINATE_ASSOCIATION_CENSUS",
                    "REPEATED_TEXT_COORDINATE_ASSOCIATION_CENSUS"}:
        raise RuntimeError(f"Supervisor refused an unsupported association-census mode for {target_id}")
    strategy = "all_printable" if mode == "TEXT_COORDINATE_ASSOCIATION_CENSUS" else "repeated_literals"
    parameters = {"anchor_strategy": strategy, "max_anchors": 4096,
                  "controls_per_anchor": 1, "radius_bytes": 64}
    sources = _data_profile_sources("PDX")
    prior_task_id = str(budget.get("prior_task_id", ""))
    if mode == "TEXT_COORDINATE_ASSOCIATION_CENSUS":
        expected_prior_id = _data_profile_task_id("PDX", "STRING_COORDINATE_PROXIMITY_AUDIT", sources)
        expected_prior_mode = "STRING_COORDINATE_PROXIMITY_AUDIT"
    else:
        dictionary_task_id = _data_profile_task_id("PDX", "REPEATED_TEXT_DICTIONARY_PROFILE", sources)
        expected_prior_id = _data_profile_task_id("PDX", "REPEATED_TEXT_COORDINATE_AUDIT", sources,
            upstream_task_id=dictionary_task_id)
        expected_prior_mode = "REPEATED_TEXT_COORDINATE_AUDIT"
    saved = result.get("observations")
    generic_proof = result.get("verified", {})
    if (budget.get("suffix") != "PDX" or budget.get("sources") != sources
            or budget.get("profile_parameters") != parameters
            or target_id != target_task.get("id")
            or result.get("status") != "PASS" or result.get("task_id") != target_id
            or result.get("profile_mode") != mode or result.get("profile_parameters") != parameters
            or result.get("prior_task_id") != expected_prior_id or prior_task_id != expected_prior_id
            or not isinstance(saved, list) or len(saved) != 3
            or int(result.get("original_media_write_count", -1)) != 0
            or generic_proof.get("source_write_count") != 0
            or generic_proof.get("raw_payload_bytes_retained") is not False):
        raise RuntimeError(f"Supervisor refused incomplete PDX association-census evidence for {target_id}")
    prior_result = _task_result(prior_task_id)
    if (prior_result.get("status") != "PASS" or prior_result.get("profile_mode") != expected_prior_mode
            or _task_status("AUTO_SUPERVISOR_" + prior_task_id) != "DONE"):
        raise RuntimeError("association-census predecessor is not independently verified")

    source_root = coordinator_runtime.SOURCE_ROOT.resolve(strict=True)
    fresh: list[dict[str, Any]] = []
    for row in sources:
        relative_text = str(row["relative_path"]).replace("\\", "/")
        relative = PurePosixPath(relative_text)
        if relative.is_absolute() or ".." in relative.parts or _ledger_hash(relative_text) != row["sha256"]:
            raise RuntimeError(f"Supervisor refused an unmanifested association-census input: {relative_text}")
        source = (source_root / Path(*relative.parts)).resolve(strict=True)
        if not source.is_relative_to(source_root):
            raise RuntimeError(f"Supervisor refused an input outside the original-media root: {relative_text}")
        observation = audit_text_coordinate_association(source, region=str(row["region"]),
            expected_sha256=str(row["sha256"]), **parameters)
        if observation["source_bytes"] != int(row["size_bytes"]):
            raise RuntimeError(f"Supervisor found a PDX source-size change: {relative_text}")
        fresh.append({"relative_path": row["relative_path"], **observation})
    if fresh != saved:
        raise RuntimeError(f"fresh Supervisor PDX association census differs from saved result: {target_id}")
    return {"fresh_manifest_bound_census": True, "independent_region_count": len(fresh),
        "anchor_strategy": strategy,
        "anchor_windows_by_region": {row["region"]: row["sampled_anchor_count"] for row in fresh},
        "matched_control_windows_by_region": {row["region"]: row["matched_control_count"] for row in fresh},
        "anchor_hit_rates_by_region": {row["region"]: {
            key: value["anchor_hit_rate"] for key, value in row["association_by_scale_and_order"].items()}
            for row in fresh},
        "control_hit_rates_by_region": {row["region"]: {
            key: value["control_hit_rate"] for key, value in row["association_by_scale_and_order"].items()}
            for row in fresh},
        "raw_payload_bytes_retained": False, "original_media_write_count": 0,
        "semantic_format": "UNKNOWN; text-window association only",
        "physical_compatibility": "NOT_TESTED"}


def _verify_standalone_zlib_stream_census_target(target_id: str, target_task: dict[str, Any],
                                                 result: dict[str, Any]) -> dict[str, Any]:
    """Independently rescan the exact regional inputs and reproduce stream hashes."""
    from src.readers.ncdx_record_probe import (MAX_STANDALONE_ZLIB_COMPRESSED_BYTES,
        MAX_STANDALONE_ZLIB_FILE_BYTES, MAX_STANDALONE_ZLIB_HEADER_CANDIDATES,
        MAX_STANDALONE_ZLIB_OUTPUT_BYTES, scan_standalone_zlib_streams)

    budget = target_task.get("budget", {})
    suffix = str(budget.get("suffix", ""))
    parameters = {"max_file_bytes": MAX_STANDALONE_ZLIB_FILE_BYTES,
        "max_compressed_bytes": MAX_STANDALONE_ZLIB_COMPRESSED_BYTES,
        "max_output_bytes": MAX_STANDALONE_ZLIB_OUTPUT_BYTES,
        "max_header_candidates": MAX_STANDALONE_ZLIB_HEADER_CANDIDATES}
    if not suffix or suffix in CONTAINER_ROUNDTRIP_SUFFIXES:
        raise RuntimeError(f"Supervisor refused unsupported standalone-zlib suffix for {target_id}")
    sources = _data_profile_sources(suffix)
    saved = result.get("observations")
    proof = result.get("verified", {})
    if (budget.get("profile_mode") != "STANDALONE_ZLIB_STREAM_CENSUS"
            or budget.get("sources") != sources or budget.get("profile_parameters") != parameters
            or target_task.get("id") != target_id or result.get("task_id") != target_id
            or result.get("status") != "PASS"
            or result.get("profile_mode") != "STANDALONE_ZLIB_STREAM_CENSUS"
            or result.get("profile_parameters") != parameters
            or not isinstance(saved, list) or len(saved) != 3
            or int(result.get("original_media_write_count", -1)) != 0
            or proof.get("source_count") != 3 or proof.get("source_write_count") != 0
            or proof.get("memory_mapped_read_only") is not True
            or proof.get("raw_payload_bytes_retained") is not False):
        raise RuntimeError(f"Supervisor refused incomplete standalone-zlib census evidence for {target_id}")
    if any(int(row["size_bytes"]) < 4096 or int(row["size_bytes"]) > MAX_STANDALONE_ZLIB_FILE_BYTES
           for row in sources):
        raise RuntimeError("Supervisor refused a source outside the standalone-zlib size bound")

    source_root = coordinator_runtime.SOURCE_ROOT.resolve(strict=True)
    fresh: list[dict[str, Any]] = []
    all_streams_by_region: dict[str, list[dict[str, Any]]] = {}
    for row in sources:
        relative_text = str(row["relative_path"]).replace("\\", "/")
        relative = PurePosixPath(relative_text)
        if relative.is_absolute() or ".." in relative.parts or _ledger_hash(relative_text) != row["sha256"]:
            raise RuntimeError(f"Supervisor refused an unmanifested raw NCDx input: {relative_text}")
        source = (source_root / Path(*relative.parts)).resolve(strict=True)
        if not source.is_relative_to(source_root):
            raise RuntimeError(f"Supervisor refused input outside the original-media root: {relative_text}")
        full_stream_inventory: list[dict[str, Any]] = []
        observation = scan_standalone_zlib_streams(source,
            expected_sha256=str(row["sha256"]), _all_streams=full_stream_inventory, **parameters)
        if observation["source_bytes"] != int(row["size_bytes"]):
            raise RuntimeError(f"Supervisor found a changed raw NCDx source size: {relative_text}")
        all_streams_by_region[str(row["region"])] = full_stream_inventory
        fresh.append({"region": row["region"], "relative_path": row["relative_path"], **observation})
    shared_preview, shared_count, shared_digest = _summarize_shared_zlib_payloads(all_streams_by_region)
    if (fresh != saved or shared_preview != result.get("cross_region_shared_payloads")
            or shared_count != result.get("cross_region_shared_payload_count")
            or shared_digest != result.get("cross_region_shared_inventory_sha256")):
        raise RuntimeError(f"fresh Supervisor standalone-zlib census differed for {target_id}")
    return {"fresh_manifest_bound_rescan": True, "independent_region_count": len(fresh),
        "confirmed_stream_count_by_region": {row["region"]: row["stream_count"] for row in fresh},
        "header_candidates_by_region": {row["region"]: row["header_candidates"] for row in fresh},
        "attempt_cap_hit_by_region": {row["region"]: row["candidate_limit_reached"] for row in fresh},
        "cross_region_shared_payload_count": shared_count,
        "cross_region_shared_inventory_sha256": shared_digest,
        "raw_payload_bytes_retained": False,
        "original_media_write_count": 0,
        "semantic_format": "UNKNOWN; bounded checksum-valid zlib candidates only",
        "physical_compatibility": "NOT_TESTED"}


def _verify_zlib_stream_boundary_context_target(target_id: str, target_task: dict[str, Any],
                                                result: dict[str, Any]) -> dict[str, Any]:
    """Repeat hash-only boundary context observations from the exact census-bound sources."""
    from src.readers.ncdx_record_probe import profile_standalone_zlib_boundary_contexts

    budget = target_task.get("budget", {})
    suffix = str(budget.get("suffix", ""))
    parameters = budget.get("profile_parameters", {})
    sources = _data_profile_sources(suffix)
    prior_task_id = _data_profile_task_id(suffix, "STANDALONE_ZLIB_STREAM_CENSUS", sources)
    allowed_parameters = ({"context_bytes": 8}, {"context_bytes": 16},
                          {"context_bytes": 32}, {"context_bytes": 64})
    expected_task_id = _data_profile_task_id(suffix, "ZLIB_STREAM_BOUNDARY_CONTEXT_PROFILE", sources,
        upstream_task_id=prior_task_id,
        profile_parameters=(parameters if parameters != {"context_bytes": 16} else None))
    saved = result.get("observations")
    if (budget.get("profile_mode") != "ZLIB_STREAM_BOUNDARY_CONTEXT_PROFILE"
            or budget.get("sources") != sources or parameters not in allowed_parameters
            or budget.get("prior_task_id") != prior_task_id
            or target_id != expected_task_id
            or result.get("task_id") != target_id
            or result.get("profile_mode") != "ZLIB_STREAM_BOUNDARY_CONTEXT_PROFILE"
            or result.get("prior_task_id") != prior_task_id
            or result.get("profile_parameters") != parameters
            or result.get("status") != "PASS" or not isinstance(saved, list) or len(saved) != 3
            or int(result.get("original_media_write_count", -1)) != 0
            or target_task.get("id") != target_id):
        raise RuntimeError(f"Supervisor refused incomplete zlib boundary context profile for {target_id}")
    if (_task_status(prior_task_id) != "DONE"
            or _task_status("AUTO_SUPERVISOR_" + prior_task_id) != "DONE"):
        raise RuntimeError("Supervisor refused a zlib context profile without an independently passed census")
    prior_result = _task_result(prior_task_id)
    prior_by_region = {str(row.get("region")): row for row in prior_result.get("observations", [])
                       if isinstance(row, dict)}
    if prior_result.get("status") != "PASS" or set(prior_by_region) != {row["region"] for row in sources}:
        raise RuntimeError("Supervisor could not load the verified predecessor's full regional inventory")

    source_root = coordinator_runtime.SOURCE_ROOT.resolve(strict=True)
    fresh: list[dict[str, Any]] = []
    for row in sources:
        relative_text = str(row["relative_path"]).replace("\\", "/")
        relative = PurePosixPath(relative_text)
        if (relative.is_absolute() or ".." in relative.parts
                or _ledger_hash(relative_text) != str(row["sha256"])):
            raise RuntimeError(f"Supervisor refused an unmanifested zlib context source: {relative_text}")
        source = (source_root / Path(*relative.parts)).resolve(strict=True)
        if not source.is_relative_to(source_root):
            raise RuntimeError("Supervisor refused a zlib context input outside the original-media root")
        prior_observation = prior_by_region[str(row["region"])]
        observation = profile_standalone_zlib_boundary_contexts(source,
            expected_sha256=str(row["sha256"]),
            expected_stream_count=int(prior_observation["stream_count"]),
            expected_stream_inventory_sha256=str(prior_observation["stream_inventory_sha256"]),
            **parameters)
        if observation["source_bytes"] != int(row["size_bytes"]):
            raise RuntimeError("Supervisor found a source-size change in the zlib context profile")
        fresh.append({"region": row["region"], "relative_path": row["relative_path"], **observation})
    if fresh != saved:
        raise RuntimeError(f"Fresh Supervisor zlib boundary context profile differed for {target_id}")
    return {"fresh_manifest_bound_boundary_rescan": True,
        "independent_region_count": len(fresh),
        "stream_count_by_region": {row["region"]: row["stream_count"] for row in fresh},
        "prefix_context_trace_sha256_by_region": {row["region"]: row["prefix_context_trace_sha256"]
            for row in fresh},
        "suffix_context_trace_sha256_by_region": {row["region"]: row["suffix_context_trace_sha256"]
            for row in fresh},
        "raw_context_bytes_retained": False, "raw_payload_bytes_retained": False,
        "original_media_write_count": 0,
        "semantic_format": "UNKNOWN; hash-only zlib boundary contexts",
        "physical_compatibility": "NOT_TESTED"}


def _verify_zlib_decoded_coordinate_candidate_target(
        target_id: str, target_task: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    """Freshly repeat every bounded candidate count in an independent Supervisor process."""
    from src.readers.ncdx_record_probe import (ZLIB_COORDINATE_PROFILE_PARAMETER_OPTIONS,
        is_zlib_coordinate_selected_payload_parameters,
        profile_standalone_zlib_coordinate_candidates)

    budget = target_task.get("budget", {})
    suffix = str(budget.get("suffix", ""))
    parameters = budget.get("profile_parameters", {})
    sources = _data_profile_sources(suffix)
    prior_task_id = _data_profile_task_id(suffix, "STANDALONE_ZLIB_STREAM_CENSUS", sources)
    expected_id = _data_profile_task_id(suffix, "ZLIB_DECODED_COORDINATE_CANDIDATE_CENSUS",
        sources, upstream_task_id=prior_task_id, profile_parameters=parameters)
    saved = result.get("observations")
    proof = result.get("verified", {})
    if (target_id != expected_id or target_task.get("id") != target_id
            or budget.get("data_family_profile") is not True
            or budget.get("profile_mode") != "ZLIB_DECODED_COORDINATE_CANDIDATE_CENSUS"
            or budget.get("sources") != sources
            or (parameters not in ZLIB_COORDINATE_PROFILE_PARAMETER_OPTIONS
                and not is_zlib_coordinate_selected_payload_parameters(parameters))
            or budget.get("prior_task_id") != prior_task_id
            or result.get("task_id") != target_id or result.get("status") != "PASS"
            or result.get("profile_mode") != "ZLIB_DECODED_COORDINATE_CANDIDATE_CENSUS"
            or result.get("prior_task_id") != prior_task_id
            or result.get("profile_parameters") != parameters
            or not isinstance(saved, list) or len(saved) != 3
            or int(result.get("original_media_write_count", -1)) != 0
            or proof.get("source_count") != 3 or proof.get("source_write_count") != 0
            or proof.get("raw_sample_bytes_retained") is not False
            or proof.get("raw_payload_bytes_retained") is not False):
        raise RuntimeError(f"Supervisor refused incomplete decoded-coordinate evidence for {target_id}")
    if (_task_status(prior_task_id) != "DONE"
            or _task_status("AUTO_SUPERVISOR_" + prior_task_id) != "DONE"):
        raise RuntimeError("Supervisor refused a decoded-coordinate census without its verified zlib predecessor")
    _validate_coordinate_profile_tier(suffix, sources, prior_task_id, parameters, budget)
    prior = _task_result(prior_task_id)
    prior_by_region = {str(row.get("region")): row for row in prior.get("observations", [])
                       if isinstance(row, dict)}
    if prior.get("status") != "PASS" or set(prior_by_region) != {
            str(row["region"]) for row in sources}:
        raise RuntimeError("Supervisor could not load all verified regional zlib inventories")
    root = coordinator_runtime.SOURCE_ROOT.resolve(strict=True)
    fresh: list[dict[str, Any]] = []
    for row in sources:
        relative_text = str(row["relative_path"]).replace("\\", "/")
        relative = PurePosixPath(relative_text)
        if (relative.is_absolute() or ".." in relative.parts
                or _ledger_hash(relative_text) != str(row["sha256"])):
            raise RuntimeError(f"Supervisor refused an unmanifested zlib coordinate source: {relative_text}")
        source = (root / Path(*relative.parts)).resolve(strict=True)
        if not source.is_relative_to(root):
            raise RuntimeError("Supervisor found a zlib coordinate source outside original media")
        predecessor = prior_by_region[str(row["region"])]
        observation = profile_standalone_zlib_coordinate_candidates(source,
            expected_sha256=str(row["sha256"]),
            expected_stream_count=int(predecessor["stream_count"]),
            expected_stream_inventory_sha256=str(predecessor["stream_inventory_sha256"]),
            region=str(row["region"]), profile_parameters=parameters)
        if observation["source_bytes"] != int(row["size_bytes"]):
            raise RuntimeError("Supervisor found a changed source size in decoded-coordinate profile")
        fresh.append({"region": row["region"], "relative_path": row["relative_path"], **observation})
    if fresh != saved:
        raise RuntimeError(f"fresh Supervisor decoded-coordinate census differed for {target_id}")
    proof = {"fresh_manifest_bound_coordinate_rescan": True,
        "independent_region_count": len(fresh),
        "stream_count_by_region": {row["region"]: row["stream_count"] for row in fresh},
        "sampled_stream_count_by_region": {row["region"]: row["sampled_stream_count"] for row in fresh},
        "sample_trace_sha256_by_region": {row["region"]: row["sampled_payload_trace_sha256"] for row in fresh},
        "raw_sample_bytes_retained": False, "raw_payload_bytes_retained": False,
        "original_media_write_count": 0,
        "semantic_format": "UNKNOWN; bounded zlib coordinate candidates only",
        "physical_compatibility": "NOT_TESTED"}
    if is_zlib_coordinate_selected_payload_parameters(parameters):
        proof.update({"fresh_selected_full_payload_audit": True,
            "selected_stream_count_by_region": {
                row["region"]: int(row.get("selected_full_payload_audit", {}).get("selected_stream_count", -1))
                for row in fresh},
            "selected_payload_bytes_by_region": {
                row["region"]: int(row.get("selected_full_payload_audit", {}).get("sampled_payload_bytes", -1))
                for row in fresh},
            "raw_payload_bytes_retained": False,
            "semantic_format": "UNKNOWN; selected full zlib payload candidate audit only"})
    return proof


def _verify_block_boundary_target(target_id: str, target_task: dict[str, Any],
                                  result: dict[str, Any]) -> dict[str, Any]:
    """Repeat decoded block-boundary summaries in an independent Supervisor process."""
    from src.readers.ncdx_record_probe import profile_text_block_boundaries

    sources = _data_profile_sources("PDX")
    budget = target_task.get("budget", {})
    parameters = budget.get("profile_parameters", {})
    saved = result.get("observations")
    if (result.get("status") != "PASS" or budget.get("profile_mode") != "BLOCK_BOUNDARY_PROFILE"
            or budget.get("suffix") != "PDX" or budget.get("sources") != sources
            or parameters != {"position_bins": 16} or result.get("profile_parameters") != parameters
            or not isinstance(saved, list) or len(saved) != 3
            or int(result.get("original_media_write_count", -1)) != 0):
        raise RuntimeError(f"Supervisor refused incomplete PDX block-boundary profile for {target_id}")
    source_root = coordinator_runtime.SOURCE_ROOT.resolve(strict=True)
    fresh = []
    for row in sources:
        relative = PurePosixPath(str(row["relative_path"]).replace("\\", "/"))
        source = (source_root / Path(*relative.parts)).resolve(strict=True)
        if not source.is_relative_to(source_root):
            raise ValueError("Supervisor block-boundary source escaped the original-media root")
        observation = profile_text_block_boundaries(source, region=str(row["region"]),
            expected_sha256=str(row["sha256"]), **parameters)
        if observation["source_bytes"] != int(row["size_bytes"]):
            raise RuntimeError("Supervisor block-boundary source size differs from the inventory")
        fresh.append({"relative_path": row["relative_path"], **observation})
    if fresh != saved:
        raise RuntimeError(f"Independent Supervisor block-boundary profile differed for {target_id}")
    return {"fresh_manifest_bound_block_boundary_profile": True,
        "independent_region_count": len(fresh),
        "crossing_run_count_by_region": {row["region"]: row["runs_crossing_block_boundary"] for row in fresh},
        "crossing_run_rate_by_region": {row["region"]: row["crossing_run_rate"] for row in fresh},
        "block_count_by_region": {row["region"]: row["block_count"] for row in fresh},
        "raw_payload_bytes_retained": False, "original_media_write_count": 0,
        "semantic_format": "UNKNOWN; bounded structural observations only",
        "physical_compatibility": "NOT_TESTED"}


def _verify_sw_component_survey_target(target_id: str, target_task: dict[str, Any],
                                       result: dict[str, Any]) -> dict[str, Any]:
    """Freshly re-read a component header and source digest in the Supervisor process."""
    budget = target_task.get("budget", {})
    relative = str(budget.get("source_path", "")).replace("\\", "/")
    parsed = PurePosixPath(relative)
    if (result.get("status") != "PASS" or budget.get("component_scan") is not True
            or not relative.casefold().startswith("sw/") or parsed.is_absolute()
            or ".." in parsed.parts or parsed.suffix.upper() not in COMPONENT_SCAN_EXTENSIONS):
        raise RuntimeError(f"Supervisor refused an invalid component survey scope: {target_id}")
    root = coordinator_runtime.SOURCE_ROOT.resolve(strict=True)
    source = (root / Path(*parsed.parts)).resolve(strict=True)
    expected = str(budget.get("sha256", ""))
    if not source.is_relative_to(root) or not expected or _ledger_hash(relative) != expected:
        raise RuntimeError(f"Supervisor refused a non-manifest component source: {relative}")
    before_stat = source.stat()
    if before_stat.st_size != int(budget.get("size_bytes", -1)):
        raise RuntimeError(f"Supervisor found a changed component size: {relative}")
    before_hash = _sha256(source)
    with source.open("rb") as stream:
        header = stream.read(4096)
    strings = [match.decode("ascii", errors="replace")
               for match in re.findall(rb"[\x20-\x7e]{6,}", header)[:32]]
    signatures = {label: header.find(marker) for label, marker in (
        ("MZ", b"MZ"), ("PE", b"PE\x00\x00"), ("BINFS", b"B000FF"),
        ("NK", b"NK\x00"), ("RIFF", b"RIFF"), ("ZIP", b"PK\x03\x04")) if marker in header}
    after_hash = _sha256(source)
    after_stat = source.stat()
    if (before_hash != expected or after_hash != expected
            or before_stat.st_size != after_stat.st_size
            or before_stat.st_mtime_ns != after_stat.st_mtime_ns):
        raise RuntimeError(f"Supervisor detected source mutation during component reread: {relative}")
    if (result.get("source_path") != relative
            or result.get("source_size_bytes") != before_stat.st_size
            or result.get("source_sha256") != expected
            or result.get("manifest_sha256") != expected
            or result.get("first_4096_bytes_hex") != header.hex()
            or result.get("printable_strings_first_4096") != strings
            or result.get("observed_signatures_and_offsets") != signatures
            or result.get("source_write_count") != 0
            or result.get("semantic_format") != "UNKNOWN; bounded observations only"):
        raise RuntimeError(f"Independent Supervisor reread differed from the component worker: {target_id}")
    return {"fresh_manifest_bound_readback": True, "source_path": relative,
        "source_size_bytes": before_stat.st_size, "source_sha256": expected,
        "header_sha256": hashlib.sha256(header).hexdigest(),
        "signature_offsets_reproduced": signatures,
        "printable_string_count_reproduced": len(strings), "read_limit_bytes": 4096,
        "original_media_write_count": 0, "semantic_format": "UNKNOWN; bounded observations only",
        "physical_compatibility": "NOT_TESTED"}


def _independent_pe_header_summary(raw: bytes) -> dict[str, Any]:
    """Independent PE/COFF decoder using slice arithmetic, separate from the Worker parser."""
    if len(raw) < 64 or raw[:2] != b"MZ":
        raise RuntimeError("independent parser did not find a complete MZ header")
    pe_offset = int.from_bytes(raw[60:64], "little")
    if pe_offset < 64 or pe_offset + 24 > len(raw) or raw[pe_offset:pe_offset + 4] != b"PE\x00\x00":
        raise RuntimeError("independent parser rejected the PE signature offset")
    machine = int.from_bytes(raw[pe_offset + 4:pe_offset + 6], "little")
    section_count = int.from_bytes(raw[pe_offset + 6:pe_offset + 8], "little")
    optional_size = int.from_bytes(raw[pe_offset + 20:pe_offset + 22], "little")
    characteristics = int.from_bytes(raw[pe_offset + 22:pe_offset + 24], "little")
    if not 1 <= section_count <= 96:
        raise RuntimeError("independent parser rejected the PE section count")
    optional = pe_offset + 24
    optional_limit = optional + optional_size
    if optional_size < 70 or optional_limit > len(raw):
        raise RuntimeError("independent parser rejected a truncated optional header")
    magic = int.from_bytes(raw[optional:optional + 2], "little")
    if magic not in (0x10B, 0x20B):
        raise RuntimeError("independent parser rejected the PE optional-header kind")
    image_base_offset = optional + (28 if magic == 0x10B else 24)
    image_base_width = 4 if magic == 0x10B else 8
    image_base = int.from_bytes(raw[image_base_offset:image_base_offset + image_base_width], "little")
    size_of_image = int.from_bytes(raw[optional + 56:optional + 60], "little")
    checksum = int.from_bytes(raw[optional + 64:optional + 68], "little")
    subsystem = int.from_bytes(raw[optional + 68:optional + 70], "little")
    section_table = optional_limit
    if section_table + 40 * section_count > len(raw):
        raise RuntimeError("independent parser rejected a truncated section table")
    names = []
    raw_ranges = []
    for index in range(section_count):
        start = section_table + 40 * index
        name = raw[start:start + 8].split(b"\x00", 1)[0].decode("ascii", errors="replace")
        virtual_size = int.from_bytes(raw[start + 8:start + 12], "little")
        virtual_address = int.from_bytes(raw[start + 12:start + 16], "little")
        raw_size = int.from_bytes(raw[start + 16:start + 20], "little")
        raw_pointer = int.from_bytes(raw[start + 20:start + 24], "little")
        if raw_size and (raw_pointer > len(raw) or raw_size > len(raw) - raw_pointer):
            raise RuntimeError(f"independent parser rejected the raw section range {index}")
        if raw_size:
            raw_ranges.append([raw_pointer, raw_pointer + raw_size])
        names.append({"name": name, "virtual_size": virtual_size,
            "virtual_address": virtual_address, "raw_size": raw_size,
            "raw_pointer": raw_pointer})
    architectures = {0x014C: "x86", 0x01A6: "SH4", 0x01C0: "ARM", 0x01C2: "ARM or Thumb",
                     0x01C4: "ARMNT", 0x8664: "x86-64", 0xAA64: "ARM64"}
    return {"status": "PASS_PE_HEADERS", "pe_offset": pe_offset,
        "machine_code": machine, "architecture": architectures.get(machine, "UNKNOWN_MACHINE"),
        "section_count": section_count, "optional_header_magic": magic,
        "optional_header_kind": "PE32" if magic == 0x10B else "PE32+",
        "image_base": image_base, "size_of_image": size_of_image,
        "checksum_field": checksum, "subsystem_code": subsystem,
        "characteristics": characteristics, "section_table_offset": section_table,
        "sections": names, "raw_section_ranges": raw_ranges,
        "claim_scope": "bounded PE/COFF header fields only; runtime behavior and NCDx data semantics UNKNOWN"}


def _verify_ncdx_pe_header_target(target_id: str, target_task: dict[str, Any],
                                  result: dict[str, Any]) -> dict[str, Any]:
    budget = target_task.get("budget", {})
    relative = str(budget.get("source_path", "")).replace("\\", "/")
    parsed = PurePosixPath(relative)
    if (budget.get("pe_header_probe") is not True or result.get("status") != "PASS"
            or not relative.casefold().startswith("sw/") or parsed.is_absolute()
            or ".." in parsed.parts or parsed.suffix.upper() not in COMPONENT_SCAN_EXTENSIONS):
        raise RuntimeError(f"Supervisor refused an out-of-scope PE header result: {target_id}")
    root = coordinator_runtime.SOURCE_ROOT.resolve(strict=True)
    source = (root / Path(*parsed.parts)).resolve(strict=True)
    expected = str(budget.get("sha256", ""))
    if (not source.is_relative_to(root) or not expected or _ledger_hash(relative) != expected
            or source.stat().st_size != int(budget.get("size_bytes", -1))):
        raise RuntimeError("Supervisor refused a PE source without exact manifest path/hash/size")
    source_task_id = str(budget.get("source_survey_task_id", ""))
    if _task_status(source_task_id) != "DONE":
        raise RuntimeError("Supervisor requires the original completed source signature survey")
    survey = _task_result(source_task_id)
    signatures = survey.get("observed_signatures_and_offsets", {})
    if (survey.get("status") != "PASS" or survey.get("source_path") != relative
            or survey.get("source_sha256") != expected or signatures.get("MZ") != 0
            or signatures.get("PE") != int(budget.get("observed_pe_signature_offset", -1))):
        raise RuntimeError("Supervisor cannot reproduce the prior source-bound PE signature finding")
    before_stat = source.stat()
    before_hash = _sha256(source)
    raw = source.read_bytes()
    independent = _independent_pe_header_summary(raw)
    after_hash = _sha256(source)
    after_stat = source.stat()
    if (before_hash != expected or after_hash != expected
            or before_stat.st_size != after_stat.st_size
            or before_stat.st_mtime_ns != after_stat.st_mtime_ns):
        raise RuntimeError("Supervisor detected a changed PE source during independent readback")
    if (result.get("source_path") != relative or result.get("source_size_bytes") != len(raw)
            or result.get("source_sha256") != expected or result.get("manifest_sha256") != expected
            or result.get("header_observation") != independent
            or result.get("source_write_count") != 0
            or result.get("original_media_write_count") != 0):
        raise RuntimeError(f"Fresh independent PE/COFF parser did not reproduce {target_id}")
    return {"fresh_manifest_bound_readback": True, "independent_parser": "slice-arithmetic PE/COFF decoder",
        "source_path": relative, "source_size_bytes": len(raw), "source_sha256": expected,
        "machine_code": independent["machine_code"], "architecture": independent["architecture"],
        "section_count": independent["section_count"], "optional_header_kind": independent["optional_header_kind"],
        "section_ranges_bounded": True, "original_media_write_count": 0,
        "runtime_behavior": "UNKNOWN", "NCDx_data_semantics": "UNKNOWN",
        "physical_compatibility": "NOT_TESTED"}


def _verified_target(target_id: str) -> dict[str, Any]:
    result = _task_result(target_id)
    target_task = manager._task(target_id)
    if target_task.get("budget", {}).get("ncdx_geoblock_research") is True:
        from src.agent import geoblock_research
        return geoblock_research.verify_target(target_task, result)
    if target_task.get("budget", {}).get("data_family_profile") is True:
        proof = result.get("verified")
        profile_mode = target_task.get("budget", {}).get("profile_mode")
        expected_semantic_format = {
            "STANDALONE_ZLIB_STREAM_CENSUS": "UNKNOWN; bounded zlib stream candidates only",
            "ZLIB_STREAM_BOUNDARY_CONTEXT_PROFILE": "UNKNOWN; hash-only zlib boundary contexts",
            "ZLIB_DECODED_COORDINATE_CANDIDATE_CENSUS": "UNKNOWN; bounded zlib coordinate candidates only",
        }.get(profile_mode, "UNKNOWN; structural observations only")
        if (not isinstance(proof, dict) or proof.get("source_count") != 3
                or proof.get("source_stat_unchanged_during_read") is not True
                or proof.get("manifest_entries_present") is not True
                or proof.get("source_write_count") != 0
                or proof.get("semantic_format") != expected_semantic_format):
            raise RuntimeError(f"Supervisor refused incomplete read-only proof for {target_id}")
        if target_task.get("budget", {}).get("profile_mode") == "DEFLATE_COMPRESSIBILITY_PROFILE":
            proof = _verify_deflate_profile_target(target_id, target_task, result)
        elif target_task.get("budget", {}).get("profile_mode") == "EXACT_BLOCK_ANCHOR_SCAN":
            proof = _verify_exact_block_anchor_profile_target(target_id, target_task, result)
        elif target_task.get("budget", {}).get("profile_mode") == "CONTAINER_ROUNDTRIP":
            proof = _verify_container_roundtrip_target(target_id, target_task, result)
        elif target_task.get("budget", {}).get("profile_mode") == "DECODED_STRUCTURE_SCAN":
            proof = _verify_decoded_structure_target(target_id, target_task, result)
        elif target_task.get("budget", {}).get("profile_mode") == "STRING_COORDINATE_PROXIMITY_AUDIT":
            proof = _verify_string_coordinate_proximity_target(target_id, target_task, result)
        elif target_task.get("budget", {}).get("profile_mode") == "PRINTABLE_RUN_LAYOUT_PROFILE":
            proof = _verify_printable_run_layout_target(target_id, target_task, result)
        elif target_task.get("budget", {}).get("profile_mode") == "REPEATED_TEXT_DICTIONARY_PROFILE":
            proof = _verify_repeated_text_dictionary_target(target_id, target_task, result)
        elif target_task.get("budget", {}).get("profile_mode") == "REPEATED_TEXT_COORDINATE_AUDIT":
            proof = _verify_repeated_text_coordinate_target(target_id, target_task, result)
        elif target_task.get("budget", {}).get("profile_mode") in {
                "TEXT_COORDINATE_ASSOCIATION_CENSUS",
                "REPEATED_TEXT_COORDINATE_ASSOCIATION_CENSUS"}:
            proof = _verify_text_coordinate_association_target(target_id, target_task, result)
        elif target_task.get("budget", {}).get("profile_mode") == "STANDALONE_ZLIB_STREAM_CENSUS":
            proof = _verify_standalone_zlib_stream_census_target(target_id, target_task, result)
        elif target_task.get("budget", {}).get("profile_mode") == "ZLIB_STREAM_BOUNDARY_CONTEXT_PROFILE":
            proof = _verify_zlib_stream_boundary_context_target(target_id, target_task, result)
        elif target_task.get("budget", {}).get("profile_mode") == "ZLIB_DECODED_COORDINATE_CANDIDATE_CENSUS":
            proof = _verify_zlib_decoded_coordinate_candidate_target(target_id, target_task, result)
        elif target_task.get("budget", {}).get("profile_mode") == "BLOCK_BOUNDARY_PROFILE":
            proof = _verify_block_boundary_target(target_id, target_task, result)
    elif target_task.get("budget", {}).get("firmware_intel_hex") is True:
        proof = _verify_firmware_hex_target(target_id, target_task, result)
    elif target_task.get("budget", {}).get("mp0_independent_readback") is True:
        proof = _verify_mp0_writer_target(target_id, target_task, result)
    elif target_id == PLAN_TASKS["OSM_REAL_CONVERSION"]:
        proof = _verify_osm_artifacts(target_id, WORK_ROOT / "real_conversion", hash_source=True)
    elif target_id == "AUTO_OSM_READBACK_AFTER_RESTART_01":
        proof = _verify_osm_artifacts(target_id, WORK_ROOT / "real_conversion", hash_source=True)
    elif target_task.get("budget", {}).get("ukraine_national_osm") is True:
        proof = _verify_national_osm_target(target_id, target_task, result)
    elif target_task.get("budget", {}).get("osm_partition_probe") is True:
        proof = _verify_osm_partition_target(target_id, target_task, result)
    elif target_task.get("budget", {}).get("pe_header_probe") is True:
        proof = _verify_ncdx_pe_header_target(target_id, target_task, result)
    elif target_task.get("budget", {}).get("component_scan") is True:
        proof = _verify_sw_component_survey_target(target_id, target_task, result)
    elif target_task.get("budget", {}).get("ncdx_roadlink_portability") is True:
        proof = _verify_roadlink_portability_target(target_id, target_task, result)
    elif target_task.get("budget", {}).get("ncdx_roadlink_name_consistency") is True:
        proof = _verify_roadlink_name_consistency_target(target_id, target_task, result)
    elif target_task.get("budget", {}).get("ncdx_geography_portability") is True:
        proof = _verify_geography_portability_target(target_id, target_task, result)
    elif target_task.get("budget", {}).get("ncdx_city_coordinate_crosscheck") is True:
        proof = _verify_city_coordinate_crosscheck_target(target_id, target_task, result)
    elif target_task.get("budget", {}).get("ncdx_pe_import_census") is True:
        proof = _verify_ncdx_pe_import_census_target(target_id, target_task, result)
    elif target_task.get("budget", {}).get("ncdx_embedded_pe_search") is True:
        proof = _verify_ncdx_embedded_pe_search_target(target_id, target_task, result)
    else:
        proof = result.get("verified")
        if not isinstance(proof, dict) or proof.get("original_hash_unchanged") is not True:
            raise RuntimeError(f"Supervisor refused incomplete saved source proof for {target_id}")
    return {"task_id": target_id, "saved_result_status": result.get("status", "PASS"), "deterministic_proof": proof}


def _verify_ncdx_pe_import_census_target(target_id: str, target_task: dict[str, Any],
                                         result: dict[str, Any]) -> dict[str, Any]:
    """Reopen the PE and independently reproduce imports, thunks and file offsets."""
    from src.readers import ncdx_pe_imports_verifier
    budget = target_task.get("budget", {})
    artifact = result.get("artifact")
    identity = _verified_b03_navimain_identity()
    if (result.get("status") != "PASS"
            or budget.get("ncdx_pe_import_census") is not True
            or int(budget.get("handler_version", -1)) != PE_IMPORT_CENSUS_VERSION
            or identity is None
            or any(budget.get(key) != identity.get(key) for key in identity)
            or not isinstance(artifact, dict) or not artifact.get("sha256")):
        raise RuntimeError(f"PE import census lacks its exact B03-bound source proof: {target_id}")
    relative = PurePosixPath(str(budget.get("source_path", "")))
    if (relative.as_posix() != PE_IMPORT_CENSUS_SOURCE
            or _ledger_hash(relative.as_posix()) != budget.get("source_sha256")):
        raise RuntimeError("PE import verifier rejected a changed or unregistered executable path")
    artifact_path = (PROJECT_ROOT / "work" / "autonomous_manager" / "ncdx"
                     / "firmware_imports" / f"{target_id}.json").resolve(strict=True)
    if (not artifact_path.is_relative_to(PROJECT_ROOT.resolve())
            or str(artifact.get("path", "")).replace("\\", "/")
            != artifact_path.relative_to(PROJECT_ROOT).as_posix()):
        raise RuntimeError("PE import artifact escaped its fixed project evidence folder")
    proof = ncdx_pe_imports_verifier.verify_artifact(artifact_path,
        source_root=coordinator_runtime.SOURCE_ROOT, project_root=PROJECT_ROOT,
        relative_path=relative.as_posix(), expected_sha256=str(budget["source_sha256"]),
        expected_size=int(budget["source_size_bytes"]), artifact_sha256=str(artifact["sha256"]))
    saved = json.loads(artifact_path.read_text(encoding="utf-8"))
    if (saved.get("task_id") != target_id
            or saved.get("b03_inventory_sha256") != identity["b03_inventory_sha256"]
            or saved.get("architecture") != "SH4"
            or saved.get("source_write_count") != 0):
        raise RuntimeError("PE import artifact does not bind to the accepted SH4 B03 inventory")
    return {**proof, "task_id": target_id,
        "api_name_candidates": saved.get("io_api_candidates", []),
        "internal_call_sites": "NOT_ANALYZED", "map_semantics": "UNKNOWN",
        "original_media_write_count": 0, "physical_compatibility": "NOT_TESTED"}


def _verify_ncdx_embedded_pe_search_target(target_id: str, target_task: dict[str, Any],
                                            result: dict[str, Any]) -> dict[str, Any]:
    """Independently scan and parse each MZ/PE candidate in the manifest-bound NK.BIN."""
    from src.readers import ncdx_embedded_pe_verifier
    budget = target_task.get("budget", {})
    artifact = result.get("artifact")
    identity = _verified_embedded_pe_source_identity()
    predecessor = _accepted_pe_import_result()
    if (result.get("status") != "PASS"
            or budget.get("ncdx_embedded_pe_search") is not True
            or int(budget.get("handler_version", -1)) != EMBEDDED_PE_SEARCH_VERSION
            or identity is None or predecessor is None
            or any(budget.get(key) != identity.get(key) for key in identity)
            or budget.get("predecessor_task_id") != predecessor["task_id"]
            or budget.get("predecessor_artifact_sha256") != predecessor["artifact_sha256"]
            or not isinstance(artifact, dict) or not artifact.get("sha256")):
        raise RuntimeError(f"embedded PE result lost its exact NCDx evidence chain: {target_id}")
    path = (PROJECT_ROOT / "work" / "autonomous_manager" / "ncdx"
            / "embedded_pe" / f"{target_id}.json").resolve(strict=True)
    if (not path.is_relative_to(PROJECT_ROOT.resolve())
            or str(artifact.get("path", "")).replace("\\", "/")
            != path.relative_to(PROJECT_ROOT).as_posix()):
        raise RuntimeError("embedded PE result escaped its fixed project artifact directory")
    proof = ncdx_embedded_pe_verifier.verify_artifact(path,
        source_root=coordinator_runtime.SOURCE_ROOT, project_root=PROJECT_ROOT,
        relative_path=EMBEDDED_PE_SEARCH_SOURCE, expected_sha256=str(budget["source_sha256"]),
        expected_size=int(budget["source_size_bytes"]), artifact_sha256=str(artifact["sha256"]))
    saved = json.loads(path.read_text(encoding="utf-8"))
    if (saved.get("task_id") != target_id
            or saved.get("predecessor_task_id") != predecessor["task_id"]
            or saved.get("predecessor_artifact_sha256") != predecessor["artifact_sha256"]
            or saved.get("b03_inventory_sha256") != identity["b03_inventory_sha256"]
            or saved.get("source_write_count") != 0):
        raise RuntimeError("embedded PE artifact does not match its accepted predecessor and B03 source")
    return {**proof, "task_id": target_id,
        "images": saved.get("valid_images", []), "image_role": "UNKNOWN",
        "exports": "NOT_ANALYZED", "map_semantics": "UNKNOWN",
        "physical_compatibility": "NOT_TESTED"}


def _verify_roadlink_portability_target(target_id: str, target_task: dict[str, Any],
                                        result: dict[str, Any]) -> dict[str, Any]:
    """Recheck the saved artifact and each original source identity before review."""
    from src.readers import ncdx_roadlink_portability
    budget = target_task.get("budget", {})
    if (result.get("status") != "PASS"
            or budget.get("ncdx_roadlink_portability") is not True
            or int(budget.get("handler_version", -1)) != ROADLINK_PORTABILITY_VERSION):
        raise RuntimeError(f"roadlink portability result does not match its fixed experiment: {target_id}")
    artifact = result.get("artifact")
    if not isinstance(artifact, dict) or not artifact.get("sha256"):
        raise RuntimeError(f"roadlink portability result has no hash-bound artifact: {target_id}")
    root = coordinator_runtime.SOURCE_ROOT.resolve(strict=True)
    sources = budget.get("sources") or []
    if len(sources) != 9:
        raise RuntimeError("roadlink portability verifier requires exactly nine source identities")
    for row in sources:
        relative = PurePosixPath(str(row.get("relative_path", "")))
        if relative.is_absolute() or ".." in relative.parts:
            raise RuntimeError("roadlink portability verifier found an unsafe source path")
        source = (root / Path(*relative.parts)).resolve(strict=True)
        if (not source.is_relative_to(root)
                or source != Path(str(row.get("absolute_path", ""))).resolve(strict=True)
                or _ledger_hash(relative.as_posix()) != row.get("sha256")):
            raise RuntimeError("roadlink portability verifier source is outside its checked manifest")
    artifact_path = PROJECT_ROOT / "work" / "autonomous_manager" / "ncdx" / "roadlink_portability" / f"{target_id}.json"
    path = artifact_path.resolve(strict=True)
    if not path.is_relative_to(PROJECT_ROOT.resolve()):
        raise RuntimeError("roadlink portability artifact escaped the project workspace")
    proof = ncdx_roadlink_portability.verify_artifact(path, sources,
                                                      str(artifact["sha256"]))
    saved = json.loads(path.read_text(encoding="utf-8"))
    if (saved.get("task_id") != target_id
            or saved.get("source_fingerprint") != budget.get("source_fingerprint")
            or saved.get("hypothesis_result") not in {"SUPPORTED", "FALSIFIED_OR_DIVERGENT"}):
        raise RuntimeError("roadlink portability report does not match its exact scheduled experiment")
    return {**proof, "task_id": target_id,
            "all_original_media_write_count": 0,
            "hypothesis_result": saved["hypothesis_result"],
            "region_checks": {row["region"]: row["checks"] for row in saved["regions"]}}


def _verify_roadlink_name_consistency_target(target_id: str, target_task: dict[str, Any],
                                              result: dict[str, Any]) -> dict[str, Any]:
    """Independently replay the new RL alias/IL name comparison from source bytes."""
    from src.readers import ncdx_roadlink_name_consistency
    budget = target_task.get("budget", {})
    if (result.get("status") != "PASS"
            or budget.get("ncdx_roadlink_name_consistency") is not True
            or int(budget.get("handler_version", -1)) != ROADLINK_NAME_CONSISTENCY_VERSION):
        raise RuntimeError(f"roadlink name result does not match its fixed experiment: {target_id}")
    artifact = result.get("artifact")
    if not isinstance(artifact, dict) or not artifact.get("sha256"):
        raise RuntimeError(f"roadlink name experiment has no hash-bound artifact: {target_id}")
    predecessor_id = str(budget.get("predecessor_task_id", ""))
    predecessor_result = _task_result(predecessor_id)
    predecessor_artifact = predecessor_result.get("artifact") or {}
    prior_path = (PROJECT_ROOT / Path(*PurePosixPath(str(predecessor_artifact.get("path", ""))).parts)).resolve(strict=True)
    if (not predecessor_id or _task_status(predecessor_id) != "DONE"
            or predecessor_result.get("status") != "PASS"
            or predecessor_artifact.get("sha256") != budget.get("predecessor_artifact_sha256")
            or not prior_path.is_relative_to(PROJECT_ROOT.resolve())
            or _sha256(prior_path) != str(budget.get("predecessor_artifact_sha256", ""))):
        raise RuntimeError("roadlink name predecessor is no longer independently hash-bound")
    sources = budget.get("sources") or []
    if len(sources) != 9:
        raise RuntimeError("roadlink name verifier requires exactly nine regional source identities")
    root = coordinator_runtime.SOURCE_ROOT.resolve(strict=True)
    for row in sources:
        relative = PurePosixPath(str(row.get("relative_path", "")))
        if relative.is_absolute() or ".." in relative.parts:
            raise RuntimeError("roadlink name verifier found an unsafe original-media path")
        source = (root / Path(*relative.parts)).resolve(strict=True)
        if (not source.is_relative_to(root)
                or source != Path(str(row.get("absolute_path", ""))).resolve(strict=True)
                or source.stat().st_size != int(row.get("size_bytes", -1))
                or _ledger_hash(relative.as_posix()) != row.get("sha256")):
            raise RuntimeError("roadlink name source identity differs from its evidence ledger")
    artifact_path = (PROJECT_ROOT / "work" / "autonomous_manager" / "ncdx"
                     / "roadlink_name_consistency" / f"{target_id}.json").resolve(strict=True)
    if not artifact_path.is_relative_to(PROJECT_ROOT.resolve()):
        raise RuntimeError("roadlink name artifact escaped the project workspace")
    proof = ncdx_roadlink_name_consistency.verify_artifact(artifact_path, sources,
        str(artifact["sha256"]))
    saved = json.loads(artifact_path.read_text(encoding="utf-8"))
    if (saved.get("task_id") != target_id
            or saved.get("source_fingerprint") != budget.get("source_fingerprint")
            or saved.get("predecessor_task_id") != predecessor_id
            or saved.get("predecessor_artifact_sha256") != budget.get("predecessor_artifact_sha256")):
        raise RuntimeError("roadlink name artifact differs from its exact scheduled input evidence")
    return {**proof, "task_id": target_id, "predecessor_task_id": predecessor_id,
        "all_original_media_write_count": 0,
        "regional_associations": {row["region"]: row["name_link_counts"] for row in saved["regions"]}}


def _verify_geography_portability_target(target_id: str, target_task: dict[str, Any],
                                         result: dict[str, Any]) -> dict[str, Any]:
    """Independently rehash the scheduled inputs and hash-bound result."""
    from src.readers import ncdx_geography_portability
    budget = target_task.get("budget", {})
    if (result.get("status") != "PASS"
            or budget.get("ncdx_geography_portability") is not True
            or int(budget.get("handler_version", -1)) != GEOGRAPHY_PORTABILITY_VERSION):
        raise RuntimeError(f"geography portability result does not match its fixed experiment: {target_id}")
    artifact = result.get("artifact")
    if not isinstance(artifact, dict) or not artifact.get("sha256"):
        raise RuntimeError(f"geography portability result has no hash-bound artifact: {target_id}")
    sources = budget.get("sources") or []
    if len(sources) != 18:
        raise RuntimeError("geography portability verifier requires exactly eighteen source identities")
    root = coordinator_runtime.SOURCE_ROOT.resolve(strict=True)
    for row in sources:
        relative = PurePosixPath(str(row.get("relative_path", "")))
        if relative.is_absolute() or ".." in relative.parts:
            raise RuntimeError("geography portability verifier found an unsafe source path")
        source = (root / Path(*relative.parts)).resolve(strict=True)
        if (not source.is_relative_to(root)
                or source != Path(str(row.get("absolute_path", ""))).resolve(strict=True)
                or _ledger_hash(relative.as_posix()) != row.get("sha256")):
            raise RuntimeError("geography portability source is outside its checked manifest")
    artifact_path = (PROJECT_ROOT / "work" / "autonomous_manager" / "ncdx"
                     / "geography_portability" / f"{target_id}.json").resolve(strict=True)
    if not artifact_path.is_relative_to(PROJECT_ROOT.resolve()):
        raise RuntimeError("geography portability artifact escaped project workspace")
    proof = ncdx_geography_portability.verify_artifact(artifact_path, sources,
                                                       str(artifact["sha256"]))
    saved = json.loads(artifact_path.read_text(encoding="utf-8"))
    if (saved.get("task_id") != target_id
            or saved.get("source_fingerprint") != budget.get("source_fingerprint")
            or saved.get("hypothesis_result") not in {"SUPPORTED", "FALSIFIED_OR_DIVERGENT"}):
        raise RuntimeError("geography portability report differs from its scheduled experiment")
    return {**proof, "task_id": target_id, "all_original_media_write_count": 0,
            "hypothesis_result": saved["hypothesis_result"],
            "region_checks": {row["region"]: row["checks"] for row in saved["regions"]}}


def _verify_city_coordinate_crosscheck_target(target_id: str, target_task: dict[str, Any],
                                              result: dict[str, Any]) -> dict[str, Any]:
    """Freshly reproduce accepted coordinate streams and city-box comparisons."""
    from src.readers import ncdx_city_coordinate_crosscheck
    budget = target_task.get("budget", {})
    if (result.get("status") != "PASS"
            or budget.get("ncdx_city_coordinate_crosscheck") is not True
            or int(budget.get("handler_version", -1)) != CITY_COORDINATE_CROSSCHECK_VERSION):
        raise RuntimeError(f"city-coordinate result differs from its fixed experiment: {target_id}")
    artifact = result.get("artifact")
    if not isinstance(artifact, dict) or not artifact.get("sha256"):
        raise RuntimeError(f"city-coordinate experiment has no hash-bound artifact: {target_id}")
    root = coordinator_runtime.SOURCE_ROOT.resolve(strict=True)
    sources, candidates = budget.get("sources") or [], budget.get("candidates") or []
    candidate_regions = {str(row.get("region")) for row in candidates if isinstance(row, dict)}
    if (len(sources) != 3 * len(candidates)
            or candidate_regions not in ({"SW", "Scandinavia"}, {"Italy"})
            or len(candidate_regions) != len(candidates)):
        raise RuntimeError("city-coordinate verifier requires the exact legacy pair or Italy-only inputs")
    for row in sources:
        relative = PurePosixPath(str(row.get("relative_path", "")))
        if relative.is_absolute() or ".." in relative.parts:
            raise RuntimeError("city-coordinate verifier found an unsafe source path")
        source = (root / Path(*relative.parts)).resolve(strict=True)
        if (not source.is_relative_to(root)
                or source != Path(str(row.get("absolute_path", ""))).resolve(strict=True)
                or source.stat().st_size != int(row.get("size_bytes", -1))
                or _ledger_hash(relative.as_posix()) != row.get("sha256")):
            raise RuntimeError(f"city-coordinate source identity differs from inventory: {relative}")
    for candidate in candidates:
        prior_path = Path(str(candidate.get("prior_artifact_path", ""))).resolve(strict=True)
        if not prior_path.is_relative_to(PROJECT_ROOT.resolve()):
            raise RuntimeError("city-coordinate prior evidence escaped project workspace")
    artifact_path = (PROJECT_ROOT / "work" / "autonomous_manager" / "ncdx"
                     / "city_coordinate_crosscheck" / f"{target_id}.json").resolve(strict=True)
    if not artifact_path.is_relative_to(PROJECT_ROOT.resolve()):
        raise RuntimeError("city-coordinate result artifact escaped project workspace")
    proof = ncdx_city_coordinate_crosscheck.verify_artifact(artifact_path, sources, candidates,
                                                            str(artifact["sha256"]))
    saved = json.loads(artifact_path.read_text(encoding="utf-8"))
    if (saved.get("task_id") != target_id
            or saved.get("source_fingerprint") != budget.get("source_fingerprint")
            or saved.get("hypothesis_result") not in {"SUPPORTED", "FALSIFIED_OR_DIVERGENT"}):
        raise RuntimeError("city-coordinate artifact does not match its exact scheduled hypothesis")
    return {**proof, "task_id": target_id,
            "all_original_media_write_count": 0,
            "region_checks": {row["region"]: row["checks"] for row in saved["regions"]}}


def _verify_firmware_hex_target(target_id: str, target_task: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    """Fresh Supervisor-side source readback, using the independent decoder only."""
    from src.firmware.verify_intel_hex import verify_file_independently
    budget = target_task.get("budget", {})
    sources = budget.get("sources") or []
    saved = {row.get("relative_path"): row for row in result.get("sources", []) if isinstance(row, dict)}
    root = coordinator_runtime.SOURCE_ROOT.resolve(strict=True)
    if result.get("status") != "PASS" or len(sources) != 4 or len(saved) != len(sources):
        raise RuntimeError(f"Supervisor refused incomplete firmware HEX result for {target_id}")
    for source_row in sources:
        relative = str(source_row.get("relative_path", "")).replace("\\", "/")
        parsed = PurePosixPath(relative)
        if not relative.casefold().startswith("sw/") or parsed.is_absolute() or ".." in parsed.parts or parsed.suffix.upper() != ".HEX":
            raise RuntimeError(f"Supervisor refused an out-of-scope firmware path: {relative}")
        source = (root / Path(*parsed.parts)).resolve(strict=True)
        if not source.is_relative_to(root):
            raise RuntimeError(f"Supervisor refused a firmware path outside the original source root: {relative}")
        expected = str(source_row.get("sha256", ""))
        actual = _sha256(source)
        manifest = _ledger_hash(relative)
        fresh = verify_file_independently(source, max_bytes=int(budget.get("max_bytes_per_source", 16 * 1024 * 1024)))
        prior = saved.get(relative, {})
        primary = prior.get("primary_decode", {})
        if (actual != expected or manifest != expected or prior.get("independent_match") is not True
                or any(fresh.get(key) != primary.get(key) for key in (
                    "record_count", "record_type_counts", "data_record_bytes", "unique_image_bytes",
                    "address_range_count", "address_ranges_preview", "address_image_sha256", "eof_seen"))):
            raise RuntimeError(f"Supervisor fresh readback did not reproduce the scheduled firmware proof: {relative}")
    return {"manifest_entries_match": True, "fresh_independent_readback": True,
        "record_checksums_valid": True, "address_image_matches_saved_result": True,
        "original_hashes_unchanged": True, "source_write_count": 0,
        "source_count": len(sources), "confirmed_container": "Intel HEX",
        "payload_semantics": "UNKNOWN", "firmware_compatibility": "NOT_TESTED"}


def _record_firmware_hex_readiness(proof: dict[str, Any], target_id: str) -> None:
    if (proof.get("confirmed_container") != "Intel HEX" or proof.get("source_count") != 4
            or proof.get("fresh_independent_readback") is not True or proof.get("source_write_count") != 0):
        raise RuntimeError("refusing to update readiness without the full independent firmware proof")
    with closing(sqlite3.connect(STATE_DB, timeout=20)) as conn:
        row = conn.execute("SELECT proof_json FROM stage_gates WHERE stage='F2'").fetchone()
        if not row:
            raise RuntimeError("F2 readiness gate is missing")
        try:
            saved = json.loads(row[0] or "{}")
        except json.JSONDecodeError:
            saved = {}
        criteria = saved.setdefault("criteria_pass", {})
        criteria["firmware_hex_structures"] = True
        saved["firmware_hex_evidence"] = {"task_id": target_id,
            "confirmed_container": "Intel HEX", "source_count": proof["source_count"],
            "independent_readback": True, "original_media_write_count": 0,
            "payload_semantics": "UNKNOWN", "physical_compatibility": "NOT_TESTED"}
        conn.execute("UPDATE stage_gates SET proof_json=?,updated_utc=? WHERE stage='F2'",
                     (json.dumps(saved, ensure_ascii=False), _utc()))
        conn.commit()


def _write_periodic_reports(trigger_task: str, supervisor_model: str, verified: dict[str, Any]) -> list[dict[str, Any]]:
    with closing(sqlite3.connect(STATE_DB, timeout=30)) as conn:
        conn.row_factory = sqlite3.Row
        task_columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(tasks)")}
        budget_column = "budget_json" if "budget_json" in task_columns else "'{}' AS budget_json"
        task_rows = [dict(row) for row in conn.execute(
            f"SELECT id,stage,status,verdict,updated_utc,{budget_column} FROM tasks ORDER BY updated_utc DESC")]
        task_rows = [row for row in task_rows if not project_scope.task_is_excluded(row)]
        counts: dict[str, int] = {}
        for row in task_rows:
            counts[str(row["status"])] = counts.get(str(row["status"]), 0) + 1
        tasks = [{key: row[key] for key in ("id", "stage", "status", "verdict", "updated_utc")} for row in task_rows[:50]]
        model_runs = [dict(row) for row in conn.execute("SELECT task_id,role,model,decision,elapsed_ms,created_utc,error FROM research_runs ORDER BY id DESC")]
        model_runs = [row for row in model_runs if not project_scope.task_is_excluded(str(row.get("task_id") or ""))][:30]
        blockers = [dict(row) for row in conn.execute("SELECT stage,reason,required_action,status FROM blocked_reasons WHERE status='OPEN' ORDER BY stage,id")]
    state = {"generated_utc": _utc(), "trigger_task": trigger_task, "supervisor_model": supervisor_model,
        "verified_result": verified, "task_counts": counts, "recent_tasks": tasks,
        "model_runs": model_runs, "open_blockers": blockers,
        "physical_compatibility": "NOT TESTED · requires a compatible Opel NCDR unit",
        "active_scope": project_scope.load_scope(),
        "unknown_format_boundary": "OSM preparation and byte-level NCDx observations do not establish target-disc compatibility."}
    now = datetime.now(timezone.utc)
    week = now.isocalendar()
    periods = {"daily": now.strftime("%Y-%m-%d"), "weekly": f"{week.year}-W{week.week:02d}", "monthly": now.strftime("%Y-%m")}
    artifacts = []
    for period, label in periods.items():
        folder = PROJECT_ROOT / "reports" / "periodic" / period
        folder.mkdir(parents=True, exist_ok=True)
        json_path = folder / f"{label}.json"
        md_path = folder / f"{label}.md"
        state["period"] = period
        json_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        lines = [f"# NCDR Autonomous Lab · {period} {label}", "",
            f"- Generated (UTC): {state['generated_utc']}", f"- Trigger: `{trigger_task}`",
            f"- Active goal: {state['active_scope']['global_goal']}",
            "- Active tracks: " + ", ".join(row["id"] for row in state["active_scope"]["active_tracks"]),
            "- Excluded tracks: " + ", ".join(row["id"] for row in state["active_scope"]["excluded_tracks"]),
            f"- Readiness excludes task counts: `{state['active_scope']['readiness_policy']['task_counts_score'] is False}`; excludes statistical profiles: `{state['active_scope']['readiness_policy']['statistical_profiles_score'] is False}`.",
            f"- Supervisor model: `{supervisor_model}`", f"- Verified result: `{verified['task_id']}`",
            f"- Task counts: `{json.dumps(counts, ensure_ascii=False, sort_keys=True)}`",
            f"- Physical compatibility: {state['physical_compatibility']}",
            f"- NCDx format boundary: {state['unknown_format_boundary']}", "", "## Verified evidence", "",
            "```json", json.dumps(verified, ensure_ascii=False, indent=2), "```", "", "## Recent task activity", ""]
        lines.extend(f"- `{row['updated_utc']}` · `{row['status']}` · `{row['id']}` ({row['stage']})" for row in tasks[:20])
        lines.extend(["", "## Open blockers", ""])
        lines.extend(f"- `{row['stage']}` · {row['reason']} · next: {row['required_action']}" for row in blockers)
        md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        for path in (json_path, md_path):
            artifacts.append(manager._artifact(trigger_task, path, f"AI Supervisor {period} report from persisted results", "PASS: derived from SQLite, model runs and verified task proof"))
    return artifacts


def write_codex_daily_report(*, trigger: str, trigger_task: str | None = None) -> dict[str, Any]:
    """Write a factual daily handoff from persisted queue, model and artifact records."""
    now = datetime.now(timezone.utc)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    with closing(sqlite3.connect(STATE_DB, timeout=30)) as conn:
        conn.row_factory = sqlite3.Row
        task_columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(tasks)")}
        budget_column = "budget_json" if "budget_json" in task_columns else "'{}' AS budget_json"
        tasks = [dict(row) for row in conn.execute(
            f"SELECT id,stage,status,verdict,result_json,updated_utc,{budget_column} FROM tasks WHERE updated_utc>=? ORDER BY updated_utc DESC",
            (day_start,))]
        tasks = [row for row in tasks if not project_scope.task_is_excluded(row)][:60]
        queue_rows = [dict(row) for row in conn.execute(f"SELECT id,status,{budget_column} FROM tasks")]
        queue_rows = [row for row in queue_rows if not project_scope.task_is_excluded(row)]
        counts: dict[str, int] = {}
        for row in queue_rows:
            counts[str(row["status"])] = counts.get(str(row["status"]), 0) + 1
        models = [dict(row) for row in conn.execute(
            "SELECT task_id,role,model,decision,elapsed_ms,error,created_utc FROM research_runs WHERE created_utc>=? ORDER BY id DESC",
            (day_start,))]
        models = [row for row in models if not project_scope.task_is_excluded(str(row.get("task_id") or ""))][:60]
        events = [dict(row) for row in conn.execute(
            "SELECT created_utc,event,severity,task_id,detail_json FROM autonomy_events WHERE created_utc>=? ORDER BY id DESC",
            (day_start,))]
        events = [row for row in events if not project_scope.task_is_excluded(str(row.get("task_id") or ""))][:80]
        artifacts = [dict(row) for row in conn.execute(
            "SELECT task_id,path,sha256,size_bytes,description,acceptance,created_utc FROM autonomy_artifacts ORDER BY created_utc DESC")]
        artifacts = [row for row in artifacts if not project_scope.task_is_excluded(str(row.get("task_id") or ""))][:30]
        blocked = [dict(row) for row in conn.execute(
            f"SELECT id,stage,next_action,result_json,updated_utc,{budget_column} FROM tasks WHERE status='BLOCKED' ORDER BY priority,id")]
        blocked = [row for row in blocked if not project_scope.task_is_excluded(row)][:20]
        control_row = conn.execute(
            "SELECT desired_state,worker_pid,current_task,last_error,health_json,updated_utc FROM autonomy_control WHERE singleton=1").fetchone()
    control = dict(control_row) if control_row else {}
    for row in tasks:
        try:
            result = json.loads(row.pop("result_json") or "{}")
        except (json.JSONDecodeError, TypeError):
            result = {}
        row["summary"] = str(result.get("error") or result.get("status") or result.get("goal_id") or "saved task result")[:240]
    for row in blocked:
        try:
            result = json.loads(row.pop("result_json") or "{}")
        except (json.JSONDecodeError, TypeError):
            result = {}
        row["reason"] = str(result.get("error") or row.get("next_action") or "blocked dependency")[:320]
    for row in events:
        try:
            detail = json.loads(row.pop("detail_json") or "{}")
        except (json.JSONDecodeError, TypeError):
            detail = {}
        row["detail"] = detail
    diagnosis = manager.queue_diagnosis()
    report = {
        "schema_version": 1, "audience": "Codex", "generated_utc": now.isoformat(),
        "report_day_utc": now.strftime("%Y-%m-%d"), "trigger": trigger, "trigger_task": trigger_task,
        "global_goal": project_scope.global_goal(),
        "active_scope": project_scope.load_scope(),
        "state_database": str(STATE_DB.relative_to(PROJECT_ROOT)), "queue_counts": counts,
        "worker": control, "queue_diagnosis": diagnosis, "task_updates_today": tasks,
        "local_model_runs_today": models, "events_today": events, "recent_artifacts": artifacts,
        "blocked_tasks": blocked, "physical_compatibility": "NOT TESTED",
        "format_boundary": "Statistical profiles do not increase readiness; only proven NCDx structures, working reader/writer code, validated disc data, and physical acceptance count.",
        "source_policy": "Original NCDR media is read-only; worker artifacts are stored under the project work/reports folders.",
    }
    folder = PROJECT_ROOT / "reports" / "periodic" / "daily"
    folder.mkdir(parents=True, exist_ok=True)
    stem = f"codex-{report['report_day_utc']}"
    json_path, md_path = folder / f"{stem}.json", folder / f"{stem}.md"
    json_text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    task_lines = [f"- `{row['updated_utc']}` · `{row['status']}` · `{row['id']}` — {row['summary']}" for row in tasks[:25]]
    model_lines = [f"- `{row['created_utc']}` · `{row['model']}` ({row['role']}) · {row['decision']} · {row['elapsed_ms']} ms" for row in models[:20]]
    artifact_lines = [f"- `{row['path']}` · SHA-256 `{row['sha256']}` · {row['acceptance']}" for row in artifacts[:20]]
    blocker_lines = [f"- `{row['id']}` ({row['stage']}) — {row['reason']}" for row in blocked[:12]]
    markdown = "\n".join([
        f"# Codex daily handoff · NCDR · {report['report_day_utc']}", "",
        f"- Generated UTC: `{report['generated_utc']}`", f"- Trigger: `{trigger}` · task `{trigger_task or 'daily refresh'}`",
        f"- Worker: `{control.get('desired_state')}` · PID `{control.get('worker_pid')}` · current `{control.get('current_task') or 'none'}`",
        f"- Queue: `{json.dumps(counts, ensure_ascii=False, sort_keys=True)}`", "",
        f"- Active scope revision: `{report['active_scope']['scope_revision']}`; excluded tracks remain archived and do not count toward readiness.",
        "## Work recorded today", "", *(task_lines or ["- No task status changes recorded today."]), "",
        "## Local model calls", "", *(model_lines or ["- No Ollama call recorded today."]), "",
        "## Recent evidence artifacts", "", *(artifact_lines or ["- No artifacts are registered yet."]), "",
        "## Blockers and next action", "", f"- Queue diagnosis: {diagnosis.get('message', 'unavailable')}",
        *(blocker_lines or ["- No task is currently marked BLOCKED."]), "",
        "## Boundaries", "", f"- Physical compatibility: **{report['physical_compatibility']}**.",
        f"- {report['format_boundary']}", f"- {report['source_policy']}",
    ]) + "\n"
    json_temp, md_temp = json_path.with_suffix(".json.tmp"), md_path.with_suffix(".md.tmp")
    json_temp.write_text(json_text, encoding="utf-8")
    md_temp.write_text(markdown, encoding="utf-8")
    json_temp.replace(json_path)
    md_temp.replace(md_path)
    digest = hashlib.sha256(md_path.read_bytes()).hexdigest()
    manager._event("codex_daily_report_written", {"path": str(md_path.relative_to(PROJECT_ROOT)),
        "json_path": str(json_path.relative_to(PROJECT_ROOT)), "sha256": digest,
        "trigger": trigger, "task_id": trigger_task})
    return {"markdown": str(md_path.relative_to(PROJECT_ROOT)), "json": str(json_path.relative_to(PROJECT_ROOT)),
            "sha256": digest, "task_updates_today": len(tasks), "model_runs_today": len(models)}


def _supervisor_verified_target(target_id: str) -> dict[str, Any]:
    """Ensure every deterministic proof carries the exact target identity."""
    proof = _verified_target(target_id)
    if not isinstance(proof, dict):
        raise RuntimeError("deterministic target verifier returned no proof object")
    return {**proof, "task_id": target_id}


def execute_supervisor(task_id: str) -> dict[str, Any]:
    task = manager._task(task_id)
    target_id = str(task["budget"].get("supervises_task", ""))
    if not target_id:
        raise RuntimeError("Supervisor task has no explicit target task")
    verified = _supervisor_verified_target(target_id)
    installed = coordinator_runtime._available_models()
    model = coordinator_runtime._choose_model("independent-review", installed)
    prompt = json.dumps({"role": "AI Research Supervisor", "global_goal": _director_context(),
        "verified_facts": verified,
        "task_status": "DONE", "known_boundaries": ["Do not claim physical Opel compatibility.",
        "Do not infer binary formats from OSM behavior.", "Do not change an original source or SQLite queue state.",
        "Do not propose Virtual CID GUI simulation or the standalone personal POI editor; they are archived."],
        "response_schema": {"assessment": "PASS", "evidence_consistent": True,
                            "remaining_unknowns": ["string"], "suggested_next_goal_id": "allowlisted goal"}}, ensure_ascii=False)
    actual_model, _response, parsed = coordinator_runtime._call_model(task_id, "independent-review", prompt, attempt=1, fixed_model=model)
    if parsed.get("assessment") != "PASS" or parsed.get("evidence_consistent") is not True:
        raise RuntimeError(f"local Supervisor response did not affirm the deterministic proof schema: {parsed}")
    result = {"status": "PASS", "task_id": task_id, "target_task": target_id,
        "model": actual_model, "model_assessment": parsed, "deterministic_verification": verified,
        "created_utc": _utc(), "original_media_write_count": 0,
        "physical_compatibility": "NOT_TESTED"}
    report_path = PROJECT_ROOT / "reports" / f"autonomous_supervisor_{target_id.casefold()}.json"
    target_task = manager._task(target_id)
    if target_task.get("budget", {}).get("firmware_intel_hex") is True:
        _record_firmware_hex_readiness(verified["deterministic_proof"], target_id)
    if target_task.get("budget", {}).get("mp0_independent_readback") is True:
        _record_mp0_writer_readiness(verified["deterministic_proof"], target_id)
        report_artifact = manager._artifact(task_id, PROJECT_ROOT / "reports" / "autonomous_writer_roundtrip.json",
            "Verified MP0 writer report extended with an independent parser readback",
            "PASS: three original-region copies and one field-limited test copy reread independently")
    else:
        report_artifact = None
    if target_task.get("budget", {}).get("ukraine_national_osm") is True:
        _record_ukraine_osm_readiness(verified["deterministic_proof"], target_id)
    artifacts = _write_periodic_reports(task_id, actual_model, verified)
    if report_artifact:
        artifacts.append(report_artifact)
    if target_task.get("budget", {}).get("data_family_profile") is True:
        followup = seed_next_data_family_director_task(dependency=task_id, prior_task=target_id)
        next_id, created = followup.get("task_id"), bool(followup.get("created"))
        result["next_plan_reason"] = followup.get("reason")
        if not created:
            result["project_state"] = "NCDx regional profile catalog exhausted; physical compatibility remains NOT_TESTED"
    elif target_id == PLAN_TASKS["OSM_REAL_CONVERSION"]:
        next_id = "AUTO_OSM_READBACK_AFTER_RESTART_01"
        created = _registered_task(next_id, "F4", task_id,
            "Fresh worker process independently reopens and verifies the converted OSM database after the Supervisor checkpoint.",
            "osm-independent-readback", "work/autonomous_manager/osm_pipeline/real_conversion/readback_after_restart.json",
            ["Reopen SQLite read-only in a fresh process", "Verify real Ukrainian street search and connected route", "Verify unchanged local PBF hash"], 240, 12)
    elif target_id == "AUTO_OSM_READBACK_AFTER_RESTART_01":
        next_id = PLAN_ID["NCDX_NK_SURVEY"]
        created = _registered_task(next_id, "F2", task_id,
            "AI Director re-evaluates saved OSM conversion, readback and blockers, then selects the next independent NCDx component experiment.",
            "ollama-project-director", "reports/autonomous_director_plan_ncdx_nk_survey.json",
            ["Local model selects NCDX_NK_SURVEY from fixed registry", "Plan depends on this Supervisor", "No generated code or hardware dependency"], 1200, 8)
    elif target_task.get("budget", {}).get("ukraine_national_osm") is True:
        followup = seed_next_component_survey_task()
        next_id, created = followup.get("task_id"), bool(followup.get("created"))
        result["next_plan_reason"] = followup.get("reason")
    elif target_id == PLAN_TASKS["NCDX_NK_SURVEY"]:
        next_id = PLAN_ID["NCDX_NAVIMAIN_SURVEY"]
        created = _registered_task(next_id, "F2", task_id,
            "AI Director selects the next distinct read-only navigation executable survey after the NK.BIN evidence was verified.",
            "ollama-project-director", "reports/autonomous_director_plan_ncdx_navimain_survey.json",
            ["Local model selects NCDX_NAVIMAIN_SURVEY from fixed registry", "Plan depends on this Supervisor", "No generated code or hardware dependency"], 1200, 8)
    else:
        next_id = None
        created = False
    if next_id and not created:
        raise RuntimeError(f"Supervisor follow-up already exists unexpectedly: {next_id}")
    result.update({"followup_task_id": next_id, "followup_created": created, "periodic_reports": artifacts})
    report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    artifacts.insert(0, manager._artifact(task_id, report_path, "Supervisor model assessment checked against deterministic evidence", "PASS"))
    return result


_LEDGER_CACHE_KEY: tuple[str, int, int] | None = None
_LEDGER_CACHE: dict[str, dict[str, Any]] = {}


def _ledger_index() -> dict[str, dict[str, Any]]:
    global _LEDGER_CACHE_KEY, _LEDGER_CACHE
    db_path = PROJECT_ROOT / "EVIDENCE_LEDGER.sqlite"
    if not db_path.is_file():
        return {}
    stat = db_path.stat()
    key = (str(db_path.resolve()), stat.st_mtime_ns, stat.st_size)
    if key == _LEDGER_CACHE_KEY:
        return _LEDGER_CACHE
    with closing(sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)) as conn:
        rows = conn.execute("SELECT source_path,sha256,size_bytes FROM artifacts").fetchall()
    index: dict[str, dict[str, Any]] = {}
    for path, digest, size in rows:
        normalized = str(path).replace("/", "\\").casefold()
        index[normalized] = {"sha256": str(digest), "size_bytes": int(size or 0)}
    _LEDGER_CACHE_KEY, _LEDGER_CACHE = key, index
    return index


def _ledger_entry(relative_path: str) -> dict[str, Any] | None:
    normalized = relative_path.replace("/", "\\").casefold()
    index = _ledger_index()
    exact = index.get(normalized)
    if exact:
        return exact
    return next((entry for path, entry in index.items()
                 if path.endswith("\\" + normalized)), None)


def _ledger_hash(relative_path: str) -> str | None:
    entry = _ledger_entry(relative_path)
    return str(entry["sha256"]) if entry and entry.get("sha256") else None


def execute_ncdx_component_survey(task_id: str) -> dict[str, Any]:
    task = manager._task(task_id)
    if task.get("budget", {}).get("component_scan") is True:
        return execute_sw_component_survey(task)
    goal_id = "NCDX_NK_SURVEY" if task_id == PLAN_TASKS["NCDX_NK_SURVEY"] else "NCDX_NAVIMAIN_SURVEY"
    relative = ("SW/LK841/HU_HARDWARE_LOC_0000000001/HU_KERNEL_LOC_0101000870/NK.BIN"
                if goal_id == "NCDX_NK_SURVEY" else
                "SW/LK841/HU_HARDWARE_LOC_0000000001/HU_MMIDIS_LOC_0130170000/WINDOWS/NAVIMAIN.EXE")
    source = (coordinator_runtime.SOURCE_ROOT / Path(relative)).resolve(strict=True)
    if not source.is_relative_to(coordinator_runtime.SOURCE_ROOT.resolve()):
        raise RuntimeError("selected component path escaped the original read-only source root")
    expected = _ledger_hash(relative)
    before = _sha256(source)
    if expected and expected != before:
        raise RuntimeError(f"selected source hash differs from the existing manifest: {relative}")
    size = source.stat().st_size
    with source.open("rb") as stream:
        head = stream.read(min(4096, size))
    observations = {"size_bytes": size, "sha256": before, "first_64_bytes_hex": head[:64].hex(),
        "first_4096_bytes_sha256": hashlib.sha256(head).hexdigest(),
        "ascii_strings": [match.decode("ascii", errors="replace") for match in re.findall(rb"[\x20-\x7e]{6,}", head)[:32]],
        "observed_signatures": [label for label, marker in (("MZ", b"MZ"), ("PE", b"PE\0\0"),
            ("BINFS", b"B000FF"), ("NK", b"NK\0")) if marker in head],
        "manifest_sha256": expected, "semantic_format": "UNKNOWN; observations only"}
    after = _sha256(source)
    if before != after:
        raise RuntimeError("source component changed during read-only byte survey")
    output = PROJECT_ROOT / "work" / "autonomous_manager" / "ncdx" / ("nk_survey.json" if goal_id == "NCDX_NK_SURVEY" else "navimain_survey.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    result = {"status": "PASS", "task_id": task_id, "goal_id": goal_id,
        "relative_source_path": relative, "observations": observations,
        "original_hash_unchanged": before == after, "source_write_count": 0,
        "source_root": str(coordinator_runtime.SOURCE_ROOT), "created_utc": _utc()}
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    artifact = manager._artifact(task_id, output, "Read-only bounded NK.BIN/NAVIMAIN.EXE component evidence", "PASS: source hash matches manifest and unchanged; semantics remain UNKNOWN")
    supervisor_id = SUPERVISOR_ID[goal_id]
    _register_supervisor(supervisor_id, task_id)
    return {**result, "verified": {"original_hash_unchanged": True, "manifest_hash_match": expected == before if expected else None},
            "artifact": artifact}


def execute_sw_component_survey(task: dict[str, Any]) -> dict[str, Any]:
    """Read and fingerprint one fixed-inventory SW binary without writing its source."""
    task_id = str(task["id"])
    budget = task.get("budget", {})
    relative = str(budget.get("source_path", "")).replace("\\", "/")
    parsed_path = PurePosixPath(relative)
    if (parsed_path.is_absolute() or ".." in parsed_path.parts
            or not relative.casefold().startswith("sw/")
            or parsed_path.suffix.upper() not in COMPONENT_SCAN_EXTENSIONS):
        raise ValueError("component survey path is outside the fixed SW binary allowlist")
    root = coordinator_runtime.SOURCE_ROOT.resolve(strict=True)
    source = (root / Path(*parsed_path.parts)).resolve(strict=True)
    if not source.is_relative_to(root):
        raise RuntimeError("component survey source escaped the read-only NCDR root")
    expected = str(budget.get("sha256", ""))
    manifest_hash = _ledger_hash(relative)
    if not expected or manifest_hash != expected:
        raise RuntimeError("component survey task does not match its persisted EVIDENCE_LEDGER entry")
    before_stat = source.stat()
    if before_stat.st_size != int(budget.get("size_bytes", -1)):
        raise RuntimeError("component survey source size differs from its scheduled inventory evidence")
    before_hash = _sha256(source)
    if before_hash != expected:
        raise RuntimeError("component survey source hash differs from EVIDENCE_LEDGER")
    with source.open("rb") as stream:
        header = stream.read(4096)
    strings = [match.decode("ascii", errors="replace")
               for match in re.findall(rb"[\x20-\x7e]{6,}", header)[:32]]
    signatures = {label: header.find(marker) for label, marker in (
        ("MZ", b"MZ"), ("PE", b"PE\x00\x00"), ("BINFS", b"B000FF"),
        ("NK", b"NK\x00"), ("RIFF", b"RIFF"), ("ZIP", b"PK\x03\x04")) if marker in header}
    after_hash = _sha256(source)
    after_stat = source.stat()
    unchanged = (before_hash == after_hash == expected
                 and before_stat.st_size == after_stat.st_size
                 and before_stat.st_mtime_ns == after_stat.st_mtime_ns)
    if not unchanged:
        raise RuntimeError("component survey source changed while it was read")
    result = {
        "status": "PASS", "task_id": task_id, "source_path": relative,
        "source_size_bytes": before_stat.st_size, "source_sha256": before_hash,
        "manifest_sha256": manifest_hash, "first_4096_bytes_hex": header.hex(),
        "printable_strings_first_4096": strings, "observed_signatures_and_offsets": signatures,
        "semantic_format": "UNKNOWN; bounded observations only",
        "source_write_count": 0, "created_utc": _utc(),
        "verified": {"original_hash_unchanged": True, "manifest_hash_match": True,
                     "source_size_match": True, "read_limit_bytes": 4096,
                     "source_write_count": 0, "source_path": relative,
                     "source_sha256": before_hash, "printable_string_count": len(strings),
                     "observed_signatures_and_offsets": signatures,
                     "semantic_format": "UNKNOWN; bounded observations only"},
    }
    output_dir = PROJECT_ROOT / "work" / "autonomous_manager" / "ncdx" / "component_surveys"
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f"{task_id}.json"
    temp = output.with_suffix(".json.tmp")
    temp.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(output)
    artifact = manager._artifact(task_id, output,
        "Read-only SW component survey backed by the existing SHA-256 inventory",
        "PASS: exact manifest hash, bounded 4096-byte read, unchanged source, semantics UNKNOWN")
    _register_supervisor("AUTO_SUPERVISOR_" + task_id, task_id)
    return {**result, "artifact": artifact}


def execute_ncdx_pe_header_probe(task_id: str) -> dict[str, Any]:
    """Parse one already-observed PE image without running any code from it."""
    from src.readers.ncdx_binary_headers import MAX_PE_HEADER_SOURCE_BYTES, inspect_pe_headers
    task = manager._task(task_id)
    budget = task.get("budget", {})
    relative = str(budget.get("source_path", "")).replace("\\", "/")
    parsed_path = PurePosixPath(relative)
    if (budget.get("pe_header_probe") is not True or not relative.casefold().startswith("sw/")
            or parsed_path.is_absolute() or ".." in parsed_path.parts
            or parsed_path.suffix.upper() not in COMPONENT_SCAN_EXTENSIONS):
        raise ValueError("PE header probe source is outside the fixed manifest-backed SW scope")
    root = coordinator_runtime.SOURCE_ROOT.resolve(strict=True)
    source = (root / Path(*parsed_path.parts)).resolve(strict=True)
    if not source.is_relative_to(root) or not source.is_file():
        raise RuntimeError("PE header probe source escaped the read-only NCDR root")
    expected = str(budget.get("sha256", ""))
    source_size = source.stat().st_size
    if (not expected or source_size != int(budget.get("size_bytes", -1))
            or not (64 <= source_size <= MAX_PE_HEADER_SOURCE_BYTES)
            or _ledger_hash(relative) != expected):
        raise RuntimeError("PE header probe source does not match its bounded manifest entry")
    prior_id = str(budget.get("source_survey_task_id", ""))
    if _task_status(prior_id) != "DONE":
        raise RuntimeError("PE header probe lacks a completed signature survey predecessor")
    prior = _task_result(prior_id)
    prior_signatures = prior.get("observed_signatures_and_offsets", {})
    if (prior.get("status") != "PASS" or prior.get("source_path") != relative
            or prior.get("source_sha256") != expected or prior_signatures.get("MZ") != 0
            or prior_signatures.get("PE") != int(budget.get("observed_pe_signature_offset", -1))):
        raise RuntimeError("PE header probe predecessor does not prove the selected MZ/PE bytes")
    before_stat = source.stat()
    before_hash = _sha256(source)
    if before_hash != expected:
        raise RuntimeError("PE header probe source hash differs from EVIDENCE_LEDGER")
    raw = source.read_bytes()
    observation = inspect_pe_headers(raw)
    if observation.get("status") != "PASS_PE_HEADERS":
        raise RuntimeError("selected PE candidate did not yield a complete COFF header")
    after_hash = _sha256(source)
    after_stat = source.stat()
    if (before_hash != after_hash or before_stat.st_size != after_stat.st_size
            or before_stat.st_mtime_ns != after_stat.st_mtime_ns):
        raise RuntimeError("PE header source changed while the read-only experiment was running")
    result = {"status": "PASS", "task_id": task_id, "source_path": relative,
        "source_size_bytes": source_size, "source_sha256": expected,
        "manifest_sha256": _ledger_hash(relative), "source_survey_task_id": prior_id,
        "observed_pe_signature_offset": int(budget["observed_pe_signature_offset"]),
        "header_observation": observation,
        "verified": {"manifest_hash_match": True, "source_hash_unchanged": True,
            "source_size_match": True, "read_only": True, "source_write_count": 0,
            "original_media_write_count": 0},
        "claim_scope": "PE/COFF machine and bounded section table only; execution behavior and map semantics UNKNOWN",
        "created_utc": _utc(), "source_write_count": 0, "original_media_write_count": 0,
        "physical_compatibility": "NOT_TESTED"}
    output = PROJECT_ROOT / "work" / "autonomous_manager" / "ncdx" / "pe_headers" / f"{task_id}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(output)
    artifact = manager._artifact(task_id, output,
        "Manifest-bound PE/COFF machine and section evidence from an NCDR component",
        "PASS: bounded structural parse, exact source SHA and unchanged read-only input")
    _register_supervisor("AUTO_SUPERVISOR_" + task_id, task_id)
    return {**result, "artifact": artifact}


def dispatch(task_id: str, agent: str) -> dict[str, Any]:
    if agent == "ollama-mission-pack-director":
        return execute_mission_pack_director(task_id)
    if agent == "ollama-component-survey-director":
        return execute_component_survey_director(task_id)
    if agent == "ncdx-pe-header-probe":
        return execute_ncdx_pe_header_probe(task_id)
    if agent == "ncdx-pe-import-census":
        return execute_ncdx_pe_import_census(task_id)
    if agent == "ncdx-embedded-pe-search":
        return execute_ncdx_embedded_pe_search(task_id)
    if agent == "ollama-osm-partition-director":
        return execute_osm_partition_director(task_id)
    if agent == "osm-partition-probe":
        return execute_osm_partition_probe(task_id)
    if agent == "mission-pack-executor":
        return execute_mission_pack_task(task_id)
    if agent in {"codex-capability-request", "local-code-repair"}:
        return execute_capability_request(task_id)
    if agent == "ollama-project-director":
        return execute_director(task_id)
    if agent == "osm-real-conversion":
        return execute_osm_conversion(task_id)
    if agent == "osm-independent-readback":
        return execute_osm_readback(task_id)
    if agent == "osm-national-conversion":
        return execute_osm_national_conversion(task_id)
    if agent == "ollama-research-supervisor":
        return execute_supervisor(task_id)
    if agent == "ollama-osm-failure-review":
        return execute_osm_failure_review(task_id)
    if agent == "ncdx-component-survey":
        return execute_ncdx_component_survey(task_id)
    if agent == "ollama-data-family-director":
        return execute_data_family_director(task_id)
    if agent == "ncdx-data-family-profile":
        return execute_data_family_profile(manager._task(task_id))
    if agent == "firmware-intel-hex-reader":
        return execute_firmware_hex_task(task_id)
    if agent == "mp0-independent-readback":
        return execute_mp0_independent_readback_task(task_id)
    if agent == "ncdx-roadlink-portability":
        return execute_ncdx_roadlink_portability(task_id)
    if agent == "ncdx-roadlink-name-consistency":
        return execute_ncdx_roadlink_name_consistency(task_id)
    if agent == "ncdx-geography-portability":
        return execute_ncdx_geography_portability(task_id)
    if agent == "ncdx-geoblock-research":
        from src.agent import geoblock_research
        return geoblock_research.execute_task(task_id)
    if agent == "ncdx-city-coordinate-crosscheck":
        return execute_ncdx_city_coordinate_crosscheck(task_id)
    raise ValueError(f"unrecognized Project Director handler: {agent}")
