"""Evidence-bound discovery and replay for NCDx geographic blocks.

Coordinates remain candidates, never decoded roads. Original media is read-only.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import sqlite3
import struct
import zlib
from typing import Any

from src.agent import autonomous_manager, coordinator_runtime, project_director, state_store
from src.readers import ncdx_city_coordinate_crosscheck as city_reader
from src.readers import ncdx_geoblock_analyzer as analyzer

PROJECT_ROOT = Path(__file__).resolve().parents[2]
STATE_DB = PROJECT_ROOT / "project_state.sqlite"
REGISTRY_PATH = PROJECT_ROOT / "evidence" / "verified_handlers" / "ncdx_geoblock_research.json"
TEST_PATHS = ("tests/unit/test_ncdx_geoblock_analyzer.py",
              "tests/unit/test_ncdx_geoblock_research.py")
AGENT_NAME = "ncdx-geoblock-research"
PROFILE_ID = re.compile(r"AUTO_NCDX_DATA_MG2_ZLIB_DECODED_COORDINATE_CANDIDATE_CENSUS_[a-f0-9]{8,32}\Z")
MIN_PRIOR_ADJACENT_PAIRS = 3
MIN_PRIOR_REGION_PAIRS = 30
MAX_COMPRESSED_STREAM_BYTES = 1024 * 1024
MAX_DECOMPRESSED_BYTES = 4 * 1024 * 1024
HEADER_FAMILIES = ("MP0", "MG1", "MG2", "MG3")


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _safe_project_file(root: Path, relative: str) -> Path:
    parsed = PurePosixPath(str(relative).replace("\\", "/"))
    if parsed.is_absolute() or ".." in parsed.parts or not parsed.parts:
        raise ValueError(f"unsafe project-relative path: {relative}")
    resolved_root = root.resolve(strict=True)
    target = (resolved_root / Path(*parsed.parts)).resolve(strict=True)
    if not target.is_relative_to(resolved_root) or not target.is_file():
        raise ValueError(f"project artifact escaped the repository: {relative}")
    return target


def tool_registry_status(project_root: Path = PROJECT_ROOT,
                         registry_path: Path | None = None) -> dict[str, Any]:
    """Require hash-bound tests before allowing this research handler to run."""
    root = project_root.resolve(strict=True)
    manifest = registry_path or (root / "evidence" / "verified_handlers" / "ncdx_geoblock_research.json")
    if not manifest.is_file():
        return {"allowed": False, "reason": "verified handler registry entry is missing"}
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"allowed": False, "reason": f"handler registry cannot be read: {type(exc).__name__}"}
    if data.get("status") != "VERIFIED_MANUAL" or data.get("handler") != AGENT_NAME:
        return {"allowed": False, "reason": "handler registry status or identity is not verified"}
    expected = data.get("files")
    required = ("src/readers/ncdx_geoblock_analyzer.py", "src/agent/geoblock_research.py", *TEST_PATHS)
    if not isinstance(expected, dict):
        return {"allowed": False, "reason": "handler registry has no file hashes"}
    try:
        actual = {relative: _sha256_file(_safe_project_file(root, relative)) for relative in required}
    except (OSError, ValueError) as exc:
        return {"allowed": False, "reason": f"verified handler file is unavailable: {type(exc).__name__}"}
    if actual != expected:
        return {"allowed": False, "reason": "verified handler source/test hashes have changed"}
    return {"allowed": True, "status": data["status"], "registry_sha256": _sha256_file(manifest),
            "files": actual, "verification_method": data.get("verification_method"),
            "qwen_codegen_status": data.get("qwen_codegen_status")}


def _expected_region_path(region: str, suffix: str) -> str:
    region_row = next((row for row in coordinator_runtime.REGIONS if row[0] == region), None)
    if not region_row:
        raise ValueError(f"unknown NCDx region: {region}")
    return (Path(region_row[1]) / f"{region_row[2]}.{suffix}").as_posix()


def _candidate_id(pair: dict[str, Any]) -> str:
    identity = {"v": 1, "payload": pair["payload_sha256"], "measurement": pair["measurement"],
        "inputs": [{key: item[key] for key in ("region", "relative_path", "source_sha256")}
                   for item in pair["inputs"]]}
    return hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:16].upper()


def _build_candidate_pairs(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Pair only identical full-payload hashes with the same measured alignment."""
    unique: dict[tuple, dict[str, Any]] = {}
    for row in candidates:
        if (row.get("region") not in {x[0] for x in coordinator_runtime.REGIONS}
                or row.get("selected_full_payload") is not True
                or int(row.get("prior_adjacent_pairs", 0)) < MIN_PRIOR_ADJACENT_PAIRS
                or int(row.get("prior_region_pairs", 0)) < MIN_PRIOR_REGION_PAIRS):
            continue
        key = (row["region"], row["relative_path"], int(row["source_offset"]),
               row["decompressed_sha256"], row["measurement"])
        old = unique.get(key)
        if old is None or (row["prior_adjacent_pairs"], row["prior_region_pairs"]) > (
                old["prior_adjacent_pairs"], old["prior_region_pairs"]):
            unique[key] = row
    grouped: dict[tuple[str, str], dict[str, list[dict[str, Any]]]] = {}
    for row in unique.values():
        grouped.setdefault((row["decompressed_sha256"], row["measurement"]), {}).setdefault(
            row["region"], []).append(row)
    result = []
    best_per_source_pair: dict[tuple, dict[str, Any]] = {}
    for (payload_sha, measurement), regions in grouped.items():
        names = sorted(regions)
        for i, left_name in enumerate(names):
            for right_name in names[i + 1:]:
                for left in regions[left_name]:
                    for right in regions[right_name]:
                        inputs = sorted([left, right], key=lambda item: item["region"])
                        pair = {"payload_sha256": payload_sha,
                            "payload_bytes": int(inputs[0]["decompressed_bytes"]),
                            "measurement": measurement, "inputs": inputs,
                            "minimum_prior_adjacent_pairs": min(int(x["prior_adjacent_pairs"]) for x in inputs),
                            "minimum_prior_region_pairs": min(int(x["prior_region_pairs"]) for x in inputs)}
                        pair["candidate_id"] = _candidate_id(pair)
                        source_pair_key = (payload_sha, tuple((x["region"], x["relative_path"], x["source_sha256"])
                            for x in inputs))
                        previous = best_per_source_pair.get(source_pair_key)
                        score = (pair["minimum_prior_adjacent_pairs"], pair["minimum_prior_region_pairs"],
                                 pair["measurement"], tuple(-int(x["source_offset"]) for x in inputs))
                        old_score = ((previous["minimum_prior_adjacent_pairs"], previous["minimum_prior_region_pairs"],
                                      previous["measurement"], tuple(-int(x["source_offset"]) for x in previous["inputs"]))
                                     if previous else None)
                        if previous is None or score > old_score:
                            best_per_source_pair[source_pair_key] = pair
    result = list(best_per_source_pair.values())
    return sorted(result, key=lambda x: (-x["minimum_prior_adjacent_pairs"],
        -x["minimum_prior_region_pairs"], x["payload_sha256"], x["measurement"], x["candidate_id"]))


