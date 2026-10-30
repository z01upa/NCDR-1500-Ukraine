"""Bounded, read-only PE/COFF header inspection for NCDR software evidence."""

from __future__ import annotations

import struct


MAX_PE_HEADER_SOURCE_BYTES = 32 * 1024 * 1024
MAX_PE_SECTIONS = 96

_MACHINE_ARCHITECTURES = {
    0x014C: "x86",
    0x01A6: "SH4",
    0x01C0: "ARM",
    0x01C2: "ARM or Thumb",
    0x01C4: "ARMNT",
    0x8664: "x86-64",
    0xAA64: "ARM64",
}


def inspect_pe_headers(data: bytes) -> dict[str, object]:
    """Parse bounded structural headers; never execute or interpret file code."""
    if len(data) > MAX_PE_HEADER_SOURCE_BYTES:
        raise ValueError("PE source exceeds the fixed 32 MiB inspection limit")
    if len(data) < 64 or data[:2] != b"MZ":
        raise ValueError("source does not contain a complete DOS MZ header")
    pe_offset = struct.unpack_from("<I", data, 0x3C)[0]
    if pe_offset < 64 or pe_offset + 24 > len(data):
        raise ValueError("PE header offset is outside the source")
    if data[pe_offset:pe_offset + 4] != b"PE\x00\x00":
        raise ValueError("MZ image does not contain a PE signature at e_lfanew")
    machine, section_count, _timestamp, _symbol_ptr, _symbol_count, optional_size, characteristics = \
        struct.unpack_from("<HHIIIHH", data, pe_offset + 4)
    if not 1 <= section_count <= MAX_PE_SECTIONS:
        raise ValueError("PE section count is outside the bounded parser policy")
    optional_offset = pe_offset + 24
    optional_end = optional_offset + optional_size
    if optional_size < 70 or optional_end > len(data):
        raise ValueError("PE optional header is truncated or too short for independent fields")
    optional_magic = struct.unpack_from("<H", data, optional_offset)[0]
    if optional_magic not in {0x10B, 0x20B}:
        raise ValueError(f"unsupported PE optional-header magic 0x{optional_magic:04x}")
    image_base_offset = optional_offset + (28 if optional_magic == 0x10B else 24)
    image_base_width = 4 if optional_magic == 0x10B else 8
    if image_base_offset + image_base_width > optional_end:
        raise ValueError("PE image-base field is outside the optional header")
    image_base = int.from_bytes(data[image_base_offset:image_base_offset + image_base_width], "little")
    size_of_image = struct.unpack_from("<I", data, optional_offset + 56)[0]
    checksum = struct.unpack_from("<I", data, optional_offset + 64)[0]
    subsystem = struct.unpack_from("<H", data, optional_offset + 68)[0]
    section_table_offset = optional_end
    if section_table_offset + section_count * 40 > len(data):
        raise ValueError("PE section table extends beyond the source")
    sections = []
    raw_ranges = []
    for index in range(section_count):
        offset = section_table_offset + index * 40
        name = data[offset:offset + 8].split(b"\x00", 1)[0].decode("ascii", errors="replace")
        virtual_size, virtual_address, raw_size, raw_pointer = struct.unpack_from("<IIII", data, offset + 8)
        if raw_size and (raw_pointer > len(data) or raw_size > len(data) - raw_pointer):
            raise ValueError(f"PE section {index} raw range extends beyond the source")
        if raw_size:
            raw_ranges.append([raw_pointer, raw_pointer + raw_size])
        sections.append({"name": name, "virtual_size": virtual_size,
            "virtual_address": virtual_address, "raw_size": raw_size,
            "raw_pointer": raw_pointer})
    return {
        "status": "PASS_PE_HEADERS",
        "pe_offset": pe_offset,
        "machine_code": machine,
        "architecture": _MACHINE_ARCHITECTURES.get(machine, "UNKNOWN_MACHINE"),
        "section_count": section_count,
        "optional_header_magic": optional_magic,
        "optional_header_kind": "PE32" if optional_magic == 0x10B else "PE32+",
        "image_base": image_base,
        "size_of_image": size_of_image,
        "checksum_field": checksum,
        "subsystem_code": subsystem,
        "characteristics": characteristics,
        "section_table_offset": section_table_offset,
        "sections": sections,
        "raw_section_ranges": raw_ranges,
        "claim_scope": "bounded PE/COFF header fields only; runtime behavior and NCDx data semantics UNKNOWN",
    }
