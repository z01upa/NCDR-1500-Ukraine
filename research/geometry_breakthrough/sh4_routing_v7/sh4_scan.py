"""Bounded, read-only SH4 scan of the existing NAVIMAIN.EXE."""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import re
import sys
from collections import deque
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[2]
VENDOR = HERE / "vendor"
XREF_DIR = PROJECT / "research" / "geometry_breakthrough" / "xref_v4"
for path in (VENDOR, PROJECT, XREF_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import pypcode  # noqa: E402
from firmware_xref import NAVIMAIN, NAVIMAIN_SHA256  # noqa: E402
from src.readers.ncdx_binary_headers import inspect_pe_headers  # noqa: E402
from src.readers.ncdx_pe_imports import parse_imports  # noqa: E402

LANGUAGE = "SuperH4:LE:32:default"
EXPECTED_ENTRY_VA = 0x11E24
EXPECTED_ENTRY_FILE_OFFSET = 0x1224
EXPECTED_CONTROL = ((bytes.fromhex("0900"), "nop"),
                    (bytes.fromhex("0b00"), "rts"),
                    (bytes.fromhex("0b40"), "jsr"))
DIRECT_BRANCHES = {"bra", "bsr", "bt", "bf", "bt/s", "bf/s"}
CONDITIONAL_BRANCHES = {"bt", "bf", "bt/s", "bf/s"}
TERMINATORS = {"rts", "rte", "sleep"}
PC_LITERAL = re.compile(r"^0x([0-9a-fA-F]+),\s*r(\d+)$")
INDIRECT_LOAD = re.compile(r"^@r(\d+),\s*r(\d+)$")
REGISTER_TRANSFER = re.compile(r"^@(r\d+)$")
DIRECT_TARGET = re.compile(r"0x([0-9a-fA-F]+)")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _preferred_image_base(data: bytes, pe_offset: int) -> int:
    return int.from_bytes(data[pe_offset + 24 + 28:pe_offset + 24 + 32], "little")


def _entry_rva(data: bytes, pe_offset: int) -> int:
    return int.from_bytes(data[pe_offset + 24 + 16:pe_offset + 24 + 20], "little")


def _file_offset_for_va(va: int, image_base: int, sections: list[dict[str, Any]]) -> int:
    rva = va - image_base
    for section in sections:
        start = int(section["virtual_address"])
        size = int(section["raw_size"])
        if start <= rva < start + size:
            return int(section["raw_pointer"]) + rva - start
    raise ValueError(f"VA 0x{va:08x} has no file-backed PE section")


def _decode_one(ctx: Any, text: bytes, text_va: int, address: int) -> dict[str, Any]:
    offset = address - text_va
    if offset < 0 or offset + 2 > len(text) or address & 1:
        raise ValueError(f"unaligned or out-of-range SH4 address 0x{address:08x}")
    instruction = ctx.disassemble(text[offset:offset + 2], address,
                                  max_instructions=1).instructions[0]
    return {
        "va": address,
        "bytes": text[offset:offset + 2].hex(),
        "mnem": instruction.mnem.lower(),
        "body": instruction.body.strip(),
    }


def _branch_target(body: str) -> int | None:
    match = DIRECT_TARGET.search(body)
    return int(match.group(1), 16) if match else None


def _pdata_roots(data: bytes, section: dict[str, Any], image_base: int,
                 text_start: int, text_end: int) -> list[dict[str, int]]:
    raw_start = int(section["raw_pointer"])
    size = int(section["virtual_size"])
    if size % 8:
        raise ValueError(f".pdata virtual size {size} is not divisible by 8")
    roots = []
    for offset in range(raw_start, raw_start + size, 8):
        first = int.from_bytes(data[offset:offset + 4], "little")
        second = int.from_bytes(data[offset + 4:offset + 8], "little")
        if not text_start <= first < text_end:
            raise ValueError(f".pdata entry 0x{first:08x} is outside .text")
        roots.append({"va": first, "raw_record_offset": offset,
                      "opaque_word": second})
    if any(roots[i]["va"] >= roots[i + 1]["va"]
           for i in range(len(roots) - 1)):
        raise ValueError(".pdata first words are not strictly increasing")
    return roots


def _walk_root(ctx: Any, text: bytes, text_va: int, root: int, end: int) -> dict[str, Any]:
    queue = deque([root])
    instructions: dict[int, dict[str, Any]] = {}
    delay_slots: set[int] = set()
    bad: list[dict[str, Any]] = []
    direct_calls: list[dict[str, int]] = []
    indirect_transfers: list[dict[str, Any]] = []
    branches: list[dict[str, Any]] = []

    def add_delay(address: int) -> None:
        if root <= address < end:
            delay_slots.add(address)

    while queue:
        address = queue.popleft()
        if address in instructions or not root <= address < end or address & 1:
            continue
        try:
            row = _decode_one(ctx, text, text_va, address)
        except Exception as exc:  # preserve exact failure address, do not guess past it
            bad.append({"va": address, "error": type(exc).__name__, "detail": str(exc)})
            continue
        instructions[address] = row
        mnem = row["mnem"]
        target = _branch_target(row["body"])

        if mnem in CONDITIONAL_BRANCHES:
            add_delay(address + 2)
            branches.append({"va": address, "mnem": mnem, "target": target})
            if target is not None and root <= target < end:
                queue.append(target)
            queue.append(address + 4)
        elif mnem == "bra":
            add_delay(address + 2)
            branches.append({"va": address, "mnem": mnem, "target": target})
            if target is not None and root <= target < end:
                queue.append(target)
        elif mnem == "bsr":
            add_delay(address + 2)
            if target is not None:
                direct_calls.append({"va": address, "target": target})
            queue.append(address + 4)
        elif mnem in {"jsr", "jmp", "bsrf", "braf"}:
            add_delay(address + 2)
            indirect_transfers.append({"va": address, "mnem": mnem,
                                       "operand": row["body"]})
            if mnem in {"jsr", "bsrf"}:
                queue.append(address + 4)
        elif mnem in TERMINATORS:
            add_delay(address + 2)
        else:
            queue.append(address + 2)

    # Delay slots execute, but must not be followed as linear fall-through after
    # the delayed branch/return. Decode them as evidence only.
    for address in sorted(delay_slots):
        if address in instructions:
            continue
        try:
            instructions[address] = _decode_one(ctx, text, text_va, address)
        except Exception as exc:
            bad.append({"va": address, "error": type(exc).__name__, "detail": str(exc),
                        "delay_slot": True})

    backwards = [row for row in branches
                 if row["target"] is not None and row["target"] < row["va"]]
    return {
        "root_va": root,
        "range_end_va_exclusive": end,
        "reachable_instruction_count": len(instructions),
        "decode_failures": bad,
        "direct_calls": direct_calls,
        "indirect_transfers": indirect_transfers,
        "branches": branches,
        "back_edges": backwards,
        "instructions": [instructions[a] for a in sorted(instructions)],
    }


def _import_lookup(imports: dict[str, Any], image_base: int) -> dict[int, dict[str, Any]]:
    result = {}
    for module in imports["modules"]:
        for item in module["imports"]:
            result[image_base + int(item["iat_rva"])] = {
                "module": module["module"],
                "symbol": item.get("name") or f"ordinal_{item.get('ordinal')}",
                "ordinal": item.get("ordinal"),
                "iat_va": image_base + int(item["iat_rva"]),
            }
    return result


def _read_word_at_va(data: bytes, va: int, image_base: int,
                     sections: list[dict[str, Any]]) -> int:
    offset = _file_offset_for_va(va, image_base, sections)
    return int.from_bytes(data[offset:offset + 4], "little")


def _import_call_xrefs(functions: list[dict[str, Any]], data: bytes, image_base: int,
                       sections: list[dict[str, Any]], imports: dict[str, Any]) -> list[dict[str, Any]]:
    iat = _import_lookup(imports, image_base)
    calls: list[dict[str, Any]] = []

    def thunk_import(target: int) -> tuple[dict[str, Any] | None, int | None]:
        text = next(s for s in sections if s["name"] == ".text")
        text_start = image_base + int(text["virtual_address"])
        text_end = text_start + int(text["virtual_size"])
        if not text_start <= target < text_end:
            return None, None
        # A thunk is accepted only when its first instruction loads a literal
        # pointing at an imported address and its second instruction jumps via
        # that same register.
        off = _file_offset_for_va(target, image_base, sections)
        raw = data[off:off + 2]
        ctx = pypcode.Context(LANGUAGE)
        try:
            first = ctx.disassemble(raw, target, max_instructions=1).instructions[0]
            match = PC_LITERAL.match(first.body.strip()) if first.mnem.lower() == "mov.l" else None
            if not match:
                return None, None
            literal_va = int(match.group(1), 16)
            register = int(match.group(2))
            imported_va = _read_word_at_va(data, literal_va, image_base, sections)
            if imported_va not in iat:
                return None, None
            second_off = _file_offset_for_va(target + 2, image_base, sections)
            second = ctx.disassemble(data[second_off:second_off + 2], target + 2,
                                     max_instructions=1).instructions[0]
            if second.mnem.lower() == "jmp" and second.body.strip() == f"@r{register}":
                return iat[imported_va], imported_va
            # This image's import stubs load the IAT address, dereference it,
            # then jump through the resolved address.
            load = INDIRECT_LOAD.match(second.body.strip()) if second.mnem.lower() == "mov.l" else None
            if not load or tuple(map(int, load.groups())) != (register, register):
                return None, None
            third_off = _file_offset_for_va(target + 4, image_base, sections)
            third = ctx.disassemble(data[third_off:third_off + 2], target + 4,
                                    max_instructions=1).instructions[0]
            if third.mnem.lower() != "jmp" or third.body.strip() != f"@r{register}":
                return None, None
            return iat[imported_va], imported_va
        except Exception:
            return None, None

    for function in functions:
        registers: dict[int, dict[str, Any]] = {}
        previous: int | None = None
        for row in function["instructions"]:
            address = int(row["va"])
            if previous is not None and address != previous + 2:
                registers.clear()
            previous = address
            mnem, body = row["mnem"], row["body"]

            transfer = REGISTER_TRANSFER.match(body) if mnem in {"jsr", "jmp"} else None
            if transfer:
                register = int(transfer.group(1)[1:])
                target = registers.get(register)
                if target:
                    resolved = target.get("import")
                    slot = target.get("iat_va")
                    if not resolved and target.get("kind") == "text":
                        resolved, slot = thunk_import(int(target["va"]))
                    if resolved:
                        calls.append({"call_va": address, "root_va": function["root_va"],
                                      "transfer": mnem, "target_va": target.get("va", slot),
                                      "import_iat_va": slot, "import": resolved})

            pc_load = PC_LITERAL.match(body) if mnem == "mov.l" else None
            indirect_load = INDIRECT_LOAD.match(body) if mnem == "mov.l" else None
            if pc_load:
                literal_va = int(pc_load.group(1), 16)
                register = int(pc_load.group(2))
                try:
                    value = _read_word_at_va(data, literal_va, image_base, sections)
                except (ValueError, IndexError):
                    registers.pop(register, None)
                else:
                    if value in iat:
                        registers[register] = {"kind": "iat", "iat_va": value,
                                               "import": iat[value]}
                    elif image_base + int(next(s for s in sections if s["name"] == ".text")
                                          ["virtual_address"]) <= value < image_base + int(next(
                                              s for s in sections if s["name"] == ".text")["virtual_address"]
                                          ) + int(next(s for s in sections if s["name"] == ".text")
                                                   ["virtual_size"]):
                        registers[register] = {"kind": "text", "va": value}
                    else:
                        registers.pop(register, None)
            elif indirect_load:
                source, destination = map(int, indirect_load.groups())
                if source in registers:
                    registers[destination] = registers[source]
                else:
                    registers.pop(destination, None)
            else:
                # Invalidate a simple register destination where recognizable.
                dest = re.search(r",\s*r(\d+)\s*$", body)
                if dest:
                    registers.pop(int(dest.group(1)), None)
                if mnem in DIRECT_BRANCHES or mnem in TERMINATORS:
                    registers.clear()

    unique = {(r["call_va"], r["import_iat_va"]): r for r in calls}
    return [unique[key] for key in sorted(unique)]


def _import_thunk_evidence(calls: list[dict[str, Any]], data: bytes,
                           image_base: int, sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    text_section = next(s for s in sections if s["name"] == ".text")
    text_va = image_base + int(text_section["virtual_address"])
    text_end = text_va + int(text_section["virtual_size"])
    text = data[int(text_section["raw_pointer"]):int(text_section["raw_pointer"])
                + int(text_section["virtual_size"])]
    ctx = pypcode.Context(LANGUAGE)
    by_target: dict[int, dict[str, Any]] = {}
    for call in calls:
        target = call.get("target_va")
        if target is None or not text_va <= int(target) < text_end:
            continue
        target = int(target)
        if target in by_target:
            continue
        rows = []
        for address in range(target, min(target + 8, text_end), 2):
            try:
                rows.append(_decode_one(ctx, text, text_va, address))
            except Exception:
                break
        by_target[target] = {"thunk_va": target, "resolved_import": call["import"],
                             "import_iat_va": call["import_iat_va"],
                             "instructions": rows}
    return [by_target[key] for key in sorted(by_target)]


def _source_anchor_hashes() -> dict[str, str]:
    anchors = {
        "xref_v4_firmware_xref.json": XREF_DIR / "evidence" / "firmware_xref.json",
        "astra_core_v5_NODE_GRAPH_SPEC.md": PROJECT / "research" / "geometry_breakthrough"
                                             / "astra_core_v5" / "NODE_GRAPH_SPEC.md",
        "astra_core_v5_BINARY_FINDINGS.md": PROJECT / "research" / "geometry_breakthrough"
                                               / "astra_core_v5" / "BINARY_FINDINGS.md",
        "astra_core_v5_pass_a_frozen_rule.json": PROJECT / "research" / "geometry_breakthrough"
                                                   / "astra_core_v5" / "evidence"
                                                   / "pass_a_frozen_rule.json",
    }
    return {name: sha256(path.read_bytes()) for name, path in anchors.items()}


def analyze() -> dict[str, Any]:
    source_before = sha256(NAVIMAIN.read_bytes())
    if source_before != NAVIMAIN_SHA256:
        raise ValueError("NAVIMAIN.EXE differs from the immutable xref_v4 SHA-256")
    data = NAVIMAIN.read_bytes()
    headers = inspect_pe_headers(data)
    if headers["architecture"] != "SH4":
        raise ValueError(f"existing PE reader reports {headers['architecture']}, expected SH4")
    image_base = _preferred_image_base(data, int(headers["pe_offset"]))
    entry_rva = _entry_rva(data, int(headers["pe_offset"]))
    entry_va = image_base + entry_rva
    entry_file_offset = _file_offset_for_va(entry_va, image_base, headers["sections"])
    if (entry_va, entry_file_offset) != (EXPECTED_ENTRY_VA, EXPECTED_ENTRY_FILE_OFFSET):
        raise ValueError("NAVIMAIN entry mapping differs from the existing xref_v4 evidence")

    text_section = next(s for s in headers["sections"] if s["name"] == ".text")
    text_va = image_base + int(text_section["virtual_address"])
    text_end = text_va + int(text_section["virtual_size"])
    text_raw = int(text_section["raw_pointer"])
    text = data[text_raw:text_raw + int(text_section["virtual_size"])]
    pdata_section = next(s for s in headers["sections"] if s["name"] == ".pdata")
    roots = _pdata_roots(data, pdata_section, image_base, text_va, text_end)

    ctx = pypcode.Context(LANGUAGE)
    control_results = []
    for code, expected in EXPECTED_CONTROL:
        instruction = ctx.disassemble(code, 0x1000, max_instructions=1).instructions[0]
        control_results.append({"bytes": code.hex(), "expected_mnem": expected,
                                "decoded_mnem": instruction.mnem.lower(),
                                "decoded_body": instruction.body.strip(),
                                "pass": instruction.mnem.lower() == expected})
    if not all(row["pass"] for row in control_results):
        raise ValueError("SH4 endian/decoder control instruction mismatch")

    functions = []
    for index, root in enumerate(roots):
        end = roots[index + 1]["va"] if index + 1 < len(roots) else text_end
        functions.append(_walk_root(ctx, text, text_va, root["va"], end))
    import_calls = _import_call_xrefs(functions, data, image_base,
                                     headers["sections"], parse_imports(data))
    import_thunks = _import_thunk_evidence(import_calls, data, image_base,
                                           headers["sections"])

    immediate_hits = []
    opcode_counts: dict[str, int] = {}
    for function in functions:
        for row in function["instructions"]:
            opcode_counts[row["mnem"]] = opcode_counts.get(row["mnem"], 0) + 1
            match = re.search(r"#(-?0x[0-9a-fA-F]+)", row["body"])
            if match and int(match.group(1), 16) in {10, -10, 14, -14}:
                immediate_hits.append({"va": row["va"], "mnem": row["mnem"],
                                       "body": row["body"]})

    entry_window = []
    for address in range(entry_va, entry_va + 0x3C, 2):
        entry_window.append(_decode_one(ctx, text, text_va, address))
    literal_targets = []
    for row in entry_window:
        match = PC_LITERAL.match(row["body"]) if row["mnem"] == "mov.l" else None
        if match:
            literal_va = int(match.group(1), 16)
            literal_value = _read_word_at_va(data, literal_va, image_base, headers["sections"])
            literal_targets.append({"instruction_va": row["va"], "literal_va": literal_va,
                                    "loaded_value": literal_value})

    function_113f8 = next(function for function in functions
                          if function["root_va"] == 0x113F8)
    rdata_section = next(s for s in headers["sections"] if s["name"] == ".rdata")
    rdata_start = image_base + int(rdata_section["virtual_address"])
    rdata_end = rdata_start + int(rdata_section["virtual_size"])
    trace_sequence = []
    for row in function_113f8["instructions"]:
        if 0x115EE <= row["va"] <= 0x11604:
            item = dict(row)
            pc_load = PC_LITERAL.match(row["body"]) if row["mnem"] == "mov.l" else None
            if pc_load:
                literal_va = int(pc_load.group(1), 16)
                value = _read_word_at_va(data, literal_va, image_base, headers["sections"])
                item["literal_va"] = literal_va
                item["loaded_value"] = value
                if rdata_start <= value < rdata_end:
                    string_offset = _file_offset_for_va(value, image_base, headers["sections"])
                    string_end = string_offset
                    while string_end + 1 < len(data) and data[string_end:string_end + 2] != b"\0\0":
                        string_end += 2
                    item["loaded_utf16le"] = data[string_offset:string_end].decode(
                        "utf-16le", errors="replace")
            trace_sequence.append(item)
    original_disc_root = NAVIMAIN.parents[5]
    trace_dll_paths = sorted(str(path) for path in original_disc_root.rglob("NaviTrace.dll")
                             if path.is_file())

    total_reachable = sum(f["reachable_instruction_count"] for f in functions)
    total_errors = sum(len(f["decode_failures"]) for f in functions)
    all_back_edges = [row for f in functions for row in f["back_edges"]]
    report = {
        "tool": {"name": "pypcode", "version": importlib.metadata.version("pypcode"),
                 "language_id": LANGUAGE, "language_control_pass": all(
                     row["pass"] for row in control_results)},
        "source": {"path": str(NAVIMAIN), "size_bytes": len(data),
                   "sha256_before": source_before, "expected_sha256": NAVIMAIN_SHA256,
                   "sha256_after": sha256(NAVIMAIN.read_bytes()),
                   "changed_by_scan": sha256(NAVIMAIN.read_bytes()) != source_before},
        "inputs_reused_read_only": {
            "xref_v4": str(XREF_DIR / "evidence" / "firmware_xref.json"),
            "astra_core_v5_rule": str(PROJECT / "research" / "geometry_breakthrough"
                                      / "astra_core_v5" / "NODE_GRAPH_SPEC.md"),
            "anchor_sha256": _source_anchor_hashes(),
        },
        "pe": {"architecture_from_existing_reader": headers["architecture"],
               "image_base": image_base, "entry_rva": entry_rva,
               "entry_va": entry_va, "entry_file_offset": entry_file_offset,
               "text_va_start": text_va, "text_va_end_exclusive": text_end,
               "text_raw_offset": text_raw, "text_virtual_size": len(text),
               "pdata_va": image_base + int(pdata_section["virtual_address"]),
               "pdata_virtual_size": int(pdata_section["virtual_size"])},
        "decoder_controls": control_results,
        "pdata_roots": [{**r, "range_end_va_exclusive":
                         (roots[i + 1]["va"] if i + 1 < len(roots) else text_end)}
                        for i, r in enumerate(roots)],
        "scan": {"pdata_root_count": len(roots),
                 "reachable_instruction_count_with_per_root_duplicates": total_reachable,
                 "cfg_decode_failure_count": total_errors,
                 "backward_direct_branch_count": len(all_back_edges),
                 "immediate_10_or_14_hits": immediate_hits,
                 "mnem_counts_with_per_root_duplicates": dict(sorted(opcode_counts.items())),
                 "scope": "Direct control-flow from .pdata first-word roots within each next-root range; indirect jump-table targets are not followed."},
        "entrypoint_window": entry_window,
        "entrypoint_pc_literal_targets": literal_targets,
        "import_thunks": import_thunks,
        "dynamic_module_sequence": {
            "description": "Observed code passes a NaviTrace.dll string to an imported call, then passes the returned value and an Initialize string to a second imported call, and invokes the returned pointer.",
            "instructions": trace_sequence,
            "import_call_xrefs": [row for row in import_calls
                                  if row["call_va"] in {0x115F2, 0x115FC}],
            "pseudocode": "h = coredll_ordinal_528(L\"NaviTrace.dll\"); p = coredll_ordinal_530(h, L\"Initialize\"); p();",
            "following_indirect_call_va": 0x11602,
            "exact_basename_search": {"root": str(original_disc_root),
                                       "basename": "NaviTrace.dll",
                                       "matches": trace_dll_paths},
        },
        "import_call_xrefs": import_calls,
        "functions": [{k: v for k, v in function.items() if k != "instructions"}
                      for function in functions],
        "reachable_disassembly": [
            {"root_va": function["root_va"], "instructions": function["instructions"]}
            for function in functions
        ],
        "interpretation": {
            "confirmed_code_role": "The entry routine calls local routines at 0x11cd4, 0x113f8 and 0x11d08. Reachable code includes calls to named MI_CF communication-manager imports, including GetProcessName, GetInstance, CreateInstance and RegisterStatusHandler.",
            "section5_routing_semantics": "NOT_FOUND_IN_SCANNED_NAVIMAIN_CODE",
            "sections6_to9_rt_rl_consumer": "NOT_FOUND_IN_SCANNED_NAVIMAIN_CODE",
            "astra_section4_control": "Astra's confirmed node continuation consumes the next physical 10-byte record for high-degree nodes. The scan found no direct #0xA/#0xE immediate in the reached instruction inventory; this is only a bounded pattern check, not proof that equivalent arithmetic is absent.",
            "packing": "No common packer markers were present in xref_v4; PE sections and code were readable. Custom/runtime unpacking is not excluded.",
            "reason_for_nonfinding": "NAVIMAIN's reachable code is dominated by short MFC/COM-style wrappers and manager setup; Section 5 fields and MP0/route strings are not identified. The coredll and MFC ordinal APIs remain unresolved, and indirect targets/runtime-loaded COM components are outside this static scan.",
            "next_hypothesis": "The graph reader is likely behind a runtime-created MI_CF COM/service component rather than this NAVIMAIN bootstrap. Resolve the CreateInstance GUID and COM/service registration or identify its installed server module, then scan that module's file-I/O/MP0 consumers before considering NK.BIN.",
        },
    }
    if report["source"]["sha256_after"] != source_before:
        raise RuntimeError("source hash changed during read-only scan")
    return report


def write_evidence(report: dict[str, Any]) -> None:
    evidence = HERE / "evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / "sh4_scan.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    nav_lines = ["; Read-only SH4 disassembly; PDATA-root CFG scan; pypcode 4.0.1",
                 f"; source_sha256={report['source']['sha256_before']}"]
    function_meta = {row["root_va"]: row for row in report["functions"]}
    for function in report["reachable_disassembly"]:
        meta = function_meta[function["root_va"]]
        nav_lines.append(f"\n; root=0x{function['root_va']:08x} "
                         f"range_end=0x{meta['range_end_va_exclusive']:08x} "
                         f"reachable={meta['reachable_instruction_count']}")
        for row in function["instructions"]:
            nav_lines.append(f"{row['va']:08x}  {row['bytes']}  {row['mnem']:<8} {row['body']}")
    (evidence / "bounded_disassembly.txt").write_text("\n".join(nav_lines) + "\n",
                                                        encoding="utf-8")
    thunk_lines = ["; Import thunks reached by statically resolved indirect calls",
                   f"; source_sha256={report['source']['sha256_before']}"]
    for thunk in report["import_thunks"]:
        imported = thunk["resolved_import"]
        thunk_lines.append(f"\n; thunk=0x{thunk['thunk_va']:08x} "
                           f"IAT=0x{thunk['import_iat_va']:08x} "
                           f"{imported['module']}!{imported['symbol']}")
        for row in thunk["instructions"]:
            thunk_lines.append(f"{row['va']:08x}  {row['bytes']}  {row['mnem']:<8} {row['body']}")
    (evidence / "import_thunks.txt").write_text("\n".join(thunk_lines) + "\n",
                                                encoding="utf-8")


def main() -> None:
    report = analyze()
    write_evidence(report)
    print(json.dumps({"source_sha256": report["source"]["sha256_after"],
                      "pdata_roots": report["scan"]["pdata_root_count"],
                      "reachable_instruction_count":
                          report["scan"]["reachable_instruction_count_with_per_root_duplicates"],
                      "decode_failures": report["scan"]["cfg_decode_failure_count"],
                      "resolved_import_call_xrefs": len(report["import_call_xrefs"]),
                      "result": report["interpretation"]["section5_routing_semantics"]},
                     indent=2))


if __name__ == "__main__":
    main()