def _accepted_candidate_inputs(db_path: Path = STATE_DB) -> list[dict[str, Any]]:
    """Read only DONE MG2 profiles whose independent Supervisor is DONE."""
    db = db_path.resolve(strict=True)
    conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("SELECT id,result_json FROM tasks WHERE agent='ncdx-data-family-profile' "
            "AND status='DONE' AND id LIKE 'AUTO_NCDX_DATA_MG2_ZLIB_DECODED_COORDINATE_CANDIDATE_CENSUS_%'").fetchall()
        accepted = []
        for row in rows:
            task_id = str(row["id"])
            if not PROFILE_ID.fullmatch(task_id):
                continue
            supervisor = conn.execute("SELECT status,verdict,result_json FROM tasks WHERE id=?",
                ("AUTO_SUPERVISOR_" + task_id,)).fetchone()
            if not supervisor or supervisor["status"] != "DONE" or supervisor["verdict"] != "PASS":
                continue
            try:
                supervisor_result = json.loads(supervisor["result_json"] or "{}")
            except json.JSONDecodeError:
                continue
            if supervisor_result.get("status") != "PASS":
                continue
            try:
                result = json.loads(row["result_json"] or "{}")
            except json.JSONDecodeError:
                continue
            if (result.get("status") != "PASS" or result.get("suffix") != "MG2"
                    or result.get("profile_mode") != "ZLIB_DECODED_COORDINATE_CANDIDATE_CENSUS"
                    or result.get("profile_parameters", {}).get("tier") != "selected_full_payload_audit"):
                continue
            artifact = result.get("artifact")
            if not isinstance(artifact, dict) or not artifact.get("path") or not artifact.get("sha256"):
                continue
            for obs in result.get("observations", []):
                region = str(obs.get("region", ""))
                relative = str(obs.get("relative_path", "")).replace("\\", "/")
                if (relative != _expected_region_path(region, "MG2")
                        or len(str(obs.get("source_sha256", ""))) != 64
                        or obs.get("source_stat_unchanged") is not True):
                    continue
                selected = {(int(x.get("stream_index", -1)), str(x.get("full_payload_sha256", "")))
                    for x in (obs.get("selected_full_payload_audit") or {}).get("selected_streams", [])}
                for summary in obs.get("candidate_stream_summaries", []):
                    try:
                        stream = int(summary["stream_index"])
                        offset = int(summary["source_offset"])
                        compressed = int(summary["compressed_bytes"])
                        decoded = int(summary["decompressed_bytes"])
                        payload_sha = str(summary["decompressed_sha256"])
                    except (KeyError, TypeError, ValueError):
                        continue
                    if ((stream, payload_sha) not in selected or not re.fullmatch(r"[0-9a-f]{64}", payload_sha)
                            or offset < 0 or not 0 < compressed <= MAX_COMPRESSED_STREAM_BYTES
                            or not 0 < decoded <= MAX_DECOMPRESSED_BYTES):
                        continue
                    for measured in summary.get("candidate_measurements", []):
                        try:
                            region_pairs = int(measured.get("region_candidate_pairs", 0))
                            adjacent = int(measured.get("adjacent_pairs_within_5km", 0))
                            measurement = str(measured["measurement"])
                        except (KeyError, TypeError, ValueError):
                            continue
                        if region_pairs < MIN_PRIOR_REGION_PAIRS or adjacent < MIN_PRIOR_ADJACENT_PAIRS:
                            continue
                        accepted.append({"profile_task_id": task_id, "profile_artifact": artifact,
                            "region": region, "relative_path": relative, "source_sha256": str(obs["source_sha256"]),
                            "stream_count": int(obs.get("stream_count", 0)),
                            "stream_inventory_sha256": str(obs.get("stream_inventory_sha256", "")),
                            "stream_index": stream, "source_offset": offset, "compressed_bytes": compressed,
                            "decompressed_bytes": decoded, "decompressed_sha256": payload_sha,
                            "measurement": measurement, "prior_region_pairs": region_pairs,
                            "prior_adjacent_pairs": adjacent, "selected_full_payload": True})
        return accepted
    finally:
        conn.close()


