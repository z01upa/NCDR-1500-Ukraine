"""Targeted validation of previously observed NCDx coordinate candidates.

This reader reopens only two evidence-selected zlib streams and their CTY/CNY
tables. It tests the candidate values against independent city bounding boxes;
it never retains raw payload bytes or claims road geometry.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re
import struct
from typing import Any
import zlib

from src.readers.ncdx_container import (
    MAX_FILE_BYTES, MAX_LOGICAL_BYTES, iter_decoded_blocks, read_index,
)


FORMAT_VERSION = 1
HEADER_BYTES = 94
CTY_STRIDE = 178
CNY_STRIDE = 174
MAX_STREAM_BYTES = 1024 * 1024
MAX_DECODED_BYTES = 4 * 1024 * 1024
REGION_BOUNDS = {
    "SW": (35.0, -10.0, 72.0, 40.0),
    "Italy": (35.0, 6.0, 48.0, 20.0),
    "Scandinavia": (54.0, 3.0, 72.0, 33.0),
}
CONTROL_BOUNDS = {
    "SW": (35.0, 35.0, 72.0, 85.0),
    "Italy": (35.0, 35.0, 48.0, 80.0),
    "Scandinavia": (24.0, 3.0, 42.0, 33.0),
}
MEASUREMENT = "alignment_0/scale_1000000_lat_lon"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _load_prior_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    report_path = Path(str(candidate["prior_artifact_path"])).resolve(strict=True)
    expected_report_sha = str(candidate["prior_artifact_sha256"])
    if sha256_file(report_path) != expected_report_sha:
        raise ValueError("prior accepted coordinate report hash changed")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if (report.get("status") != "PASS" or report.get("task_id") != candidate["prior_task_id"]
            or report.get("profile_mode") != "ZLIB_DECODED_COORDINATE_CANDIDATE_CENSUS"):
        raise ValueError("prior evidence is not an accepted decoded-coordinate census")
    observation = next((row for row in report.get("observations", [])
        if row.get("region") == candidate["region"]
        and row.get("relative_path") == candidate["map_relative_path"]), None)
    if not observation:
        raise ValueError("prior coordinate report does not contain the selected regional source")
    if (observation.get("source_sha256") != candidate["map_sha256"]
            or int(observation.get("stream_count", -1)) != int(candidate["stream_count"])
            or observation.get("stream_inventory_sha256") != candidate["stream_inventory_sha256"]):
        raise ValueError("prior census source or stream inventory differs from the selected input")
    summary = next((row for row in observation.get("candidate_stream_summaries", [])
        if int(row.get("stream_index", -1)) == int(candidate["stream_index"])
        and int(row.get("source_offset", -1)) == int(candidate["source_offset"])
        and int(row.get("compressed_bytes", -1)) == int(candidate["compressed_bytes"])
        and row.get("decompressed_sha256") == candidate["decompressed_sha256"]), None)
    if not summary:
        raise ValueError("prior census does not bind the selected stream offset and payload hash")
    measurements = {row.get("measurement"): row for row in summary.get("candidate_measurements", [])}
    measured = measurements.get(candidate.get("measurement"))
    if (not measured or int(measured.get("adjacent_pairs_within_5km", 0))
            < int(candidate.get("prior_adjacent_pairs", 1))):
        raise ValueError("prior report does not support the selected short-step candidate")
    selected = next((row for row in (observation.get("selected_full_payload_audit") or {}).get("selected_streams", [])
        if int(row.get("stream_index", -1)) == int(candidate["stream_index"])
        and row.get("full_payload_sha256") == candidate["decompressed_sha256"]), None)
    if not selected:
        raise ValueError("selected stream was not fully re-read and hash-bound by the prior census")
    return {"prior_report_sha256": expected_report_sha,
            "prior_source_sha256": observation["source_sha256"],
            "stream_inventory_sha256": observation["stream_inventory_sha256"],
            "candidate_measurement": measured}


def _read_fixed_table(path: Path, table: str, *, cny_count: int | None = None
                      ) -> tuple[dict[str, Any], list[tuple[int, int, int, int]]]:
    stride, expected_type = (CNY_STRIDE, 12) if table == "CNY" else (CTY_STRIDE, 3)
    before = path.stat()
    header: bytes | None = None
    carry = bytearray()
    record_index = 0
    logical_size = 0
    digest = hashlib.sha256()
    boxes: list[tuple[int, int, int, int]] = []
    bad_ids = bad_refs = bad_reserved = bad_bounds = bad_names = 0
    with path.open("rb") as stream:
        index = read_index(stream, max_file_bytes=MAX_FILE_BYTES,
                           max_logical_bytes=MAX_LOGICAL_BYTES)
        for offset, block in iter_decoded_blocks(stream, index):
            digest.update(block)
            if offset == 0:
                if len(block) < HEADER_BYTES or block[:7] != b"SIEMENS":
                    raise ValueError(f"{path.name}: invalid Siemens table header")
                header = block[:HEADER_BYTES]
                payload = block[HEADER_BYTES:]
            else:
                payload = block
            carry.extend(payload)
            complete = len(carry) - len(carry) % stride
            for pos in range(0, complete, stride):
                row = bytes(carry[pos:pos + stride])
                if table == "CNY":
                    region_id = struct.unpack_from("<H", row, 0)[0]
                    if region_id != record_index:
                        bad_ids += 1
                    if not row[30:].split(b"\0", 1)[0].decode("cp1252").strip():
                        bad_names += 1
                else:
                    city_id, region_id = struct.unpack_from("<II", row, 0)
                    if city_id != record_index:
                        bad_ids += 1
                    if cny_count is None or region_id >= cny_count:
                        bad_refs += 1
                    if row[8:18] != b"\0" * 10:
                        bad_reserved += 1
                    x1, y1, x2, y2 = struct.unpack_from("<iiii", row, 18)
                    if not (-18000000 <= x1 <= x2 <= 18000000
                            and -9000000 <= y1 <= y2 <= 9000000):
                        bad_bounds += 1
                    else:
                        boxes.append((x1, y1, x2, y2))
                    if not row[34:].split(b"\0", 1)[0].decode("cp1252").strip():
                        bad_names += 1
                record_index += 1
            if complete:
                del carry[:complete]
            logical_size += len(block)
    after = path.stat()
    if header is None:
        raise ValueError(f"{path.name}: empty table")
    type_id = struct.unpack_from("<H", header, 84)[0]
    declared_count = struct.unpack_from("<I", header, 86)[0]
    unchanged = before.st_size == after.st_size and before.st_mtime_ns == after.st_mtime_ns
    matched = (type_id == expected_type and record_index == declared_count
        and logical_size == HEADER_BYTES + declared_count * stride and not carry and unchanged
        and bad_ids == bad_refs == bad_reserved == bad_bounds == bad_names == 0)
    return ({"type_id": type_id, "expected_type_id": expected_type,
        "declared_record_count": declared_count, "parsed_record_count": record_index,
        "logical_size_bytes": logical_size, "stride_bytes": stride,
        "logical_sha256": digest.hexdigest(), "source_size_bytes": before.st_size,
        "source_unchanged_during_read": unchanged, "bad_ids": bad_ids,
        "bad_region_references": bad_refs, "bad_reserved_fields": bad_reserved,
        "bad_bounds": bad_bounds, "empty_names": bad_names,
        "table_schema_pass": matched}, boxes)


def _point_in_city_bbox(lat: float, lon: float,
                        boxes: list[tuple[int, int, int, int]]) -> bool:
    lat_i, lon_i = round(lat * 100000), round(lon * 100000)
    return any(x1 <= lon_i <= x2 and y1 <= lat_i <= y2
               for x1, y1, x2, y2 in boxes)


def _scan_coordinates(payload: bytes, measurement: str, region: str,
                       boxes: list[tuple[int, int, int, int]]) -> dict[str, Any]:
    match = re.fullmatch(r"alignment_(\d+)/scale_(\d+)_(lat_lon|lon_lat)", measurement)
    if not match:
        raise ValueError("coordinate measurement is outside the fixed signed-int32 profile")
    alignment, scale = int(match.group(1)), int(match.group(2))
    order = match.group(3)
    if alignment > 7 or scale not in {100000, 1000000, 10000000}:
        raise ValueError("coordinate alignment or scale is outside the bounded profile")
    min_lat, min_lon, max_lat, max_lon = REGION_BOUNDS[region]
    cmin_lat, cmin_lon, cmax_lat, cmax_lon = CONTROL_BOUNDS[region]
    candidate_pairs = control_pairs = city_bbox_hits = adjacent = 0
    unique_city_hits: set[int] = set()
    max_continuous_steps = current_run = 0
    previous: tuple[int, float, float] | None = None
    for pair_index, offset in enumerate(range(alignment, len(payload) - 7, 8)):
        first, second = struct.unpack_from("<ii", payload, offset)
        lat, lon = ((first / scale, second / scale) if order == "lat_lon"
                    else (second / scale, first / scale))
        in_region = min_lat <= lat <= max_lat and min_lon <= lon <= max_lon
        if cmin_lat <= lat <= cmax_lat and cmin_lon <= lon <= cmax_lon:
            control_pairs += 1
        if in_region:
            candidate_pairs += 1
            city_index = next((index for index, box in enumerate(boxes)
                if box[0] <= round(lon * 100000) <= box[2]
                and box[1] <= round(lat * 100000) <= box[3]), None)
            if city_index is not None:
                city_bbox_hits += 1
                unique_city_hits.add(city_index)
            if previous is not None and previous[0] == pair_index - 1:
                _, prior_lat, prior_lon = previous
                mean_lat = math.radians((lat + prior_lat) / 2.0)
                dx = (lon - prior_lon) * math.cos(mean_lat) * 111.32
                dy = (lat - prior_lat) * 111.32
                distance = math.hypot(dx, dy)
                if 0.0 < distance <= 5.0:
                    adjacent += 1
                    current_run = current_run + 1 if current_run else 2
                    max_continuous_steps = max(max_continuous_steps, current_run)
                else:
                    current_run = 1
            else:
                current_run = 1
            previous = (pair_index, lat, lon)
        else:
            current_run = 0
            previous = None
    return {"measurement": measurement, "coordinate_candidate_pairs_in_region": candidate_pairs,
        "coordinate_pairs_in_displaced_control": control_pairs,
        "points_inside_cty_city_bounding_boxes": city_bbox_hits,
        "distinct_cty_city_boxes_hit": len(unique_city_hits),
        "adjacent_pairs_within_5km": adjacent,
        "max_continuous_region_candidate_points": max_continuous_steps,
        "payload_bytes_examined": len(payload),
        "raw_coordinate_values_retained": False}


def analyze(sources: list[dict[str, Any]], candidates: list[dict[str, Any]]) -> dict[str, Any]:
    candidate_regions = {str(row.get("region")) for row in candidates}
    if (not candidates or len(candidate_regions) != len(candidates)
            or candidate_regions not in ({"SW", "Scandinavia"}, {"Italy"})):
        raise ValueError("coordinate cross-check requires the legacy SW/Scandinavia pair or one Italy stream")
    by_region: dict[str, dict[str, dict[str, Any]]] = {}
    for row in sources:
        key = (str(row["region"]), Path(str(row["relative_path"])).suffix.upper().lstrip("."))
        if key[1] not in {"CTY", "CNY", "MG1"} or key[1] in by_region.setdefault(key[0], {}):
            raise ValueError("unexpected or duplicate coordinate cross-check source")
        if key[0] not in REGION_BOUNDS:
            continue
        path = Path(str(row["absolute_path"]))
        if (not path.is_file() or path.stat().st_size != int(row["size_bytes"])
                or sha256_file(path) != str(row["sha256"])):
            raise ValueError(f"{key}: current source differs from its inventory")
        by_region[key[0]][key[1]] = row
    if set(by_region) != candidate_regions or any(set(rows) != {"CTY", "CNY", "MG1"}
                                                   for rows in by_region.values()):
        raise ValueError("coordinate cross-check requires exact CTY/CNY/MG1 inputs for selected regions")
    result_rows = []
    for candidate in candidates:
        region = str(candidate["region"])
        prior = _load_prior_candidate(candidate)
        rows = by_region[region]
        table_paths = {name: Path(str(rows[name]["absolute_path"])) for name in ("CTY", "CNY")}
        cny, _ = _read_fixed_table(table_paths["CNY"], "CNY")
        cty, boxes = _read_fixed_table(table_paths["CTY"], "CTY",
            cny_count=int(cny["parsed_record_count"]))
        if not cny["table_schema_pass"] or not cty["table_schema_pass"]:
            raise RuntimeError(f"{region}: city tables failed their independently evidenced fixed schema")
        map_source = Path(str(rows["MG1"]["absolute_path"]))
        if str(candidate["map_relative_path"]) != str(rows["MG1"]["relative_path"]):
            raise ValueError("selected coordinate source does not match this region's inventoried MG1")
        before_stat = map_source.stat()
        before_hash = sha256_file(map_source)
        if before_hash != str(rows["MG1"]["sha256"]):
            raise ValueError(f"{region}/MG1: source hash changed before stream read")
        offset = int(candidate["source_offset"])
        compressed_bytes = int(candidate["compressed_bytes"])
        decoded_expected = int(candidate["decompressed_bytes"])
        if (offset < 0 or not 0 < compressed_bytes <= MAX_STREAM_BYTES
                or not 16 <= decoded_expected <= MAX_DECODED_BYTES
                or offset + compressed_bytes > before_stat.st_size):
            raise ValueError("selected zlib stream range is outside fixed bounded limits")
        with map_source.open("rb") as stream:
            stream.seek(offset)
            compressed = stream.read(compressed_bytes)
        decoder = zlib.decompressobj()
        payload = decoder.decompress(compressed, MAX_DECODED_BYTES + 1)
        if len(payload) > MAX_DECODED_BYTES or decoder.unconsumed_tail:
            raise ValueError("selected zlib stream exceeded the decoded output limit")
        payload += decoder.flush(MAX_DECODED_BYTES + 1 - len(payload))
        if (not decoder.eof or decoder.unused_data or decoder.unconsumed_tail
                or len(payload) != decoded_expected
                or hashlib.sha256(payload).hexdigest() != str(candidate["decompressed_sha256"])):
            raise ValueError("selected zlib stream length, checksum, or exact boundary differs from prior evidence")
        after_hash = sha256_file(map_source)
        after_stat = map_source.stat()
        source_unchanged = (before_hash == after_hash == str(rows["MG1"]["sha256"])
            and before_stat.st_size == after_stat.st_size
            and before_stat.st_mtime_ns == after_stat.st_mtime_ns)
        if not source_unchanged:
            raise RuntimeError(f"{region}/MG1 source changed during read-only experiment")
        measurement = _scan_coordinates(payload, str(candidate["measurement"]), region, boxes)
        checks = {
            "prior_census_artifact_hash_matches": True,
            "prior_full_stream_sha256_reproduced": True,
            "current_map_source_unchanged": source_unchanged,
            "cty_cny_tables_verified": cty["table_schema_pass"] and cny["table_schema_pass"],
            "candidate_measurement_reproduced": (
                measurement["coordinate_candidate_pairs_in_region"]
                >= int(prior["candidate_measurement"]["region_candidate_pairs"])
                and measurement["adjacent_pairs_within_5km"]
                >= int(prior["candidate_measurement"]["adjacent_pairs_within_5km"])),
            "city_bbox_hits_exceed_control": (
                measurement["points_inside_cty_city_bounding_boxes"]
                > measurement["coordinate_pairs_in_displaced_control"]),
        }
        result_rows.append({"region": region, "prior_census": {
                "task_id": candidate["prior_task_id"],
                "artifact_sha256": prior["prior_report_sha256"],
                "stream_inventory_sha256": prior["stream_inventory_sha256"],
                "stream_index": int(candidate["stream_index"]),
                "source_offset": offset, "compressed_bytes": compressed_bytes,
                "decompressed_bytes": len(payload),
                "decompressed_sha256": hashlib.sha256(payload).hexdigest(),
                "measurement": candidate["measurement"],
                "reported_candidate_pairs": int(prior["candidate_measurement"]["region_candidate_pairs"]),
                "reported_adjacent_pairs_within_5km": int(prior["candidate_measurement"]["adjacent_pairs_within_5km"])},
            "cty": cty, "cny": cny, "coordinate_association": measurement,
            "checks": checks, "source_identities": {
                name: {"relative_path": str(rows[name]["relative_path"]),
                       "sha256": str(rows[name]["sha256"]),
                       "size_bytes": int(rows[name]["size_bytes"])}
                for name in ("CTY", "CNY", "MG1")}})
    supported = all(all(row["checks"].values()) for row in result_rows)
    hypothesis = (
        "An independently accepted Italian MG1 stream measured at 1e5 scale and lon/lat order "
        "contains candidate points inside Italian CTY city boxes more often than in a displaced control window."
        if candidate_regions == {"Italy"} else
        "Two independently accepted MG1 streams with repeated geographic short-step candidates contain points inside their own region's CTY city boxes more often than in the displaced control window.")
    return {"status": "PASS", "format_version": FORMAT_VERSION,
        "experiment": "ncdx_candidate_coordinates_vs_cty_city_boxes",
        "hypothesis": hypothesis,
        "hypothesis_result": "SUPPORTED" if supported else "FALSIFIED_OR_DIVERGENT",
        "regions": result_rows, "original_media_write_count": 0,
        "claim_scope": "Validation of bounded signed-integer coordinate candidates against CTY city bounding boxes only; not road geometry, topology, routing, or physical disk compatibility."}


def verify_artifact(path: Path, sources: list[dict[str, Any]], candidates: list[dict[str, Any]],
                    expected_sha256: str) -> dict[str, Any]:
    if not path.is_file() or sha256_file(path) != expected_sha256:
        raise ValueError("coordinate cross-check artifact hash changed")
    saved = json.loads(path.read_text(encoding="utf-8"))
    if (saved.get("status") != "PASS"
            or saved.get("experiment") != "ncdx_candidate_coordinates_vs_cty_city_boxes"
            or saved.get("format_version") != FORMAT_VERSION
            or saved.get("original_media_write_count") != 0
            or len(saved.get("regions", [])) != len(candidates)):
        raise ValueError("coordinate cross-check artifact schema is invalid")
    replay = analyze(sources, candidates)
    if (saved.get("hypothesis_result") != replay.get("hypothesis_result")
            or saved.get("regions") != replay.get("regions")
            or saved.get("claim_scope") != replay.get("claim_scope")):
        raise ValueError("independent coordinate/CTY replay differs from saved evidence")
    identities = [source for row in saved["regions"]
                  for source in row.get("source_identities", {}).values()]
    if len(identities) != len(candidates) * 3:
        raise ValueError("coordinate cross-check must bind exactly three current files per selected region")
    return {"status": "PASS", "artifact_sha256": expected_sha256,
            "verified_source_count": len(identities),
            "regions": {row["region"]: row["checks"] for row in saved["regions"]},
            "hypothesis_result": saved["hypothesis_result"],
            "original_media_write_count": 0,
            "claim_scope": saved["claim_scope"]}
