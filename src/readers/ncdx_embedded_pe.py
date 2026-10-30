"""Bounded search for structurally valid PE images embedded in opaque firmware."""

from __future__ import annotations

import hashlib
import struct
from typing import Any

from src.readers.ncdx_binary_headers import inspect_pe_headers


MAX_SOURCE_BYTES = 32 * 1024 * 1024
MAX_MZ_CANDIDATES = 8192


def scan_embedded_pe(data: bytes) -> dict[str, Any]:
    if len(data) > MAX_SOURCE_BYTES:
        raise ValueError("embedded PE scan exceeds the fixed 32 MiB source bound")
    offsets: list[int] = []
    cursor = 0
    while len(offsets) < MAX_MZ_CANDIDATES:
        found = data.find(b"MZ", cursor)
        if found < 0:
            break
        offsets.append(found)
        cursor = found + 2
    markers_truncated = data.find(b"MZ", cursor) >= 0
    valid: list[dict[str, Any]] = []
    signature_candidates = 0
    rejected_headers = 0
    for base in offsets:
        if base + 64 > len(data):
            rejected_headers += 1
            continue
        pe_relative = int.from_bytes(data[base + 60:base + 64], "little")
        pe_absolute = base + pe_relative
        if (pe_relative < 64 or pe_absolute + 24 > len(data)
                or data[pe_absolute:pe_absolute + 4] != b"PE\x00\x00"):
            continue
        signature_candidates += 1
        try:
            headers = inspect_pe_headers(data[base:])
        except (ValueError, struct.error):
            rejected_headers += 1
            continue
        raw_end = max((int(row["raw_pointer"]) + int(row["raw_size"])
                       for row in headers["sections"]), default=0)
        image_end = base + raw_end
        if image_end > len(data):
            rejected_headers += 1
            continue
        header_end = int(headers["section_table_offset"]) + 40 * int(headers["section_count"])
        if header_end > len(data) - base:
            rejected_headers += 1
            continue
        valid.append({"base_offset": base, "pe_header_offset": base + int(headers["pe_offset"]),
            "machine_code": int(headers["machine_code"]), "architecture": str(headers["architecture"]),
            "optional_header_kind": str(headers["optional_header_kind"]),
            "section_count": int(headers["section_count"]), "image_base": int(headers["image_base"]),
            "size_of_image": int(headers["size_of_image"]), "section_table_offset": base + int(headers["section_table_offset"]),
            "raw_section_ranges": [[base + int(start), base + int(end)]
                                    for start, end in headers["raw_section_ranges"]],
            "raw_image_end_offset": image_end,
            "embedded_raw_bytes_sha256": hashlib.sha256(data[base:image_end]).hexdigest()})
    valid.sort(key=lambda item: (item["base_offset"], item["machine_code"]))
    return {"status": "PASS", "source_size_bytes": len(data),
        "mz_marker_count_scanned": len(offsets), "mz_marker_scan_truncated": markers_truncated,
        "pe_signature_candidate_count": signature_candidates,
        "rejected_structural_header_count": rejected_headers,
        "valid_pe_image_count": len(valid), "valid_images": valid,
        "claim_scope": "embedded MZ/PE structural headers and raw section bounds only; module role, executable behavior, exports, map semantics, and device compatibility remain UNKNOWN"}
