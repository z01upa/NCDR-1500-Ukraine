"""One-pass metadata inventory and bounded executable-module scan for NCDR."""
from __future__ import annotations

import csv
import hashlib
import json
import re
import struct
import sys
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
import os
from typing import Any

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[2]
NCDR_ROOT = Path(os.environ.get("NCDR_SOURCE_ROOT", Path(__file__).resolve().parents[3]))
OLD_MANIFEST = PROJECT / "inventory" / "discs_manifest.csv"
EVIDENCE = HERE / "evidence"
TEXT_SCAN_ROOTS = {"SW"}
MAX_PE_BYTES = 32 * 1024 * 1024
MAX_EXPORTS = 32768
MAX_ZIP_MODULE_BYTES = 32 * 1024 * 1024
EXEC_SUFFIXES = {".exe", ".dll", ".ocx", ".sys", ".cpl", ".drv"}
TEXT_SUFFIXES = {
    ".c", ".cc", ".cpp", ".h", ".hpp", ".idl", ".rc", ".def", ".reg",
    ".ini", ".cfg", ".xml", ".json", ".txt", ".md", ".csv", ".bat", ".cmd",
    ".ps1", ".yaml", ".yml", ".html", ".htm",
}
KEY_TERMS = (
    "EUZ.MP0", "EUZ.RT", "EUZ.RL", "NaviTrace.dll", "MI_CF_RemoteComManager",
    "MI_CF_CommunicationBroker", "CreateInstance", "Navigation", "Routing",
    "Navi Registry", "NaviMain", "MMIDIS",
)
SERVICE_STRING = re.compile(
    r"(?i)(?:Navi[^\x00]{0,80}|[^\x00]{0,40}(?:route|routing|navigation|service|registry)[^\x00]{0,80})"
)

sys.path.insert(0, str(PROJECT))
from src.readers.ncdx_binary_headers import inspect_pe_headers  # noqa: E402
from src.readers.ncdx_pe_imports import parse_imports  # noqa: E402


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _rva_offset(rva: int, size: int, headers: dict[str, Any], data_size: int) -> int:
    if rva < 0 or size < 0:
        raise ValueError("negative RVA/range")
    headers_size = int(headers.get("size_of_headers", 0))
    if rva < headers_size:
        offset = rva
        if size > headers_size - rva:
            raise ValueError("RVA range crosses PE headers")
    else:
        offset = -1
        for section in headers["sections"]:
            start, raw_size = int(section["virtual_address"]), int(section["raw_size"])
            if start <= rva < start + raw_size:
                if size > raw_size - (rva - start):
                    raise ValueError("RVA range crosses raw section bounds")
                offset = int(section["raw_pointer"]) + rva - start
                break
        if offset < 0:
            raise ValueError(f"RVA 0x{rva:x} is not file-backed")
    if offset > data_size or size > data_size - offset:
        raise ValueError("RVA range outside file")
    return offset


