"""Targeted, read-only PE/NK cross-reference study for MP0 node readers.

This reuses the project's bounded PE/import/embedded-PE readers. It does not
disassemble SH4 instructions or assign meanings to Section 4/5 fields.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import os
import shutil
import struct
import sys
from typing import Any

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[2]
EVIDENCE = HERE / "evidence"
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from src.readers.ncdx_binary_headers import inspect_pe_headers  # noqa: E402
from src.readers.ncdx_pe_imports import parse_imports  # noqa: E402
from src.readers.ncdx_embedded_pe import scan_embedded_pe  # noqa: E402

NAVIMAIN = Path(os.environ.get("NCDR_SOURCE_ROOT", Path(__file__).resolve().parents[3])) / 'SW' / 'LK841' / 'HU_HARDWARE_LOC_0000000001' / 'HU_MMIDIS_LOC_0130170000' / 'WINDOWS' / 'NAVIMAIN.EXE'
NK_BIN = Path(os.environ.get("NCDR_SOURCE_ROOT", Path(__file__).resolve().parents[3])) / 'SW' / 'LK841' / 'HU_HARDWARE_LOC_0000000001' / 'HU_KERNEL_LOC_0101000870' / 'NK.BIN'
NAVIMAIN_SHA256 = "8bbeb2a919a4b5e470dd1eaaf47dd029dd2ccf12586b1a4ebb0ea9729087fb07"
NK_SHA256 = "d5a626f03cd1ef945d699b17332d57acf8f7c6fd7bbe765fbbcc771e14d90847"
TOPOLOGY_EVIDENCE = PROJECT / "research" / "geometry_breakthrough" / "topology_v3" / "evidence" / "node_link_validation.json"
WRITER_V2_PREFLIGHT = PROJECT / "research" / "geometry_breakthrough" / "writer_v2" / "evidence" / "edge_insertion_preflight.json"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hits(data: bytes, needle: bytes, limit: int = 40) -> list[int]:
    found: list[int] = []
    cursor = 0
    while len(found) < limit:
        at = data.find(needle, cursor)
        if at < 0:
            break
        found.append(at)
        cursor = at + 1
    return found


def _rva_file_offset(rva: int, headers: dict[str, Any]) -> tuple[int, str]:
    for section in headers["sections"]:
        start = int(section["virtual_address"])
        raw_size = int(section["raw_size"])
        if start <= rva < start + raw_size:
            return int(section["raw_pointer"]) + rva - start, str(section["name"])
    if rva < int(headers.get("size_of_headers", 0)):
        return rva, "PE_HEADERS"
    raise ValueError(f"RVA 0x{rva:X} is not backed by raw PE bytes")


def _navimain_report(data: bytes) -> dict[str, Any]:
    headers = inspect_pe_headers(data)
    if headers["architecture"] != "SH4":
        raise ValueError(f"unexpected NAVIMAIN architecture: {headers['architecture']}")
    pe_offset = int(headers["pe_offset"])
    optional = pe_offset + 24
    entry_rva = struct.unpack_from("<I", data, optional + 16)[0]
    image_base = struct.unpack_from("<I", data, optional + 28)[0]
    section_table = int(headers["section_table_offset"])
    sections = []
    for index, section in enumerate(headers["sections"]):
        row = section_table + 40 * index
        characteristics = struct.unpack_from("<I", data, row + 36)[0]
        start, name = int(section["raw_pointer"]), str(section["name"])
        size = int(section["raw_size"])
        chunk = data[start:start + size]
        entropy_counts = [chunk.count(bytes([value])) for value in range(256)]
        import math
        entropy = -sum((count / len(chunk)) * math.log2(count / len(chunk))
                       for count in entropy_counts if count) if chunk else 0.0
        sections.append({**section, "characteristics_hex": f"0x{characteristics:08x}",
                         "raw_entropy_bits_per_byte": round(entropy, 4)})
    entry_offset, entry_section = _rva_file_offset(entry_rva, headers)
    imports = parse_imports(data)
    text_section = next(row for row in headers["sections"] if row["name"] == ".text")
    text_start = int(text_section["raw_pointer"])
    text_end = text_start + int(text_section["raw_size"])
    text = data[text_start:text_end]
    iat_refs: list[dict[str, Any]] = []
    for module in imports["modules"]:
        for item in module["imports"]:
            iat_rva = int(item["iat_rva"])
            preferred_va = image_base + iat_rva
            literal = struct.pack("<I", preferred_va)
            for relative in _hits(text, literal):
                iat_refs.append({"module": module["module"],
                    "symbol": item.get("name", f"ordinal_{item.get('ordinal')}"),
                    "ordinal": item.get("ordinal"), "iat_rva": iat_rva,
                    "preferred_va_literal": f"0x{preferred_va:08x}",
                    "literal_file_offset": text_start + relative,
                    "literal_rva": int(text_section["virtual_address"]) + relative,
                    "raw_hex": literal.hex()})
    packer_markers = (b"UPX!", b"MPRESS1", b"Themida", b"ASPack", b"PECompact", b"PKLITE", b"FSG!")
    overlays_start = max(int(row["raw_pointer"]) + int(row["raw_size"])
                         for row in headers["sections"])
    named_imports = [{"module": module["module"], "name": item["name"]}
                     for module in imports["modules"] for item in module["imports"]
                     if "name" in item]
    return {
        "sha256": _sha(data), "size_bytes": len(data), "pe": {
            "machine_code": headers["machine_code"], "architecture": headers["architecture"],
            "optional_header_kind": headers["optional_header_kind"],
            "image_base": image_base, "size_of_image": headers["size_of_image"],
            "entry_point_rva": f"0x{entry_rva:08x}",
            "entry_point_va": f"0x{image_base + entry_rva:08x}",
            "entry_point_file_offset": f"0x{entry_offset:08x}",
            "entry_point_section": entry_section,
            "entry_point_hex_64_bytes": data[entry_offset:entry_offset + 64].hex(),
            "sections": sections,
            "file_backed_sections_end": overlays_start,
            "overlay_bytes": len(data) - overlays_start,
            "overlay_sha256": _sha(data[overlays_start:]),
            "overlay_hex": data[overlays_start:].hex(),
        },
        "imports": {"total": imports["import_count"], "modules": [
            {"module": module["module"], "named_count": sum("name" in row for row in module["imports"]),
             "ordinal_count": sum("ordinal" in row for row in module["imports"]),
             "named_symbols": [row["name"] for row in module["imports"] if "name" in row]}
            for module in imports["modules"]],
            "named_io_api_candidates": imports["io_api_candidates"],
            "preferred_va_iat_literals_found_in_text": len(iat_refs),
            "iat_literal_reference_samples": iat_refs[:80],
            "interpretation": "Named import census only; coredll/MFC ordinal targets are unresolved and may include file APIs."},
        "packer_check": {"known_marker_offsets": {
            marker.decode("ascii"): _hits(data, marker) for marker in packer_markers},
            "requires_unpacking": "NOT_ESTABLISHED; conventional section table and entrypoint are readable, but absence of known markers cannot exclude runtime unpacking"},
        "target_strings": {term: {"ascii_offsets": _hits(data, term.encode("ascii")),
                                  "utf16le_offsets": _hits(data, term.encode("utf-16le"))}
                           for term in ("MP0", "EUZ.MP0", "node", "edge", "route", "graph", "map")},
        "reader_procedure": "NOT_LOCATED; no SH4 instruction decoder is available in the current environment",
        "section4_section5_algorithm": "NOT_RECOVERED_FROM_NAVIMAIN",
    }


def _nk_report(data: bytes) -> dict[str, Any]:
    embedded = scan_embedded_pe(data)
    marker_offsets = _hits(data, b"MZ", limit=8192)
    pe_signatures = _hits(data, b"PE\x00\x00", limit=8192)
    pe_candidates = []
    for at in pe_signatures:
        if at + 24 <= len(data):
            machine, sections = struct.unpack_from("<HH", data, at + 4)
            pe_candidates.append({"file_offset": at, "machine_code": f"0x{machine:04x}",
                                  "section_count": sections,
                                  "matches_NAVIMAIN_SH4_machine": machine == 0x01A6})
    first_non_ff = next((index for index in range(32, len(data)) if data[index] != 0xFF), None)
    ecec_offsets = _hits(data, b"ECEC")
    ecec_contexts = []
    for at in ecec_offsets[:8]:
        pointer = struct.unpack_from("<I", data, at + 4)[0] if at + 8 <= len(data) else None
        pointer_offsets = _hits(data, struct.pack("<I", pointer), limit=40) if pointer is not None else []
        ecec_contexts.append({"file_offset": at,
            "preceding_4_bytes_hex": data[max(0, at - 4):at].hex(),
            "following_u32_le_untyped": pointer,
            "same_dword_occurrence_offsets": pointer_offsets,
            "following_64_bytes_hex": data[at:at + 64].hex()})
    return {
        "sha256": _sha(data), "size_bytes": len(data),
        "prefix_ascii": data[:32].rstrip(b"\x00\xff").decode("ascii", "replace"),
        "first_non_ff_after_byte_32": first_non_ff,
        "ce00ff_marker_offsets": _hits(data, b"CE00FF\n"),
        "ce_marker_context_hex": (data[0x400:0x440].hex() if len(data) >= 0x440 else None),
        "ecec_marker_offsets": ecec_offsets,
        "ecec_marker_contexts": ecec_contexts,
        "mz_marker_count": len(marker_offsets), "mz_marker_offsets": marker_offsets,
        "embedded_pe_scan": {key: embedded[key] for key in (
            "status", "mz_marker_count_scanned", "pe_signature_candidate_count",
            "rejected_structural_header_count", "valid_pe_image_count")},
        "raw_pe_signature_count": len(pe_signatures), "raw_pe_signature_candidates": pe_candidates,
        "target_strings": {term: {"ascii_offsets": _hits(data, term.encode("ascii")),
                                   "utf16le_offsets": _hits(data, term.encode("utf-16le"))}
                           for term in ("NAVIMAIN", "NAVIMAIN.EXE", "MMIDIS.EXE", "EUZ.MP0", "MP0", "ROMHDR")},
        "image_format": "UNKNOWN; CE00FF marker at 0x400 is recorded but not parsed as a ROM/module table",
        "node_reader_code": "NOT_LOCATED; no valid PE module extracted and no NK image loader is available",
    }


def analyze() -> dict[str, Any]:
    nav_before = _sha(NAVIMAIN.read_bytes())
    nk_before = _sha(NK_BIN.read_bytes())
    if nav_before != NAVIMAIN_SHA256 or nk_before != NK_SHA256:
        raise ValueError("NAVIMAIN.EXE or NK.BIN differs from the existing immutable manifest")
    nav_bytes, nk_bytes = NAVIMAIN.read_bytes(), NK_BIN.read_bytes()
    nav = _navimain_report(nav_bytes)
    nk = _nk_report(nk_bytes)

    prior = json.loads(TOPOLOGY_EVIDENCE.read_text(encoding="utf-8"))
    high = prior["high_nibble_gt4_records"]["actual_primary_incidence_by_stored_low_nibble_and_incidence"]
    zero_primary_high = sum(value for key, value in high.items() if key.endswith("actual_primary_incidence=0"))
    preflight = json.loads(WRITER_V2_PREFLIGHT.read_text(encoding="utf-8"))
    candidate = preflight["candidate"]
    disassemblers = ("sh-elf-objdump", "sh4-linux-gnu-objdump", "llvm-objdump",
                     "objdump", "dumpbin", "radare2", "rizin", "ghidraRun", "ndisasm")
    rom_extractors = ("romimage", "dumprom", "romxip", "zunextract")
    nav_after, nk_after = _sha(NAVIMAIN.read_bytes()), _sha(NK_BIN.read_bytes())
    if nav_after != nav_before or nk_after != nk_before:
        raise RuntimeError("an original firmware file changed during the read-only analysis")
    return {
        "status": "PASS_BOUNDED_XREF_WITH_CODE_READER_UNRESOLVED",
        "sources": {"NAVIMAIN.EXE": {**nav, "path": str(NAVIMAIN),
                    "sha256_after": nav_after, "source_write_count": 0},
                    "NK.BIN": {**nk, "path": str(NK_BIN),
                    "sha256_after": nk_after, "source_write_count": 0}},
        "prior_topology_context": {
            "source": "existing topology_v3 evidence; not recomputed",
            "high_low_nibble_gt4_rows_without_local_primary_endpoint_incidence": zero_primary_high,
            "node_identity_mismatches": prior["low_degree_identity_adjacency"]["mismatches"],
            "section5_endpoints_out_of_range": prior["section5_endpoint_out_of_range"],
        },
        "selected_writer_v2_candidate": candidate,
        "tooling": {"disassembler_paths": {tool: shutil.which(tool) for tool in disassemblers},
                    "rom_extractor_paths": {tool: shutil.which(tool) for tool in rom_extractors}},
        "code_level_findings": [
            "NAVIMAIN is a small SH4 PE with a conventional .text/.rdata/.data/.pdata/.rsrc layout; entry point maps to a file-backed .text range.",
            "No named file-I/O import was found, but 18 coredll imports are ordinal-only; no conclusion about file access is safe until those ordinals are resolved.",
            "The PE code section contains preferred-image-base literals for imported IAT slots. These references establish import use, not which call sites parse MP0.",
            "NK.BIN does not yield a valid embedded PE under the bounded existing scanner; its custom image/module format and executable payload layout remain unknown.",
        ],
        "unresolved": ["SH4 instruction disassembly and call graph", "coredll ordinal export mapping",
                       "NK.BIN CE00FF image/module table", "Section 4/5 reader procedure", "Section 6–9/RT/RL consumers"],
        "originals_written": False,
    }


if __name__ == "__main__":
    report = analyze()
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    target = EVIDENCE / "firmware_xref.json"
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": report["status"],
        "navimain_entry": report["sources"]["NAVIMAIN.EXE"]["pe"]["entry_point_va"],
        "navimain_entry_file_offset": report["sources"]["NAVIMAIN.EXE"]["pe"]["entry_point_file_offset"],
        "named_io_api_candidates": report["sources"]["NAVIMAIN.EXE"]["imports"]["named_io_api_candidates"],
        "ordinal_imports": report["sources"]["NAVIMAIN.EXE"]["imports"]["modules"][0]["ordinal_count"],
        "nk_valid_embedded_pe": report["sources"]["NK.BIN"]["embedded_pe_scan"]["valid_pe_image_count"],
        "high_degree_no_local_primary_endpoint": report["prior_topology_context"]["high_low_nibble_gt4_rows_without_local_primary_endpoint_incidence"]},
        ensure_ascii=False, indent=2))
