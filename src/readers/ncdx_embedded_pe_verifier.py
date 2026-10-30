"""Independent manifest-bound readback for the embedded PE header census."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import struct
from typing import Any


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _header_at(data: bytes, base: int) -> dict[str, Any]:
    available = len(data) - base
    if available < 64 or data[base:base + 2] != b"MZ":
        raise ValueError("not a complete MZ header")
    pe_relative = struct.unpack_from("<I", data, base + 60)[0]
    pe = base + pe_relative
    if pe_relative < 64 or pe + 24 > len(data) or data[pe:pe + 4] != b"PE\0\0":
        raise ValueError("invalid embedded PE signature")
    machine, section_count, _timestamp, _symbols, _symbol_count, optional_size, _characteristics = \
        struct.unpack_from("<HHIIIHH", data, pe + 4)
    optional = pe + 24
    optional_end = optional + optional_size
    if not 1 <= section_count <= 96 or optional_end > len(data) or optional_size < 70:
        raise ValueError("invalid embedded PE counts or optional header")
    magic = struct.unpack_from("<H", data, optional)[0]
    if magic not in (0x10B, 0x20B):
        raise ValueError("unsupported embedded PE optional header")
    image_offset, image_width = optional + (28 if magic == 0x10B else 24), (4 if magic == 0x10B else 8)
    image_base = int.from_bytes(data[image_offset:image_offset + image_width], "little")
    size_of_image = struct.unpack_from("<I", data, optional + 56)[0]
    section_table = optional_end
    if section_table + section_count * 40 > len(data):
        raise ValueError("embedded PE section table is outside the source")
    raw_ranges = []
    raw_end = 0
    for index in range(section_count):
        row = section_table + index * 40
        raw_size, raw_pointer = struct.unpack_from("<II", data, row + 16)
        if raw_pointer > available or raw_size > available - raw_pointer:
            raise ValueError("embedded PE section raw range escapes its image tail")
        if raw_size:
            raw_ranges.append([base + raw_pointer, base + raw_pointer + raw_size])
            raw_end = max(raw_end, raw_pointer + raw_size)
    architecture = {0x014C: "x86", 0x01A6: "SH4", 0x01C0: "ARM",
        0x01C2: "ARM or Thumb", 0x01C4: "ARMNT", 0x8664: "x86-64",
        0xAA64: "ARM64"}.get(machine, "UNKNOWN_MACHINE")
    image_end = base + raw_end
    return {"base_offset": base, "pe_header_offset": pe, "machine_code": machine,
        "architecture": architecture, "optional_header_kind": "PE32" if magic == 0x10B else "PE32+",
        "section_count": section_count, "image_base": image_base, "size_of_image": size_of_image,
        "section_table_offset": section_table, "raw_section_ranges": raw_ranges,
        "raw_image_end_offset": image_end,
        "embedded_raw_bytes_sha256": hashlib.sha256(data[base:image_end]).hexdigest()}


def _independent_scan(data: bytes) -> dict[str, Any]:
    if len(data) > 32 * 1024 * 1024:
        raise ValueError("independent embedded scan exceeds 32 MiB")
    offsets = []
    cursor = 0
    while len(offsets) < 8192:
        offset = data.find(b"MZ", cursor)
        if offset < 0:
            break
        offsets.append(offset)
        cursor = offset + 2
    truncated = data.find(b"MZ", cursor) >= 0
    candidates = 0
    rejected = 0
    valid = []
    for base in offsets:
        if base + 64 > len(data):
            rejected += 1
            continue
        relative = int.from_bytes(data[base + 60:base + 64], "little")
        pe = base + relative
        if relative < 64 or pe + 24 > len(data) or data[pe:pe + 4] != b"PE\0\0":
            continue
        candidates += 1
        try:
            valid.append(_header_at(data, base))
        except (ValueError, struct.error):
            rejected += 1
    valid.sort(key=lambda item: (item["base_offset"], item["machine_code"]))
    return {"status": "PASS", "source_size_bytes": len(data),
        "mz_marker_count_scanned": len(offsets), "mz_marker_scan_truncated": truncated,
        "pe_signature_candidate_count": candidates,
        "rejected_structural_header_count": rejected,
        "valid_pe_image_count": len(valid), "valid_images": valid,
        "claim_scope": "embedded MZ/PE structural headers and raw section bounds only; module role, executable behavior, exports, map semantics, and device compatibility remain UNKNOWN"}


def verify_artifact(artifact_path: Path, *, source_root: Path, project_root: Path,
                    relative_path: str, expected_sha256: str, expected_size: int,
                    artifact_sha256: str) -> dict[str, Any]:
    artifact = Path(artifact_path).resolve(strict=True)
    project = Path(project_root).resolve(strict=True)
    if not artifact.is_relative_to(project) or _digest(artifact) != artifact_sha256:
        raise ValueError("embedded PE evidence artifact escaped the project or changed")
    relative = PurePosixPath(relative_path)
    root = Path(source_root).resolve(strict=True)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("unsafe embedded PE source path")
    source = (root / Path(*relative.parts)).resolve(strict=True)
    if not source.is_relative_to(root):
        raise ValueError("embedded PE source escaped its fixed source root")
    before = source.stat()
    if before.st_size != expected_size:
        raise ValueError("embedded PE source size differs from the accepted manifest")
    source_hash = _digest(source)
    if source_hash != expected_sha256:
        raise ValueError("embedded PE source hash differs from the accepted manifest")
    fresh = _independent_scan(source.read_bytes())
    saved = json.loads(artifact.read_text(encoding="utf-8"))
    after_hash = _digest(source)
    after = source.stat()
    if (after_hash != source_hash or before.st_size != after.st_size
            or before.st_mtime_ns != after.st_mtime_ns):
        raise ValueError("embedded PE source changed during independent replay")
    saved_scan = {key: saved.get(key) for key in fresh}
    if (saved.get("source_path") != relative.as_posix()
            or saved.get("source_sha256") != source_hash
            or saved.get("source_size_bytes") != expected_size
            or saved_scan != fresh
            or saved.get("original_media_write_count") != 0):
        raise ValueError("embedded PE report differs from the independent source replay")
    return {"status": "PASS", "independent_source_readback": "PASS",
        "source_path": relative.as_posix(), "source_size_bytes": expected_size,
        "source_sha256": source_hash, "marker_count": fresh["mz_marker_count_scanned"],
        "signature_candidate_count": fresh["pe_signature_candidate_count"],
        "valid_pe_image_count": fresh["valid_pe_image_count"],
        "source_write_count": 0, "original_media_write_count": 0,
        "claim_scope": fresh["claim_scope"]}