def _export_inventory(data: bytes, headers: dict[str, Any]) -> dict[str, Any]:
    pe = int(headers["pe_offset"])
    opt = pe + 24
    magic = int(headers["optional_header_magic"])
    directory_base = opt + (96 if magic == 0x10B else 112)
    directory_count_offset = opt + (92 if magic == 0x10B else 108)
    optional_end = int(headers["section_table_offset"])
    if directory_count_offset + 4 > optional_end:
        raise ValueError("optional header has no complete data-directory count")
    count = struct.unpack_from("<I", data, directory_count_offset)[0]
    if count < 1 or directory_base + 8 > optional_end:
        return {"rva": 0, "size": 0, "functions": 0, "named_exports": []}
    export_rva, export_size = struct.unpack_from("<II", data, directory_base)
    if export_rva == 0 and export_size == 0:
        return {"rva": 0, "size": 0, "functions": 0, "named_exports": []}
    if export_rva == 0 or export_size < 40 or export_size > 16 * 1024 * 1024:
        raise ValueError("invalid or oversized export directory")
    export_off = _rva_offset(export_rva, 40, headers, len(data))
    (_characteristics, _timestamp, _major, _minor, _name_rva, ordinal_base,
     function_count, name_count, funcs_rva, names_rva, ords_rva) = struct.unpack_from(
         "<IIHHIIIIIII", data, export_off)
    if function_count > MAX_EXPORTS or name_count > MAX_EXPORTS:
        raise ValueError("export count exceeds bounded scan limit")
    names_off = _rva_offset(names_rva, name_count * 4, headers, len(data)) if name_count else 0
    ords_off = _rva_offset(ords_rva, name_count * 2, headers, len(data)) if name_count else 0
    funcs_off = _rva_offset(funcs_rva, function_count * 4, headers, len(data)) if function_count else 0
    exports = []
    for index in range(name_count):
        name_rva = struct.unpack_from("<I", data, names_off + index * 4)[0]
        ordinal_index = struct.unpack_from("<H", data, ords_off + index * 2)[0]
        if ordinal_index >= function_count:
            raise ValueError("export name ordinal is outside function table")
        name_off = _rva_offset(name_rva, 1, headers, len(data))
        name_end = data.find(b"\0", name_off, min(len(data), name_off + 512))
        if name_end < 0:
            raise ValueError("unterminated export name")
        name = data[name_off:name_end].decode("ascii", errors="replace")
        function_rva = struct.unpack_from("<I", data, funcs_off + ordinal_index * 4)[0]
        exports.append({"name": name, "ordinal": ordinal_base + ordinal_index,
                        "function_rva": function_rva,
                        "forwarder": (export_rva <= function_rva < export_rva + export_size)})
    return {"rva": export_rva, "size": export_size,
            "function_count": function_count, "named_export_count": name_count,
            "named_exports": exports}


def _target_hits(data: bytes) -> list[dict[str, Any]]:
    lower = data.lower()
    hits = []
    for term in KEY_TERMS:
        needle = term.encode("ascii").lower()
        pos = lower.find(needle)
        while pos >= 0:
            hits.append({"term": term, "encoding": "ASCII", "offset": pos})
            pos = lower.find(needle, pos + 1)
        wide = b"".join(bytes((char, 0)) for char in term.encode("ascii"))
        pos = lower.find(wide.lower())
        while pos >= 0:
            hits.append({"term": term, "encoding": "UTF16LE", "offset": pos})
            pos = lower.find(wide.lower(), pos + 1)
    hits.sort(key=lambda item: (item["offset"], item["term"], item["encoding"]))
    return hits


def _service_strings(data: bytes) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for encoding, pattern, codec in (
        ("ASCII", re.compile(rb"[\x20-\x7e]{5,}"), "ascii"),
        ("UTF16LE", re.compile(rb"(?:[\x20-\x7e]\x00){5,}"), "utf-16le"),
    ):
        for match in pattern.finditer(data):
            text = match.group().decode(codec, errors="ignore")
            if SERVICE_STRING.search(text):
                out.append({"encoding": encoding, "offset": match.start(),
                            "text": text[:160]})
                if len(out) >= 120:
                    return out
    return out


def _pe_record(path_label: str, data: bytes) -> dict[str, Any]:
    record: dict[str, Any] = {"path": path_label, "size_bytes": len(data),
                              "sha256": _sha(data), "header": data[:16].hex(" ")}
    try:
        headers = inspect_pe_headers(data)
    except Exception as exc:
        record.update({"pe_status": "NOT_VALID_PE", "pe_error": f"{type(exc).__name__}: {exc}"})
        return record
    record.update({
        "pe_status": "PASS_PE_HEADERS",
        "machine_code": f"0x{int(headers['machine_code']):04x}",
        "architecture": headers["architecture"],
        "optional_header": headers["optional_header_kind"],
        "image_base": f"0x{int(headers['image_base']):x}",
        "size_of_image": int(headers["size_of_image"]),
        "entry_rva": f"0x{int.from_bytes(data[int(headers['pe_offset'])+40:int(headers['pe_offset'])+44], 'little'):x}",
        "sections": [{"name": str(s["name"]), "virtual_address": f"0x{int(s['virtual_address']):x}",
                      "virtual_size": int(s["virtual_size"]), "raw_size": int(s["raw_size"]),
                      "raw_pointer": f"0x{int(s['raw_pointer']):x}"}
                     for s in headers["sections"]],
        "target_string_hits": _target_hits(data),
        "service_strings": _service_strings(data),
    })
    # The shared bounded header reader intentionally omits this field. Export
    # RVAs can still point into headers, so recover it from the PE optional
    # header before parsing exports.
    opt = int(headers["pe_offset"]) + 24
    headers["size_of_headers"] = struct.unpack_from("<I", data, opt + 60)[0]
    try:
        record["imports"] = parse_imports(data)
    except Exception as exc:
        record["imports"] = {"status": "PARSE_FAIL", "error": f"{type(exc).__name__}: {exc}"}
    try:
        record["exports"] = _export_inventory(data, headers)
    except Exception as exc:
        record["exports"] = {"status": "PARSE_FAIL", "error": f"{type(exc).__name__}: {exc}"}
    return record