def _recent_rejections(db_path: Path, limit: int = 8) -> list[dict[str, str]]:
    db = db_path.resolve(strict=True)
    conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("SELECT id,status,hypothesis,verdict,result_json FROM tasks "
            "WHERE status IN ('BLOCKED','REJECTED','FAILED') AND "
            "(id LIKE 'AUTO_NCDX_%' OR id LIKE 'AUTO_MISSION_EXEC_%') "
            "ORDER BY updated_utc DESC LIMIT ?", (limit,)).fetchall()
        output = []
        for row in rows:
            try:
                saved = json.loads(row["result_json"] or "{}")
            except json.JSONDecodeError:
                saved = {}
            output.append({"task_id": str(row["id"]), "status": str(row["status"]),
                "hypothesis": str(row["hypothesis"] or "")[:180],
                "reason": str(saved.get("error") or saved.get("reason") or row["verdict"] or "")[:180]})
        return output
    finally:
        conn.close()


def _qwen_candidate_choice(pairs: list[dict[str, Any]], db_path: Path) -> dict[str, Any]:
    """Local Director selects only an enumerated evidence-bound candidate."""
    from src.agent import mission_pack
    diagnosis = mission_pack.planner_diagnosis(db_path=db_path)
    shortlist = pairs[:8]
    context = {"unfinished_goal_count": diagnosis.get("unfinished_count"),
        "dependency_blocked_count": diagnosis.get("dependency_blocked_count"),
        "waiting_counts": diagnosis.get("waiting_counts", {}),
        "mission_diagnosis": str(diagnosis.get("message", ""))[:300],
        "recent_rejected_hypotheses": _recent_rejections(db_path),
        "candidate_pairs": [{"candidate_id": x["candidate_id"], "payload_sha256": x["payload_sha256"],
            "regions": [i["region"] for i in x["inputs"]], "measurement": x["measurement"],
            "minimum_prior_adjacent_pairs": x["minimum_prior_adjacent_pairs"],
            "minimum_prior_region_pairs": x["minimum_prior_region_pairs"]} for x in shortlist]}
    schema = {"type": "object", "properties": {"candidate_id": {"type": "string"},
        "reason": {"type": "string"}}, "required": ["candidate_id", "reason"], "additionalProperties": False}
    prompt = ("You are the local NCDx research director. Choose exactly one candidate_id from candidate_pairs. "
        "Prioritize independent cross-region evidence and CTY/bounds validation. These are coordinate candidates, "
        "not decoded roads. Do not invent evidence or choose an unlisted id. Return only JSON.\n"
        + json.dumps(context, ensure_ascii=False, separators=(",", ":")))
    try:
        model, answer_text = autonomous_manager._ollama_chat(prompt, model="qwen3.5:9b", max_tokens=220, schema=schema)
        answer = json.loads(answer_text)
        chosen = str(answer.get("candidate_id", ""))
        if chosen not in {item["candidate_id"] for item in shortlist}:
            raise ValueError("Qwen selected no registered candidate")
        return {"decision_source": "qwen3.5:9b", "model": model, "candidate_id": chosen,
            "reason": str(answer.get("reason", ""))[:400], "context": context}
    except Exception as exc:
        return {"decision_source": "deterministic_evidence_ranker", "model": None,
            "candidate_id": shortlist[0]["candidate_id"],
            "reason": f"Qwen selection unavailable or invalid ({type(exc).__name__}); highest verified evidence score used.",
            "context": context}


