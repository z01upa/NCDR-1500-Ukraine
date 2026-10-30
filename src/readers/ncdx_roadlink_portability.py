"""Read-only portability experiment for the NCDx RL -> IOF -> IL index.

The experiment tests a previously EUZ-only structural reader against the three
installed regional source sets.  It does not assign navigation semantics to IL
groups or modify source media.
"""

from __future__ import annotations

from bisect import bisect_left
import hashlib
import json
from pathlib import Path
import struct
from typing import Any, Callable

from src.readers.ncdx_container import (
    MAX_FILE_BYTES, MAX_LOGICAL_BYTES, iter_decoded_blocks, read_index,
)


HEADER_BYTES = 94
FORMAT_VERSION = 1
TABLES = {"RL": (21, 61), "IOF": (21, 6), "IL": (20, None)}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _scan_fixed(path: Path, *, stride: int, expected_type: int,
                visit: Callable[[int, int, bytes], None] | None = None) -> dict[str, Any]:
    before_stat = path.stat()
    source_before = sha256_file(path)
    digest = hashlib.sha256()
    carry = bytearray()
    carry_offset = HEADER_BYTES
    logical_bytes = 0
    record_index = 0
    header: bytes | None = None
    with path.open("rb") as stream:
        index = read_index(stream, max_file_bytes=MAX_FILE_BYTES,
                           max_logical_bytes=MAX_LOGICAL_BYTES)
        for logical_offset, block in iter_decoded_blocks(stream, index):
            digest.update(block)
            if logical_offset == 0:
                if len(block) < HEADER_BYTES or block[:7] != b"SIEMENS":
                    raise ValueError(f"{path.name}: invalid decoded Siemens header")
                header = block[:HEADER_BYTES]
                payload = block[HEADER_BYTES:]
                carry_offset = HEADER_BYTES
            else:
                payload = block
            carry.extend(payload)
            complete = len(carry) - (len(carry) % stride)
            for position in range(0, complete, stride):
                if visit is not None:
                    visit(record_index, carry_offset + position,
                          bytes(carry[position:position + stride]))
                record_index += 1
            if complete:
                del carry[:complete]
                carry_offset += complete
            logical_bytes += len(block)
    if header is None:
        raise ValueError(f"{path.name}: empty decoded container")
    type_id = struct.unpack_from("<H", header, 84)[0]
    declared_count = struct.unpack_from("<I", header, 86)[0]
    source_after = sha256_file(path)
    after_stat = path.stat()
    stable = (source_before == source_after and before_stat.st_size == after_stat.st_size
              and before_stat.st_mtime_ns == after_stat.st_mtime_ns)
    return {
        "source_sha256_before": source_before,
        "source_sha256_after": source_after,
        "source_size_bytes": before_stat.st_size,
        "source_mtime_unchanged": before_stat.st_mtime_ns == after_stat.st_mtime_ns,
        "source_unchanged": stable,
        "logical_sha256": digest.hexdigest(),
        "logical_size_bytes": logical_bytes,
        "container_block_count": index.block_count,
        "container_block_size_bytes": index.block_size_bytes,
        "type_id": type_id,
        "expected_type_id": expected_type,
        "declared_record_count": declared_count,
        "parsed_record_count": record_index,
        "stride_bytes": stride,
        "trailing_bytes": len(carry),
        "fixed_table_matches_header": (type_id == expected_type
            and record_index == declared_count
            and logical_bytes == HEADER_BYTES + declared_count * stride
            and not carry),
    }