def _load_old_manifest() -> dict[str, dict[str, str]]:
    if not OLD_MANIFEST.exists():
        return {}
    with OLD_MANIFEST.open("r", encoding="utf-8-sig", newline="") as stream:
        return {row["relative_path"].replace("/", "\\").casefold(): row
                for row in csv.DictReader(stream)}


def inventory() -> dict[str, Any]:
    if not NCDR_ROOT.is_dir():
        raise FileNotFoundError(f"NCDR source root not found: {NCDR_ROOT}")
    old_manifest = _load_old_manifest()
    physical_rows = []
    pe_records = []
    zip_members = []
    text_hits = []
    roots = Counter()
    extensions = Counter()
    total_size = 0
    prior_equal = 0
    prior_size_mismatch = []
    new_paths = []
    current_path_keys = set()
    unreadable = []
    for path in sorted(NCDR_ROOT.rglob("*")):
        if not path.is_file():
            continue
        try:
            stat = path.stat()
            with path.open("rb") as stream:
                head = stream.read(64)
            rel = str(path.relative_to(NCDR_ROOT)).replace("/", "\\")
        except OSError as exc:
            unreadable.append({"path": str(path), "error": f"{type(exc).__name__}: {exc}"})
            continue
        key = rel.casefold()
        current_path_keys.add(key)
        ext = path.suffix.lower()
        roots[rel.split("\\", 1)[0]] += 1
        extensions[ext or "[no extension]"] += 1
        total_size += stat.st_size
        previous = old_manifest.get(key)
        if previous and int(previous["length_bytes"]) == stat.st_size:
            prior_equal += 1
        elif previous:
            prior_size_mismatch.append({"path": rel, "old_size": int(previous["length_bytes"]),
                                        "current_size": stat.st_size})
        else:
            new_paths.append(rel)
        physical_rows.append({"path": rel, "size_bytes": stat.st_size,
                              "extension": ext or "", "header_16": head[:16].hex(" "),
                              "signature": ("MZ" if head[:2] == b"MZ" else
                                            "CE00FF" if head.startswith(b"CE\x00\xff") else
                                            "ZIP" if head.startswith(b"PK\x03\x04") else
                                            "GZIP" if head.startswith(b"\x1f\x8b") else "OTHER"),
                              "previous_manifest_sha256": previous.get("sha256") if previous else None,
                              "previous_manifest_size_match": bool(previous and
                                  int(previous["length_bytes"]) == stat.st_size)})

        named_executable = ext in EXEC_SUFFIXES
        if head[:2] == b"MZ" or named_executable:
            if stat.st_size <= MAX_PE_BYTES:
                try:
                    data = path.read_bytes()
                    rec = _pe_record(rel, data)
                    if rec["pe_status"] == "PASS_PE_HEADERS" or named_executable:
                        pe_records.append(rec)
                except OSError as exc:
                    unreadable.append({"path": rel, "error": f"{type(exc).__name__}: {exc}"})
            else:
                pe_records.append({"path": rel, "size_bytes": stat.st_size,
                                   "pe_status": "SKIPPED_OVER_32_MIB_BOUND",
                                   "header": head[:16].hex(" ")})

        # Search text source/config files only in the actual SW tree. Code
        # strings are independently searched in every PE candidate above.
        if rel.split("\\", 1)[0].casefold() in {r.casefold() for r in TEXT_SCAN_ROOTS} \
                and ext in TEXT_SUFFIXES and stat.st_size <= 64 * 1024 * 1024:
            try:
                raw = path.read_bytes()
                hits = _target_hits(raw)
                if hits:
                    text_hits.append({"path": rel, "hits": hits[:80]})
            except OSError as exc:
                unreadable.append({"path": rel, "error": f"{type(exc).__name__}: {exc}"})

        if ext == ".zip":
            try:
                with zipfile.ZipFile(path) as archive:
                    for member in archive.infolist():
                        zip_members.append({"archive": rel, "member": member.filename,
                                            "size_bytes": member.file_size,
                                            "extension": Path(member.filename).suffix.lower()})
                        if Path(member.filename).suffix.lower() in EXEC_SUFFIXES and \
                                member.file_size <= MAX_ZIP_MODULE_BYTES:
                            try:
                                embedded = archive.read(member)
                                pe_records.append(_pe_record(f"{rel}!{member.filename}", embedded))
                            except Exception as exc:
                                unreadable.append({"path": f"{rel}!{member.filename}",
                                                   "error": f"{type(exc).__name__}: {exc}"})
            except (OSError, zipfile.BadZipFile) as exc:
                unreadable.append({"path": rel, "error": f"{type(exc).__name__}: {exc}"})

    missing_old = sorted(set(old_manifest) - current_path_keys)
    unique_pes: dict[str, dict[str, Any]] = {}
    for record in pe_records:
        digest = record.get("sha256")
        if digest and digest in unique_pes:
            unique_pes[digest].setdefault("duplicate_paths", []).append(record["path"])
        elif digest:
            unique_pes[digest] = record
    pe_records = list(unique_pes.values())
    inventory_jsonl = EVIDENCE / "physical_files.jsonl"
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    inventory_jsonl.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n"
                                                 for row in physical_rows), encoding="utf-8")
    report = {
        "source_root": str(NCDR_ROOT),
        "physical_file_count": len(physical_rows),
        "physical_total_bytes": total_size,
        "root_directory_file_counts": dict(sorted(roots.items())),
        "extensions": dict(extensions.most_common()),
        "old_manifest": {"path": str(OLD_MANIFEST), "entries": len(old_manifest),
                         "same_path_and_size": prior_equal,
                         "new_current_paths": len(new_paths),
                         "changed_size_paths": prior_size_mismatch,
                         "missing_old_paths": len(missing_old),
                         "new_path_examples": new_paths[:100],
                         "missing_path_examples": missing_old[:100]},
        "pe_module_unique_content_count": len(pe_records),
        "pe_modules": pe_records,
        "zip_member_count": len(zip_members),
        "zip_executable_members": [row for row in zip_members
                                   if row["extension"] in EXEC_SUFFIXES],
        "text_target_hits_in_sw": text_hits,
        "unreadable_or_bounded_skips": unreadable,
        "string_search_terms": list(KEY_TERMS),
        "string_search_scope": "ASCII and UTF-16LE target strings in PE candidates; selected code/config text file extensions in the actual SW tree; no full 11 GB binary data scan.",
        "physical_inventory_jsonl": str(inventory_jsonl),
    }
    (EVIDENCE / "module_inventory.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return report


def main() -> None:
    report = inventory()
    print(json.dumps({"physical_files": report["physical_file_count"],
                      "total_bytes": report["physical_total_bytes"],
                      "unique_pe_candidate_contents": report["pe_module_unique_content_count"],
                      "zip_members": report["zip_member_count"],
                      "unreadable_or_skipped": len(report["unreadable_or_bounded_skips"]),
                      "same_old_path_and_size": report["old_manifest"]["same_path_and_size"],
                      "new_paths": report["old_manifest"]["new_current_paths"],
                      "changed_sizes": len(report["old_manifest"]["changed_size_paths"]),
                      "missing_old": report["old_manifest"]["missing_old_paths"]}, indent=2))


if __name__ == "__main__":
    main()