def seed_next_task(db_path: Path = STATE_DB) -> dict[str, Any]:
    """Extend the queue with one non-duplicate, experimentally executable candidate."""
    registry = tool_registry_status(PROJECT_ROOT)
    if not registry.get("allowed"):
        return {"created": False, "reason": f"handler is not installed: {registry.get('reason')}"}
    queue = autonomous_manager.queue_diagnosis()
    if queue.get("eligible_task_ids") or queue.get("leased_count"):
        return {"created": False, "reason": "queue is not idle; eligible work retains priority"}
    pairs = _build_candidate_pairs(_accepted_candidate_inputs(db_path))
    if not pairs:
        return {"created": False, "reason": "no accepted cross-region MG2 pair has the same full-payload hash and measurement with >=3 prior adjacent geographic candidates in both regions"}
    conn = sqlite3.connect(f"file:{db_path.resolve().as_posix()}?mode=ro", uri=True, timeout=10)
    try:
        existing = {str(row[0]) for row in conn.execute("SELECT id FROM tasks WHERE id LIKE 'AUTO_NCDX_GEOBLOCK_%'")}
    finally:
        conn.close()
    work = PROJECT_ROOT / "work" / "autonomous_manager" / "ncdx" / "geoblock_research"
    available = [x for x in pairs if "AUTO_NCDX_GEOBLOCK_" + x["candidate_id"] not in existing
        and not (work / f"AUTO_NCDX_GEOBLOCK_{x['candidate_id']}.json").exists()]
    if not available:
        return {"created": False, "reason": "all qualifying payload pairs already have a durable task or artifact; duplicates were not created"}
    decision = _qwen_candidate_choice(available, db_path)
    pair = next(x for x in available if x["candidate_id"] == decision["candidate_id"])
    task_id = "AUTO_NCDX_GEOBLOCK_" + pair["candidate_id"]
    dependencies = sorted({dep for row in pair["inputs"] for dep in
        (row["profile_task_id"], "AUTO_SUPERVISOR_" + row["profile_task_id"])})
    task = {"id": task_id, "stage": "F2", "depends_on": dependencies,
        "hypothesis": (f"The same full-payload MG2 block ({pair['payload_sha256'][:16]}) contains a stable "
            f"geographic-coordinate candidate pattern across {', '.join(x['region'] for x in pair['inputs'])}; "
            "CTY bounds and displaced controls can distinguish geography-correlated candidates from arbitrary hits."),
        "evidence": [{"research_expansion": "cross_region_geoblock", "candidate_id": pair["candidate_id"],
            "payload_sha256": pair["payload_sha256"], "measurement": pair["measurement"],
            "prior_inputs": pair["inputs"], "director_decision": decision,
            "claim_limit": "coordinate candidates only; no road geometry decoded"}],
        "agent": AGENT_NAME, "budget": {"timeout_s": 600, "attempts": 1, "source_write": False,
            "ncdx_geoblock_research": True, "handler_version": 1,
            "handler_registry_sha256": registry["registry_sha256"], "candidate_pair": pair,
            "source_families": list(HEADER_FAMILIES), "max_stream_bytes": MAX_COMPRESSED_STREAM_BYTES,
            "max_decompressed_bytes": MAX_DECOMPRESSED_BYTES},
        "deliverables": [f"work/autonomous_manager/ncdx/geoblock_research/{task_id}.json"],
        "tests": ["Prior profile and Supervisor records remain DONE/PASS with exact selected full-payload hashes",
            "Read-only source hashes and MP0/MG1/MG2/MG3 header observations are reproduced",
            "CTY/CNY schema checks and fresh independent coordinate replay agree",
            "Geographic, CTY-box, displaced-control, and interregional criteria are reported",
            "No route or road decoding claim is emitted"],
        "next_action": "Persist evidence, request independent Supervisor replay, then schedule a different unused accepted candidate.",
        "retry_limit": 1, "priority": 4}
    created = state_store.add_task(task, db_path=db_path)
    if created:
        autonomous_manager._event("ncdx_geoblock_research_opportunity_created", {
            "task_id": task_id, "candidate_id": pair["candidate_id"],
            "payload_sha256": pair["payload_sha256"], "regions": [x["region"] for x in pair["inputs"]],
            "measurement": pair["measurement"], "director": decision["decision_source"],
            "codex_cli_used": False}, task_id=task_id)
    return {"created": created, "task_id": task_id if created else None,
        "candidate_id": pair["candidate_id"], "decision": decision["decision_source"],
        "reason": decision["reason"], "dependencies": dependencies}


def _read_manifest_sources(regions: set[str]) -> tuple[Path, dict[tuple[str, str], dict[str, Any]]]:
    root = coordinator_runtime.SOURCE_ROOT.resolve(strict=True)
    expected = {}
    for suffix in (*HEADER_FAMILIES, "CTY", "CNY"):
        for row in project_director._data_profile_sources(suffix):
            if str(row["region"]) in regions:
                expected[(str(row["region"]), suffix)] = row
    for region in regions:
        for suffix in (*HEADER_FAMILIES, "CTY", "CNY"):
            if (region, suffix) not in expected or expected[(region, suffix)]["relative_path"] != _expected_region_path(region, suffix):
                raise RuntimeError(f"manifest has no exact read-only source for {region}.{suffix}")
    return root, expected


