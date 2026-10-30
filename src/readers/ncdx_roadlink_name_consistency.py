"""Read-only cross-region test of RL aliases against IL linked names.

The report retains aggregate counts and hashes only. A name match is an
observed text/reference association; it does not prove road geometry or
routing semantics.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct
from typing import Any, Callable

from src.readers.ncdx_container import (
    MAX_FILE_BYTES, MAX_LOGICAL_BYTES, iter_decoded_blocks, read_index,
)


FORMAT_VERSION = 1
HEADER_BYTES = 94
RL_STRIDE = 61
IOF_STRIDE = 6
REGIONS = {"SW", "Italy", "Scandinavia"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _normalize_name(raw: bytes) -> str:
    text = raw.split(b"\0", 1)[0].decode("cp1252", errors="strict")
    return " ".join(text.replace(";", " ").replace(",", " ").replace("-", " ")
                       .upper().split())


def _scan_fixed(path: Path, *, stride: int, expected_type: int,
                visit: Callable[[int, bytes], None]) -> dict[str, Any]:
    before = path.stat()
    before_hash = sha256_file(path)
    digest = hashlib.sha256()
    carry = bytearray()
    record_index = 0
    logical_size = 0
    header: bytes | None = None
    with path.open("rb") as stream:
        index = read_index(stream, max_file_bytes=MAX_FILE_BYTES,
                           max_logical_bytes=MAX_LOGICAL_BYTES)
        for offset, block in iter_decoded_blocks(stream, index):
            digest.update(block)
            if offset == 0:
                if len(block) < HEADER_BYTES or block[:7] != b"SIEMENS":
                    raise ValueError(f"{path.name}: invalid decoded table header")
                header = block[:HEADER_BYTES]
                carry.extend(block[HEADER_BYTES:])
            else:
                carry.extend(block)
            complete = len(carry) - len(carry) % stride
            for pos in range(0, complete, stride):
                visit(record_index, bytes(carry[pos:pos + stride]))
                record_index += 1
            if complete:
                del carry[:complete]
            logical_size += len(block)
    if header is None:
        raise ValueError(f"{path.name}: empty decoded table")
    after = path.stat()
    after_hash = sha256_file(path)
    type_id = struct.unpack_from("<H", header, 84)[0]
    declared = struct.unpack_from("<I", header, 86)[0]
    unchanged = (before_hash == after_hash and before.st_size == after.st_size
                 and before.st_mtime_ns == after.st_mtime_ns)
    return {"source_sha256": before_hash, "source_unchanged": unchanged,
        "source_size_bytes": before.st_size, "logical_sha256": digest.hexdigest(),
        "logical_size_bytes": logical_size, "type_id": type_id,
        "expected_type_id": expected_type, "declared_record_count": declared,
        "parsed_record_count": record_index, "stride_bytes": stride,
        "trailing_bytes": len(carry),
        "fixed_table_valid": (unchanged and type_id == expected_type
            and declared == record_index and logical_size == HEADER_BYTES + declared * stride
            and not carry)}


def _scan_il(path: Path, *, expected_type: int,
             visit: Callable[[int, int, str], None]) -> dict[str, Any]:
    before = path.stat()
    before_hash = sha256_file(path)
    digest = hashlib.sha256()
    carry = bytearray()
    carry_offset = HEADER_BYTES
    logical_size = 0
    record_index = 0
    boundaries: list[int] = []
    header: bytes | None = None
    with path.open("rb") as stream:
        index = read_index(stream, max_file_bytes=MAX_FILE_BYTES,
                           max_logical_bytes=MAX_LOGICAL_BYTES)
        for offset, block in iter_decoded_blocks(stream, index):
            digest.update(block)
            if offset == 0:
                if len(block) < HEADER_BYTES or block[:7] != b"SIEMENS":
                    raise ValueError(f"{path.name}: invalid decoded IL header")
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
                row = bytes(carry[consumed:terminator + 1])
                link_id = struct.unpack_from("<I", row, 0)[0]
                boundaries.append(carry_offset + consumed)
                visit(record_index, link_id, _normalize_name(row[11:]))
                consumed = terminator + 1
                record_index += 1
            if consumed:
                del carry[:consumed]
                carry_offset += consumed
            logical_size += len(block)
    if header is None:
        raise ValueError(f"{path.name}: empty decoded IL table")
    after = path.stat()
    after_hash = sha256_file(path)
    type_id = struct.unpack_from("<H", header, 84)[0]
    declared = struct.unpack_from("<I", header, 86)[0]
    unchanged = (before_hash == after_hash and before.st_size == after.st_size
                 and before.st_mtime_ns == after.st_mtime_ns)
    return {"source_sha256": before_hash, "source_unchanged": unchanged,
        "source_size_bytes": before.st_size, "logical_sha256": digest.hexdigest(),
        "logical_size_bytes": logical_size, "type_id": type_id,
        "expected_type_id": expected_type, "declared_record_count": declared,
        "parsed_record_count": record_index, "record_prefix_bytes": 11,
        "unterminated_tail_bytes": len(carry), "boundaries": boundaries,
        "variable_table_valid": (unchanged and type_id == expected_type
            and declared == record_index and not carry and logical_size > HEADER_BYTES)}


def _analyze_region(region: str, paths: dict[str, Path], expected: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if region not in REGIONS or set(paths) != {"RL", "IOF", "IL"} or set(expected) != {"RL", "IOF", "IL"}:
        raise ValueError("roadlink name experiment requires exact RL/IOF/IL sources for a supported region")
    for table, path in paths.items():
        identity = expected[table]
        if (not path.is_file() or path.stat().st_size != int(identity["size_bytes"])
                or sha256_file(path) != str(identity["sha256"])):
            raise ValueError(f"{region}/{table}: source differs from the pinned evidence ledger")

    aliases: dict[int, set[str]] = {}
    bad_rl_prefix = 0
    def visit_rl(_index: int, row: bytes) -> None:
        nonlocal bad_rl_prefix
        link_id = struct.unpack_from("<I", row, 0)[0]
        if row[4:7] != b"\0\0\0":
            bad_rl_prefix += 1
        name = _normalize_name(row[7:])
        if name:
            aliases.setdefault(link_id, set()).add(name)
    rl = _scan_fixed(paths["RL"], stride=RL_STRIDE, expected_type=21, visit=visit_rl)

    groups: list[tuple[int, int, int]] = []
    bad_iof_flags = 0
    def visit_iof(index: int, row: bytes) -> None:
        nonlocal bad_iof_flags
        offset, packed_count = struct.unpack_from("<IH", row, 0)
        if offset:
            if packed_count & 0x8000:
                bad_iof_flags += 1
            groups.append((index, offset, packed_count & 0x7fff))
        elif not packed_count & 0x8000:
            bad_iof_flags += 1
    iof = _scan_fixed(paths["IOF"], stride=IOF_STRIDE, expected_type=21, visit=visit_iof)
    iof_count = int(iof["declared_record_count"])

    il_rows: list[tuple[int, str]] = []
    def visit_il(_index: int, link_id: int, name: str) -> None:
        il_rows.append((link_id, name))
    il = _scan_il(paths["IL"], expected_type=20, visit=visit_il)
    boundaries = il["boundaries"]
    boundary_index_by_offset = {offset: index for index, offset in enumerate(boundaries)}
    pointer_errors = 0
    previous_offset = -1
    for position, (group_id, offset, declared_count) in enumerate(groups):
        if offset <= previous_offset:
            pointer_errors += 1
        previous_offset = offset
        start = boundary_index_by_offset.get(offset)
        if start is None:
            pointer_errors += 1
            continue
        end = (boundary_index_by_offset[groups[position + 1][1]]
               if position + 1 < len(groups)
               and groups[position + 1][1] in boundary_index_by_offset else len(boundaries))
        if end - start != declared_count or group_id >= iof_count:
            pointer_errors += 1

    direct_matches = control_matches = target_aliases = 0
    names_seen = 0
    out_of_range_targets = 0
    displaced_prime = 137
    for link_id, name in il_rows:
        if link_id >= iof_count:
            out_of_range_targets += 1
            continue
        names_seen += 1
        target_names = aliases.get(link_id, set())
        if target_names:
            target_aliases += 1
        if name and name in target_names:
            direct_matches += 1
        if name and name in aliases.get((link_id + displaced_prime) % iof_count, set()):
            control_matches += 1

    source_rows = {"RL": rl, "IOF": iof, "IL": il}
    checks = {"all_sources_unchanged": all(row["source_unchanged"] for row in source_rows.values()),
        "all_source_hashes_match_inventory": all(source_rows[table]["source_sha256"] == expected[table]["sha256"] for table in source_rows),
        "rl_fixed_table_valid": rl["fixed_table_valid"] and bad_rl_prefix == 0,
        "iof_fixed_table_valid": iof["fixed_table_valid"] and bad_iof_flags == 0,
        "il_variable_table_valid": il["variable_table_valid"],
        "all_il_targets_in_iof_range": out_of_range_targets == 0,
        "iof_groups_match_il_boundaries_and_counts": pointer_errors == 0}
    return {"region": region,
        "sources": {table: {key: row[key] for key in ("relative_path", "sha256", "size_bytes")}
                    for table, row in expected.items()},
        "table_counts": {"rl_records": rl["parsed_record_count"],
            "rl_ids_with_text_alias": len(aliases), "iof_records": iof["parsed_record_count"],
            "iof_external_groups": len(groups), "il_records": il["parsed_record_count"]},
        "name_link_counts": {"il_names_with_target_alias": target_aliases,
            "il_names_compared": names_seen, "normalized_direct_matches": direct_matches,
            "normalized_displaced_control_matches": control_matches,
            "direct_match_fraction": round(direct_matches / names_seen, 6) if names_seen else None,
            "displaced_control_fraction": round(control_matches / names_seen, 6) if names_seen else None,
            "displaced_reference_delta": direct_matches - control_matches,
            "control_shift_iof_records": displaced_prime},
        "checks": checks, "pointer_error_count": pointer_errors,
        "bad_rl_prefix_count": bad_rl_prefix, "bad_iof_flag_count": bad_iof_flags,
        "out_of_range_il_target_count": out_of_range_targets,
        "semantic_claim": "normalized RL/IL text-reference association only; road geometry/topology/routing UNKNOWN"}


def analyze(sources: list[dict[str, Any]]) -> dict[str, Any]:
    if len(sources) != 9:
        raise ValueError("roadlink name portability requires nine manifest-pinned regional sources")
    grouped: dict[str, dict[str, dict[str, Any]]] = {}
    for row in sources:
        region = str(row["region"])
        table = Path(str(row["relative_path"])).suffix.upper().lstrip(".")
        if region not in REGIONS or table not in {"RL", "IOF", "IL"}:
            raise ValueError("roadlink name manifest has an unsupported region or table")
        bucket = grouped.setdefault(region, {})
        if table in bucket:
            raise ValueError(f"duplicate {region}/{table} manifest input")
        bucket[table] = row
    if set(grouped) != REGIONS or any(set(rows) != {"RL", "IOF", "IL"} for rows in grouped.values()):
        raise ValueError("roadlink name portability requires RL/IOF/IL for all three installed regions")
    region_rows = []
    for region in ("SW", "Italy", "Scandinavia"):
        rows = grouped[region]
        result = _analyze_region(region,
            {table: Path(str(row["absolute_path"])) for table, row in rows.items()}, rows)
        region_rows.append(result)
    valid = all(all(row["checks"].values()) for row in region_rows)
    association_supported = sum(
        row["name_link_counts"]["displaced_reference_delta"] > 0 for row in region_rows) >= 2
    return {"status": "PASS" if valid else "FAIL", "format_version": FORMAT_VERSION,
        "experiment": "ncdx_rl_il_normalized_name_link_portability",
        "hypothesis_result": "SUPPORTED" if valid and association_supported else "FALSIFIED_OR_DIVERGENT",
        "regions": region_rows, "original_media_write_count": 0,
        "claim_scope": "Cross-region normalized RL alias to IL linked-name comparison against a displaced IOF reference control; no geometry, topology, route, or physical disc claim."}


def _independent_parse_table(path: Path, table: str) -> dict[str, Any]:
    """Independently parse one bounded table without buffering the full decode."""
    expected_type = {"RL": 21, "IOF": 21, "IL": 20}[table]
    before = path.stat()
    source_hash = sha256_file(path)
    header_prefix = bytearray()
    header: bytes | None = None
    carry = bytearray()
    carry_offset = HEADER_BYTES
    logical_size = 0
    logical_digest = hashlib.sha256()
    record_count = 0
    aliases: dict[int, set[str]] = {}
    groups: list[tuple[int, int, int]] = []
    il_rows: list[tuple[int, str]] = []
    boundaries: list[int] = []
    bad_prefix = 0
    bad_flags = 0

    with path.open("rb") as stream:
        index = read_index(stream, max_file_bytes=MAX_FILE_BYTES,
                           max_logical_bytes=MAX_LOGICAL_BYTES)
        for offset, block in iter_decoded_blocks(stream, index):
            if offset != logical_size:
                raise ValueError(f"independent verifier found a {table} logical gap")
            logical_digest.update(block)
            payload = block
            if header is None:
                needed = HEADER_BYTES - len(header_prefix)
                header_prefix.extend(block[:needed])
                payload = block[needed:]
                if len(header_prefix) == HEADER_BYTES:
                    header = bytes(header_prefix)
                    if header[:7] != b"SIEMENS":
                        raise ValueError(f"independent verifier rejected {table} header")
            if header is not None and payload:
                carry.extend(payload)
                if table in {"RL", "IOF"}:
                    stride = RL_STRIDE if table == "RL" else IOF_STRIDE
                    complete = len(carry) - len(carry) % stride
                    for start in range(0, complete, stride):
                        row = bytes(carry[start:start + stride])
                        if table == "RL":
                            target = int.from_bytes(row[0:4], "little")
                            if row[4:7] != b"\0\0\0":
                                bad_prefix += 1
                            name = _normalize_name(row[7:])
                            if name:
                                aliases.setdefault(target, set()).add(name)
                        else:
                            pointer, packed = struct.unpack_from("<IH", row, 0)
                            if pointer:
                                bad_flags += bool(packed & 0x8000)
                                groups.append((record_count, pointer, packed & 0x7fff))
                            else:
                                bad_flags += not bool(packed & 0x8000)
                        record_count += 1
                    if complete:
                        del carry[:complete]
                else:
                    consumed = 0
                    while len(carry) - consumed >= 12:
                        terminator = carry.find(b"\0", consumed + 11)
                        if terminator < 0:
                            break
                        row = carry[consumed:terminator + 1]
                        target = int.from_bytes(row[0:4], "little")
                        boundaries.append(carry_offset + consumed)
                        il_rows.append((target, _normalize_name(bytes(row[11:-1]))))
                        consumed = terminator + 1
                        record_count += 1
                    if consumed:
                        del carry[:consumed]
                        carry_offset += consumed
            logical_size += len(block)

    if header is None:
        raise ValueError(f"independent verifier found an incomplete {table} header")
    type_id = struct.unpack_from("<H", header, 84)[0]
    declared_count = struct.unpack_from("<I", header, 86)[0]
    if type_id != expected_type or declared_count != record_count or carry:
        raise ValueError(f"independent verifier rejected {table} type, count, or trailing bytes")
    if table in {"RL", "IOF"}:
        stride = RL_STRIDE if table == "RL" else IOF_STRIDE
        if logical_size != HEADER_BYTES + declared_count * stride:
            raise ValueError(f"independent verifier rejected {table} fixed record length")
    after = path.stat()
    source_hash_after = sha256_file(path)
    unchanged = (before.st_size == after.st_size and before.st_mtime_ns == after.st_mtime_ns
                 and source_hash == source_hash_after)
    return {"source_sha256": source_hash, "source_size_bytes": before.st_size,
        "source_unchanged": unchanged, "logical_sha256": logical_digest.hexdigest(),
        "logical_size_bytes": logical_size, "type_id": type_id,
        "declared_record_count": declared_count, "parsed_record_count": record_count,
        "aliases": aliases, "groups": groups, "il_rows": il_rows,
        "boundaries": boundaries, "bad_prefix_count": bad_prefix,
        "bad_flag_count": bad_flags}


def _independent_region_verify(region: str, rows: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Reparse source tables with independent bounded streaming record parsers."""
    identities: dict[str, dict[str, Any]] = {}
    parsed: dict[str, dict[str, Any]] = {}
    for table in ("RL", "IOF", "IL"):
        row = rows[table]
        path = Path(str(row["absolute_path"]))
        if path.stat().st_size != int(row["size_bytes"]) or sha256_file(path) != str(row["sha256"]):
            raise ValueError(f"independent verifier found a changed {region}/{table} source")
        identity = _independent_parse_table(path, table)
        if not identity["source_unchanged"] or identity["source_sha256"] != row["sha256"]:
            raise ValueError(f"independent verifier detected a source change in {region}/{table}")
        parsed[table] = identity
        # Keep the saved source identity schema aligned with the worker artifact.
        # The independent logical digest is checked below through the replayed
        # counts and record structure, but it is not an input inventory field.
        identities[table] = {"relative_path": row["relative_path"], "sha256": identity["source_sha256"],
            "size_bytes": identity["source_size_bytes"]}

    aliases = parsed["RL"]["aliases"]
    groups = parsed["IOF"]["groups"]
    il_rows = parsed["IL"]["il_rows"]
    boundaries = parsed["IL"]["boundaries"]
    counts = {table: parsed[table]["parsed_record_count"] for table in ("RL", "IOF", "IL")}
    bad_rl_prefix = parsed["RL"]["bad_prefix_count"]
    bad_iof_flags = parsed["IOF"]["bad_flag_count"]

    boundary_map = {offset: index for index, offset in enumerate(boundaries)}
    pointer_errors = 0
    prior_offset = -1
    for index, (group_id, offset, declared) in enumerate(groups):
        start = boundary_map.get(offset)
        if start is None or offset <= prior_offset or group_id >= counts["IOF"]:
            pointer_errors += 1
            prior_offset = offset
            continue
        prior_offset = offset
        next_group = groups[index + 1][1] if index + 1 < len(groups) else None
        end = boundary_map.get(next_group, len(boundaries)) if next_group is not None else len(boundaries)
        if end - start != declared:
            pointer_errors += 1

    direct = control = aliases_found = out_of_range = 0
    for link_id, name in il_rows:
        if link_id >= counts["IOF"]:
            out_of_range += 1
            continue
        target_aliases = aliases.get(link_id, set())
        aliases_found += bool(target_aliases)
        direct += bool(name and name in target_aliases)
        control += bool(name and name in aliases.get((link_id + 137) % counts["IOF"], set()))
    checks = {"all_sources_unchanged": True,
        "all_source_hashes_match_inventory": all(identities[t]["sha256"] == rows[t]["sha256"] for t in rows),
        "rl_fixed_table_valid": not bad_rl_prefix,
        "iof_fixed_table_valid": not bad_iof_flags,
        "il_variable_table_valid": True,
        "all_il_targets_in_iof_range": not out_of_range,
        "iof_groups_match_il_boundaries_and_counts": not pointer_errors}
    link_counts = {"il_names_with_target_alias": aliases_found, "il_names_compared": len(il_rows),
        "normalized_direct_matches": direct, "normalized_displaced_control_matches": control,
        "direct_match_fraction": round(direct / len(il_rows), 6) if il_rows else None,
        "displaced_control_fraction": round(control / len(il_rows), 6) if il_rows else None,
        "displaced_reference_delta": direct - control, "control_shift_iof_records": 137}
    return {"region": region, "sources": identities,
        "table_counts": {"rl_records": counts["RL"], "rl_ids_with_text_alias": len(aliases),
            "iof_records": counts["IOF"], "iof_external_groups": len(groups), "il_records": len(il_rows)},
        "name_link_counts": link_counts, "checks": checks,
        "pointer_error_count": pointer_errors, "bad_rl_prefix_count": bad_rl_prefix,
        "bad_iof_flag_count": bad_iof_flags, "out_of_range_il_target_count": out_of_range}


