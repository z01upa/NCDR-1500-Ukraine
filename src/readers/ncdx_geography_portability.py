"""Read-only cross-region CTY/CNY and spatial-header portability experiment.

The result tests a fixed, evidence-backed structural schema. Spatial header
coordinates remain a candidate interpretation; this module does not decode
MP0/MG road records or claim routing semantics.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct
from typing import Any

from src.readers.ncdx_container import (
    MAX_FILE_BYTES, MAX_LOGICAL_BYTES, iter_decoded_blocks, read_index,
)


FORMAT_VERSION = 1
HEADER_BYTES = 94
TABLES = {"CTY": (3, 178), "CNY": (12, 174)}
MAP_HEADERS = ("MP0", "MG1", "MG2", "MG3")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _scan_table(path: Path, *, expected_type: int, stride: int,
                region_count: int | None = None) -> dict[str, Any]:
    before = path.stat()
    logical_sha = hashlib.sha256()
    carry = bytearray()
    parsed_count = 0
    logical_bytes = 0
    region_names: list[str] = []
    city_extent = [2**31 - 1, 2**31 - 1, -(2**31), -(2**31)]
    bad_city_ids = bad_region_refs = bad_reserved = bad_bounds = bad_names = 0
    header: bytes | None = None
    with path.open("rb") as stream:
        index = read_index(stream, max_file_bytes=MAX_FILE_BYTES,
                           max_logical_bytes=MAX_LOGICAL_BYTES)
        for logical_offset, block in iter_decoded_blocks(stream, index):
            logical_sha.update(block)
            if logical_offset == 0:
                if len(block) < HEADER_BYTES or block[:7] != b"SIEMENS":
                    raise ValueError(f"{path.name}: invalid decoded Siemens header")
                header = block[:HEADER_BYTES]
                payload = block[HEADER_BYTES:]
            else:
                payload = block
            carry.extend(payload)
            complete = len(carry) - len(carry) % stride
            for position in range(0, complete, stride):
                record = bytes(carry[position:position + stride])
                if expected_type == TABLES["CNY"][0]:
                    region_id = struct.unpack_from("<H", record, 0)[0]
                    name = record[30:].split(b"\0", 1)[0].decode("cp1252")
                    if region_id != parsed_count:
                        bad_region_refs += 1
                    if not name.strip():
                        bad_names += 1
                    region_names.append(name)
                else:
                    city_id, region_id = struct.unpack_from("<II", record, 0)
                    x1, y1, x2, y2 = struct.unpack_from("<iiii", record, 18)
                    if city_id != parsed_count:
                        bad_city_ids += 1
                    if region_count is None or region_id >= region_count:
                        bad_region_refs += 1
                    if record[8:18] != b"\0" * 10:
                        bad_reserved += 1
                    if not (-18000000 <= x1 <= x2 <= 18000000
                            and -9000000 <= y1 <= y2 <= 9000000):
                        bad_bounds += 1
                    else:
                        city_extent = [min(city_extent[0], x1), min(city_extent[1], y1),
                                       max(city_extent[2], x2), max(city_extent[3], y2)]
                    if not record[34:].split(b"\0", 1)[0].decode("cp1252").strip():
                        bad_names += 1
                parsed_count += 1
            if complete:
                del carry[:complete]
            logical_bytes += len(block)
    after = path.stat()
    if header is None:
        raise ValueError(f"{path.name}: empty decoded container")
    file_type = struct.unpack_from("<H", header, 84)[0]
    declared_count = struct.unpack_from("<I", header, 86)[0]
    source_stable = (before.st_size == after.st_size
                     and before.st_mtime_ns == after.st_mtime_ns)
    row: dict[str, Any] = {
        "logical_sha256": logical_sha.hexdigest(), "logical_size_bytes": logical_bytes,
        "container_block_count": index.block_count,
        "container_block_size_bytes": index.block_size_bytes,
        "type_id": file_type, "expected_type_id": expected_type,
        "declared_record_count": declared_count, "parsed_record_count": parsed_count,
        "stride_bytes": stride, "trailing_bytes": len(carry),
        "source_size_bytes": before.st_size, "source_mtime_unchanged": source_stable,
        "fixed_table_matches_header": (file_type == expected_type
            and declared_count == parsed_count
            and logical_bytes == HEADER_BYTES + declared_count * stride
            and not carry and source_stable),
        "bad_sequential_ids": bad_city_ids if expected_type == TABLES["CTY"][0]
                              else bad_region_refs,
        "bad_region_references": bad_region_refs if expected_type == TABLES["CTY"][0] else 0,
        "bad_reserved_fields": bad_reserved, "bad_geographic_bounds": bad_bounds,
        "empty_names": bad_names,
    }
    if expected_type == TABLES["CTY"][0]:
        row["city_extent_int32"] = city_extent
        row["city_extent_candidate_degrees"] = [value / 100000 for value in city_extent]
    else:
        row["region_name_count"] = len(region_names)
        row["region_name_preview"] = region_names[:8]
    return row


def _scan_map_header(path: Path) -> dict[str, Any]:
    before = path.stat()
    with path.open("rb") as stream:
        header = stream.read(110)
    after = path.stat()
    if len(header) != 110:
        raise ValueError(f"{path.name}: truncated spatial header")
    file_type = struct.unpack_from("<H", header, 84)[0]
    declared_count = struct.unpack_from("<I", header, 86)[0]
    preceding_u32 = struct.unpack_from("<I", header, 90)[0]
    bbox_int32 = list(struct.unpack_from("<iiii", header, 94))
    bbox = [value / 100000 for value in bbox_int32]
    stable = before.st_size == after.st_size and before.st_mtime_ns == after.st_mtime_ns
    valid = (-180 <= bbox[0] <= bbox[2] <= 180
             and -90 <= bbox[1] <= bbox[3] <= 90)
    return {"type_id": file_type, "expected_type_id": 7,
            "declared_record_count": declared_count,
            "preceding_u32_uninterpreted": preceding_u32,
            "candidate_bbox_int32": bbox_int32,
            "candidate_bbox_degrees": bbox,
            "candidate_bbox_order_and_range_valid": valid,
            "header_bytes_read": len(header), "source_size_bytes": before.st_size,
            "source_mtime_unchanged": stable,
            "spatial_header_matches_known_schema": file_type == 7 and declared_count > 0
                and valid and stable}


def analyze(sources: list[dict[str, Any]]) -> dict[str, Any]:
    by_region: dict[str, dict[str, dict[str, Any]]] = {}
    for row in sources:
        table = Path(str(row["relative_path"])).suffix.removeprefix(".").upper()
        if table not in {*TABLES, *MAP_HEADERS}:
            raise ValueError("unexpected geography portability source")
        region = str(row["region"])
        if table in by_region.setdefault(region, {}):
            raise ValueError(f"duplicate {region}/{table} input")
        path = Path(str(row["absolute_path"]))
        if (not path.is_file() or path.stat().st_size != int(row["size_bytes"])
                or sha256_file(path) != str(row["sha256"])):
            raise ValueError(f"{region}/{table}: source differs from inventory")
        by_region[region][table] = row
    if len(by_region) != 3 or any(set(rows) != {*TABLES, *MAP_HEADERS}
                                  for rows in by_region.values()):
        raise ValueError("geography portability requires CTY/CNY and MP0/MG1-3 for all three regions")

    results = []
    for region, rows in by_region.items():
        paths = {table: Path(str(row["absolute_path"])) for table, row in rows.items()}
        cny = _scan_table(paths["CNY"], expected_type=12, stride=174)
        cty = _scan_table(paths["CTY"], expected_type=3, stride=178,
                          region_count=int(cny["parsed_record_count"]))
        boxes = {map_name: _scan_map_header(paths[map_name]) for map_name in MAP_HEADERS}
        city = cty["city_extent_candidate_degrees"]
        mp0 = boxes["MP0"]["candidate_bbox_degrees"]
        mp0_encloses_city = (mp0[0] <= city[0] and mp0[1] <= city[1]
                             and mp0[2] >= city[2] and mp0[3] >= city[3])
        mg_overlaps_city = {}
        for name in MAP_HEADERS[1:]:
            box = boxes[name]["candidate_bbox_degrees"]
            mg_overlaps_city[name] = (box[0] <= city[2] and box[2] >= city[0]
                                      and box[1] <= city[3] and box[3] >= city[1])
        checks = {
            "cty_schema_matches_header": cty["fixed_table_matches_header"],
            "cny_schema_matches_header": cny["fixed_table_matches_header"],
            "cty_ids_region_links_reserved_fields_bounds_and_names_valid": (
                cty["bad_sequential_ids"] == 0 and cty["bad_region_references"] == 0
                and cty["bad_reserved_fields"] == 0 and cty["bad_geographic_bounds"] == 0
                and cty["empty_names"] == 0),
            "cny_ids_and_names_valid": (cny["bad_sequential_ids"] == 0
                                         and cny["empty_names"] == 0),
            "all_mp0_mg_headers_match_known_schema": all(
                box["spatial_header_matches_known_schema"] for box in boxes.values()),
            "mp0_candidate_bbox_encloses_all_cty_city_boxes": mp0_encloses_city,
            "mg_candidate_bboxes_overlap_cty_extent": all(mg_overlaps_city.values()),
        }
        results.append({"region": region, "cty": cty, "cny": cny, "map_headers": boxes,
                        "checks": checks, "mg_overlap_by_level": mg_overlaps_city,
                        "mp0_encloses_city_extent": mp0_encloses_city,
                        "sources": {table: {"relative_path": str(rows[table]["relative_path"]),
                            "sha256": str(rows[table]["sha256"]),
                            "size_bytes": int(rows[table]["size_bytes"])}
                            for table in sorted(rows)}})
    all_checks = all(all(region["checks"].values()) for region in results)
    return {"status": "PASS", "format_version": FORMAT_VERSION,
            "experiment": "ncdx_cty_cny_spatial_header_portability",
            "hypothesis": "The EUZ CTY/CNY structural schema and candidate map-header coordinate fields generalize to IZ and SCZ; MP0 candidate bounds enclose each region's city boxes and MG levels overlap them.",
            "hypothesis_result": "SUPPORTED" if all_checks else "FALSIFIED_OR_DIVERGENT",
            "regions": results, "original_media_write_count": 0,
            "claim_scope": "Cross-region structural schema and candidate bounding-box relationship only; map-record geometry, coverage completeness, topology, routing and physical media compatibility remain UNKNOWN.",
            "spatial_header_offset": 94, "coordinate_scale_candidate": 100000}


def verify_artifact(path: Path, expected_sources: list[dict[str, Any]],
                    expected_sha256: str) -> dict[str, Any]:
    if not path.is_file() or sha256_file(path) != expected_sha256:
        raise ValueError("geography portability artifact is missing or has changed")
    saved = json.loads(path.read_text(encoding="utf-8"))
    if (saved.get("status") != "PASS"
            or saved.get("experiment") != "ncdx_cty_cny_spatial_header_portability"
            or saved.get("format_version") != FORMAT_VERSION
            or saved.get("original_media_write_count") != 0
            or len(saved.get("regions", [])) != 3):
        raise ValueError("geography portability artifact schema is invalid")
    expected = {(str(row["region"]), Path(str(row["relative_path"])).suffix.upper()): row
                for row in expected_sources}
    seen: set[tuple[str, str]] = set()
    for region in saved["regions"]:
        checks = region.get("checks", {})
        if not checks or any(value is not True for value in checks.values()):
            raise ValueError(f"{region.get('region')}: one or more structural checks failed")
        for table, observed in region.get("sources", {}).items():
            key = (str(region.get("region")), "." + table)
            bound = expected.get(key)
            if bound is None or key in seen:
                raise ValueError("artifact contains missing, duplicate, or unallowlisted source")
            seen.add(key)
            source = Path(str(bound["absolute_path"]))
            stat = source.stat()
            if (stat.st_size != int(bound["size_bytes"])
                    or str(observed.get("sha256")) != str(bound["sha256"])
                    or sha256_file(source) != str(bound["sha256"])):
                raise ValueError(f"current source identity changed for {key}")
    if seen != set(expected) or len(seen) != 18:
        raise ValueError("artifact must bind exactly eighteen sources across three regions")
    return {"status": "PASS", "artifact_sha256": expected_sha256,
            "verified_source_count": len(seen),
            "hypothesis_result": saved.get("hypothesis_result"),
            "original_media_write_count": 0,
            "claim_scope": saved.get("claim_scope")}