def _source_identity(root: Path, row: dict[str, Any]) -> tuple[Path, dict[str, Any]]:
    relative = PurePosixPath(str(row["relative_path"]).replace("\\", "/"))
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("original-media path must be relative")
    source = (root / Path(*relative.parts)).resolve(strict=True)
    if not source.is_relative_to(root) or not source.is_file():
        raise ValueError("original-media source escaped configured root")
    before = source.stat()
    digest = _sha256_file(source)
    after = source.stat()
    signature = lambda item: (item.st_size, item.st_mtime_ns, item.st_ctime_ns)
    if digest != str(row["sha256"]) or before.st_size != int(row["size_bytes"]) or signature(before) != signature(after):
        raise RuntimeError(f"source differs from the saved manifest or changed during read: {relative}")
    return source, {"region": row["region"], "relative_path": relative.as_posix(),
        "size_bytes": after.st_size, "sha256": digest, "stat_signature": list(signature(after)),
        "source_write_count": 0}


def _read_candidate_stream(root: Path, expected: dict[str, Any], candidate: dict[str, Any],
                           source_identity: dict[str, Any]) -> bytes:
    task_id = str(candidate.get("profile_task_id", ""))
    if not PROFILE_ID.fullmatch(task_id) or candidate.get("relative_path") != _expected_region_path(candidate.get("region", ""), "MG2"):
        raise ValueError("candidate is outside the accepted MG2 task/path allowlist")
    profile = project_director._task_result(task_id)
    supervisor_id = "AUTO_SUPERVISOR_" + task_id
    supervisor = project_director._task_result(supervisor_id) if project_director._task_status(supervisor_id) == "DONE" else {}
    if (project_director._task_status(supervisor_id) != "DONE" or supervisor.get("status") != "PASS"
            or profile.get("status") != "PASS"
            or profile.get("profile_mode") != "ZLIB_DECODED_COORDINATE_CANDIDATE_CENSUS"):
        raise RuntimeError("candidate is no longer independently accepted")
    artifact = profile.get("artifact", {})
    artifact_path = _safe_project_file(PROJECT_ROOT, str(artifact.get("path", "")))
    if artifact.get("sha256") != candidate.get("profile_artifact", {}).get("sha256") or _sha256_file(artifact_path) != artifact.get("sha256"):
        raise RuntimeError("prior accepted profile artifact hash changed")
    obs = next((x for x in profile.get("observations", []) if x.get("region") == candidate.get("region")
        and x.get("relative_path") == candidate.get("relative_path")), None)
    if (not obs or obs.get("source_sha256") != expected["sha256"]
            or obs.get("stream_inventory_sha256") != candidate.get("stream_inventory_sha256")
            or int(obs.get("stream_count", -1)) != int(candidate.get("stream_count", -2))):
        raise RuntimeError("profile source/stream inventory does not match task input")
    summary = next((x for x in obs.get("candidate_stream_summaries", [])
        if int(x.get("stream_index", -1)) == int(candidate["stream_index"])
        and int(x.get("source_offset", -1)) == int(candidate["source_offset"])
        and int(x.get("compressed_bytes", -1)) == int(candidate["compressed_bytes"])
        and x.get("decompressed_sha256") == candidate.get("decompressed_sha256")), None)
    measured = next((x for x in (summary or {}).get("candidate_measurements", [])
        if x.get("measurement") == candidate.get("measurement")), None)
    full = next((x for x in (obs.get("selected_full_payload_audit") or {}).get("selected_streams", [])
        if int(x.get("stream_index", -1)) == int(candidate["stream_index"])
        and x.get("full_payload_sha256") == candidate.get("decompressed_sha256")), None)
    if (not summary or not measured or not full
            or int(measured.get("adjacent_pairs_within_5km", 0)) < MIN_PRIOR_ADJACENT_PAIRS
            or int(measured.get("region_candidate_pairs", 0)) < MIN_PRIOR_REGION_PAIRS):
        raise RuntimeError("accepted report no longer supports this selected full-payload coordinate measurement")
    source = (root / Path(*PurePosixPath(candidate["relative_path"]).parts)).resolve(strict=True)
    before = source.stat()
    signature = [before.st_size, before.st_mtime_ns, before.st_ctime_ns]
    if signature != source_identity["stat_signature"]:
        raise RuntimeError("MG2 source changed after manifest-bound verification")
    offset, count = int(candidate["source_offset"]), int(candidate["compressed_bytes"])
    if offset < 0 or not 0 < count <= MAX_COMPRESSED_STREAM_BYTES or offset + count > before.st_size:
        raise ValueError("compressed stream is outside bounded source")
    with source.open("rb") as stream:
        stream.seek(offset)
        compressed = stream.read(count)
    if len(compressed) != count:
        raise RuntimeError("compressed stream was truncated")
    decoder = zlib.decompressobj()
    payload = decoder.decompress(compressed, MAX_DECOMPRESSED_BYTES + 1)
    if (len(payload) != int(candidate["decompressed_bytes"]) or len(payload) > MAX_DECOMPRESSED_BYTES
            or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail
            or hashlib.sha256(payload).hexdigest() != candidate["decompressed_sha256"]):
        raise RuntimeError("bounded zlib replay did not reproduce exact full-payload hash and EOF")
    after = source.stat()
    if [after.st_size, after.st_mtime_ns, after.st_ctime_ns] != signature:
        raise RuntimeError("MG2 source changed during selected stream read")
    return payload