def _scan_il(path: Path, *, expected_type: int, iof_count: int,
             rl_references: set[int]) -> tuple[dict[str, Any], list[int]]:
    before_stat = path.stat()
    source_before = sha256_file(path)
    digest = hashlib.sha256()
    carry = bytearray()
    carry_offset = HEADER_BYTES
    logical_bytes = 0
    record_index = 0
    boundaries: list[int] = []
    out_of_range = 0
    no_rl_alias = 0
    header: bytes | None = None
    with path.open("rb") as stream:
        index = read_index(stream, max_file_bytes=MAX_FILE_BYTES,
                           max_logical_bytes=MAX_LOGICAL_BYTES)
        for logical_offset, block in iter_decoded_blocks(stream, index):
            digest.update(block)
            if logical_offset == 0:
                if len(block) < HEADER_BYTES or block[:7] != b"SIEMENS":
                    raise ValueError(f"{path.name}: invalid decoded Siemens header")
                header = block[:HEADER_BYTES]
                payload = block[HEADER_BYTES:]
                carry_offset = HEADER_BYTES
            else:
                payload = block
            carry.extend(payload)
            consumed = 0
            while len(carry) >= 12:
                terminator = carry.find(b"\0", consumed + 11)
                if terminator < 0:
                    break
                boundaries.append(carry_offset + consumed)
                link_id = struct.unpack_from("<I", carry, consumed)[0]
                if link_id >= iof_count:
                    out_of_range += 1
                if link_id not in rl_references:
                    no_rl_alias += 1
                # Names are read to prove a terminator exists, but their text is
                # deliberately not promoted to a road-semantic claim here.
                carry[consumed + 11:terminator].decode("cp1252", errors="replace")
                consumed = terminator + 1
                record_index += 1
            if consumed:
                del carry[:consumed]
                carry_offset += consumed
            logical_bytes += len(block)
    if header is None:
        raise ValueError(f"{path.name}: empty decoded container")
    type_id = struct.unpack_from("<H", header, 84)[0]
    declared_count = struct.unpack_from("<I", header, 86)[0]
    source_after = sha256_file(path)
    after_stat = path.stat()
    stable = (source_before == source_after and before_stat.st_size == after_stat.st_size
              and before_stat.st_mtime_ns == after_stat.st_mtime_ns)
    result = {
        "source_sha256_before": source_before,
        "source_sha256_after": source_after,
        "source_size_bytes": before_stat.st_size,
        "source_mtime_unchanged": before_stat.st_mtime_ns == after_stat.st_mtime_ns,
        "source_unchanged": stable,
        "logical_sha256": digest.hexdigest(),
        "logical_size_bytes": logical_bytes,
        "container_block_count": index.block_count,
        "container_block_size_bytes": index.block_size_bytes,
        "type_id": type_id,
        "expected_type_id": expected_type,
        "declared_record_count": declared_count,
        "parsed_record_count": record_index,
        "record_prefix_bytes": 11,
        "unterminated_tail_bytes": len(carry),
        "out_of_range_iof_ids": out_of_range,
        "il_ids_without_rl_alias": no_rl_alias,
        "variable_table_matches_header": (type_id == expected_type
            and record_index == declared_count and not carry
            and logical_bytes > HEADER_BYTES),
    }
    return result, boundaries


