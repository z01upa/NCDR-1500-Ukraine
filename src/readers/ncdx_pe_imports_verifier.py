"""Independent source-and-import readback for the bounded PE import census."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import struct
from typing import Any


def _digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            value.update(chunk)
    return value.hexdigest()


def _read_cstring(data: bytes, index: int) -> str:
    if not 0 <= index < len(data):
        raise ValueError("independent verifier found an out-of-file string")
    finish = data.find(b"\0", index, min(len(data), index + 257))
    if finish < 0:
        raise ValueError("independent verifier found an unbounded string")
    text = data[index:finish]
    if not text or any(byte < 32 or byte > 126 for byte in text):
        raise ValueError("independent verifier found a non-printable import name")
    return text.decode("ascii")


def _independent_imports(data: bytes) -> dict[str, Any]:
    if len(data) > 32 * 1024 * 1024:
        raise ValueError("source exceeds the independent verifier's 32 MiB limit")
    if len(data) < 64 or data[:2] != b"MZ":
        raise ValueError("source is not a PE image")
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    if pe < 64 or pe + 24 > len(data) or data[pe:pe + 4] != b"PE\0\0":
        raise ValueError("invalid PE signature or offset")
    _machine, sections_count, _ts, _symbols, _symbol_count, optional_size, _flags = struct.unpack_from(
        "<HHIIIHH", data, pe + 4)
    optional = pe + 24
    optional_stop = optional + optional_size
    magic = struct.unpack_from("<H", data, optional)[0]
    if magic not in (0x10B, 0x20B):
        raise ValueError("unsupported PE optional header")
    if optional_stop > len(data) or sections_count < 1 or sections_count > 96:
        raise ValueError("invalid PE optional header or section count")
    if magic == 0x10B:
        count_index, table_index, width = optional + 92, optional + 96, 4
    else:
        count_index, table_index, width = optional + 108, optional + 112, 8
    count = struct.unpack_from("<I", data, count_index)[0]
    if count <= 1:
        return {"import_directory_rva": 0, "import_directory_size": 0, "modules": [], "import_count": 0}
    table = struct.unpack_from("<II", data, table_index + 8)
    import_rva, import_size = table
    if not import_rva or import_size < 20 or import_size > 1024 * 1024:
        raise ValueError("invalid import directory")
    headers_size = struct.unpack_from("<I", data, optional + 60)[0]
    section_offset = optional_stop
    section_rows = []
    for index in range(sections_count):
        offset = section_offset + index * 40
        if offset + 40 > len(data):
            raise ValueError("truncated PE section table")
        _name = data[offset:offset + 8]
        virtual_size, virtual_start, raw_size, raw_start = struct.unpack_from("<IIII", data, offset + 8)
        if raw_start > len(data) or raw_size > len(data) - raw_start:
            raise ValueError("section raw range escapes source")
        section_rows.append((virtual_start, raw_size, raw_start))

    def to_file(rva: int, length: int) -> int:
        if rva < headers_size:
            start = rva
        else:
            found = None
            for virtual, raw_length, raw_offset in section_rows:
                delta = rva - virtual
                if 0 <= delta < raw_length and length <= raw_length - delta:
                    found = raw_offset + delta
                    break
            if found is None:
                raise ValueError("RVA is outside raw-backed sections")
            start = found
        if start > len(data) or length > len(data) - start:
            raise ValueError("RVA mapping is beyond source")
        return start

    directory_file = to_file(import_rva, import_size)
    descriptors = []
    import_total = 0
    terminated = False
    for position in range(min(import_size // 20, 128)):
        current = directory_file + position * 20
        original, _date, _chain, module_rva, iat_rva = struct.unpack_from("<IIIII", data, current)
        if original == module_rva == iat_rva == 0:
            terminated = True
            break
        if not module_rva or not iat_rva:
            raise ValueError("incomplete import descriptor")
        module_offset = to_file(module_rva, 1)
        module = _read_cstring(data, module_offset).lower()
        lookup = original or iat_rva
        function_rows = []
        thunk_terminated = False
        for slot in range(4096):
            lookup_rva = lookup + slot * width
            entry_offset = to_file(lookup_rva, width)
            number = int.from_bytes(data[entry_offset:entry_offset + width], "little")
            if number == 0:
                thunk_terminated = True
                break
            iat = iat_rva + slot * width
            iat_offset = to_file(iat, width)
            if number & (1 << (width * 8 - 1)):
                function_rows.append({"ordinal": number & 0xFFFF, "iat_rva": iat,
                                      "iat_file_offset": iat_offset})
            else:
                named_rva = number & ((1 << (width * 8 - 1)) - 1)
                named_offset = to_file(named_rva, 3)
                ordinal_hint = struct.unpack_from("<H", data, named_offset)[0]
                function_rows.append({"name": _read_cstring(data, named_offset + 2),
                    "hint": ordinal_hint, "name_rva": named_rva, "iat_rva": iat,
                    "iat_file_offset": iat_offset})
        if not thunk_terminated:
            raise ValueError("unbounded thunk sequence")
        import_total += len(function_rows)
        descriptors.append({"module": module, "descriptor_rva": import_rva + position * 20,
            "descriptor_file_offset": current, "name_rva": module_rva,
            "name_file_offset": module_offset, "first_thunk_rva": iat_rva,
            "original_first_thunk_rva": original, "imports": function_rows})
    if not terminated:
        raise ValueError("missing import descriptor terminator")
    candidates = []
    for descriptor in descriptors:
        for function in descriptor["imports"]:
            name = function.get("name")
            if isinstance(name, str) and any(part in name.casefold() for part in (
                    "file", "read", "write", "open", "close", "deviceio", "findfirst", "findnext")):
                candidates.append({"module": descriptor["module"], "name": name,
                    "iat_rva": function["iat_rva"], "iat_file_offset": function["iat_file_offset"],
                    "classification": "NAME_MATCH_ONLY; call sites and behavior not analyzed"})
    return {"import_directory_rva": import_rva, "import_directory_size": import_size,
            "modules": descriptors, "import_count": import_total,
            "io_api_candidates": candidates}


def verify_artifact(artifact_path: Path, *, source_root: Path, project_root: Path,
                    relative_path: str, expected_sha256: str, expected_size: int,
                    artifact_sha256: str) -> dict[str, Any]:
    artifact = Path(artifact_path).resolve(strict=True)
    project = Path(project_root).resolve(strict=True)
    if not artifact.is_relative_to(project) or _digest(artifact) != artifact_sha256:
        raise ValueError("PE import artifact is outside the workspace or its hash changed")
    rel = PurePosixPath(relative_path)
    root = Path(source_root).resolve(strict=True)
    if rel.is_absolute() or ".." in rel.parts:
        raise ValueError("unsafe PE input path")
    source = (root / Path(*rel.parts)).resolve(strict=True)
    if not source.is_relative_to(root) or source.stat().st_size != expected_size:
        raise ValueError("PE source path or size differs from its scheduled identity")
    before_stat = source.stat()
    source_hash = _digest(source)
    if source_hash != expected_sha256:
        raise ValueError("PE source hash differs from the evidence ledger")
    parsed = _independent_imports(source.read_bytes())
    saved = json.loads(artifact.read_text(encoding="utf-8"))
    after_hash = _digest(source)
    after_stat = source.stat()
    if (after_hash != source_hash or before_stat.st_size != after_stat.st_size
            or before_stat.st_mtime_ns != after_stat.st_mtime_ns):
        raise ValueError("PE source changed during independent verification")
    saved_parsed = {key: saved.get(key) for key in parsed}
    if (saved.get("source_path") != rel.as_posix()
            or saved.get("source_sha256") != source_hash
            or saved.get("source_size_bytes") != expected_size
            or saved_parsed != parsed
            or saved.get("original_media_write_count") != 0):
        raise ValueError("saved PE import observations do not match fresh independent parsing")
    return {"status": "PASS", "independent_source_readback": "PASS",
        "source_path": rel.as_posix(), "source_size_bytes": expected_size,
        "source_sha256": source_hash, "module_count": len(parsed["modules"]),
        "import_count": parsed["import_count"], "import_table_reproduced": True,
        "original_media_write_count": 0,
        "claim_scope": "import table and IAT locations only; no call sites, map semantics, or device behavior proven"}