def verify_artifact(path: Path, sources: list[dict[str, Any]], expected_sha256: str) -> dict[str, Any]:
    if not path.is_file() or sha256_file(path) != expected_sha256:
        raise ValueError("roadlink name artifact hash changed")
    saved = json.loads(path.read_text(encoding="utf-8"))
    if (saved.get("status") != "PASS" or saved.get("format_version") != FORMAT_VERSION
            or saved.get("experiment") != "ncdx_rl_il_normalized_name_link_portability"
            or saved.get("original_media_write_count") != 0):
        raise ValueError("roadlink name artifact schema is invalid")
    replay_rows: dict[str, dict[str, dict[str, Any]]] = {}
    for source in sources:
        region = str(source["region"])
        table = Path(str(source["relative_path"])).suffix.upper().lstrip(".")
        replay_rows.setdefault(region, {})[table] = source
    if set(replay_rows) != REGIONS or any(set(tables) != {"RL", "IOF", "IL"}
                                          for tables in replay_rows.values()):
        raise ValueError("independent verifier requires the exact three-region source set")
    independent = [_independent_region_verify(region, replay_rows[region])
                   for region in ("SW", "Italy", "Scandinavia")]
    saved_by_region = {str(row.get("region")): row for row in saved.get("regions", [])}
    for proof in independent:
        saved_region = saved_by_region.get(proof["region"])
        if not saved_region:
            raise ValueError("independent verifier could not bind a saved regional result")
        for key in ("sources", "table_counts", "name_link_counts", "checks", "pointer_error_count",
                    "bad_rl_prefix_count", "bad_iof_flag_count", "out_of_range_il_target_count"):
            if saved_region.get(key) != proof.get(key):
                raise ValueError(f"independent name verifier disagreed on {key}")
    hypothesis = ("SUPPORTED" if all(all(row["checks"].values()) for row in independent)
        and sum(row["name_link_counts"]["displaced_reference_delta"] > 0 for row in independent) >= 2
        else "FALSIFIED_OR_DIVERGENT")
    if (saved.get("hypothesis_result") != hypothesis
            or saved.get("claim_scope") != "Cross-region normalized RL alias to IL linked-name comparison against a displaced IOF reference control; no geometry, topology, route, or physical disc claim."):
        raise ValueError("independent roadlink name interpretation differs from saved evidence")
    return {"status": "PASS", "artifact_sha256": expected_sha256,
        "verified_source_count": len(sources),
        "region_checks": {region: proof["checks"] for region, proof in zip(
            ("SW", "Italy", "Scandinavia"), independent)},
        "hypothesis_result": hypothesis, "original_media_write_count": 0,
        "claim_scope": saved["claim_scope"]}