def _independent_all_city_box_counts(payload: bytes, measurement: str, region: str,
                                     boxes: list[tuple[int, int, int, int]]) -> dict[str, int]:
    """Naively enumerate every overlapping CTY box, independently of the spatial index."""
    match = re.fullmatch(r"alignment_([0-7])/scale_(100000|1000000|10000000)_(lat_lon|lon_lat)", measurement)
    if not match:
        raise ValueError("independent verifier rejected measurement")
    start, scale, order = int(match.group(1)), int(match.group(2)), match.group(3)
    bounds = city_reader.REGION_BOUNDS[region]
    hits, unique = 0, set()
    for offset in range(start, len(payload) - 7, 8):
        first, second = struct.unpack_from("<ii", payload, offset)
        lat, lon = ((first / scale, second / scale) if order == "lat_lon" else (second / scale, first / scale))
        if not (bounds[0] <= lat <= bounds[2] and bounds[1] <= lon <= bounds[3]):
            continue
        lat_i, lon_i = round(lat * 100000), round(lon * 100000)
        matches = [i for i, box in enumerate(boxes)
            if box[0] <= lon_i <= box[2] and box[1] <= lat_i <= box[3]]
        if matches:
            hits += 1
            unique.update(matches)
    return {"points_inside_cty_city_bounding_boxes": hits, "distinct_cty_city_boxes_hit": len(unique)}


def _read_region_tables(region: str, identities: dict) -> tuple[dict[str, Any], list[tuple[int, int, int, int]]]:
    cny_path, cny_source = identities[(region, "CNY")]
    cty_path, cty_source = identities[(region, "CTY")]
    cny, _ = city_reader._read_fixed_table(cny_path, "CNY")
    cty, boxes = city_reader._read_fixed_table(cty_path, "CTY", cny_count=int(cny["parsed_record_count"]))
    if any(not x.get("table_schema_pass") or not x.get("source_unchanged_during_read") for x in (cny, cty)):
        raise RuntimeError(f"{region} CTY/CNY table schema or read stability check failed")
    if cty["parsed_record_count"] != len(boxes) or cty["source_size_bytes"] != cty_source["size_bytes"] or cny["source_size_bytes"] != cny_source["size_bytes"]:
        raise RuntimeError("fixed-table readback count or size differs from manifest")
    return {"cty": {"source": cty_source, **cty}, "cny": {"source": cny_source, **cny}}, boxes


def _header_observations(region: str, identities: dict,
                         boxes: list[tuple[int, int, int, int]]) -> list[dict[str, Any]]:
    output = []
    for family in HEADER_FAMILIES:
        path, source = identities[(region, family)]
        with path.open("rb") as stream:
            header = stream.read(110)
        if len(header) != 110:
            raise RuntimeError(f"{region}.{family} geographic header is truncated")
        facts = analyzer.parse_geographic_header(header)
        if not facts["bbox_valid"]:
            raise RuntimeError(f"{region}.{family} offset-94 candidate bbox is outside ordered WGS84 bounds")
        west, south, east, north = facts["bbox_i32"]
        contained = sum(west <= x1 and south <= y1 and x2 <= east and y2 <= north for x1, y1, x2, y2 in boxes)
        bounds = city_reader.REGION_BOUNDS[region]
        intersects_region = (west / 100000 <= bounds[3] and east / 100000 >= bounds[1]
            and south / 100000 <= bounds[2] and north / 100000 >= bounds[0])
        output.append({"region": region, "family": family, "source": source,
            "header_sha256": hashlib.sha256(header).hexdigest(),
            "record_count_header_field": facts["record_count"],
            "field_90_u32_uninterpreted": facts["field_90_u32_uninterpreted"],
            "candidate_bbox_i32_at_offset_94": facts["bbox_i32"],
            "candidate_bbox_degrees": facts["bbox_degrees"], "bbox_valid_wgs84": facts["bbox_valid"],
            "candidate_bbox_intersects_configured_region_bounds": intersects_region,
            "cty_city_boxes_fully_contained": contained, "cty_city_box_count": len(boxes),
            "claim_scope": "header-field and CTY-bound comparison; road/family semantics not inferred"})
    return output