def analyze_region(region: str, paths: dict[str, Path], expected: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if set(paths) != set(TABLES) or set(expected) != set(TABLES):
        raise ValueError("roadlink portability analysis requires exactly RL, IOF and IL")
    for table, path in paths.items():
        bound = expected[table]
        if not path.is_file() or path.stat().st_size != int(bound["size_bytes"]):
            raise ValueError(f"{region}/{table}: source is missing or differs from its inventory size")
        if sha256_file(path) != str(bound["sha256"]):
            raise ValueError(f"{region}/{table}: source differs from the existing SHA-256 inventory")

    rl_refs: set[int] = set()
    rl = _scan_fixed(paths["RL"], stride=TABLES["RL"][1], expected_type=TABLES["RL"][0],
        visit=lambda _idx, _off, record: rl_refs.add(struct.unpack_from("<I", record, 0)[0]))
    iof_groups: list[tuple[int, int, int]] = []
    flags = {"inline_records": 0, "invalid_flags": 0}
    iof = _scan_fixed(paths["IOF"], stride=TABLES["IOF"][1], expected_type=TABLES["IOF"][0],
        visit=lambda idx, _off, record: _collect_iof_group(record, idx, iof_groups, flags))
    iof_count = int(iof["declared_record_count"])
    il, il_boundaries = _scan_il(paths["IL"], expected_type=TABLES["IL"][0],
                                 iof_count=iof_count, rl_references=rl_refs)
    pointer_errors: list[str] = []
    previous_offset = -1
    for position, (iof_id, il_offset, declared) in enumerate(iof_groups):
        if il_offset <= previous_offset:
            pointer_errors.append(f"IOF {iof_id}: pointer is not strictly increasing")
        previous_offset = il_offset
        boundary_index = bisect_left(il_boundaries, il_offset)
        if boundary_index >= len(il_boundaries) or il_boundaries[boundary_index] != il_offset:
            pointer_errors.append(f"IOF {iof_id}: pointer is not an IL record boundary")
            continue
        next_index = (bisect_left(il_boundaries, iof_groups[position + 1][1])
                      if position + 1 < len(iof_groups) else len(il_boundaries))
        if next_index - boundary_index != declared:
            pointer_errors.append(f"IOF {iof_id}: declared count differs from IL span")
    references_in_range = all(value < iof_count for value in rl_refs)
    all_stats = {"RL": rl, "IOF": iof, "IL": il}
    checks = {
        "all_source_hashes_match_inventory": all(
            all_stats[table]["source_sha256_before"] == str(expected[table]["sha256"])
            for table in TABLES),
        "all_original_sources_unchanged": all(row["source_unchanged"]
            for row in (rl, iof, il)),
        "rl_fixed_table_matches_header": rl["fixed_table_matches_header"],
        "iof_fixed_table_matches_header": iof["fixed_table_matches_header"],
        "il_variable_table_matches_header": il["variable_table_matches_header"],
        "all_rl_reference_candidates_in_iof_range": references_in_range,
        "all_il_ids_in_iof_range": il["out_of_range_iof_ids"] == 0,
        "all_il_ids_have_rl_alias": il["il_ids_without_rl_alias"] == 0,
        "iof_pointer_groups_match_il_boundaries_and_counts": not pointer_errors,
        "iof_inline_records_have_high_bit_flag": flags["invalid_flags"] == 0,
    }
    return {
        "region": region,
        "sources": {table: {"relative_path": str(expected[table]["relative_path"]),
                            **stats} for table, stats in
                    (("RL", rl), ("IOF", iof), ("IL", il))},
        "counts": {"rl_unique_reference_ids": len(rl_refs),
                   "iof_pointer_groups": len(iof_groups),
                   "iof_inline_records": flags["inline_records"],
                   "il_record_boundaries": len(il_boundaries)},
        "checks": checks,
        "pointer_error_count": len(pointer_errors),
        "pointer_error_examples": pointer_errors[:8],
        "rl_reference_ids_out_of_range": not references_in_range,
        "interpretation": "SUPPORTED" if all(checks.values()) else "DIVERGENCE_RECORDED",
    }


def _collect_iof_group(record: bytes, index: int, groups: list[tuple[int, int, int]],
                       _increment_counter: dict[str, int] | None) -> None:
    offset, count = struct.unpack_from("<IH", record, 0)
    if offset:
        if count & 0x8000:
            if _increment_counter is not None:
                _increment_counter["invalid_flags"] += 1
        groups.append((index, offset, count & 0x7fff))
    elif count & 0x8000:
        if _increment_counter is not None:
            _increment_counter["inline_records"] += 1
    elif _increment_counter is not None:
        _increment_counter["invalid_flags"] += 1


def analyze(sources: list[dict[str, Any]]) -> dict[str, Any]:
    """Run one deduplicated, read-only test across all inventoried regions."""
    by_region: dict[str, dict[str, dict[str, Any]]] = {}
    for source in sources:
        table = Path(str(source["relative_path"])).suffix.removeprefix(".").upper()
        region = str(source["region"])
        if table not in TABLES or region in by_region and table in by_region[region]:
            raise ValueError("invalid or duplicate roadlink portability input")
        by_region.setdefault(region, {})[table] = source
    regions = []
    for region, table_rows in by_region.items():
        if set(table_rows) != set(TABLES):
            raise ValueError(f"{region}: incomplete RL/IOF/IL source set")
        paths = {table: Path(str(row["absolute_path"])) for table, row in table_rows.items()}
        expected = {table: row for table, row in table_rows.items()}
        regions.append(analyze_region(region, paths, expected))
    if len(regions) != 3:
        raise ValueError("the portability experiment requires all three inventoried regions")
    hypothesis_result = ("SUPPORTED" if all(row["interpretation"] == "SUPPORTED" for row in regions)
                         else "FALSIFIED_OR_DIVERGENT")
    return {
        "status": "PASS",
        "format_version": FORMAT_VERSION,
        "experiment": "ncdx_roadlink_index_portability",
        "hypothesis": "The verified EUZ RL -> IOF -> IL structural relationships also hold for the installed IZ and SCZ datasets.",
        "hypothesis_result": hypothesis_result,
        "regions": regions,
        "original_media_write_count": 0,
        "claim_scope": "Structural cross-reference portability only; IL semantics, road geometry, topology, routing and physical disc compatibility remain UNKNOWN.",
    }


def verify_artifact(path: Path, expected_sources: list[dict[str, Any]],
                    expected_sha256: str) -> dict[str, Any]:
    """Independent Supervisor check of artifact integrity and source identity."""
    if not path.is_file() or sha256_file(path) != expected_sha256:
        raise ValueError("roadlink portability artifact is missing or has a changed hash")
    saved = json.loads(path.read_text(encoding="utf-8"))
    if (saved.get("status") != "PASS" or saved.get("experiment") != "ncdx_roadlink_index_portability"
            or saved.get("format_version") != FORMAT_VERSION or saved.get("original_media_write_count") != 0
            or len(saved.get("regions", [])) != 3):
        raise ValueError("roadlink portability artifact schema or claim boundary is invalid")
    expected = {(str(row["region"]), Path(str(row["relative_path"])).suffix.upper()): row
                for row in expected_sources}
    seen: set[tuple[str, str]] = set()
    verified_sources = 0
    for region in saved["regions"]:
        for table, observed in region.get("sources", {}).items():
            source_key = (str(region.get("region")), "." + table)
            bound = expected.get(source_key)
            if not bound:
                raise ValueError("artifact contains an unallowlisted roadlink source")
            if source_key in seen:
                raise ValueError("artifact repeats a regional roadlink source")
            seen.add(source_key)
            source = Path(str(bound["absolute_path"]))
            if (not source.is_file() or source.stat().st_size != int(bound["size_bytes"])
                    or sha256_file(source) != str(bound["sha256"])
                    or observed.get("source_sha256_before") != str(bound["sha256"])
                    or observed.get("source_sha256_after") != str(bound["sha256"])
                    or observed.get("source_size_bytes") != int(bound["size_bytes"])
                    or observed.get("source_unchanged") is not True):
                raise ValueError(f"source identity or read-only proof failed for {region.get('region')}/{table}")
            verified_sources += 1
    if verified_sources != len(expected_sources) or verified_sources != 9 or seen != set(expected):
        raise ValueError("artifact does not prove all nine inventoried RL/IOF/IL source files")
    return {"status": "PASS", "artifact_sha256": expected_sha256,
            "verified_source_count": verified_sources,
            "hypothesis_result": saved.get("hypothesis_result"),
            "original_media_write_count": 0,
            "claim_scope": saved["claim_scope"]}
