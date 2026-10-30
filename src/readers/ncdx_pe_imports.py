"""Bounded read-only PE import-table inventory for NCDx firmware research."""

from __future__ import annotations

import struct
from typing import Any

from src.readers.ncdx_binary_headers import inspect_pe_headers


MAX_SOURCE_BYTES = 32 * 1024 * 1024
MAX_IMPORT_DESCRIPTORS = 128
MAX_THUNKS_PER_MODULE = 4096
MAX_NAME_BYTES = 256
_IO_NAME_PARTS = ("file", "read", "write", "open", "close", "deviceio", "findfirst", "findnext")


def _cstring(data: bytes, offset: int, *, limit: int = MAX_NAME_BYTES) -> str:
    if offset < 0 or offset >= len(data):
        raise ValueError("PE string offset is outside the source")
    end = data.find(b"\x00", offset, min(len(data), offset + limit + 1))
    if end < 0:
        raise ValueError("PE import string is unterminated or exceeds the fixed bound")
    raw = data[offset:end]
    if not raw or any(byte < 0x20 or byte > 0x7E for byte in raw):
        raise ValueError("PE import string contains non-printable bytes")
    return raw.decode("ascii")


def _rva_to_offset(rva: int, size: int, headers: dict[str, Any], file_size: int) -> int:
    if rva < 0 or size < 0:
        raise ValueError("negative PE RVA or length")
    if rva < int(headers.get("size_of_headers", 0)):
        offset = rva
    else:
        offset = -1
        for section in headers["sections"]:
            start = int(section["virtual_address"])
            raw_size = int(section["raw_size"])
            if start <= rva and rva - start < raw_size:
                offset = int(section["raw_pointer"]) + rva - start
                if size > raw_size - (rva - start):
                    raise ValueError("PE RVA range crosses the mapped section's raw bytes")
                break
        if offset < 0:
            raise ValueError("PE RVA is not backed by a section's raw bytes")
    if offset > file_size or size > file_size - offset:
        raise ValueError("PE RVA range extends beyond the file")
    return offset


def parse_imports(data: bytes) -> dict[str, Any]:
    """Parse bounded normal PE imports; do not infer runtime behavior or map semantics."""
    if len(data) > MAX_SOURCE_BYTES:
        raise ValueError("PE source exceeds the fixed 32 MiB import-table limit")
    headers = inspect_pe_headers(data)
    pe_offset = int(headers["pe_offset"])
    optional_offset = pe_offset + 24
    magic = int(headers["optional_header_magic"])
    directory_offset = optional_offset + (96 if magic == 0x10B else 112)
    number_offset = optional_offset + (92 if magic == 0x10B else 108)
    optional_end = int(headers["section_table_offset"])
    if number_offset + 4 > optional_end:
        raise ValueError("PE data-directory count is outside the optional header")
    directory_count = struct.unpack_from("<I", data, number_offset)[0]
    if directory_count <= 1:
        return {"status": "PASS", "import_directory_rva": 0, "import_directory_size": 0,
                "modules": [], "import_count": 0, "io_api_candidates": [],
                "claim_scope": "normal import directory absent; runtime behavior remains UNKNOWN"}
    if directory_offset + 16 > optional_end:
        raise ValueError("PE import data-directory entry is truncated")
    import_rva, import_size = struct.unpack_from("<II", data, directory_offset + 8)
    if import_rva == 0 and import_size == 0:
        return {"status": "PASS", "import_directory_rva": 0, "import_directory_size": 0,
                "modules": [], "import_count": 0, "io_api_candidates": [],
                "claim_scope": "normal import directory absent; runtime behavior remains UNKNOWN"}
    if import_rva == 0 or import_size < 20 or import_size > 1024 * 1024:
        raise ValueError("PE import-directory range is invalid or exceeds the 1 MiB bound")
    headers["size_of_headers"] = struct.unpack_from("<I", data, optional_offset + 60)[0]
    directory_file_offset = _rva_to_offset(import_rva, import_size, headers, len(data))
    pointer_width = 4 if magic == 0x10B else 8
    ordinal_mask = 1 << (pointer_width * 8 - 1)
    modules: list[dict[str, Any]] = []
    io_candidates: list[dict[str, Any]] = []
    total_imports = 0
    descriptor_limit = min(MAX_IMPORT_DESCRIPTORS, import_size // 20)
    saw_terminator = False
    for descriptor_index in range(descriptor_limit):
        descriptor_rva = import_rva + descriptor_index * 20
        descriptor_offset = directory_file_offset + descriptor_index * 20
        if descriptor_offset + 20 > directory_file_offset + import_size:
            break
        original_thunk, _timestamp, _forwarder, name_rva, first_thunk = struct.unpack_from(
            "<IIIII", data, descriptor_offset)
        if not (original_thunk or name_rva or first_thunk):
            saw_terminator = True
            break
        if not name_rva or not first_thunk:
            raise ValueError("PE import descriptor lacks a module name or IAT")
        name_offset = _rva_to_offset(name_rva, 1, headers, len(data))
        module_name = _cstring(data, name_offset).lower()
        lookup_rva = original_thunk or first_thunk
        imports: list[dict[str, Any]] = []
        saw_thunk_terminator = False
        for thunk_index in range(MAX_THUNKS_PER_MODULE):
            thunk_rva = lookup_rva + thunk_index * pointer_width
            iat_rva = first_thunk + thunk_index * pointer_width
            thunk_offset = _rva_to_offset(thunk_rva, pointer_width, headers, len(data))
            value = int.from_bytes(data[thunk_offset:thunk_offset + pointer_width], "little")
            if value == 0:
                saw_thunk_terminator = True
                break
            if value & ordinal_mask:
                item = {"ordinal": value & 0xFFFF, "iat_rva": iat_rva,
                        "iat_file_offset": _rva_to_offset(iat_rva, pointer_width, headers, len(data))}
            else:
                name_rva_value = value & (ordinal_mask - 1)
                name_offset_value = _rva_to_offset(name_rva_value, 3, headers, len(data))
                hint = struct.unpack_from("<H", data, name_offset_value)[0]
                api_name = _cstring(data, name_offset_value + 2)
                item = {"name": api_name, "hint": hint, "name_rva": name_rva_value,
                        "iat_rva": iat_rva,
                        "iat_file_offset": _rva_to_offset(iat_rva, pointer_width, headers, len(data))}
                if any(part in api_name.casefold() for part in _IO_NAME_PARTS):
                    io_candidates.append({"module": module_name, "name": api_name,
                        "iat_rva": iat_rva, "iat_file_offset": item["iat_file_offset"],
                        "classification": "NAME_MATCH_ONLY; call sites and behavior not analyzed"})
            imports.append(item)
        if not saw_thunk_terminator:
            raise ValueError("PE import thunk table exceeds the 4096-entry per-module bound")
        total_imports += len(imports)
        modules.append({"module": module_name, "descriptor_rva": descriptor_rva,
            "descriptor_file_offset": descriptor_offset, "name_rva": name_rva,
            "name_file_offset": name_offset, "first_thunk_rva": first_thunk,
            "original_first_thunk_rva": original_thunk, "imports": imports})
    if not saw_terminator:
        raise ValueError("PE import directory has no null descriptor within its declared bounded range")
    return {"status": "PASS", "import_directory_rva": import_rva,
        "import_directory_size": import_size, "modules": modules,
        "import_count": total_imports, "io_api_candidates": io_candidates,
        "claim_scope": "normal PE import names and IAT RVAs/file offsets only; internal call sites, runtime file access, NCDx decoding and physical compatibility remain UNKNOWN"}