def _run_pair(task_id: str, pair: dict[str, Any]) -> dict[str, Any]:
    inputs = pair.get("inputs", [])
    if (len(inputs) != 2 or len({x.get("region") for x in inputs}) != 2
            or len({x.get("decompressed_sha256") for x in inputs}) != 1
            or len({x.get("measurement") for x in inputs}) != 1
            or not re.fullmatch(r"[0-9a-f]{64}", str(pair.get("payload_sha256", "")))):
        raise ValueError("task must name one identical full-payload, same-measurement cross-region pair")
    if pair.get("candidate_id") != _candidate_id(pair):
        raise ValueError("candidate identity hash does not match its source pair")
    regions = {str(x["region"]) for x in inputs}
    root, expected = _read_manifest_sources(regions)
    identities = {key: _source_identity(root, row) for key, row in expected.items()}
    region_tables, boxes_by_region, headers = {}, {}, []
    for region in sorted(regions):
        region_tables[region], boxes_by_region[region] = _read_region_tables(region, identities)
        headers.extend(_header_observations(region, identities, boxes_by_region[region]))
    observations = []
    for candidate in sorted(inputs, key=lambda x: x["region"]):
        region = str(candidate["region"])
        row = expected[(region, "MG2")]
        if row["relative_path"] != candidate["relative_path"] or row["sha256"] != candidate["source_sha256"]:
            raise RuntimeError("MG2 candidate identity no longer matches the read-only inventory")
        mg2_identity = identities[(region, "MG2")][1]
        payload = _read_candidate_stream(root, row, candidate, mg2_identity)
        boxes = boxes_by_region[region]
        measurement = str(pair["measurement"])
        metrics = analyzer.analyze_payload(payload, measurement, city_reader.REGION_BOUNDS[region],
            city_reader.CONTROL_BOUNDS[region], boxes, max_step_km=5.0)
        legacy = city_reader._scan_coordinates(payload, measurement, region, boxes)
        all_box_counts = _independent_all_city_box_counts(payload, measurement, region, boxes)
        core_keys = ("coordinate_candidate_pairs_in_region", "coordinate_pairs_in_displaced_control",
            "points_inside_cty_city_bounding_boxes", "adjacent_pairs_within_5km",
            "max_continuous_region_candidate_points", "payload_bytes_examined")
        core_match = all(metrics[key] == legacy[key] for key in core_keys)
        overlap_match = (metrics["points_inside_cty_city_bounding_boxes"] == all_box_counts["points_inside_cty_city_bounding_boxes"]
            and metrics["distinct_cty_city_boxes_hit"] == all_box_counts["distinct_cty_city_boxes_hit"])
        if not core_match or not overlap_match:
            raise RuntimeError(f"independent geographic/CTY replay disagrees for {region}")
        observations.append({"region": region, "prior_profile_task_id": candidate["profile_task_id"],
            "prior_profile_artifact": candidate["profile_artifact"], "map_source": mg2_identity,
            "stream_index": int(candidate["stream_index"]), "source_offset": int(candidate["source_offset"]),
            "compressed_bytes": int(candidate["compressed_bytes"]), "decompressed_bytes": len(payload),
            "decompressed_sha256": hashlib.sha256(payload).hexdigest(), "measurement": measurement,
            "prior_geographic_signal": {"region_candidate_pairs": int(candidate["prior_region_pairs"]),
                "adjacent_pairs_within_5km": int(candidate["prior_adjacent_pairs"])},
            "tables": region_tables[region], "metrics": metrics,
            "independent_verification": {"legacy_fixed_parser_match": core_match,
                "legacy_first_match_unique_cty_boxes": legacy["distinct_cty_city_boxes_hit"],
                "all_overlap_cty_box_enumeration_match": overlap_match,
                "all_overlap_cty_box_metrics": all_box_counts,
                "verifier": "ncdx_city_coordinate_crosscheck plus independent all-overlap box enumeration"},
            "source_write_count": 0, "original_media_write_count": 0})
    geographic = all(x["metrics"]["coordinate_candidate_pairs_in_region"] >= 40
        and x["metrics"]["points_inside_cty_city_bounding_boxes"] >= 5
        and x["metrics"]["distinct_cty_city_boxes_hit"] >= 3
        and x["metrics"]["adjacent_pairs_within_5km"] >= MIN_PRIOR_ADJACENT_PAIRS
        and x["metrics"]["coordinate_pairs_in_displaced_control"] < x["metrics"]["coordinate_candidate_pairs_in_region"]
        for x in observations)
    same_payload = len({x["decompressed_sha256"] for x in observations}) == 1
    return {"task_id": task_id, "schema_version": 1,
        "experiment": "cross_region_geoblock_coordinate_and_header_validation",
        "candidate_id": pair["candidate_id"], "candidate_payload_sha256": pair["payload_sha256"],
        "measurement": pair["measurement"], "regions": observations, "header_observations": headers,
        "interregional_check": {"same_full_decompressed_payload_sha256": same_payload,
            "regions": sorted(regions), "same_measurement": True,
            "both_regions_pass_geographic_cty_control_thresholds": geographic,
            "thresholds": {"minimum_region_candidate_pairs": 40, "minimum_cty_box_hits": 5,
                "minimum_distinct_cty_boxes": 3, "minimum_adjacent_pairs_within_5km": 3,
                "control_pairs_less_than_region_pairs": True}},
        "hypothesis_result": "SUPPORTED_COORDINATE_CANDIDATE_ONLY" if same_payload and geographic else "WEAK_OR_DIVERGENT_CANDIDATE",
        "road_geometry_decoded": False,
        "claim_scope": "reproducible geographic coordinate candidates and header/CTY comparisons only; no route, road, or navigation semantics proven",
        "source_write_count": 0, "original_media_write_count": 0,
        "reproducibility": "manifest-bound source hashes, exact compressed offsets, zlib EOF and full-payload hashes, fresh CTY/CNY parse and independent readback"}


def execute_task(task_id: str) -> dict[str, Any]:
    registry = tool_registry_status(PROJECT_ROOT)
    task = autonomous_manager._task(task_id)
    budget = task.get("budget", {})
    if (task.get("agent") != AGENT_NAME or budget.get("ncdx_geoblock_research") is not True
            or budget.get("handler_version") != 1 or not registry.get("allowed")
            or budget.get("handler_registry_sha256") != registry.get("registry_sha256")):
        raise RuntimeError("geoblock handler refused unregistered or changed task")
    findings = _run_pair(task_id, budget.get("candidate_pair") or {})
    artifact_path = (PROJECT_ROOT / "work" / "autonomous_manager" / "ncdx" / "geoblock_research"
                     / f"{task_id}.json").resolve()
    if not artifact_path.is_relative_to((PROJECT_ROOT / "work" / "autonomous_manager").resolve()):
        raise RuntimeError("artifact path escaped manager-owned work")
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = artifact_path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps({"status": "PASS", "task_id": task_id,
        "created_utc": _utc(), "findings": findings},
        ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, artifact_path)
    artifact = autonomous_manager._artifact(task_id, artifact_path,
        "Read-only cross-region MG2 geoblock and CTY/header correlation evidence",
        "PASS: full-payload provenance, geographic bounds and independent replay reproduced; road semantics UNKNOWN")
    supervisor_id = "AUTO_SUPERVISOR_" + task_id
    if not project_director._register_supervisor(supervisor_id, task_id) and project_director._task_status(supervisor_id) not in {"PENDING", "LEASED", "DONE"}:
        raise RuntimeError("geoblock Supervisor task could not be durably registered")
    autonomous_manager._event("ncdx_geoblock_experiment_finished", {
        "candidate_id": findings["candidate_id"], "hypothesis_result": findings["hypothesis_result"],
        "road_geometry_decoded": False, "artifact_sha256": artifact["sha256"],
        "source_write_count": 0}, task_id=task_id)
    return {"status": "PASS", "task_id": task_id, "findings": findings, "artifact": artifact,
        "supervisor_task_id": supervisor_id, "source_write_count": 0, "original_media_write_count": 0}


def verify_target(target_task: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    """Fresh deterministic Supervisor replay; never writes to sources or project state."""
    registry = tool_registry_status(PROJECT_ROOT)
    budget, task_id = target_task.get("budget", {}), str(target_task.get("id", ""))
    if (not registry.get("allowed") or budget.get("ncdx_geoblock_research") is not True
            or budget.get("handler_version") != 1
            or budget.get("handler_registry_sha256") != registry.get("registry_sha256")
            or result.get("status") != "PASS" or result.get("source_write_count") != 0
            or result.get("original_media_write_count") != 0):
        raise RuntimeError("Supervisor refused unregistered geoblock evidence or source writes")
    artifact = result.get("artifact")
    relative = f"work/autonomous_manager/ncdx/geoblock_research/{task_id}.json"
    if not isinstance(artifact, dict) or str(artifact.get("path", "")).replace("\\", "/") != relative:
        raise RuntimeError("Supervisor refused missing or unexpected geoblock artifact")
    path = _safe_project_file(PROJECT_ROOT, relative)
    actual = _sha256_file(path)
    if actual != artifact.get("sha256") or path.stat().st_size != int(artifact.get("size_bytes", -1)):
        raise RuntimeError("Supervisor artifact hash or size changed")
    saved = json.loads(path.read_text(encoding="utf-8"))
    if saved.get("task_id") != task_id or saved.get("status") != "PASS":
        raise RuntimeError("Supervisor artifact identity or status is invalid")
    fresh = _run_pair(task_id, budget.get("candidate_pair") or {})
    if saved.get("findings") != fresh or result.get("findings") != fresh:
        raise RuntimeError("fresh source and CTY replay differs from saved evidence")
    return {"artifact_sha256": actual, "fresh_source_and_table_hashes_match": True,
        "full_payload_zlib_eof_and_hash_match": True, "independent_coordinate_replay_match": True,
        "cross_region_geographic_cty_controls_match": True,
        "header_family_count": len(fresh["header_observations"]), "region_count": len(fresh["regions"]),
        "hypothesis_result": fresh["hypothesis_result"], "road_geometry_decoded": False,
        "source_write_count": 0, "original_media_write_count": 0, "claim_scope": fresh["claim_scope"]}
